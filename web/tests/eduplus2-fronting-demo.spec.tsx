import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  buildAuthRefreshCommand,
  buildDemoWebSocketUrl,
  buildDemoStartTurnCommand,
  buildEduPlus2DemoStartUrl,
  buildWebSocketProtocols,
  shouldRefreshToken,
  redactCredential,
} from "@/lib/eduplus2-fronting-demo";

const Page = (await import("@/app/enterprise/eduplus2/fronting-demo/page")).default;

describe("EduPlus2 fronting auth demo page", () => {
  it("builds a start URL with only the safe return target", () => {
    const url = buildEduPlus2DemoStartUrl(
      "http://localhost/enterprise/eduplus2/fronting-demo",
    );
    expect(url).toBe(
      "/api/v1/auth/eduplus2/demo/start?return_to=http%3A%2F%2Flocalhost%2Fenterprise%2Feduplus2%2Ffronting-demo",
    );
  });

  it("redacts JWT-like credentials instead of returning raw token text", () => {
    const token = "header.payload.signature";
    const redacted = redactCredential(token);
    expect(redacted).toMatch(/^<redacted:jwt:/);
    expect(redacted).not.toContain(token);
  });

  it("keeps the WebSocket token out of the URL and builds auth_refresh", () => {
    const token = "header.payload.signature";
    expect(buildWebSocketProtocols(token)).toEqual(["deeptutor-token", token]);
    expect(
      buildDemoWebSocketUrl({
        protocol: "https:",
        host: "deeptutor-demo.lfun.pub",
      } as Location),
    ).toBe("wss://deeptutor-demo.lfun.pub/api/v1/ws");
    expect(
      buildDemoWebSocketUrl(
        {
          protocol: "https:",
          host: "deeptutor-demo.lfun.pub",
        } as Location,
        "wss://deeptutor-demo-ws.lfun.pub/api/v1/ws",
      ),
    ).toBe("wss://deeptutor-demo-ws.lfun.pub/api/v1/ws");
    expect("wss://deeptutor-demo.lfun.pub/api/v1/ws").not.toContain(token);
    expect(buildAuthRefreshCommand(token, "cmd-1")).toEqual({
      type: "auth_refresh",
      command_id: "cmd-1",
      dt_token: token,
      protocol_version: "2.0",
    });
  });


  it("builds WebSocket start_turn with resource references instead of upload payload", () => {
    const command = buildDemoStartTurnCommand(" 请分析附件 ", [" res_img_1 ", "", "res_audio_2"]);

    expect(command).toMatchObject({
      type: "start_turn",
      protocol_version: "2.0",
      content: "请分析附件",
      capability: "chat",
      resource_ids: ["res_img_1", "res_audio_2"],
      attachments: [],
    });
    expect(JSON.stringify(command)).not.toContain("base64");
    expect(JSON.stringify(command)).not.toContain("http://third-party");
  });

  it("refreshes when the token is expired or inside the refresh leeway", () => {
    expect(shouldRefreshToken({ nowSeconds: 100, expiresAt: 100, leewaySeconds: 30 })).toBe(
      true,
    );
    expect(shouldRefreshToken({ nowSeconds: 80, expiresAt: 100, leewaySeconds: 30 })).toBe(
      true,
    );
    expect(shouldRefreshToken({ nowSeconds: 60, expiresAt: 100, leewaySeconds: 30 })).toBe(
      false,
    );
  });

  it("renders demo-only guidance and starts the EduPlus2 redirect", async () => {
    const user = userEvent.setup();
    window.history.pushState({}, "", "/enterprise/eduplus2/fronting-demo");
    render(<Page />);

    expect(
      screen.getByRole("heading", { name: /EduPlus2 统一认证前置应用 Demo/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/仅用于 local\/test 联调/)).toBeInTheDocument();
    expect(screen.getAllByText(/pre-signed upload/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/prompt \+ resource_ids/).length).toBeGreaterThan(0);

    const originalLocation = window.location;
    const assign = vi.fn();
    try {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { ...originalLocation, origin: "http://localhost", assign },
      });
      await user.click(
        screen.getByRole("button", { name: /使用 EduPlus2 统一认证测试/ }),
      );
      expect(assign).toHaveBeenCalledWith(
        "/api/v1/auth/eduplus2/demo/start?return_to=http%3A%2F%2Flocalhost%2Fenterprise%2Feduplus2%2Ffronting-demo",
      );
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    }
  });

  it("uses an internal scroll container because the global app shell hides body overflow", () => {
    window.history.pushState({}, "", "/enterprise/eduplus2/fronting-demo");
    render(<Page />);

    const root = screen.getByTestId("eduplus2-fronting-demo-scroll-root");
    expect(root).toHaveClass("h-full");
    expect(root).toHaveClass("overflow-y-auto");
    expect(root).not.toHaveClass("overflow-hidden");
  });

  it("uses dt_token only for the API probe and never persists or renders it", async () => {
    window.history.pushState(
      {},
      "",
      "/enterprise/eduplus2/fronting-demo?demo_session=session-1",
    );
    const rawToken = "dt.secret.token";
    const setLocal = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/v1/auth/eduplus2/demo/result")) {
        return Response.json({
          ok: true,
          request_id: "demo-req-1",
          token_type: "Bearer",
          dt_token: rawToken,
          summary: {
            request_id: "demo-req-1",
            client_id: "client-a",
            external_user_hash: "sha256:external",
            internal_user_hash: "sha256:internal",
          },
          steps: [
            { id: "redirect", label: "EduPlus2 Redirect", status: "done" },
            {
              id: "code_exchange",
              label: "Authorization Code Token Exchange",
              status: "done",
            },
            {
              id: "deeptutor_exchange",
              label: "DeepTutor Token Exchange",
              status: "done",
            },
            { id: "api_probe", label: "DeepTutor API Probe", status: "pending" },
          ],
        });
      }
      expect(url).toBe("/api/auth/status");
      expect((init?.headers as Record<string, string>).Authorization).toBe(
        `Bearer ${rawToken}`,
      );
      return Response.json({
        enabled: true,
        authenticated: true,
        user_id: "internal-user-raw",
        role: "user",
        is_admin: false,
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<Page />);

    await waitFor(() =>
      expect(screen.getByText(/DeepTutor API 已接受 dt_token/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(rawToken)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(rawToken);
    expect(setLocal).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("uploads a selected file through pre-signed HTTP APIs before referencing its resource_id over WebSocket", async () => {
    const user = userEvent.setup();
    window.history.pushState(
      {},
      "",
      "/enterprise/eduplus2/fronting-demo?demo_session=session-upload",
    );
    const rawToken = "dt.upload.token";
    const uploadHeaders = {
      "content-type": "image/png",
      "content-length": "10",
      "x-amz-meta-sha256": "server-side-policy-sha",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/v1/auth/eduplus2/demo/result")) {
        return Response.json({
          ok: true,
          request_id: "demo-req-upload",
          token_type: "Bearer",
          dt_token: rawToken,
          summary: { request_id: "demo-req-upload" },
          steps: [
            { id: "redirect", label: "EduPlus2 Redirect", status: "done" },
            { id: "code_exchange", label: "Authorization Code Token Exchange", status: "done" },
            { id: "deeptutor_exchange", label: "DeepTutor Token Exchange", status: "done" },
            { id: "api_probe", label: "DeepTutor API Probe", status: "pending" },
          ],
        });
      }
      if (url === "/api/auth/status") {
        return Response.json({
          enabled: true,
          authenticated: true,
          user_id: "internal-user-raw",
          role: "user",
          is_admin: false,
        });
      }
      if (url === "/api/v1/resources/upload-intents") {
        expect(init?.method).toBe("POST");
        expect((init?.headers as Record<string, string>).Authorization).toBe(
          `Bearer ${rawToken}`,
        );
        const body = JSON.parse(String(init?.body));
        expect(body).toMatchObject({
          modality: "image",
          mime_type: "image/png",
          size_bytes: 10,
          purpose: "chat_turn",
          filename: "diagram.png",
        });
        expect(body.sha256).toMatch(/^[0-9a-f]{64}$/);
        expect(JSON.stringify(body)).not.toContain("base64");
        expect(JSON.stringify(body)).not.toContain("https://upload.example");
        return Response.json({
          resource_id: "res_demo_image",
          object_id: "obj-demo-image",
          resource_kind: "turn_input",
          upload_url: "https://upload.example/presigned-put",
          headers: uploadHeaders,
          expires_in: 900,
          constraints: {
            mime_type: "image/png",
            size_bytes: 10,
            modality: "image",
            purpose: "chat_turn",
          },
        });
      }
      if (url === "https://upload.example/presigned-put") {
        expect(init?.method).toBe("PUT");
        expect(init?.body).toBeInstanceOf(File);
        expect(init?.headers).toMatchObject({
          "content-type": "image/png",
          "x-amz-meta-sha256": "server-side-policy-sha",
        });
        expect(init?.headers).not.toHaveProperty("content-length");
        return new Response(null, { status: 204 });
      }
      if (url === "/api/v1/resources/upload-intents/res_demo_image/complete") {
        expect(init?.method).toBe("POST");
        expect((init?.headers as Record<string, string>).Authorization).toBe(
          `Bearer ${rawToken}`,
        );
        return Response.json({
          resource_id: "res_demo_image",
          object_id: "obj-demo-image",
          resource_kind: "turn_input",
          state: "ready",
          size_bytes: 10,
          sha256: "a".repeat(64),
          mime_type: "image/png",
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const sockets: Array<{
      listeners: Record<string, Array<(event?: unknown) => void>>;
      sent: string[];
      emit: (type: string, event?: unknown) => void;
    }> = [];
    class FakeWebSocket {
      static OPEN = 1;
      readyState = 0;
      listeners: Record<string, Array<(event?: unknown) => void>> = {};
      sent: string[] = [];

      constructor(
        public url: string,
        public protocols: string[],
      ) {
        sockets.push(this);
      }

      addEventListener(type: string, listener: (event?: unknown) => void) {
        this.listeners[type] = [...(this.listeners[type] ?? []), listener];
      }

      send(payload: string) {
        this.sent.push(payload);
      }

      close() {
        this.readyState = 3;
      }

      emit(type: string, event?: unknown) {
        if (type === "open") this.readyState = FakeWebSocket.OPEN;
        for (const listener of this.listeners[type] ?? []) {
          listener(event);
        }
      }
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);

    render(<Page />);
    await waitFor(() =>
      expect(screen.getByText(/DeepTutor API 已接受 dt_token/)).toBeInTheDocument(),
    );

    expect(screen.queryByText(/Resource pre-upload contract/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /pre-signed upload → prompt \+ resource_ids/ }),
    ).not.toBeInTheDocument();
    const wsCard = screen
      .getByRole("heading", { name: /真实 \/api\/v1\/ws 对话测试/ })
      .closest("section");
    expect(wsCard).not.toBeNull();
    const wsControls = within(wsCard as HTMLElement);

    await user.upload(
      wsControls.getByLabelText(/选择图片、音频、视频或文档文件/),
      new File(["demo-image"], "diagram.png", { type: "image/png" }),
    );
    await user.click(wsControls.getByRole("button", { name: /上传并登记资源/ }));

    await waitFor(() =>
      expect(wsControls.getByLabelText(/已完成上传的 resource_ids/)).toHaveValue(
        "res_demo_image",
      ),
    );
    expect(wsControls.getAllByText(/res_demo_image/).length).toBeGreaterThan(0);
    await user.clear(wsControls.getByLabelText(/已完成上传的 resource_ids/));

    await user.click(wsControls.getByRole("button", { name: /开始 WebSocket 对话/ }));
    expect(sockets).toHaveLength(1);
    await act(async () => {
      sockets[0].emit("open");
    });
    await waitFor(() => expect(sockets[0].sent).toHaveLength(1));
    const startTurn = JSON.parse(sockets[0].sent[0]);
    expect(startTurn.resource_ids).toEqual(["res_demo_image"]);
    expect(startTurn.attachments).toEqual([]);
    expect(JSON.stringify(startTurn)).not.toContain("https://upload.example");
    expect(JSON.stringify(startTurn)).not.toContain("base64");
  });

  it("restores completed demo resource_ids after a page reload before starting WebSocket", async () => {
    const user = userEvent.setup();
    window.history.pushState(
      {},
      "",
      "/enterprise/eduplus2/fronting-demo?demo_session=session-persisted-resource",
    );
    window.sessionStorage.setItem(
      "deeptutor.eduplus2.frontingDemo.resourceIds.v1",
      JSON.stringify(["res_persisted_image"]),
    );
    const rawToken = "dt.persisted.token";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/v1/auth/eduplus2/demo/result")) {
        return Response.json({
          ok: true,
          request_id: "demo-req-persisted-resource",
          token_type: "Bearer",
          dt_token: rawToken,
          summary: { request_id: "demo-req-persisted-resource" },
          steps: [
            { id: "redirect", label: "EduPlus2 Redirect", status: "done" },
            { id: "code_exchange", label: "Authorization Code Token Exchange", status: "done" },
            { id: "deeptutor_exchange", label: "DeepTutor Token Exchange", status: "done" },
            { id: "api_probe", label: "DeepTutor API Probe", status: "pending" },
          ],
        });
      }
      if (url === "/api/auth/status") {
        return Response.json({
          enabled: true,
          authenticated: true,
          user_id: "internal-user-raw",
          role: "user",
          is_admin: false,
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const sockets: Array<{
      listeners: Record<string, Array<(event?: unknown) => void>>;
      sent: string[];
      emit: (type: string, event?: unknown) => void;
    }> = [];
    class FakeWebSocket {
      static OPEN = 1;
      readyState = 0;
      listeners: Record<string, Array<(event?: unknown) => void>> = {};
      sent: string[] = [];

      constructor() {
        sockets.push(this);
      }

      addEventListener(type: string, listener: (event?: unknown) => void) {
        this.listeners[type] = [...(this.listeners[type] ?? []), listener];
      }

      send(payload: string) {
        this.sent.push(payload);
      }

      close() {
        this.readyState = 3;
      }

      emit(type: string, event?: unknown) {
        if (type === "open") this.readyState = FakeWebSocket.OPEN;
        for (const listener of this.listeners[type] ?? []) {
          listener(event);
        }
      }
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);

    render(<Page />);
    await waitFor(() =>
      expect(screen.getByText(/DeepTutor API 已接受 dt_token/)).toBeInTheDocument(),
    );
    const wsCard = screen
      .getByRole("heading", { name: /真实 \/api\/v1\/ws 对话测试/ })
      .closest("section");
    expect(wsCard).not.toBeNull();
    const wsControls = within(wsCard as HTMLElement);
    expect(wsControls.getByLabelText(/已完成上传的 resource_ids/)).toHaveValue(
      "res_persisted_image",
    );

    await user.click(wsControls.getByRole("button", { name: /开始 WebSocket 对话/ }));
    expect(sockets).toHaveLength(1);
    await act(async () => {
      sockets[0].emit("open");
    });
    await waitFor(() => expect(sockets[0].sent).toHaveLength(1));
    const startTurn = JSON.parse(sockets[0].sent[0]);
    expect(startTurn.resource_ids).toEqual(["res_persisted_image"]);
    expect(startTurn.attachments).toEqual([]);
  });


  it("refreshes a rejected demo token before opening WebSocket", async () => {
    const user = userEvent.setup();
    window.history.pushState(
      {},
      "",
      "/enterprise/eduplus2/fronting-demo?demo_session=session-refresh-before-ws",
    );
    const rawToken = "dt.rejected.token";
    const refreshedToken = "dt.refreshed.token";
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/v1/auth/eduplus2/demo/result")) {
        return Response.json({
          ok: true,
          request_id: "demo-req-refresh-before-ws",
          token_type: "Bearer",
          dt_token: rawToken,
          expires_at: Math.floor(Date.now() / 1000) + 300,
          summary: { request_id: "demo-req-refresh-before-ws" },
          steps: [
            { id: "redirect", label: "EduPlus2 Redirect", status: "done" },
            { id: "code_exchange", label: "Authorization Code Token Exchange", status: "done" },
            { id: "deeptutor_exchange", label: "DeepTutor Token Exchange", status: "done" },
            { id: "api_probe", label: "DeepTutor API Probe", status: "pending" },
          ],
        });
      }
      if (url === "/api/auth/status") {
        return Response.json({ enabled: true, authenticated: false });
      }
      if (url === "/api/v1/auth/eduplus2/demo/refresh") {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({
          demo_session: "session-refresh-before-ws",
        });
        return Response.json({
          ok: true,
          request_id: "demo-req-refresh-before-ws-2",
          token_type: "Bearer",
          dt_token: refreshedToken,
          expires_at: Math.floor(Date.now() / 1000) + 300,
          summary: { request_id: "demo-req-refresh-before-ws-2" },
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const sockets: Array<{ url: string; protocols: string[] }> = [];
    class FakeWebSocket {
      static OPEN = 1;
      readyState = 0;
      constructor(
        public url: string,
        public protocols: string[],
      ) {
        sockets.push(this);
      }
      addEventListener() {}
      send() {}
      close() {}
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);

    render(<Page />);
    await waitFor(() =>
      expect(screen.getByText(/DeepTutor API 未接受该 dt_token/)).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /开始 WebSocket 对话/ }));

    await waitFor(() => expect(sockets).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/eduplus2/demo/refresh",
      expect.objectContaining({ method: "POST" }),
    );
    expect(sockets[0].protocols).toEqual(["deeptutor-token", refreshedToken]);
    expect(sockets[0].protocols).not.toContain(rawToken);
  });

  it("uses a visible native resource file input instead of a JavaScript proxy button", () => {
    window.history.pushState({}, "", "/enterprise/eduplus2/fronting-demo");
    render(<Page />);

    const wsCard = screen
      .getByRole("heading", { name: /真实 \/api\/v1\/ws 对话测试/ })
      .closest("section");
    expect(wsCard).not.toBeNull();
    const wsControls = within(wsCard as HTMLElement);
    const fileInput = wsControls.getByLabelText(
      /选择图片、音频、视频或文档文件/,
    ) as HTMLInputElement;

    expect(wsControls.queryByRole("button", { name: "选择文件" })).not.toBeInTheDocument();
    expect(fileInput).toHaveAttribute("type", "file");
    expect(fileInput).not.toHaveClass("sr-only");
    expect(fileInput).toHaveClass("cursor-pointer");
  });
});
