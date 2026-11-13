"""Deterministic user-visible status replies from current Workflow authority."""

from __future__ import annotations

from app.schemas.agent_operation_contexts import WorkflowStateCapsuleV1, WorkflowWorkItemSummaryV1
from app.services.response_locale_resolver import ResponseLocaleResolverV1


class WorkflowStatusReplyRenderer:
    """Render bounded status prose without another model call or state mutation."""

    def __init__(self, locale_resolver: ResponseLocaleResolverV1 | None = None) -> None:
        self._locale_resolver = locale_resolver or ResponseLocaleResolverV1()

    def render(self, capsule: WorkflowStateCapsuleV1) -> str:
        locale = self._locale_resolver.resolve(capsule.response_locale)
        language = "zh-TW" if locale == "zh-TW" else "zh-CN" if locale.startswith("zh") else "en"
        stage = self._stage_label(capsule.journey_stage, language)
        counts = capsule.node_status_counts
        total = sum(counts.values())
        ready = counts.get("ready", 0)
        remaining = counts.get("draft", 0) + counts.get("working", 0) + counts.get("failed", 0)
        sections: list[str] = []
        if language == "zh-TW":
            sections.append(f"已完成：{ready}/{total} 個節點已就緒。")
            if capsule.journey_stage is not None:
                sections.append(f"目前階段：{stage}。")
            elif capsule.guidance_session_id is None:
                sections.append("目前沒有進行中的引導工作階段。")
            sections.extend(self._current_zh(capsule, traditional=True))
            sections.append(f"剩餘：{remaining} 個節點尚未就緒。")
            if total > 0 and remaining == 0:
                sections.append("目前已有的節點均已就緒。")
        elif language == "zh-CN":
            sections.append(f"已完成：{ready}/{total} 个节点已就绪。")
            if capsule.journey_stage is not None:
                sections.append(f"当前阶段：{stage}。")
            elif capsule.guidance_session_id is None:
                sections.append("当前没有进行中的引导会话。")
            sections.extend(self._current_zh(capsule, traditional=False))
            sections.append(f"剩余：{remaining} 个节点尚未就绪。")
            if total > 0 and remaining == 0:
                sections.append("当前已有的节点均已就绪。")
        else:
            sections.append(f"Ready: {ready} ready nodes of {total}.")
            if capsule.journey_stage is not None:
                sections.append(f"Current stage: {stage}.")
            elif capsule.guidance_session_id is None:
                sections.append("No guided session is active.")
            sections.extend(self._current_en(capsule))
            sections.append(f"Remaining: {remaining} nodes ({remaining} remaining).")
            if total > 0 and remaining == 0:
                sections.append("All current nodes are ready.")
        if capsule.next_valid_action is not None:
            label = capsule.next_valid_action.objective or capsule.next_valid_action.action_kind
            sections.append(
                (
                    "下一步："
                    if language == "zh-CN"
                    else "下一步："
                    if language == "zh-TW"
                    else "Next: "
                )
                + label
            )
        return " ".join(section for section in sections if section)

    @staticmethod
    def _stage_label(stage: str | None, language: str) -> str:
        # Presentation labels for canonical enums; never used to interpret user text.
        labels = {
            "intake": ("Requirements", "需求确认", "需求確認"),
            "world_view": ("World design", "世界观设计", "世界觀設計"),
            "product": ("Product design", "产品设计", "產品設計"),
            "props": ("Prop design", "道具设计", "道具設計"),
            "character": ("Character design", "角色设计", "角色設計"),
            "scene": ("Scene design", "场景设计", "場景設計"),
            "narrative_direction": ("Creative direction", "创意方向", "創意方向"),
            "style_lock": ("Style selection", "风格确认", "風格確認"),
            "storyboard_plan": ("Storyboard planning", "分镜规划", "分鏡規劃"),
            "storyboard_grids": ("Storyboard images", "分镜九宫格", "分鏡九宮格"),
            "videos": ("Video production", "视频制作", "影片製作"),
            "bgm": ("Background music", "背景音乐", "背景音樂"),
            "editing": ("Editing", "剪辑", "剪輯"),
            "completed": ("Guided production complete", "引导制作完成", "引導製作完成"),
        }
        return labels.get(stage or "", ("Production", "制作", "製作"))[
            2 if language == "zh-TW" else 1 if language == "zh-CN" else 0
        ]

    @staticmethod
    def _prompt_work(capsule: WorkflowStateCapsuleV1) -> WorkflowWorkItemSummaryV1 | None:
        return next(
            (
                item
                for item in capsule.active_work
                if item.prompt_preparation_state in {"leased", "working"}
            ),
            None,
        )

    @staticmethod
    def _current_en(capsule: WorkflowStateCapsuleV1) -> tuple[str, ...]:
        action = capsule.current_action
        if action is not None:
            if action.ownership_status in {"orphaned", "inconsistent"}:
                return (
                    "Production is blocked by backend recovery "
                    f"({action.error_code or action.leaf_error_code or 'workflow_state_inconsistent'}). "
                    "No user action is currently available.",
                )
            if action.ownership_status == "awaiting":
                return (f"Waiting for user action: {action.owner_state}.",)
        prompt = WorkflowStatusReplyRenderer._prompt_work(capsule)
        if prompt is not None:
            return (f"Writing the prompt for {prompt.title}.",)
        if action is not None:
            if action.ownership_status == "owned":
                return (
                    f"System work is in progress: {action.action_kind}. "
                    "No user action is required.",
                )
        if capsule.active_work:
            item = capsule.active_work[0]
            return (f"Current work: {item.title} is {item.node_status}.",)
        return ()

    @staticmethod
    def _current_zh(
        capsule: WorkflowStateCapsuleV1,
        *,
        traditional: bool,
    ) -> tuple[str, ...]:
        action = capsule.current_action
        if action is not None:
            if action.ownership_status in {"orphaned", "inconsistent"}:
                return (
                    "生产被后端恢复阻塞，当前没有可执行的用户操作。"
                    if not traditional
                    else "生產被後端恢復阻塞，目前沒有可執行的使用者操作。",
                )
            if action.ownership_status == "awaiting":
                prefix = "等待用户操作" if not traditional else "等待使用者操作"
                return (f"{prefix}：{action.owner_state}。",)
        prompt = WorkflowStatusReplyRenderer._prompt_work(capsule)
        if prompt is not None:
            activity = "正在編寫提示詞" if traditional else "正在编写提示词"
            return (f"{prompt.title}：{activity}。",)
        if action is not None:
            if action.ownership_status == "owned":
                return (
                    "系统正在处理，无需用户操作。"
                    if not traditional
                    else "系統正在處理，無需使用者操作。",
                )
        if capsule.active_work:
            item = capsule.active_work[0]
            prefix = "当前工作" if not traditional else "目前工作"
            states = {
                "draft": ("待处理", "待處理"),
                "working": ("处理中", "處理中"),
                "failed": ("处理失败", "處理失敗"),
                "ready": ("已就绪", "已就緒"),
            }
            state = states[item.node_status][int(traditional)]
            return (f"{prefix}：{item.title}（{state}）。",)
        return ()
