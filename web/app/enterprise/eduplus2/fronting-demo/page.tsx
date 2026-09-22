"use client";

import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  AuthStatusPayload,
  buildAuthRefreshCommand,
  buildDemoStartTurnCommand,
  buildDemoWebSocketUrl,
  buildEduPlus2DemoStartUrl,
  buildWebSocketProtocols,
  defaultDemoSteps,
  DemoResultPayload,
  DemoStep,
  EDUPLUS2_FRONTING_DEMO_REFRESH_PATH,
  hashIdentifier,
  mergeProbeStep,
  mergeStepStatus,
  normalizeDemoResourceIds,
  shouldRefreshToken,
} from "@/lib/eduplus2-fronting-demo";

type ProbeState = {
  status: "idle" | "pending" | "success" | "failed";
  authenticated?: boolean;
  role?: string;
  userHash?: string;
  message?: string;
};

type ResourceUploadStatus =
  | "queued"
  | "hashing"
  | "intent"
  | "uploading"
  | "completing"
  | "done"
  | "failed";

type ResourceUploadItem = {
  clientId: string;
  filename: string;
  mimeType: string;
  modality: "file" | "image" | "audio" | "video" | "document";
  sizeBytes: number;
  sha256?: string;
  resourceId?: string;
  status: ResourceUploadStatus;
  message?: string;
};

type UploadIntentResponse = {
  resource_id: string;
  object_id?: string;
  resource_kind?: string;
  upload_url: string;
  headers?: Record<string, string>;
  expires_in?: number;
  constraints?: Record<string, unknown>;
};

type CompleteUploadResponse = {
  resource_id: string;
  object_id?: string;
  resource_kind?: string;
  state?: string;
  size_bytes?: number;
  sha256?: string;
  mime_type?: string;
};

const STATUS_STYLES: Record<string, string> = {
  idle: "border-slate-200 bg-white/80 text-slate-600 dark:border-slate-800 dark:bg-slate-950/60 dark:text-slate-300",
  pending:
    "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100",
  done: "border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-100",
  success:
    "border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-100",
  failed:
    "border-rose-200 bg-rose-50 text-rose-950 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-100",
  skipped:
    "border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-400",
};

const ERRORS = [
  ["config_missing", "检查 DT_EDUPLUS2_AUTHORIZATION_ENDPOINT/TOKEN_ENDPOINT/CLIENT_ID/SECRET_REF。"],
  ["state_invalid", "state 已过期或回跳不是本次 demo 启动生成；请重新点击测试按钮。"],
  ["authorization_denied", "EduPlus2 登录或授权被拒绝；请确认测试账号和 client 授权。"],
  ["code_missing", "callback 未携带 authorization code；请检查 response_type=code。"],
  ["service_unavailable", "EduPlus2 token endpoint 或 DeepTutor exchange 后端不可用。"],
  ["deeptutor_unauthorized", "DeepTutor 拒绝 EduPlus2 user JWT；请检查 issuer/JWKS/claims。"],
  ["deeptutor_forbidden", "client/app/tenant 未注册或处于 inactive/suspended 状态。"],
  ["deeptutor_tenant_mismatch", "JWT tid 与已注册 client/tenant 不一致。"],
  ["deeptutor_rate_limited", "同一用户/client 触发限流或 replay 防护；请稍后重试。"],
] as const;

const RESOURCE_IDS_STORAGE_KEY = "deeptutor.eduplus2.frontingDemo.resourceIds.v1";

function statusLabel(status: string): string {
  return (
    {
      idle: "等待",
      pending: "进行中",
      done: "完成",
      success: "成功",
      failed: "失败",
      skipped: "跳过",
    }[status] ?? status
  );
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function webSocketUrl(): string {
  return buildDemoWebSocketUrl(window.location);
}

function detectUploadModality(file: File): ResourceUploadItem["modality"] {
  const mime = (file.type || "").toLowerCase();
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("audio/")) return "audio";
  if (mime.startsWith("video/")) return "video";
  if (
    mime.startsWith("text/") ||
    mime === "application/pdf" ||
    mime.includes("document") ||
    mime.includes("presentation") ||
    mime.includes("spreadsheet")
  ) {
    return "document";
  }
  return "file";
}

function makeUploadItem(file: File, index: number): ResourceUploadItem {
  return {
    clientId: `${file.name}:${file.size}:${file.lastModified}:${index}`,
    filename: file.name || `upload-${index + 1}.bin`,
    mimeType: file.type || "application/octet-stream",
    modality: detectUploadModality(file),
    sizeBytes: file.size,
    status: "queued",
  };
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function uploadStatusLabel(status: ResourceUploadStatus): string {
  return (
    {
      queued: "等待上传",
      hashing: "计算 SHA-256",
      intent: "申请 upload intent",
      uploading: "直传 ObjectStore",
      completing: "完成确认",
      done: "完成",
      failed: "失败",
    }[status] ?? status
  );
}

async function sha256Hex(file: File): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("当前浏览器不支持 SHA-256 计算，无法申请受控上传。");
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(digest)]
    .map((item) => item.toString(16).padStart(2, "0"))
    .join("");
}

