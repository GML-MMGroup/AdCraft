from __future__ import annotations

from html import escape
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from app.schemas.workflow_v2_production_acceptance import (
    V2ProductionAcceptanceReport,
    V2ProductionAcceptanceReviewEntry,
)
from app.services.v2_production_acceptance_store import V2ProductionAcceptanceStore


_GROUPS = (
    ("product", "Product"),
    ("character", "Character"),
    ("scene", "Scene"),
    ("storyboard", "Storyboard"),
    ("bgm", "BGM"),
    ("final_composition", "Final Composition"),
)
_DEFAULT_MANUAL_CHECKS = (
    "Product-reference fidelity",
    "Character identity and style consistency",
    "Scene-brief fidelity",
    "Storyboard continuity",
    "Shot-video fidelity",
    "Final audiovisual quality",
)
_REMOTE_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_EVENT_HANDLER = re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE)
_ABSOLUTE_PATH = re.compile(r"(?<![\w])/(?!media/)[A-Za-z0-9._~!$&'()*+,;=:@%/\-]+")
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|credential|password|secret|token|signature|api[_-]?key)",
    re.IGNORECASE,
)


class V2ProductionAcceptanceReviewRenderer:
    def __init__(
        self,
        data_dir: Path,
        *,
        store: V2ProductionAcceptanceStore | None = None,
    ) -> None:
        self._store = store or V2ProductionAcceptanceStore(data_dir)

    def render(self, report: V2ProductionAcceptanceReport) -> str:
        document = _render_document(report)
        return self._store.save_review_html(report.acceptance_run_id, document)


def _render_document(report: V2ProductionAcceptanceReport) -> str:
    fixture_title = _text(report.fixture_snapshot.get("title") or report.fixture_id)
    sections = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Production Acceptance Review - {fixture_title}</title>",
        "<style>",
        _STYLES,
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        "<header>",
        '<p class="eyebrow">V2 Production Acceptance</p>',
        f"<h1>{fixture_title}</h1>",
        '<dl class="summary">',
        _definition("Acceptance run", report.acceptance_run_id),
        _definition("Workflow", report.workflow_id),
        _definition("Execution", report.execution_id),
        _definition("Lifecycle", report.lifecycle_status),
        _definition("Technical verdict", report.technical_verdict),
        _definition("Created", report.created_at),
        "</dl>",
        '<p class="notice">Technical pass does not imply creative approval.</p>',
        "</header>",
        _render_checks(report),
        _render_failures(report),
        _render_warnings(report),
        _render_metrics(report.metrics),
        _render_manifest(report.review_manifest),
        _render_lineage(report.review_manifest),
        _render_manual_review(report.fixture_snapshot),
        "</main>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(sections)


