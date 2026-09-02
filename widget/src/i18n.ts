// Widget 界面文案 i18n(ML Closure G-L4)。
// UI_LANGUAGE 与 ANSWER_LANGUAGE 分离:此处只管界面文案,不决定答案语言。
// zh 文案与既有用户可见行为逐字一致(含与后端 SERVICE_UNAVAILABLE_MSG 的对齐)。


export interface UiStrings {
  /** 空会话兜底欢迎语(站点 welcome 未配置时的回落) */
  defaultWelcome: string;
  placeholder: string;
  send: string;
  serviceUnavailable: string;
  uploadFailed: string;
  attachTitle: string;
}

const EN: UiStrings = {
  defaultWelcome: "Hi! I'm Ask Camthink.ai — how can I help?",
  placeholder: "Type your question...",
  send: "Send",
  serviceUnavailable: "Service temporarily unavailable. Please try again later.",
  uploadFailed: "Upload failed",
  attachTitle: "Attach .txt or .log",
};

const ZH: UiStrings = {
  defaultWelcome: "你好!我是 Ask Camthink.ai,有什么可以帮你?",
  placeholder: "输入你的问题...",
  send: "发送",
  // 与后端 SERVICE_UNAVAILABLE_MSG 逐字一致(PC-01 客户端最后防线文案)
  serviceUnavailable: "服务暂时不可用,请稍后再试。",
  uploadFailed: "上传失败",
  attachTitle: "附加 .txt 或 .log 文件",
};

export function uiStrings(lang: "en" | "zh"): UiStrings {
  return lang === "zh" ? ZH : EN;
}
