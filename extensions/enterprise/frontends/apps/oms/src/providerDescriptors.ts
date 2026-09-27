import snapshot from "./provider-descriptors.generated.json";

export type ProviderOption = {
  value: string;
  label: string;
  base_url?: string;
  status?: string;
  auth_mode?: string;
  api_formats?: string[];
  default_api_format?: string;
  base_urls?: Record<string, string>;
  default_dim?: string;
  requires_api_key?: boolean;
  requires_base_url?: boolean;
};

type ConnectionService = { provider: string; base_url: string; default_model: string; default_dim?: string };
type ConnectionTarget = { provider: string; label: string; default_base_url: string; services: Record<string, ConnectionService> };

const providers = snapshot.providers as Record<string, ProviderOption[]>;
const targets = snapshot.connection_targets as ConnectionTarget[];

export const descriptorSource = snapshot.source;
export const descriptorSourceRevision = snapshot.source_revision;
export const reasoningSourceRevision = snapshot.reasoning_source_revision;
export function providerOptions(serviceId: string) {
  return (providers[serviceId] ?? []).filter(option => option.status !== "deprecated");
}
export function providerOption(serviceId: string, value: string) {
  return (providers[serviceId] ?? []).find(option => option.value === value);
}
export function connectionOptions() { return targets; }
export function connectionTarget(provider: string) { return targets.find(target => target.provider === provider); }
export function connectionService(provider: string, serviceId: string) { return connectionTarget(provider)?.services[serviceId]; }

// 仅用于演示“有候选”状态；不是供应商实时返回的模型目录。
export function demoModelCandidates(serviceId: string, provider: string): string[] {
  if ((serviceId === "llm" || serviceId === "task") && provider === "dashscope") return ["qwen-plus"];
  return [];
}

// DeepTutor 的 DashScope adapter 内建该模型的维度；未知模型不得套用。
export function demoEmbeddingDimensions(provider: string, model: string): number[] {
  if (provider === "aliyun" && model === "qwen3-vl-embedding") return [256, 512, 768, 1024, 1536, 2048, 2560];
  return [];
}

// 原型离线复现 DeepTutor web/lib/reasoning-effort.ts 的模型族规则；源码修订由快照检查拦截。
// 正式 OMS 必须改为受权 descriptor，而不是依赖此前端判断供应商能力。
export function demoReasoningOptions(binding: string, model: string, declared: string = "auto"): { value: string; label: string }[] {
  if (declared === "no") return [];
  const aliases: Record<string, string> = { azure: "azure_openai", azureopenai: "azure_openai", google: "gemini", google_genai: "gemini", claude: "anthropic", openai_compatible: "custom", anthropic_compatible: "custom_anthropic" };
  const key = binding.trim().toLowerCase().replaceAll("-", "_");
  const provider = aliases[key] ?? key;
  const name = model.trim().toLowerCase();
  const has = (...patterns: string[]) => patterns.some(pattern => name.includes(pattern));
  let values: string[] = [];
  if (provider === "gemini" || name.includes("gemini")) {
    values = has("gemini-3", "gemini-2.5-pro") ? ["minimal", "low", "medium", "high"] : has("gemini-2.5") ? ["none", "low", "medium", "high"] : ["low", "medium", "high"];
  } else if (provider === "anthropic" || provider === "custom_anthropic" || name.includes("claude")) {
    values = has("opus-4-7", "opus-4-8", "opus-5", "sonnet-5", "fable-5", "mythos-5") ? ["none", "adaptive"] : has("claude-3-7", "claude-4", "claude-sonnet-4", "claude-opus-4", "claude-haiku-4") ? ["none", "low", "medium", "high"] : [];
  } else if (provider === "custom") {
    values = ["none", "low", "medium", "high"];
  } else if (["deepseek", "volcengine", "volcengine_coding_plan", "byteplus", "byteplus_coding_plan", "dashscope", "minimax"].includes(provider)) {
    values = provider === "minimax" || has("deepseek-reasoner", "deepseek-v4-pro", "qwen3", "qwen-3", "qwq", "qwen-plus") ? ["minimal", "high"] : [];
  } else if (["openai", "azure_openai", "openai_codex", "github_copilot"].includes(provider)) {
    values = has("gpt-5.6-sol") ? ["none", "low", "medium", "high", "xhigh", "max"] : has("gpt-5", "codex") ? ["minimal", "low", "medium", "high", "xhigh"] : has("o1", "o3", "o4") ? ["low", "medium", "high"] : [];
  }
  if (!values.length && declared === "yes") values = ["none", "low", "medium", "high"];
  const labels: Record<string, string> = { "": "自动（供应商默认）", none: "关闭（none）", minimal: "最低（minimal）", low: "低（low）", medium: "中（medium）", high: "高（high）", xhigh: "更高（xhigh）", max: "最高（max）", adaptive: "自适应（adaptive）" };
  return values.length ? ["", ...values].map(value => ({ value, label: labels[value] ?? value })) : [];
}