function browserUploadHeaders(headers: Record<string, string> | undefined): Record<string, string> {
  const safe: Record<string, string> = {};
  for (const [name, value] of Object.entries(headers ?? {})) {
    const lower = name.toLowerCase();
    if (lower === "host" || lower === "content-length") continue;
    safe[lower] = String(value);
  }
  return safe;
}

function appendResourceIds(current: string, resourceIds: string[]): string {
  return normalizeDemoResourceIds([...normalizeDemoResourceIds(current), ...resourceIds]).join(", ");
}

function completedUploadResourceIds(items: ResourceUploadItem[]): string[] {
  return normalizeDemoResourceIds(
    items
      .filter((item) => item.status === "done" && item.resourceId)
      .map((item) => item.resourceId || ""),
  );
}

function collectOutboundResourceIds(
  resourceIdsInput: string,
  uploadItems: ResourceUploadItem[],
): string[] {
  return normalizeDemoResourceIds([
    ...normalizeDemoResourceIds(resourceIdsInput),
    ...completedUploadResourceIds(uploadItems),
  ]);
}

function readStoredResourceIds(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(RESOURCE_IDS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) return normalizeDemoResourceIds(parsed.map(String));
    if (typeof parsed === "string") return normalizeDemoResourceIds(parsed);
  } catch {
    return [];
  }
  return [];
}

function storeResourceIds(resourceIds: string[] | string) {
  if (typeof window === "undefined") return;
  try {
    const normalized = normalizeDemoResourceIds(resourceIds);
    if (normalized.length) {
      window.sessionStorage.setItem(
        RESOURCE_IDS_STORAGE_KEY,
        JSON.stringify(normalized),
      );
    } else {
      window.sessionStorage.removeItem(RESOURCE_IDS_STORAGE_KEY);
    }
  } catch {
    // sessionStorage 在隐私模式或受限 WebView 中可能不可用；资源仍通过当前页面状态发送。
  }
}


function withResourceUploadStep(steps: DemoStep[]): DemoStep[] {
  if (steps.some((step) => step.id === "resource_upload")) return steps;
  const next: DemoStep[] = [];
  for (const step of steps) {
    next.push(step);
    if (step.id === "api_probe") {
      next.push({
        id: "resource_upload",
        label: "Resource Upload Reference",
        status: "idle",
      });
    }
  }
  return next;
}

function formatDemoError(summary: Record<string, unknown>, fallback: string): string {
  const reason = String(summary.reason || fallback || "demo_result_failed");
  const detail = String(summary.detail || "");
  return detail && detail !== reason ? `${reason}（${detail}）` : reason;
}

