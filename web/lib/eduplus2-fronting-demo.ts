export const EDUPLUS2_FRONTING_DEMO_PATH =
  "/enterprise/eduplus2/fronting-demo";
export const EDUPLUS2_FRONTING_DEMO_START_PATH =
  "/api/v1/auth/eduplus2/demo/start";
export const EDUPLUS2_FRONTING_DEMO_RESULT_PATH =
  "/api/v1/auth/eduplus2/demo/result";
export const EDUPLUS2_FRONTING_DEMO_REFRESH_PATH =
  "/api/v1/auth/eduplus2/demo/refresh";
export const EDUPLUS2_DEMO_WS_PATH = "/api/v1/ws";
export const EDUPLUS2_DEMO_WS_URL_ENV = "NEXT_PUBLIC_EDUPLUS2_DEMO_WS_URL";

export type DemoStepStatus = "idle" | "pending" | "done" | "failed" | "skipped";

export type DemoStep = {
  id:
    | "redirect"
    | "code_exchange"
    | "deeptutor_exchange"
    | "api_probe"
    | "ws_chat"
    | "token_refresh";
  label: string;
  status: DemoStepStatus;
  reason?: string;
};

export type DemoResultPayload = {
  ok: boolean;
  request_id: string;
  token_type: string;
  dt_token?: string;
  summary?: Record<string, unknown>;
  steps?: DemoStep[];
  created_at?: number;
  expires_at?: number;
};

export type AuthStatusPayload = {
  enabled?: boolean;
  authenticated?: boolean;
  user_id?: string;
  username?: string;
  role?: string;
  is_admin?: boolean;
};

export type AuthRefreshCommand = {
  type: "auth_refresh";
  command_id: string;
  dt_token: string;
  protocol_version: "2.0";
};

export function buildEduPlus2DemoStartUrl(returnTo: string): string {
  const params = new URLSearchParams({ return_to: returnTo });
  return `${EDUPLUS2_FRONTING_DEMO_START_PATH}?${params.toString()}`;
}

export function buildWebSocketProtocols(token: string): string[] {
  return ["deeptutor-token", token];
}

export function buildDemoWebSocketUrl(
  locationLike: Pick<Location, "protocol" | "host">,
  configuredUrl = process.env.NEXT_PUBLIC_EDUPLUS2_DEMO_WS_URL ?? "",
): string {
  const configured = configuredUrl.trim();
  if (configured) return configured;
  const protocol = locationLike.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${locationLike.host}${EDUPLUS2_DEMO_WS_PATH}`;
}

export function buildAuthRefreshCommand(
  token: string,
  commandId = `demo-refresh-${Date.now()}`,
): AuthRefreshCommand {
  return {
    type: "auth_refresh",
    command_id: commandId,
    dt_token: token,
    protocol_version: "2.0",
  };
}

export function shouldRefreshToken(input: {
  nowSeconds: number;
  expiresAt: number | null | undefined;
  leewaySeconds: number;
}): boolean {
  if (!input.expiresAt) return false;
  return input.nowSeconds >= input.expiresAt - Math.max(0, input.leewaySeconds);
}

export function redactCredential(value: string | null | undefined): string {
  const text = String(value ?? "").trim();
  if (!text) return "—";
  const kind = text.split(".").length === 3 ? "jwt" : "credential";
  let hash = 0;
  for (const char of text) {
    hash = (hash * 31 + char.charCodeAt(0)) | 0;
  }
  return `<redacted:${kind}:${Math.abs(hash).toString(16).padStart(8, "0")}>`;
}

export async function hashIdentifier(
  value: string | null | undefined,
): Promise<string> {
  const text = String(value ?? "").trim();
  if (!text) return "";
  if (globalThis.crypto?.subtle) {
    const digest = await globalThis.crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(text),
    );
    return (
      "sha256:" +
      [...new Uint8Array(digest)]
        .slice(0, 8)
        .map((item) => item.toString(16).padStart(2, "0"))
        .join("")
    );
  }
  let hash = 0;
  for (const char of text) {
    hash = (hash * 31 + char.charCodeAt(0)) | 0;
  }
  return `sha256:${Math.abs(hash).toString(16).padStart(8, "0")}`;
}

export function defaultDemoSteps(): DemoStep[] {
  return [
    { id: "redirect", label: "EduPlus2 Redirect", status: "idle" },
    {
      id: "code_exchange",
      label: "Authorization Code Token Exchange",
      status: "idle",
    },
    {
      id: "deeptutor_exchange",
      label: "DeepTutor Token Exchange",
      status: "idle",
    },
    { id: "api_probe", label: "DeepTutor API Probe", status: "idle" },
    { id: "ws_chat", label: "DeepTutor WebSocket Chat", status: "idle" },
    { id: "token_refresh", label: "Token Refresh", status: "idle" },
  ];
}

export function mergeProbeStep(
  steps: DemoStep[],
  status: DemoStepStatus,
  reason?: string,
): DemoStep[] {
  return steps.map((step) =>
    step.id === "api_probe" ? { ...step, status, reason } : step,
  );
}

export function mergeStepStatus(
  steps: DemoStep[],
  id: DemoStep["id"],
  status: DemoStepStatus,
  reason?: string,
): DemoStep[] {
  return steps.map((step) =>
    step.id === id ? { ...step, status, reason } : step,
  );
}
