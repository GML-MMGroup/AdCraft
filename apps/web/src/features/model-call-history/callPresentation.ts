/** Display labels only: unknown operations and values retain their recorded names. */
const operations: Record<string, [string, string]> = {
  decide_turn_intent: ["理解用户需求", "判断这条消息的意图与后续处理方向。"],
  decide_next_action: ["规划下一步", "根据当前项目状态选择下一步工作。"],
  author_decision_bundle: ["整理创作方案", "生成供用户选择的创作决策。"],
  brand_slot_question: ["梳理品牌需求", "围绕尚待明确的品牌信息生成问题和选项。"],
  brand_hypothesis: ["提出品牌创意方向", "根据品牌与广告需求提出候选创意。"],
  brand_skill_recommendation: ["推荐创作 Skills", "为当前项目推荐创意方法和视听风格。"],
  brand_treatment_step: ["细化创意方案", "生成当前方案步骤的内容与选项。"],
  author_guided_script_checkpoint: ["设计脚本方案", "整理脚本内容与待确认的创作方向。"],
  prepare_role_prompt: ["编写生成提示词", "为当前创作角色准备素材生成提示词。"],
};

export function operationPresentation(operation: string | null) {
  const known = operation ? operations[operation] : null;
  return { title: known?.[0] ?? operation ?? "未命名操作", description: known?.[1] ?? "用途暂未标注，请查看这次调用的输入与输出。" };
}

export function stageLabel(stage: string | null) {
  return ({ initial: "首次调用", transport_retry: "传输重试", structured_repair: "结构化修复", capability_fallback: "能力回退" } as Record<string, string>)[stage ?? ""] ?? stage ?? "未提供";
}

export function statusLabel(status: string | null) {
  return ({ completed: "调用完成", failed: "调用失败", incomplete: "记录不完整" } as Record<string, string>)[status ?? ""] ?? status ?? "未提供";
}

export function callTime(value: string | null) {
  if (!value) return "时间未提供";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
}