export default function EduPlus2FrontingDemoPage() {
  const [steps, setSteps] = useState<DemoStep[]>(() => defaultDemoSteps());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [requestId, setRequestId] = useState("");
  const [summary, setSummary] = useState<Record<string, unknown>>({});
  const [probe, setProbe] = useState<ProbeState>({ status: "idle" });
  const [resultExpiresAt, setResultExpiresAt] = useState<number | null>(null);
  const [tokenExpiresAt, setTokenExpiresAt] = useState<number | null>(null);
  const [demoSession, setDemoSession] = useState("");
  const [dtToken, setDtToken] = useState("");
  const [refreshMessage, setRefreshMessage] = useState("等待 token 倒计时。");
  const [chatPrompt, setChatPrompt] = useState("请用一句话介绍 DeepTutor。");
  const [resourceIdsInput, setResourceIdsInput] = useState(() =>
    readStoredResourceIds().join(", "),
  );
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadItems, setUploadItems] = useState<ResourceUploadItem[]>([]);
  const [resourceUploadBusy, setResourceUploadBusy] = useState(false);
  const [resourceUploadMessage, setResourceUploadMessage] = useState(
    "请选择图片、音频、视频或文档文件；demo 会先走 HTTP pre-signed upload。",
  );
  const [wsState, setWsState] = useState<"idle" | "connecting" | "open" | "closed" | "failed">("idle");
  const [chatEvents, setChatEvents] = useState<string[]>([]);
  const [assistantText, setAssistantText] = useState("");
  const socketRef = useRef<WebSocket | null>(null);

  const startUrl = useMemo(() => {
    if (typeof window === "undefined") return "";
    return buildEduPlus2DemoStartUrl(
      `${window.location.origin}/enterprise/eduplus2/fronting-demo`,
    );
  }, []);

  const refreshToken = useCallback(
    async (reason = "scheduled") => {
      if (!demoSession) {
        setRefreshMessage("缺少 demo_session，无法自动续签。");
        return null;
      }
      setRefreshMessage(`正在续签 dt_token（${reason}）…`);
      setSteps((prev) => mergeStepStatus(prev, "token_refresh", "pending"));
      try {
        const response = await fetch(EDUPLUS2_FRONTING_DEMO_REFRESH_PATH, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ demo_session: demoSession }),
        });
        const payload = await readJson<DemoResultPayload>(response);
        if (!payload.dt_token) {
          throw new Error("refresh response missing dt_token");
        }
        setDtToken(payload.dt_token);
        setTokenExpiresAt(payload.expires_at ?? null);
        setResultExpiresAt(payload.expires_at ?? null);
        setSummary(payload.summary ?? {});
        setSteps((prev) => mergeStepStatus(prev, "token_refresh", "done"));
        const socket = socketRef.current;
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(
            JSON.stringify(buildAuthRefreshCommand(payload.dt_token)),
          );
          setRefreshMessage("已签发新 dt_token，并已向 WebSocket 发送 auth_refresh。");
        } else {
          setRefreshMessage("已签发新 dt_token；WebSocket 未连接时将在下次对话使用新 token。");
        }
        return payload;
      } catch (err) {
        setSteps((prev) =>
          mergeStepStatus(prev, "token_refresh", "failed", "refresh_failed"),
        );
        setRefreshMessage(err instanceof Error ? err.message : "refresh failed");
        return null;
      }
    },
    [demoSession],
  );

  async function runProbe(token: string, currentSteps: DemoStep[]) {
    setProbe({ status: "pending", message: "正在调用 /api/auth/status…" });
    setSteps(mergeProbeStep(currentSteps, "pending"));
    try {
      const response = await fetch("/api/auth/status", {
        credentials: "include",
        headers: { Authorization: `Bearer ${token}` },
      });
      const status = await readJson<AuthStatusPayload>(response);
      const userHash = await hashIdentifier(status.user_id || status.username || "");
      if (!status.authenticated) {
        setProbe({
          status: "failed",
          authenticated: false,
          message: "DeepTutor API 未接受该 dt_token。",
        });
        setSteps(mergeProbeStep(currentSteps, "failed", "api_status_unauthenticated"));
        return;
      }
      setProbe({
        status: "success",
        authenticated: true,
        role: status.role || "user",
        userHash,
        message: "DeepTutor API 已接受 dt_token。",
      });
      setSteps(mergeProbeStep(currentSteps, "done"));
    } catch (err) {
      setProbe({
        status: "failed",
        message: err instanceof Error ? err.message : "API probe failed",
      });
      setSteps(mergeProbeStep(currentSteps, "failed", "api_probe_failed"));
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const demoError = params.get("demo_error");
    if (demoError) {
      setError(demoError);
      setSteps([
        { id: "redirect", label: "EduPlus2 Redirect", status: "done" },
        {
          id: "code_exchange",
          label: "Authorization Code Token Exchange",
          status: "failed",
          reason: demoError,
        },
        {
          id: "deeptutor_exchange",
          label: "DeepTutor Token Exchange",
          status: "skipped",
        },
        { id: "api_probe", label: "DeepTutor API Probe", status: "skipped" },
        {
          id: "resource_upload",
          label: "Resource Upload Reference",
          status: "skipped",
        },
        { id: "ws_chat", label: "DeepTutor WebSocket Chat", status: "skipped" },
        { id: "token_refresh", label: "Token Refresh", status: "skipped" },
      ]);
      return;
    }
    const session = params.get("demo_session");
    if (!session) return;
    setDemoSession(session);
    let cancelled = false;
    setBusy(true);
    setSteps([
      { id: "redirect", label: "EduPlus2 Redirect", status: "done" },
      {
        id: "code_exchange",
        label: "Authorization Code Token Exchange",
        status: "pending",
      },
      {
        id: "deeptutor_exchange",
        label: "DeepTutor Token Exchange",
        status: "pending",
      },
      { id: "api_probe", label: "DeepTutor API Probe", status: "idle" },
      {
        id: "resource_upload",
        label: "Resource Upload Reference",
        status: "idle",
      },
      { id: "ws_chat", label: "DeepTutor WebSocket Chat", status: "idle" },
      { id: "token_refresh", label: "Token Refresh", status: "idle" },
    ]);
    (async () => {
      try {
        const response = await fetch(
          `/api/v1/auth/eduplus2/demo/result?demo_session=${encodeURIComponent(session)}`,
          { credentials: "include" },
        );
        const payload = await readJson<DemoResultPayload>(response);
        if (cancelled) return;
        const nextSteps = withResourceUploadStep(
          payload.steps?.length ? payload.steps : defaultDemoSteps(),
        );
        setSteps(nextSteps);
        setRequestId(payload.request_id || "");
        setSummary(payload.summary ?? {});
        setResultExpiresAt(payload.expires_at ?? null);
        setTokenExpiresAt(payload.expires_at ?? null);
        if (!payload.ok || !payload.dt_token) {
          setError(formatDemoError(payload.summary ?? {}, "demo_result_failed"));
          return;
        }
        setDtToken(payload.dt_token);
        await runProbe(payload.dt_token, nextSteps);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Demo result failed");
          setSteps(mergeProbeStep(defaultDemoSteps(), "failed", "result_unavailable"));
        }
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!demoSession || !tokenExpiresAt || !dtToken) return undefined;
    const nowSeconds = Math.floor(Date.now() / 1000);
    if (shouldRefreshToken({ nowSeconds, expiresAt: tokenExpiresAt, leewaySeconds: 30 })) {
      void refreshToken("expired-or-near-expiry");
      return undefined;
    }
    const delayMs = Math.max(0, (tokenExpiresAt - 30 - nowSeconds) * 1000);
    const handle = window.setTimeout(() => {
      void refreshToken("timer");
    }, delayMs);
    return () => window.clearTimeout(handle);
  }, [demoSession, dtToken, refreshToken, tokenExpiresAt]);

  useEffect(
    () => () => {
      socketRef.current?.close(1000, "demo page unmounted");
      socketRef.current = null;
    },
    [],
  );

  function start() {
    if (!startUrl) return;
    window.location.assign(startUrl);
  }

  function updateUploadItem(clientId: string, patch: Partial<ResourceUploadItem>) {
    setUploadItems((prev) =>
      prev.map((item) => (item.clientId === clientId ? { ...item, ...patch } : item)),
    );
  }

  function onResourceFilesSelected(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    setSelectedFiles(files);
    setUploadItems(files.map(makeUploadItem));
    setResourceUploadMessage(
      files.length
        ? `已选择 ${files.length} 个文件；点击上传后将依次申请 upload intent、直传 ObjectStore 并完成确认。`
        : "请选择图片、音频、视频或文档文件；demo 会先走 HTTP pre-signed upload。",
    );
  }

  async function uploadSelectedResources() {
    if (!dtToken) {
      setError("需要先完成 EduPlus2 统一认证并获得 dt_token，才能申请上传授权。");
      return;
    }
    if (!selectedFiles.length) {
      setResourceUploadMessage("请先选择要上传的文件。");
      return;
    }
    setError("");
    setResourceUploadBusy(true);
    setResourceUploadMessage("正在执行 HTTP pre-signed upload 链路…");
    setSteps((prev) => mergeStepStatus(prev, "resource_upload", "pending"));
    const completedResourceIds: string[] = [];
    let failed = false;

    for (const [index, file] of selectedFiles.entries()) {
      const item = uploadItems[index] ?? makeUploadItem(file, index);
      try {
        updateUploadItem(item.clientId, { status: "hashing", message: "计算本地 SHA-256…" });
        const sha256 = await sha256Hex(file);
        updateUploadItem(item.clientId, { sha256, status: "intent", message: "申请 upload intent…" });
        const intentResponse = await fetch("/api/v1/resources/upload-intents", {
          method: "POST",
          credentials: "include",
          headers: {
            Authorization: `Bearer ${dtToken}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            modality: detectUploadModality(file),
            mime_type: file.type || "application/octet-stream",
            size_bytes: file.size,
            sha256,
            purpose: "chat_turn",
            session_id: "",
            filename: file.name || "upload.bin",
            expires_seconds: 900,
          }),
        });
        const intent = await readJson<UploadIntentResponse>(intentResponse);
        updateUploadItem(item.clientId, {
          resourceId: intent.resource_id,
          status: "uploading",
          message: `直传 ObjectStore（TTL ${intent.expires_in ?? "—"}s）…`,
        });
        const uploadResponse = await fetch(intent.upload_url, {
          method: "PUT",
          headers: browserUploadHeaders(intent.headers),
          body: file,
        });
        if (!uploadResponse.ok) {
          throw new Error(`upload HTTP ${uploadResponse.status}`);
        }
        updateUploadItem(item.clientId, { status: "completing", message: "确认上传完成…" });
        const completedResponse = await fetch(
          `/api/v1/resources/upload-intents/${encodeURIComponent(intent.resource_id)}/complete`,
          {
            method: "POST",
            credentials: "include",
            headers: {
              Authorization: `Bearer ${dtToken}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ resource_kind: intent.resource_kind || "turn_input" }),
          },
        );
        const completed = await readJson<CompleteUploadResponse>(completedResponse);
        const resourceId = completed.resource_id || intent.resource_id;
        completedResourceIds.push(resourceId);
        updateUploadItem(item.clientId, {
          resourceId,
          status: "done",
          message: `ready / ${completed.mime_type || file.type || "application/octet-stream"}`,
        });
      } catch (err) {
        failed = true;
        updateUploadItem(item.clientId, {
          status: "failed",
          message: err instanceof Error ? err.message : "upload failed",
        });
      }
    }

    if (completedResourceIds.length) {
      setResourceIdsInput((prev) => {
        const next = appendResourceIds(prev, completedResourceIds);
        storeResourceIds(next);
        return next;
      });
    }
    setResourceUploadBusy(false);
    if (failed) {
      setSteps((prev) => mergeStepStatus(prev, "resource_upload", "failed", "upload_failed"));
      setResourceUploadMessage("部分资源上传失败；失败资源不会加入 WebSocket resource_ids。");
      return;
    }
    setSteps((prev) => mergeStepStatus(prev, "resource_upload", "done"));
    setResourceUploadMessage(
      `资源已完成上传确认：${completedResourceIds.join(", ")}。WebSocket 将只发送 resource_ids。`,
    );
  }

  async function startWsConversation() {
    let tokenForSocket = dtToken;
    if (!tokenForSocket) {
      setError("需要先完成 EduPlus2 统一认证并获得 dt_token。");
      return;
    }
    const prompt = chatPrompt.trim();
    if (!prompt) {
      setError("请输入要发送给 DeepTutor 的对话内容。");
      return;
    }
    if (resourceUploadBusy) {
      setError("资源仍在上传或完成确认中，请等待上传完成后再开始 WebSocket 对话。");
      return;
    }
    const resourceIdsForTurn = collectOutboundResourceIds(resourceIdsInput, uploadItems);
    if (resourceIdsForTurn.length) {
      const normalizedInput = resourceIdsForTurn.join(", ");
      if (normalizedInput !== resourceIdsInput) {
        setResourceIdsInput(normalizedInput);
      }
      storeResourceIds(resourceIdsForTurn);
    }
    if (
      probe.authenticated !== true ||
      shouldRefreshToken({
        nowSeconds: Math.floor(Date.now() / 1000),
        expiresAt: tokenExpiresAt,
        leewaySeconds: 15,
      })
    ) {
      const refreshed = await refreshToken(
        probe.authenticated === true ? "before-ws-chat" : "api-probe-rejected-before-ws",
      );
      if (!refreshed?.dt_token) {
        setWsState("failed");
        setSteps((prev) => mergeStepStatus(prev, "ws_chat", "failed", "auth_refresh_failed"));
        setError("当前 dt_token 不可用且续签失败；请重新点击 EduPlus2 统一认证测试。");
        return;
      }
      tokenForSocket = refreshed.dt_token;
    }
    socketRef.current?.close(1000, "restart demo chat");
    setError("");
    setAssistantText("");
    setChatEvents([]);
    setWsState("connecting");
    setSteps((prev) => mergeStepStatus(prev, "ws_chat", "pending"));
    const socket = new WebSocket(webSocketUrl(), buildWebSocketProtocols(tokenForSocket));
    socketRef.current = socket;
    socket.addEventListener("open", () => {
      setWsState("open");
      setChatEvents((prev) => [...prev, "ws.open"]);
      socket.send(
        JSON.stringify(buildDemoStartTurnCommand(prompt, resourceIdsForTurn)),
      );
    });
    socket.addEventListener("message", (event) => {
      try {
        const data = JSON.parse(String(event.data)) as Record<string, unknown>;
        const type = String(data.type || "unknown");
        if (type === "content" && typeof data.content === "string") {
          setAssistantText((prev) => prev + data.content);
        }
        if (type === "done") {
          setSteps((prev) => mergeStepStatus(prev, "ws_chat", "done"));
        }
        if (type === "auth_ack") {
          setRefreshMessage("WebSocket 已确认新 dt_token（auth_ack）。");
        }
        if (type === "auth_revoked" || type === "protocol_error" || type === "error") {
          setSteps((prev) => mergeStepStatus(prev, "ws_chat", "failed", type));
        }
        setChatEvents((prev) => [
          `${type}${data.stage ? `:${String(data.stage)}` : ""}`,
          ...prev,
        ].slice(0, 18));
      } catch {
        setChatEvents((prev) => ["invalid-json-frame", ...prev].slice(0, 18));
      }
    });
    socket.addEventListener("close", () => {
      setWsState("closed");
      setChatEvents((prev) => ["ws.close", ...prev].slice(0, 18));
    });
    socket.addEventListener("error", () => {
      setWsState("failed");
      setSteps((prev) => mergeStepStatus(prev, "ws_chat", "failed", "socket_error"));
    });
  }

  return (
    <main
      data-testid="eduplus2-fronting-demo-scroll-root"
      className="h-full overflow-y-auto bg-[radial-gradient(circle_at_12%_10%,rgba(45,212,191,0.24),transparent_28rem),radial-gradient(circle_at_86%_12%,rgba(251,191,36,0.22),transparent_28rem),linear-gradient(135deg,#f8fafc,#ecfeff_42%,#f8fafc)] px-6 py-10 text-slate-950 [scrollbar-gutter:stable] dark:bg-[radial-gradient(circle_at_12%_10%,rgba(20,184,166,0.22),transparent_28rem),radial-gradient(circle_at_86%_12%,rgba(245,158,11,0.16),transparent_28rem),linear-gradient(135deg,#020617,#042f2e_46%,#0f172a)] dark:text-white"
    >
      <section className="mx-auto flex max-w-7xl flex-col gap-6">
        <div className="grid gap-5 lg:grid-cols-[1.25fr_0.75fr]">
          <section className="relative overflow-hidden rounded-[2.25rem] border border-white/70 bg-white/80 p-8 shadow-[0_30px_100px_rgba(15,23,42,0.14)] backdrop-blur dark:border-white/10 dark:bg-slate-950/70">
            <div className="absolute right-8 top-8 h-24 w-24 rounded-full border border-teal-200/70 bg-[repeating-linear-gradient(135deg,rgba(20,184,166,0.24)_0_2px,transparent_2px_8px)] dark:border-teal-400/20" />
            <p className="text-xs font-black uppercase tracking-[0.34em] text-teal-700 dark:text-teal-200">
              Fronting app integration console
            </p>
            <h1 className="mt-4 max-w-3xl text-4xl font-black tracking-tight md:text-6xl">
              EduPlus2 统一认证前置应用 Demo
            </h1>
            <p className="mt-5 max-w-3xl text-sm leading-7 text-slate-600 dark:text-slate-300">
              点击后会跳转到 EduPlus2 authorization endpoint。回跳时由 DeepTutor demo
              后端换取 EduPlus2 user JWT，复用现有 exchange，再用 dt_token 调用
              DeepTutor API 做真实探针，并通过 /api/v1/ws 发起一轮可视化对话；资源类输入先走
              pre-signed upload，WebSocket 只提交 prompt + resource_ids。
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={start}
                className="rounded-2xl bg-slate-950 px-6 py-3 text-sm font-black text-white shadow-xl shadow-teal-900/15 transition hover:-translate-y-0.5 hover:shadow-2xl disabled:cursor-not-allowed disabled:opacity-60 dark:bg-teal-300 dark:text-slate-950"
                disabled={busy}
              >
                使用 EduPlus2 统一认证测试
              </button>
              <a
                className="rounded-2xl border border-slate-200 bg-white/80 px-5 py-3 text-sm font-bold text-slate-700 transition hover:-translate-y-0.5 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-200"
                href="/enterprise/audit/eduplus2"
              >
                查看 EduPlus2 审计
              </a>
            </div>
            <p className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs font-semibold leading-6 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
              仅用于 local/test 联调；不代表 TMS/OMS、生产 Handoff/OIDC callback、在线
              client 治理、实时撤权 SLA 或生产上线完成。
            </p>
          </section>

          <aside className="rounded-[2.25rem] border border-slate-200 bg-slate-950 p-6 text-white shadow-[0_30px_100px_rgba(15,23,42,0.18)] dark:border-slate-800">
            <p className="text-xs font-black uppercase tracking-[0.28em] text-teal-200">
              Current trace
            </p>
            <dl className="mt-5 space-y-4 text-sm">
              <div>
                <dt className="text-slate-400">Request ID</dt>
                <dd className="mt-1 font-mono text-xs text-slate-100">{requestId || "—"}</dd>
              </div>
              <div>
                <dt className="text-slate-400">Demo result expires</dt>
                <dd className="mt-1 font-mono text-xs text-slate-100">
                  {resultExpiresAt ? new Date(resultExpiresAt * 1000).toLocaleString() : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-slate-400">Token handling</dt>
                <dd className="mt-1 text-xs leading-6 text-slate-200">
                  dt_token 仅存在页面运行时内存，用于 API probe 与 WebSocket 对话；不会写入
                  localStorage/sessionStorage，也不会在页面或 URL 中渲染原文。
                </dd>
              </div>
            </dl>
          </aside>
        </div>

        {error ? (
          <div className="rounded-[1.5rem] border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-950 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-100">
            当前错误：{error}
          </div>
        ) : null}

        <section className="grid gap-4 md:grid-cols-3 xl:grid-cols-7">
          {steps.map((step, index) => (
            <article
              key={step.id}
              className={`rounded-[1.6rem] border p-5 shadow-sm ${STATUS_STYLES[step.status]}`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-950 text-xs font-black text-white dark:bg-white dark:text-slate-950">
                  {index + 1}
                </span>
                <span className="rounded-full bg-white/70 px-3 py-1 text-[11px] font-black uppercase tracking-[0.16em] dark:bg-slate-950/50">
                  {statusLabel(step.status)}
                </span>
              </div>
              <h2 className="mt-4 text-lg font-black">{step.label}</h2>
              <p className="mt-2 text-xs leading-6 opacity-80">
                {step.reason ? `reason=${step.reason}` : "等待链路推进并记录脱敏状态。"}
              </p>
            </article>
          ))}
        </section>

        <section className="grid gap-5 lg:grid-cols-[0.95fr_1.05fr]">
          <div className="rounded-[2rem] border border-slate-200 bg-white/85 p-6 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/70">
            <p className="text-xs font-black uppercase tracking-[0.24em] text-slate-500">
              DeepTutor API Probe
            </p>
            <h2 className="mt-3 text-2xl font-black">
              {probe.message || "等待 callback result"}
            </h2>
            <div className="mt-4 grid gap-3 text-sm md:grid-cols-3">
              <div className="rounded-2xl bg-slate-100 p-4 dark:bg-slate-900">
                <div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">
                  Authenticated
                </div>
                <div className="mt-2 font-black">{String(probe.authenticated ?? "—")}</div>
              </div>
              <div className="rounded-2xl bg-slate-100 p-4 dark:bg-slate-900">
                <div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">
                  Role
                </div>
                <div className="mt-2 font-black">{probe.role || "—"}</div>
              </div>
              <div className="rounded-2xl bg-slate-100 p-4 dark:bg-slate-900">
                <div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">
                  User hash
                </div>
                <div className="mt-2 truncate font-mono text-xs">{probe.userHash || "—"}</div>
              </div>
            </div>
          </div>

          <div className="rounded-[2rem] border border-slate-200 bg-white/85 p-6 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/70">
            <p className="text-xs font-black uppercase tracking-[0.24em] text-slate-500">
              Redacted exchange summary
            </p>
            <div className="mt-4 grid gap-3 text-sm md:grid-cols-2">
              {[
                ["client_id", summary.client_id],
                ["external_user_hash", summary.external_user_hash],
                ["internal_user_hash", summary.internal_user_hash],
                ["external_tenant_hash", summary.external_tenant_hash],
                ["client_registration_hash", summary.client_registration_hash],
                ["expires_at", summary.expires_at],
                ["selected_token", summary.selected_token],
                ["detail", summary.detail],
                ["selected_header_alg", summary.selected_header_alg],
                ["selected_header_kid_hash", summary.selected_header_kid_hash],
                ["selected_claim_issuer", summary.selected_claim_issuer],
                ["selected_claim_audience", summary.selected_claim_audience],
                ["selected_claim_azp", summary.selected_claim_azp],
                ["claim_iat_delta_seconds", summary.selected_claim_iat_delta_seconds],
                ["claim_nbf_delta_seconds", summary.selected_claim_nbf_delta_seconds],
                ["claim_exp_delta_seconds", summary.selected_claim_exp_delta_seconds],
              ].map(([key, value]) => (
                <div key={String(key)} className="rounded-2xl bg-slate-100 p-4 dark:bg-slate-900">
                  <div className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
                    {String(key)}
                  </div>
                  <div className="mt-2 truncate font-mono text-xs">{String(value || "—")}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-5 lg:grid-cols-[1.15fr_0.85fr]">
          <div className="rounded-[2rem] border border-slate-200 bg-white/85 p-6 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/70">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-black uppercase tracking-[0.24em] text-slate-500">
                  WebSocket chat
                </p>
                <h2 className="mt-2 text-2xl font-black">真实 /api/v1/ws 对话测试</h2>
              </div>
              <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-black text-white dark:bg-teal-300 dark:text-slate-950">
                {wsState}
              </span>
            </div>
            <div className="mt-5 rounded-[1.6rem] border border-teal-200 bg-teal-50/80 p-4 dark:border-teal-900/70 dark:bg-teal-950/25">
              <div className="grid gap-4 lg:grid-cols-[0.82fr_1.18fr]">
                <div>
                  <p className="text-xs font-black uppercase tracking-[0.2em] text-teal-700 dark:text-teal-200">
                    Resource upload for this turn
                  </p>
                  <p className="mt-2 text-xs leading-6 text-teal-950/80 dark:text-teal-50/85">
                    先在这里选择文件并点击上传并登记资源；页面会走 upload intent、pre-signed
                    PUT 和 complete，随后“开始 WebSocket 对话”只提交 prompt + resource_ids。
                  </p>
                  <div className="mt-3">
                    <p
                      id="eduplus2-resource-upload-label"
                      className="text-xs font-black uppercase tracking-[0.16em] text-teal-800 dark:text-teal-100"
                    >
                      选择图片、音频、视频或文档文件
                    </p>
                    <div className="mt-2 grid gap-3 rounded-3xl border border-dashed border-teal-300 bg-white/90 p-3 dark:border-teal-900 dark:bg-slate-950">
                      <input
                        id="eduplus2-resource-upload-input"
                        type="file"
                        multiple
                        aria-labelledby="eduplus2-resource-upload-label"
                        onChange={onResourceFilesSelected}
                        className="block w-full cursor-pointer rounded-2xl border border-teal-200 bg-white px-3 py-2 text-xs font-semibold normal-case tracking-normal text-teal-950 shadow-sm file:mr-4 file:cursor-pointer file:rounded-xl file:border-0 file:bg-teal-700 file:px-4 file:py-2 file:text-xs file:font-black file:text-white hover:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500 dark:border-teal-900 dark:bg-slate-950 dark:text-teal-50 dark:file:bg-teal-300 dark:file:text-slate-950"
                      />
                      <span className="text-xs font-semibold normal-case tracking-normal text-teal-950/75 dark:text-teal-50/80">
                        {selectedFiles.length
                          ? `已选择 ${selectedFiles.length} 个文件`
                          : "支持图片、音频、视频和文档；请直接点击上方原生文件选择控件。"}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="rounded-3xl border border-teal-200 bg-white/75 p-4 dark:border-teal-900/70 dark:bg-slate-950/50">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-xs font-semibold leading-6 text-teal-950 dark:text-teal-50/90">
                      {resourceUploadMessage}
                    </p>
                    <button
                      type="button"
                      onClick={() => void uploadSelectedResources()}
                      disabled={!dtToken || !selectedFiles.length || resourceUploadBusy}
                      className="rounded-2xl bg-teal-700 px-5 py-3 text-xs font-black text-white shadow-lg shadow-teal-900/10 transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-teal-300 dark:text-slate-950"
                    >
                      {resourceUploadBusy ? "上传中…" : "上传并登记资源"}
                    </button>
                  </div>
                  <div className="mt-4 grid gap-2">
                    {uploadItems.length ? (
                      uploadItems.map((item) => (
                        <article
                          key={item.clientId}
                          className="rounded-2xl border border-teal-100 bg-teal-50/70 p-3 text-xs text-teal-950 dark:border-teal-900 dark:bg-teal-950/30 dark:text-teal-50"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-black">{item.filename}</span>
                            <span className="rounded-full bg-white/80 px-3 py-1 font-black dark:bg-slate-950/60">
                              {uploadStatusLabel(item.status)}
                            </span>
                          </div>
                          <div className="mt-2 flex flex-wrap gap-2 font-mono text-[11px] opacity-80">
                            <span>{item.modality}</span>
                            <span>{item.mimeType}</span>
                            <span>{formatBytes(item.sizeBytes)}</span>
                            {item.sha256 ? <span>sha256:{item.sha256.slice(0, 12)}…</span> : null}
                            {item.resourceId ? <span>{item.resourceId}</span> : null}
                          </div>
                          {item.message ? (
                            <p className="mt-2 text-[11px] leading-5 opacity-80">{item.message}</p>
                          ) : null}
                        </article>
                      ))
                    ) : (
                      <p className="rounded-2xl border border-dashed border-teal-200 p-3 text-xs leading-6 text-teal-900/75 dark:border-teal-900 dark:text-teal-100/80">
                        尚未选择文件；也可以在下方手动粘贴已完成上传的 resource_id 用于 WS 验证。
                      </p>
                    )}
                  </div>
                </div>
              </div>
              <label className="mt-4 block text-xs font-black uppercase tracking-[0.18em] text-teal-800 dark:text-teal-100">
                已完成上传的 resource_ids（可选，逗号或换行分隔）
                <textarea
                  className="mt-2 min-h-20 w-full rounded-3xl border border-teal-200 bg-white p-4 font-mono text-xs normal-case tracking-normal text-slate-950 outline-none transition focus:border-teal-500 focus:ring-4 focus:ring-teal-100 dark:border-teal-900 dark:bg-slate-950 dark:text-teal-50 dark:focus:ring-teal-950"
                  placeholder="res_img_001, res_audio_002"
                  value={resourceIdsInput}
                  onChange={(event) => {
                    const next = event.target.value;
                    setResourceIdsInput(next);
                    storeResourceIds(next);
                  }}
                />
                <span className="mt-2 block text-[11px] leading-5 text-teal-900/75 dark:text-teal-100/80">
                  当前 demo 只提交 DeepTutor 已发行的资源引用；不要粘贴 URL、base64、signed upload URL 或 S3 key。
                </span>
              </label>
            </div>
            <label className="mt-5 block text-xs font-black uppercase tracking-[0.18em] text-slate-500">
              Prompt
              <textarea
                className="mt-2 min-h-24 w-full rounded-3xl border border-slate-200 bg-white p-4 text-sm normal-case tracking-normal text-slate-950 outline-none transition focus:border-teal-400 focus:ring-4 focus:ring-teal-100 dark:border-slate-800 dark:bg-slate-900 dark:text-white dark:focus:ring-teal-950"
                value={chatPrompt}
                onChange={(event) => setChatPrompt(event.target.value)}
              />
            </label>
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void startWsConversation()}
                disabled={!dtToken || resourceUploadBusy}
                className="rounded-2xl bg-teal-600 px-5 py-3 text-sm font-black text-white shadow-lg shadow-teal-900/15 transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-teal-300 dark:text-slate-950"
              >
                开始 WebSocket 对话
              </button>
              <button
                type="button"
                onClick={() => void refreshToken("manual-demo")}
                disabled={!demoSession}
                className="rounded-2xl border border-amber-300 bg-amber-50 px-5 py-3 text-sm font-black text-amber-950 transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100"
              >
                立即模拟续签
              </button>
            </div>
            <div className="mt-5 rounded-3xl bg-slate-950 p-5 text-sm text-slate-100">
              <div className="text-xs font-black uppercase tracking-[0.2em] text-teal-200">
                Assistant content
              </div>
              <p className="mt-3 min-h-20 whitespace-pre-wrap leading-7">
                {assistantText || "等待 DeepTutor WebSocket 返回 content 事件…"}
              </p>
            </div>
          </div>

          <aside className="rounded-[2rem] border border-slate-200 bg-white/85 p-6 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/70">
            <p className="text-xs font-black uppercase tracking-[0.24em] text-slate-500">
              Refresh & event log
            </p>
            <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
              {refreshMessage}
            </div>
            <div className="mt-4 grid gap-3 text-sm">
              <div className="rounded-2xl bg-slate-100 p-4 dark:bg-slate-900">
                <div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">
                  dt_token expires
                </div>
                <div className="mt-2 font-mono text-xs">
                  {tokenExpiresAt ? new Date(tokenExpiresAt * 1000).toLocaleString() : "—"}
                </div>
              </div>
              <div className="rounded-2xl bg-slate-100 p-4 dark:bg-slate-900">
                <div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">
                  Recent WS events
                </div>
                <ul className="mt-2 space-y-1 font-mono text-xs">
                  {chatEvents.length ? (
                    chatEvents.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)
                  ) : (
                    <li>—</li>
                  )}
                </ul>
              </div>
            </div>
          </aside>
        </section>

        <section className="rounded-[2rem] border border-slate-200 bg-white/80 p-6 shadow-sm dark:border-slate-800 dark:bg-slate-950/70">
          <p className="text-xs font-black uppercase tracking-[0.24em] text-slate-500">
            Error matrix
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {ERRORS.map(([code, advice]) => (
              <article key={code} className="rounded-2xl border border-slate-200 p-4 text-sm dark:border-slate-800">
                <div className="font-mono text-xs font-black text-slate-950 dark:text-white">
                  {code}
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-600 dark:text-slate-300">
                  {advice}
                </p>
              </article>
            ))}
          </div>
        </section>
      </section>
    </main>
  );
}
