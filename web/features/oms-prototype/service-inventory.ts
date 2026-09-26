import type {
  CatalogModel,
  CatalogProfile,
  ServiceName,
} from "@/features/settings/store/SettingsStore";

type InventoryEntry = {
  service: ServiceName;
  title: string;
  purpose: string;
  profileFields: readonly (keyof CatalogProfile)[];
  modelFields: readonly (keyof CatalogModel)[];
  note: string;
};

// 仅列当前设置页实际可维护、且可安全解释的属性；provider 选项始终来自后端 descriptor。
export const OMS_SERVICE_INVENTORY: readonly InventoryEntry[] = [
  {
    service: "llm",
    title: "对话模型",
    purpose: "聊天与大多数智能推理",
    profileFields: ["name", "binding", "api_format"],
    modelFields: ["name", "model", "context_window", "reasoning_effort", "capabilities"],
    note: "推理档位与接口格式随供应商能力变化。",
  },
  {
    service: "task",
    title: "后台任务模型",
    purpose: "会话标题与首页起始建议",
    profileFields: ["name", "binding", "api_format"],
    modelFields: ["name", "model", "capabilities"],
    note: "未单独配置时沿用对话模型；不复制对话模型的上下文窗口控件。",
  },
  {
    service: "embedding",
    title: "知识检索向量服务",
    purpose: "知识库导入与检索",
    profileFields: ["name", "binding"],
    modelFields: ["name", "model", "dimension", "send_dimensions"],
    note: "维度与是否发送维度参数分别配置；端点地址不是运营信息。",
  },
  {
    service: "search",
    title: "联网搜索",
    purpose: "对话中的网络检索",
    profileFields: ["name", "provider", "proxy"],
    modelFields: [],
    note: "没有模型选择；凭据/地址要求及失败回退由后端供应商描述决定。",
  },
  {
    service: "tts",
    title: "语音合成",
    purpose: "朗读助手回复",
    profileFields: ["name", "binding"],
    modelFields: ["name", "model", "voice", "response_format"],
    note: "声音名称由供应商决定；自动朗读是个人偏好，不是供应商设置。",
  },
  {
    service: "stt",
    title: "语音识别",
    purpose: "转写麦克风录音",
    profileFields: ["name", "binding"],
    modelFields: ["name", "model"],
    note: "当前设置页未提供语言提示控件，不在 OMS 原型中虚构该设置。",
  },
  {
    service: "imagegen",
    title: "文生图",
    purpose: "对话中的图片生成",
    profileFields: ["name", "binding"],
    modelFields: ["name", "model", "size", "quality", "style"],
    note: "尺寸、质量和风格是供应商相关的自由文本，不预设固定选项。",
  },
  {
    service: "videogen",
    title: "文生视频",
    purpose: "对话中的异步视频生成",
    profileFields: ["name", "binding"],
    modelFields: ["name", "model", "aspect_ratio", "duration", "resolution"],
    note: "异步任务与图片生成不同；画幅、时长和分辨率分别设置。",
  },
] as const;

export const INVENTORY_FIELD_LABELS: Partial<
  Record<keyof CatalogProfile | keyof CatalogModel, string>
> = {
  name: "显示名称",
  binding: "供应商类型",
  provider: "搜索供应商",
  api_format: "接口格式（按供应商）",
  proxy: "搜索代理（高级）",
  model: "模型标识",
  context_window: "上下文窗口",
  reasoning_effort: "推理强度（条件性）",
  capabilities: "模型能力声明",
  dimension: "向量维度",
  send_dimensions: "是否发送维度参数",
  voice: "声音名称",
  response_format: "音频输出格式",
  size: "图片尺寸",
  quality: "图片质量",
  style: "图片风格",
  aspect_ratio: "视频画幅",
  duration: "视频时长",
  resolution: "视频分辨率",
};

function demoFeeNumerator(tokens: number | null, pricePerMillion: string): bigint | string {
  if (tokens === null) return "待核算";
  if (!Number.isSafeInteger(tokens) || tokens < 0) return "用量格式有误";
  if (!/^\d{1,12}(?:\.\d{1,6})?$/.test(pricePerMillion)) return "单价格式有误";

  const [whole, fraction = ""] = pricePerMillion.split(".");
  const priceMicros = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"));
  return BigInt(tokens) * priceMicros;
}

/** 仅供演示数字使用；直接对精确金额舍入到分，不先舍入中间值。 */
export function formatDemoFee(tokens: number | null, pricePerMillion: string): string {
  const numerator = demoFeeNumerator(tokens, pricePerMillion);
  if (typeof numerator !== "bigint") return numerator;
  const cents = (numerator + 5_000_000_000n) / 10_000_000_000n;
  const amount = `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`;
  return `¥${amount}`;
}

/** 展示未舍入的逐调用示例金额；正式账单仍只由服务端 Decimal 生成。 */
export function formatDemoFeeExact(tokens: number | null, pricePerMillion: string): string {
  const numerator = demoFeeNumerator(tokens, pricePerMillion);
  if (typeof numerator !== "bigint") return numerator;
  const whole = numerator / 1_000_000_000_000n;
  const fraction = String(numerator % 1_000_000_000_000n)
    .padStart(12, "0")
    .replace(/0+$/, "");
  return `¥${whole}${fraction ? `.${fraction}` : ""}`;
}