def _render_checks(report: V2ProductionAcceptanceReport) -> str:
    rows = []
    for check in report.checks:
        rows.append(
            "<tr>"
            f"<td>{_text(check.check_id)}</td>"
            f"<td>{_text(check.stage)}</td>"
            f'<td><span class="status">{_text(check.status)}</span></td>'
            f"<td>{_text(check.message)}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="4">No automated checks recorded.</td></tr>'
    return (
        '<section><h2>Automated Checks</h2><div class="table-wrap"><table>'
        "<thead><tr><th>Check</th><th>Stage</th><th>Status</th><th>Message</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div></section>"
    )


def _render_failures(report: V2ProductionAcceptanceReport) -> str:
    items = []
    for failure in report.failures:
        identifiers = [
            value
            for value in (
                failure.node_id,
                failure.item_id,
                failure.slot_id,
                failure.asset_id,
                failure.version_id,
                failure.provider_task_id,
            )
            if value
        ]
        suffix = f" <small>{_text(' / '.join(identifiers))}</small>" if identifiers else ""
        items.append(
            f"<li><strong>{_text(failure.code)}</strong>: {_text(failure.message)}{suffix}</li>"
        )
    body = "".join(items) or "<li>None.</li>"
    return f"<section><h2>Technical Failures</h2><ul>{body}</ul></section>"


def _render_warnings(report: V2ProductionAcceptanceReport) -> str:
    body = "".join(f"<li>{_text(warning)}</li>" for warning in report.warnings)
    return f"<section><h2>Warnings</h2><ul>{body or '<li>None.</li>'}</ul></section>"


def _render_metrics(metrics: dict[str, Any]) -> str:
    rows = []
    for key in sorted(metrics):
        if _SENSITIVE_KEY.search(str(key)):
            continue
        rows.append(
            f"<tr><th>{_text(key)}</th><td>{_text(_safe_json_value(metrics[key]))}</td></tr>"
        )
    body = "".join(rows) or '<tr><td colspan="2">No metrics recorded.</td></tr>'
    return f"<section><h2>Metrics</h2><table><tbody>{body}</tbody></table></section>"


def _render_manifest(entries: list[V2ProductionAcceptanceReviewEntry]) -> str:
    grouped = {key: [] for key, _label in _GROUPS}
    for entry in sorted(entries, key=lambda item: item.order):
        grouped[entry.group].append(entry)
    sections = ["<section><h2>Ordered Media Review</h2>"]
    for group, label in _GROUPS:
        group_entries = grouped[group]
        if not group_entries:
            continue
        sections.append(f'<h3>{label}</h3><div class="media-grid">')
        sections.extend(_render_entry(entry) for entry in group_entries)
        sections.append("</div>")
    if not entries:
        sections.append("<p>No generated media is available for review.</p>")
    sections.append("</section>")
    return "".join(sections)


def _render_entry(entry: V2ProductionAcceptanceReviewEntry) -> str:
    preview = _preview(entry)
    warnings = "".join(f"<li>{_text(value)}</li>" for value in entry.warnings)
    warning_block = f"<ul>{warnings}</ul>" if warnings else ""
    probe = entry.probe
    probe_values = [
        f"type={probe.media_type}",
        f"readable={str(probe.readable).lower()}",
        f"bytes={probe.size_bytes}",
    ]
    if probe.width is not None and probe.height is not None:
        probe_values.append(f"dimensions={probe.width}x{probe.height}")
    if probe.duration_seconds is not None:
        probe_values.append(f"duration={probe.duration_seconds:g}s")
    if probe.video_codec:
        probe_values.append(f"video_codec={probe.video_codec}")
    if probe.audio_codec:
        probe_values.append(f"audio_codec={probe.audio_codec}")
    return (
        '<article class="media-item">'
        f"<h4>{entry.order}. {_text(entry.slot_type)}</h4>"
        f"{preview}"
        '<dl class="details">'
        f"{_definition('Node', entry.node_id)}"
        f"{_definition('Item', entry.item_id)}"
        f"{_definition('Slot', entry.slot_id)}"
        f"{_definition('Asset', entry.asset_id)}"
        f"{_definition('Version', entry.version_id)}"
        f"{_definition('Probe', ', '.join(probe_values))}"
        "</dl>"
        f"{warning_block}</article>"
    )


def _preview(entry: V2ProductionAcceptanceReviewEntry) -> str:
    url = _safe_media_url(entry.public_url)
    if url is None:
        return '<div class="preview missing">No safe preview URL is available.</div>'
    escaped_url = escape(url, quote=True)
    if entry.probe.media_type == "video":
        return f'<video class="preview" controls preload="metadata" src="{escaped_url}"></video>'
    if entry.probe.media_type == "audio":
        return f'<audio class="preview" controls preload="metadata" src="{escaped_url}"></audio>'
    return f'<img src="{escaped_url}" class="preview" alt="Generated acceptance asset">'


def _render_lineage(entries: list[V2ProductionAcceptanceReviewEntry]) -> str:
    blocks = []
    for entry in sorted(entries, key=lambda item: item.order):
        references = ", ".join(entry.reference_asset_ids) or None
        blocks.append(
            '<article class="lineage">'
            f"<h3>{entry.order}. {_text(entry.slot_type)}</h3>"
            '<dl class="details">'
            f"{_definition('Summary prompt', entry.summary_prompt)}"
            f"{_definition('Specialist prompt', entry.specialist_prompt)}"
            f"{_definition('Provider prompt', entry.provider_prompt)}"
            f"{_definition('Submitted references', references)}"
            f"{_definition('Provider', entry.provider)}"
            f"{_definition('Provider model', entry.provider_model)}"
            "</dl></article>"
        )
    return (
        "<section><h2>Prompt And Reference Lineage</h2>"
        f"{''.join(blocks) or '<p>No prompt lineage is available.</p>'}</section>"
    )


def _render_manual_review(fixture_snapshot: dict[str, Any]) -> str:
    configured = fixture_snapshot.get("manual_review_checks")
    checks = (
        [value for value in configured if isinstance(value, str) and value.strip()]
        if isinstance(configured, list)
        else []
    )
    checks = checks or list(_DEFAULT_MANUAL_CHECKS)
    items = "".join(
        f'<li><label><input type="checkbox" disabled> {_text(check)}</label></li>'
        for check in checks
    )
    return (
        "<section><h2>Manual Creative Review</h2>"
        "<p>This checklist is informational only; technical pass does not imply creative approval.</p>"
        f'<ul class="checklist">{items}</ul></section>'
    )


def _definition(label: str, value: Any) -> str:
    rendered = (
        _text(value) if value not in (None, "") else '<span class="unavailable">Unavailable</span>'
    )
    return f"<dt>{escape(label)}</dt><dd>{rendered}</dd>"


def _safe_media_url(value: str | None) -> str | None:
    if not value or "\\" in value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    if not parsed.path.startswith("/media/") or ".." in parsed.path.split("/"):
        return None
    return parsed.path


def _safe_json_value(value: Any) -> str:
    sanitized = _sanitize_value(value)
    if isinstance(sanitized, str):
        return sanitized
    return json.dumps(sanitized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _redact_unsafe_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return type(value).__name__


def _text(value: Any) -> str:
    return escape(_redact_unsafe_text(str(value)), quote=True)


def _redact_unsafe_text(value: str) -> str:
    text = _REMOTE_URL.sub("[remote-url-redacted]", value)
    text = re.sub(r"(?:data:|file://)[^\s<>\"']*", "[resource-redacted]", text, flags=re.IGNORECASE)
    text = _EVENT_HANDLER.sub("[event-handler-redacted]", text)
    text = _ABSOLUTE_PATH.sub("[absolute-path-redacted]", text)
    if len(text) > 512 and not any(character.isspace() for character in text):
        return "[opaque-value-redacted]"
    return text


_STYLES = """
:root { color-scheme: light; font-family: system-ui, sans-serif; color: #1f2933; background: #f4f6f8; }
body { margin: 0; }
main { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0 64px; }
header, section { background: #fff; border: 1px solid #d8dee4; border-radius: 6px; margin-bottom: 16px; padding: 20px; }
h1, h2, h3, h4 { margin: 0 0 12px; }
h2 { font-size: 1.2rem; }
h3 { margin-top: 20px; font-size: 1rem; }
.eyebrow { color: #52606d; font-size: .8rem; font-weight: 700; text-transform: uppercase; }
.notice { border-left: 4px solid #b7791f; padding: 10px 12px; background: #fffaf0; }
.summary, .details { display: grid; grid-template-columns: minmax(130px, auto) 1fr; gap: 6px 14px; }
dt { color: #52606d; font-weight: 600; }
dd { margin: 0; overflow-wrap: anywhere; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }
.media-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.media-item, .lineage { border: 1px solid #d8dee4; border-radius: 4px; padding: 12px; }
.preview { display: block; width: 100%; max-height: 360px; object-fit: contain; background: #eef1f4; margin-bottom: 12px; }
.preview.missing { min-height: 90px; display: grid; place-items: center; color: #52606d; }
.unavailable { color: #7b8794; font-style: italic; }
.checklist { list-style: none; padding: 0; }
.checklist li { margin: 8px 0; }
small { color: #52606d; }
""".strip()
