// Widget 界面文案 i18n(ML Closure G-L4)。
// UI_LANGUAGE 与 ANSWER_LANGUAGE 分离:此处只管界面文案,不决定答案语言。
// zh 文案与既有用户可见行为逐字一致(含与后端 SERVICE_UNAVAILABLE_MSG 的对齐)。


export interface UiStrings {
  /** 空会话兜底欢迎语(站点 welcome 未配置时的回落) */
  defaultWelcome: string;
  placeholder: string;
  send: string;
  serviceUnavailable: string;
  /** 预算熔断/服务繁忙(阶段⑯,与后端 budget_declined 冻结文案对齐) */
  serviceBusy: string;
  uploadFailed: string;
  attachTitle: string;
  /** Issue #24:launcher 按钮可访问名(按钮级,不依赖图标) */
  launcherOpen: string;
  // ---- I-UX-001 ----
  /** A Minimal Pill 文案 */
  pillLabel: string;
  /** B/C 关闭控件的语义动作(「现在不看」;本会话不再主动呈现) */
  notNow: string;
  /** C/聊天窗关闭控件可访问名 */
  minimize: string;
  /** 聊天窗头部可访问名(dialog 语义) */
  chatTitle: string;
  /** Trusted Actions 区可访问名 */
  trustedActions: string;
  /** 通用兜底问候(engagement 解析 LOW 档,与此处保持一致语义) */
  genericGreeting: string;
  /** Admin 预览模式的确定性本地回显(预览不产生真实 /ask 流量) */
  previewNotice: string;
  /** #40:等待首个 token 的真实状态文案(✦ 品牌星点;禁三点/进度/伪阶段) */
  preparingAnswer: string;
}

const EN: UiStrings = {
  defaultWelcome: "Hi! I'm Ask Camthink.ai — how can I help?",
  placeholder: "Type your question...",
  send: "Send",
  serviceUnavailable: "Service temporarily unavailable. Please try again later.",
  serviceBusy: "The service is busy right now. Please try again shortly.",
  uploadFailed: "Upload failed",
  attachTitle: "Attach .txt or .log",
  launcherOpen: "Open the Ask AI assistant",
  pillLabel: "Ask AI",
  notNow: "Not now",
  minimize: "Minimize",
  chatTitle: "Ask AI chat",
  trustedActions: "Suggested actions",
  genericGreeting: "How can I help?",
  previewNotice:
    "Preview mode: this exchange is rendered by the Admin live preview — no real request was sent.",
  preparingAnswer: "Preparing an answer…",
};

const ZH: UiStrings = {
  defaultWelcome: "你好!我是 Ask Camthink.ai,有什么可以帮你?",
  placeholder: "输入你的问题...",
  send: "发送",
  // 与后端 SERVICE_UNAVAILABLE_MSG 逐字一致(PC-01 客户端最后防线文案)
  serviceUnavailable: "服务暂时不可用,请稍后再试。",
  // 与后端 budget_declined 冻结文案逐字一致
  serviceBusy: "服务繁忙,请稍后再试。",
  uploadFailed: "上传失败",
  attachTitle: "附加 .txt 或 .log 文件",
  launcherOpen: "打开 Ask AI 助手",
  pillLabel: "问 AI",
  notNow: "暂不需要",
  minimize: "收起",
  chatTitle: "Ask AI 对话",
  trustedActions: "推荐操作",
  genericGreeting: "有什么可以帮你?",
  previewNotice: "预览模式:本次对话由 Admin 实时预览渲染,未发送真实请求。",
  preparingAnswer: "正在准备答案…",
};

export function uiStrings(lang: "en" | "zh"): UiStrings {
  return lang === "zh" ? ZH : EN;
}
