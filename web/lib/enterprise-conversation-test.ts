import type {
  ContextPolicy,
  StartTurnCommand,
} from "@/contracts/generated/turn-protocol";
import { buildStartTurn } from "@/contracts/parse/turn-command";
import type { DemoResultPayload } from "./eduplus2-fronting-demo";

export interface ConversationTestStartTurnInput {
  prompt: string;
  sessionId?: string | null;
  knowledgeBases?: string[];
  skills?: string[];
  mcpTools?: string[];
  resourceIds?: string[];
  contextPolicy?: ContextPolicy;
}

export interface ConversationUploadIntentInput {
  name: string;
  type?: string | null;
  size: number;
  sha256: string;
  modality: "image" | "audio" | "video" | "file" | "document";
  sessionId?: string | null;
}

export interface ConversationUploadIntentRequest {
  modality: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  purpose: "chat_turn";
  session_id: string;
  filename: string;
  expires_seconds: number;
}

export interface ConversationSendState {
  prompt: string;
  sending: boolean;
  uploading: boolean;
  failedUploadCount: number;
  isAuthenticated: boolean;
}

export interface CapabilityUsageItem {
  kind?: string;
  label?: string;
  status?: string;
  count?: number;
}

export interface CapabilityUsageSummary {
  items?: CapabilityUsageItem[];
  diagnostics?: unknown;
}

export interface FriendlyCapabilityUsageRow {
  text: string;
  kind: string;
  status: string;
}

export interface ConversationThinkingStep {
  id: string;
  kind: string;
  title: string;
  content: string;
}

export interface ConversationThinkingDisplay {
  kind: string;
  title: string;
  content: string;
  appendToPrevious: boolean;
}

function timestampOrNull(value: unknown): number | null {
  const timestamp = typeof value === "number" ? value : Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(timestamp) && timestamp > 0 ? timestamp : null;
}

export function getDemoTokenExpiresAt(payload: DemoResultPayload): number | null {
  const summaryExpiresAt =
    payload.summary && typeof payload.summary === "object"
      ? timestampOrNull(payload.summary.expires_at)
      : null;
  return summaryExpiresAt ?? timestampOrNull(payload.expires_at);
}

function cleanList(values?: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values ?? []) {
    const text = `${value ?? ""}`.trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push(text);
  }
  return out;
}

export function buildConversationTestStartTurn(
  input: ConversationTestStartTurnInput,
): StartTurnCommand {
  const content = input.prompt.trim();
  if (!content) throw new TypeError("prompt must not be empty");
  return buildStartTurn({
    content,
    capability: "chat",
    session_id: input.sessionId ?? null,
    tools: null,
    knowledge_bases: cleanList(input.knowledgeBases),
    skills: cleanList(input.skills),
    mcp_tools: cleanList(input.mcpTools),
    context_policy: input.contextPolicy ?? "required",
    resource_ids: cleanList(input.resourceIds),
    attachments: [],
    language: "zh",
    config: {},
  });
}

export function buildConversationUploadIntentRequest(
  input: ConversationUploadIntentInput,
): ConversationUploadIntentRequest {
  const filename = `${input.name ?? ""}`.trim() || "upload.bin";
  const mimeType = `${input.type ?? ""}`.trim() || "application/octet-stream";
  const digest = `${input.sha256 ?? ""}`.trim();
  if (!/^[a-fA-F0-9]{64}$/.test(digest)) throw new TypeError("sha256 must be a hex digest");
  const sizeBytes = Number(input.size);
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) {
    throw new TypeError("size must be positive");
  }
  return {
    modality: input.modality,
    mime_type: mimeType,
    size_bytes: sizeBytes,
    sha256: digest.toLowerCase(),
    purpose: "chat_turn",
    session_id: `${input.sessionId ?? ""}`,
    filename,
    expires_seconds: 900,
  };
}

export function conversationSendBlockReason(input: ConversationSendState): string {
  if (!input.prompt.trim() || input.sending) return "";
  if (!input.isAuthenticated) return "请先完成登录。";
  if (input.uploading) return "文件还在上传中，完成后再发送。";
  if (input.failedUploadCount > 0) {
    return "有文件上传失败，请移除失败项或重新选择后再发送。";
  }
  return "";
}

function publicLabel(item: CapabilityUsageItem): string {
  const kind = `${item.kind ?? ""}`;
  const label = `${item.label ?? ""}`.trim();
  if (kind === "mcp_tool") return "外部检索工具";
  if (kind === "builtin_tool") return label === "rag" ? "知识库检索" : "系统工具";
  if (kind === "resource" && label.startsWith("uploaded_resources:")) {
    const count = Number.parseInt(label.split(":")[1] ?? "0", 10);
    return count > 0 ? `上传文件 ${count} 个` : "上传文件";
  }
  if (kind === "model" && !label) return "对话模型";
  if (kind === "chat") return "连续对话";
  return label || "已选能力";
}

