import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsAuthCallback from "../apps/oms/src/OmsAuthCallback";

function ok(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json" },
  }));
}

beforeEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/oms/auth/callback?code=auth-code&state=state-123");
});

describe("OMS 前端 OAuth 回调", () => {
  it("接收授权码参数后调用后端 BFF exchange API，不在前端处理 provider token", async () => {
    const redirect = vi.fn();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      expect(init?.method).toBe("POST");
      expect(init?.credentials).toBe("include");
      expect(JSON.parse(String(init?.body))).toEqual({ code: "auth-code", state: "state-123" });
      return ok({ authenticated: true, return_url: "https://llm-agent-test.f123.pub/oms" });
    });

    render(<OmsAuthCallback redirect={redirect}/>);

    expect(await screen.findByText("正在完成 OMS 登录…")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/oms/auth/callback",
        expect.objectContaining({ method: "POST" }),
      );
      expect(redirect).toHaveBeenCalledWith("https://llm-agent-test.f123.pub/oms?oms_login=ok");
    });
  });

  it("provider 返回错误时不调用 exchange，直接返回 OMS 失败页", async () => {
    window.history.replaceState({}, "", "/oms/auth/callback?error=access_denied&state=state-123");
    const redirect = vi.fn();
    const fetchMock = vi.spyOn(globalThis, "fetch");

    render(<OmsAuthCallback redirect={redirect}/>);

    await waitFor(() => {
      expect(fetchMock).not.toHaveBeenCalled();
      expect(redirect).toHaveBeenCalledWith("/oms?oms_login=failed&reason=authorization_denied");
    });
  });
});
