import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { ChevronRightIcon } from "../icons";
import {
  DEFAULT_REGION_SETTINGS,
  FONT_CATALOG,
  TYPOGRAPHY_REGION_DEFINITIONS,
  resetAllRegionSettings,
  resetRegionSettings,
  type FontCatalogEntry,
  type TypographyRegionId,
  type TypographyRegionSettings,
} from "../features/home-typography/fontCatalog";
import { loadWebFont } from "../features/home-typography/webFontLoader";
import { HomeShowcase } from "./HomeShowcase";
import "./home.css";
import "./home-typography-lab.css";

type PreviewStyle = CSSProperties & Record<`--lab-${string}`, string>;

const fontSourceLabels = {
  local: "Local project fonts",
  system: "System fonts",
  web: "Google Fonts (loaded on selection)",
} as const;

function fontStack(font: FontCatalogEntry): string {
  return `"${font.family}", ${font.fallback}`;
}

function findFont(fontId: string): FontCatalogEntry {
  const font = FONT_CATALOG.find((entry) => entry.id === fontId);
  if (!font) {
    throw new Error(`Unknown typography font: ${fontId}`);
  }
  return font;
}

function labVariableName(regionId: TypographyRegionId, property: string): `--lab-${string}` {
  return `--lab-${regionId.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}-${property}`;
}

function previewStyle(settings: Record<TypographyRegionId, TypographyRegionSettings>): PreviewStyle {
  return TYPOGRAPHY_REGION_DEFINITIONS.reduce<PreviewStyle>((style, { id }) => {
    const setting = settings[id];
    const font = findFont(setting.fontId);

    style[labVariableName(id, "font")] = fontStack(font);
    style[labVariableName(id, "weight")] = String(setting.fontWeight);
    style[labVariableName(id, "style")] = setting.fontStyle;
    style[labVariableName(id, "size")] = `${setting.fontSizePx}px`;
    style[labVariableName(id, "line-height")] = String(setting.lineHeight);
    style[labVariableName(id, "tracking")] = `${setting.letterSpacingEm}em`;
    style[labVariableName(id, "transform")] = setting.textTransform;
    return style;
  }, {});
}

function fontGroups() {
  return (Object.keys(fontSourceLabels) as Array<FontCatalogEntry["source"]>).map((source) => ({
    source,
    label: fontSourceLabels[source],
    fonts: FONT_CATALOG.filter((font) => font.source === source),
  }));
}