function publicStatus(status?: string): string {
  switch (`${status ?? ""}`) {
    case "used":
      return "已用于回答";
    case "sent":
      return "已发送给模型";
    case "unavailable":
      return "不可用或未授权";
    case "enabled":
    default:
      return "已启用但本轮未用";
  }
}

export function formatCapabilityUsageForPeople(
  summary?: CapabilityUsageSummary | null,
): FriendlyCapabilityUsageRow[] {
  const items = Array.isArray(summary?.items) ? summary.items : [];
  if (items.length === 0) {
    return [{ text: "连续对话：已启用但本轮未用", kind: "chat", status: "enabled" }];
  }
  return items.map((item) => {
    const kind = `${item.kind ?? "unknown"}`;
    const status = `${item.status ?? "enabled"}`;
    const text = `${publicLabel(item)}：${publicStatus(status)}`;
    return { text, kind, status };
  });
}

export function isSpeechRecognitionAvailable(scope: object = globalThis): boolean {
  const candidate = scope as Record<string, unknown>;
  return (
    typeof candidate.SpeechRecognition === "function" ||
    typeof candidate.webkitSpeechRecognition === "function"
  );
}

export function isServerSpeechRecordingAvailable(scope: object = globalThis): boolean {
  const candidate = scope as Record<string, unknown>;
  const navigatorValue =
    candidate.navigator && typeof candidate.navigator === "object"
      ? (candidate.navigator as Record<string, unknown>)
      : {};
  const mediaDevices =
    navigatorValue.mediaDevices && typeof navigatorValue.mediaDevices === "object"
      ? (navigatorValue.mediaDevices as Record<string, unknown>)
      : {};
  return (
    typeof candidate.MediaRecorder === "function" &&
    typeof mediaDevices.getUserMedia === "function"
  );
}

export function conversationSpeechFailureNotice(error?: unknown): string {
  const code = String(
    error instanceof Error ? `${error.name} ${error.message}` : (error ?? ""),
  ).toLowerCase();
  if (code.includes("no active stt") || code.includes("stt model")) {
    return "当前服务还没有配置语音转写能力，请先使用文字输入或上传音频文件。";
  }
  if (
    code.includes("not-allowed") ||
    code.includes("permission") ||
    code.includes("security")
  ) {
    return "无法使用麦克风，请在浏览器地址栏允许麦克风权限后重试；也可以继续键盘输入。";
  }
  if (code.includes("no-speech")) {
    return "没有听到清晰语音，请靠近麦克风后重试；也可以继续键盘输入。";
  }
  if (code.includes("audio-capture") || code.includes("not-found")) {
    return "没有检测到可用麦克风，请检查设备后重试；也可以继续键盘输入。";
  }
  if (code.includes("network") || code.includes("service-not-allowed")) {
    return "浏览器语音服务暂时不可用，已切换为文字输入；你也可以直接上传音频文件。";
  }
  if (code.includes("empty")) {
    return "没有录到有效声音，请重新录制；也可以继续键盘输入。";
  }
  if (code.includes("timeout")) {
    return "麦克风没有响应，请检查浏览器权限或设备后重试；也可以继续键盘输入。";
  }
  return "语音输入没有成功，可以继续手动输入，或上传音频文件一起发送。";
}

export function withConversationSpeechStartTimeout<T>(
  operation: Promise<T>,
  timeoutMs = 10_000,
): Promise<T> {
  const safeTimeoutMs = Number.isFinite(timeoutMs) ? Math.max(0, timeoutMs) : 10_000;
  if (safeTimeoutMs <= 0) return operation;
  let timer: ReturnType<typeof setTimeout> | undefined;
  return new Promise<T>((resolve, reject) => {
    timer = setTimeout(() => {
      reject(new Error("microphone start timeout"));
    }, safeTimeoutMs);
    operation.then(
      (value) => {
        if (timer) clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        if (timer) clearTimeout(timer);
        reject(error);
      },
    );
  });
}

export function isConversationTerminalWebSocketEvent(type: string): boolean {
  return type === "done" || type === "error" || type === "protocol_error";
}

export function nextConversationAuthRefreshDelayMs(input: {
  nowSeconds: number;
  expiresAt: number | null | undefined;
  leewaySeconds: number;
  minDelayMs?: number;
}): number | null {
  if (!input.expiresAt) return null;
  const minDelayMs = Math.max(0, input.minDelayMs ?? 1_000);
  const refreshAtSeconds = input.expiresAt - Math.max(0, input.leewaySeconds);
  const delayMs = Math.max(0, refreshAtSeconds - input.nowSeconds) * 1_000;
  return Math.max(minDelayMs, delayMs);
}