const fields: Record<string, string> = {
  assistant_message: "Agent 回复", user_input: "用户原话", user_message: "用户消息",
  question: "问题", question_text: "问题", title: "标题", description: "说明", summary: "摘要",
  content: "内容", text: "正文", label: "选项名称", value: "内容值", options: "可选方案",
  recommended: "推荐选项", reason: "原因", rationale: "设计理由", public_summary: "方案摘要",
  context: "上下文", recent_messages: "近期对话", brand_decisions: "已确认的品牌决策",
  requirements: "创作需求", requirement_summary: "需求摘要", constraints: "执行限制",
  system_prompt: "系统提示词", user_prompt: "用户提示词", output_schema: "输出格式要求",
  generation_prompt: "生成提示词", summary_prompt: "概述提示词", negative_prompt: "排除内容",
  visual_prompt: "画面提示词", provider_prompt: "供应商提示词", editable_prompt: "可编辑提示词",
  item_prompt: "素材提示词", shot_summary_prompt: "镜头概述", slot_prompt: "素材槽位提示词",
  system_suggested_prompt: "系统建议提示词", skill_id: "Skill 标识", name: "名称", version: "版本",
  model: "模型", model_ref: "模型", provider: "供应商", execution_policy: "执行策略",
  timeout_seconds: "超时（秒）", effective_timeout_ms: "实际超时（毫秒）", max_tokens: "最大 Token 数",
  temperature: "采样温度", usage: "Token 用量", token_usage: "Token 用量",
  prompt_tokens: "输入 Token", completion_tokens: "输出 Token", total_tokens: "总 Token",
  input_tokens: "输入 Token", output_tokens: "输出 Token", finish_reason: "结束原因",
  stopReason: "结束原因", stop_reason: "结束原因", end_reason: "结束原因",
  error: "错误", errorMessage: "错误信息", message: "消息", code: "错误码",
  mode: "处理模式", ordinary_intent: "常规请求", intent: "意图", response_locale: "回复语言",
  objective: "本次目标", explicit_elements: "用户明确提到的内容", intent_kind: "请求类型",
  confirmed_values: "已确认的信息", delegated_slots: "交由 Agent 决定的信息",
  product_context: "产品与项目背景", assumptions: "待确认的假设", journey: "当前创作进度",
  slot_values: "本次整理的信息", slot_evidence: "信息依据", clarifications: "待澄清的问题",
  question_card: "品牌问题", candidates: "候选创意", creative_methods: "创意方法",
  audiovisual_styles: "视听风格", step: "方案步骤", sections: "方案详情", stage: "创作阶段",
  slot_id: "信息项标识", source_quote: "原话依据", source_id: "来源标识", kind: "信息类型",
  provenance: "信息来源", confirmed_at: "确认时间", adspec: "广告规格", items: "条目",
  item_text: "条目内容", item_key: "条目标识", state: "状态", skill_stack: "已选创作 Skills",
  selected_hypothesis: "已选创意方向", previous_steps: "此前的方案步骤", action: "下一步动作",
  hook: "创意切入点", story: "故事", character: "角色", scene: "场景", visual: "视觉风格",
  camera: "镜头设计", editing: "剪辑节奏", sound: "声音设计", risks: "风险与限制",
  arguments: "调用参数", function: "函数", tool_calls: "工具调用", type: "类型",
  completion_tokens_details: "输出 Token 明细", prompt_tokens_details: "输入 Token 明细",
  cached_tokens: "缓存 Token", reasoning_tokens: "推理 Token",
  slots: "待梳理的信息项", slot_schema_version: "信息结构版本", target_slot_id: "当前信息项",
  card_id: "问题卡标识", stage_revision: "阶段版本",
  mentioned_node_ids: "提到的画布节点", mentioned_image_asset_ids: "提到的图片素材",
  requirement_revision_id: "需求版本标识", requirement_revision_no: "需求版本号",
  requirement_digest: "需求内容摘要值", requirement_patch: "需求变更",
  current_hard_controls: "当前硬性约束", editable_directives: "可编辑指令",
  current_response_locale: "当前回复语言", workflow_context: "工作流上下文",
  style_skill_catalog: "风格 Skills 目录", requested_capability: "请求的能力",
  session_exists: "会话是否已存在", option_id: "选项标识", why: "推荐理由",
};
export function fieldLabel(key: string) { return fields[key] ?? key; }

/** Translate a small set of known enum values, keeping original values available on hover. */
export function recordedEnumLabel(key: string | undefined, value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const values: Record<string, Record<string, string>> = {
    mode: { ordinary_conversation: "常规对话" },
    intent_kind: { agent_identity: "了解 Agent 身份", agent_capabilities: "了解 Agent 能做什么", workflow_status: "查看项目进度", freeform_reply: "自由回复" },
    response_locale: { "zh-CN": "简体中文", "en-US": "英语（美国）" },
    stage: { "brand-memory": "品牌信息", "campaign": "广告需求", "hypothesis": "创意方向", "adspec": "广告规格", "skill-stack": "创作 Skills", "treatment": "创意方案", "production": "素材制作" },
  };
  return values[key ?? ""]?.[value];
}

export function parseRecordedJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  const body = /^```(?:json)?\s*\n([\s\S]*?)\n```$/.exec(trimmed)?.[1] ?? trimmed;
  try {
    const parsed: unknown = JSON.parse(body);
    return parsed !== null && typeof parsed === "object" ? parsed : value;
  } catch { return value; }
}

/** Split only the known prompt template and only when its context parses completely. */
export function readableInput(request: Record<string, unknown>) {
  const original = request.user_prompt ?? request.user;
  if (typeof original === "string" && original.startsWith("User request:\n")) {
    const separator = "\n\nValidated typed operation context:\n";
    const boundary = original.indexOf(separator);
    if (boundary >= 0) {
      const context = parseRecordedJson(original.slice(boundary + separator.length));
      if (context && typeof context === "object") {
        return { message: original.slice("User request:\n".length, boundary), context, original };
      }
    }
  }
  return { message: parseRecordedJson(original), context: request.context ?? request.agent_request, original };
}