export function HomeTypographyLabPage() {
  const [selectedRegionId, setSelectedRegionId] = useState<TypographyRegionId>("heroMain");
  const [settings, setSettings] = useState<Record<TypographyRegionId, TypographyRegionSettings>>(
    DEFAULT_REGION_SETTINGS,
  );
  const [showGuide, setShowGuide] = useState(false);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [fontLoadStatus, setFontLoadStatus] = useState("");

  const selectedSettings = settings[selectedRegionId];
  const selectedFont = findFont(selectedSettings.fontId);
  const groups = useMemo(fontGroups, []);
  const canTransform = ["navigation", "heroAction", "cardMeta"].includes(selectedRegionId);

  useEffect(() => {
    if (selectedFont.source !== "web") {
      setFontLoadStatus("");
      return;
    }

    let active = true;
    setFontLoadStatus(`Loading ${selectedFont.label}...`);
    void loadWebFont(selectedFont)
      .then(() => {
        if (active) setFontLoadStatus(`${selectedFont.label} ready`);
      })
      .catch(() => {
        if (active) setFontLoadStatus(`${selectedFont.label} could not load; the fallback remains active.`);
      });

    return () => {
      active = false;
    };
  }, [selectedFont]);

  function updateSelectedSettings(update: Partial<TypographyRegionSettings>) {
    setSettings((current) => ({
      ...current,
      [selectedRegionId]: {
        ...current[selectedRegionId],
        ...update,
      },
    }));
  }

  function changeFont(fontId: string) {
    const font = findFont(fontId);
    updateSelectedSettings({
      fontId,
      fontWeight: font.weights.includes(selectedSettings.fontWeight)
        ? selectedSettings.fontWeight
        : font.weights[0],
      fontStyle: font.supportsItalic ? selectedSettings.fontStyle : "normal",
    });
  }

  function resetSelectedRegion() {
    setSettings((current) => ({
      ...current,
      [selectedRegionId]: resetRegionSettings(selectedRegionId),
    }));
  }

  function resetAllTypography() {
    setSettings((current) => resetAllRegionSettings(current));
  }

  return (
    <main className={`home-typography-lab ${inspectorCollapsed ? "is-inspector-collapsed" : ""}`}>
      <section
        className={`home-typography-lab__preview ${showGuide ? "is-guide-visible" : ""}`}
        data-testid="home-typography-preview"
        style={previewStyle(settings)}
      >
        <header className="home-typography-lab__preview-header">
          <span className="home-typography-lab__brand" data-home-typography-region="navigation">AdCraft</span>
          <span className="home-typography-lab__preview-label" data-home-typography-region="navigation">Home surface preview</span>
        </header>
        <HomeShowcase mode="static" />
      </section>

      <aside className="home-typography-lab__inspector" aria-label="Typography controls">
        <button
          className="home-typography-lab__collapse"
          type="button"
          aria-label={inspectorCollapsed ? "Expand inspector" : "Collapse inspector"}
          title={inspectorCollapsed ? "Expand inspector" : "Collapse inspector"}
          onClick={() => setInspectorCollapsed((collapsed) => !collapsed)}
        >
          <ChevronRightIcon />
        </button>

        <div className="home-typography-lab__inspector-content">
          <header className="home-typography-lab__inspector-heading">
            <p>Internal visual calibration</p>
            <h1>Home Typography Lab</h1>
          </header>

          <div className="home-typography-lab__control-group">
            <label htmlFor="home-typography-target">Typography target</label>
            <select
              id="home-typography-target"
              value={selectedRegionId}
              onChange={(event) => setSelectedRegionId(event.target.value as TypographyRegionId)}
            >
              {TYPOGRAPHY_REGION_DEFINITIONS.map((region) => (
                <option key={region.id} value={region.id}>{region.label}</option>
              ))}
            </select>
          </div>

          <div className="home-typography-lab__control-group">
            <label htmlFor="home-typography-font">Font family</label>
            <select
              id="home-typography-font"
              value={selectedFont.id}
              onChange={(event) => changeFont(event.target.value)}
            >
              {groups.map(({ source, label, fonts }) => (
                <optgroup key={source} label={label}>
                  {fonts.map((font) => <option key={font.id} value={font.id}>{font.label}</option>)}
                </optgroup>
              ))}
            </select>
          </div>

          <div className="home-typography-lab__inline-controls">
            <div className="home-typography-lab__control-group">
              <label htmlFor="home-typography-weight">Weight</label>
              <select
                id="home-typography-weight"
                value={selectedSettings.fontWeight}
                onChange={(event) => updateSelectedSettings({ fontWeight: Number(event.target.value) })}
              >
                {selectedFont.weights.map((weight) => (
                  <option key={weight} value={weight}>{weight}</option>
                ))}
              </select>
            </div>
            <div className="home-typography-lab__control-group">
              <label htmlFor="home-typography-style">Style</label>
              <select
                id="home-typography-style"
                value={selectedSettings.fontStyle}
                onChange={(event) => updateSelectedSettings({ fontStyle: event.target.value as TypographyRegionSettings["fontStyle"] })}
              >
                <option value="normal">Normal</option>
                {selectedFont.supportsItalic ? <option value="italic">Italic</option> : null}
              </select>
            </div>
          </div>

          <div className="home-typography-lab__range-grid">
            <label>
              <span>Size <output>{selectedSettings.fontSizePx}px</output></span>
              <input
                aria-label="Font size"
                type="range"
                min="12"
                max="80"
                value={selectedSettings.fontSizePx}
                onChange={(event) => updateSelectedSettings({ fontSizePx: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Line height <output>{selectedSettings.lineHeight.toFixed(2)}</output></span>
              <input
                aria-label="Line height"
                type="range"
                min="0.9"
                max="2"
                step="0.05"
                value={selectedSettings.lineHeight}
                onChange={(event) => updateSelectedSettings({ lineHeight: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Tracking <output>{selectedSettings.letterSpacingEm.toFixed(3)}em</output></span>
              <input
                aria-label="Letter spacing"
                type="range"
                min="-0.05"
                max="0.12"
                step="0.002"
                value={selectedSettings.letterSpacingEm}
                onChange={(event) => updateSelectedSettings({ letterSpacingEm: Number(event.target.value) })}
              />
            </label>
          </div>

          <div className="home-typography-lab__control-group">
            <label htmlFor="home-typography-transform">Text transform</label>
            <select
              id="home-typography-transform"
              value={canTransform ? selectedSettings.textTransform : "none"}
              disabled={!canTransform}
              onChange={(event) => updateSelectedSettings({
                textTransform: event.target.value as TypographyRegionSettings["textTransform"],
              })}
            >
              <option value="none">None</option>
              <option value="uppercase">Uppercase</option>
              <option value="small-caps">Small caps</option>
            </select>
          </div>

          <p className="home-typography-lab__font-status" aria-live="polite">{fontLoadStatus}</p>

          <section className="home-typography-lab__specimen" aria-label="Selected font specimen">
            <span>Specimen</span>
            <p
              style={{
                fontFamily: fontStack(selectedFont),
                fontWeight: selectedSettings.fontWeight,
                fontStyle: selectedSettings.fontStyle,
                fontSize: Math.min(selectedSettings.fontSizePx, 34),
                lineHeight: selectedSettings.lineHeight,
                letterSpacing: `${selectedSettings.letterSpacingEm}em`,
                textTransform: selectedSettings.textTransform,
              }}
            >
              Sphinx of black quartz, judge my vow.
            </p>
          </section>

          <label className="home-typography-lab__guide-toggle">
            <input
              type="checkbox"
              checked={showGuide}
              onChange={(event) => setShowGuide(event.target.checked)}
            />
            <span>Show text bounds</span>
          </label>

          <div className="home-typography-lab__actions">
            <button type="button" onClick={resetSelectedRegion}>Reset selected region</button>
            <button type="button" onClick={resetAllTypography}>Reset all typography</button>
          </div>

          <section className="home-typography-lab__recipe" aria-label="Current recipe">
            <h2>Current recipe</h2>
            <dl>
              <div><dt>Target</dt><dd>{TYPOGRAPHY_REGION_DEFINITIONS.find((region) => region.id === selectedRegionId)?.label}</dd></div>
              <div><dt>Face</dt><dd>{selectedFont.label}</dd></div>
              <div><dt>Setting</dt><dd>{selectedSettings.fontWeight} / {selectedSettings.fontStyle}</dd></div>
            </dl>
          </section>
        </div>
      </aside>
    </main>
  );
}