export function formatConversationProgressForPeople(
  type: string,
  metadata: Record<string, unknown> = {},
): string {
  if (type === "tool_call") {
    const toolName = String(metadata.tool_name ?? metadata.tool ?? metadata.name ?? "");
    return toolName === "rag" ? "正在查找知识库内容…" : "正在调用辅助能力…";
  }
  if (type === "sources") return "已找到可参考内容，正在整理回答…";
  if (type === "thinking" || type === "progress") return "正在理解问题并规划回答…";
  return "";
}

function safeThinkingText(value: unknown): string {
  return String(value ?? "")
    .replace(/<\/?think(?:ing)?>/gi, "")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
}

export function splitAssistantThinkingFromAnswer(content: string): {
  answer: string;
  thinking: string;
} {
  if (!content) return { answer: "", thinking: "" };
  const thinkingParts: string[] = [];
  const answerParts: string[] = [];
  const pattern = /<think(?:ing)?>([\s\S]*?)(?:<\/think(?:ing)?>|$)/gi;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(content)) !== null) {
    answerParts.push(content.slice(cursor, match.index));
    const thinking = safeThinkingText(match[1] ?? "").trim();
    if (thinking) thinkingParts.push(thinking);
    cursor = match.index + match[0].length;
    if (match[0].length === 0) pattern.lastIndex += 1;
  }
  answerParts.push(content.slice(cursor));
  return {
    answer: answerParts.join("").replace(/<\/?think(?:ing)?>/gi, ""),
    thinking: thinkingParts.join("\n\n"),
  };
}

export function encodeConversationWavFromFloat32(
  chunks: Float32Array[],
  inputSampleRate: number,
  targetSampleRate = 16_000,
): Uint8Array {
  const inputLength = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const input = new Float32Array(inputLength);
  let offset = 0;
  for (const chunk of chunks) {
    input.set(chunk, offset);
    offset += chunk.length;
  }
  const safeInputRate = Number.isFinite(inputSampleRate) && inputSampleRate > 0 ? inputSampleRate : targetSampleRate;
  const outputLength =
    safeInputRate === targetSampleRate
      ? input.length
      : Math.max(0, Math.round((input.length * targetSampleRate) / safeInputRate));
  const dataBytes = outputLength * 2;
  const wav = new Uint8Array(44 + dataBytes);
  const view = new DataView(wav.buffer);
  writeAscii(wav, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(wav, 8, "WAVE");
  writeAscii(wav, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, targetSampleRate, true);
  view.setUint32(28, targetSampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(wav, 36, "data");
  view.setUint32(40, dataBytes, true);
  const ratio = safeInputRate / targetSampleRate;
  for (let index = 0; index < outputLength; index += 1) {
    const sourceIndex = safeInputRate === targetSampleRate ? index : Math.min(input.length - 1, Math.floor(index * ratio));
    const sample = Math.max(-1, Math.min(1, input[sourceIndex] ?? 0));
    view.setInt16(44 + index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return wav;
}

function writeAscii(buffer: Uint8Array, offset: number, text: string): void {
  for (let index = 0; index < text.length; index += 1) {
    buffer[offset + index] = text.charCodeAt(index);
  }
}

function progressThinkingTitle(content: string): string {
  if (/^\s*query\s*:/i.test(content)) return "正在理解你的问题";
  if (/retriev(?:ing|ed|e complete)/i.test(content)) {
    return /retrieving/i.test(content) ? "正在查找知识库内容" : "已找到可参考内容";
  }
  return "正在理解问题并规划回答";
}

export function formatConversationThinkingForPeople(
  type: string,
  payload: Record<string, unknown> = {},
): ConversationThinkingDisplay | null {
  if (type === "thinking") {
    return {
      kind: "thinking",
      title: "思考中",
      content: safeThinkingText(payload.content),
      appendToPrevious: true,
    };
  }
  if (type === "progress") {
    const content = safeThinkingText(payload.content);
    return {
      kind: "progress",
      title: progressThinkingTitle(content),
      content: "",
      appendToPrevious: false,
    };
  }
  if (type === "tool_call") {
    const toolName = String(payload.tool_name ?? payload.tool ?? payload.name ?? "");
    return {
      kind: "tool_call",
      title: toolName === "rag" ? "正在查找知识库内容" : "正在调用辅助能力",
      content: "",
      appendToPrevious: false,
    };
  }
  if (type === "sources") {
    return {
      kind: "sources",
      title: "已找到可参考内容",
      content: "",
      appendToPrevious: false,
    };
  }
  return null;
}

export function shouldShowConversationLoginLanding(input: {
  demoSession?: string | null;
  isAuthenticated: boolean;
  loadingAuth: boolean;
  authError?: string | null;
}): boolean {
  if (!input.demoSession) return true;
  return !input.loadingAuth && !input.isAuthenticated && Boolean(input.authError);
}
