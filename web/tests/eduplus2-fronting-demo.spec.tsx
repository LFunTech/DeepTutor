import { render, screen, waitFor } from "@testing-library/react";
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
});
