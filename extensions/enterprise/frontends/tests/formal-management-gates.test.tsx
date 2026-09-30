import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsFormalApp from "../apps/oms/src/OmsFormalApp";
import { hasOmsSessionCookie, hasOmsSessionCookieHeader, omsLoginStartUrl, omsReturnPath } from "../apps/oms/src/omsServerGate";
import TmsFormalApp from "../apps/tms/src/TmsFormalApp";

function ok(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } }));
}

beforeEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
  document.cookie = "dt_oms_csrf=; Max-Age=0; path=/";
});

describe("正式 OMS/TMS 管理入口", () => {
  it("OMS 服务端入口在无会话时构造 eduplus-platform-admin 授权码登录", () => {
    const emptyCookies = { get: () => undefined };
    const refreshCookies = { get: (name: string) => name === "dt_oms_refresh" ? { value: "refresh" } : undefined };
    const csrfHintCookies = { get: (name: string) => name === "dt_oms_csrf" ? { value: "csrf" } : undefined };

    expect(hasOmsSessionCookie(emptyCookies)).toBe(false);
    expect(hasOmsSessionCookie(refreshCookies)).toBe(true);
    expect(hasOmsSessionCookie(csrfHintCookies)).toBe(true);
    expect(hasOmsSessionCookieHeader("theme=dark; dt_oms_csrf=csrf")).toBe(true);
    expect(hasOmsSessionCookieHeader("theme=dark")).toBe(false);
    expect(omsReturnPath(["platform-people", "p 1"], { next: "/oms", tag: ["a", "b"], empty: undefined })).toBe("/oms/platform-people/p%201?next=%2Foms&tag=a&tag=b");
    expect(omsLoginStartUrl("https://deeptutor.lfun.pub", "/oms/platform-people/p%201?next=%2Foms")).toBe("https://deeptutor.lfun.pub/api/v1/oms/auth/start?return_to=https%3A%2F%2Fdeeptutor.lfun.pub%2Foms%2Fplatform-people%2Fp%25201%3Fnext%3D%252Foms");
  });

  it("OMS 正式入口只接安全 DTO，不渲染开发原型或学校账号开通", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.skills.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [{ id: "s-1", name: "首个 Agent Skill", status: "published", latest_revision: 3 }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByRole("heading", { name: "平台智能体运营后台" })).toBeInTheDocument();
    expect(screen.getByText("智能体基座")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "平台智能体运营后台导航" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "学校列表" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "模型与服务" })).toBeInTheDocument();
    expect(screen.getAllByText("正式受控入口").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("正式入口 · 安全 DTO")).toBeInTheDocument();
    expect(screen.getByText(/正式入口使用已验签 OMS 会话与 DeepTutor 本地 ops\.\* 授权/)).toBeInTheDocument();
    expect(screen.queryByText(/合成演示数据/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /学校后台开通|发起开通/ })).not.toBeInTheDocument();
    expect(screen.getByText("首个 Agent Skill")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/oms/me", expect.objectContaining({ credentials: "include" }));
  });

  it("OMS 正式入口按原型导航切换到学校范围页", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.skills.read", "ops.tenants.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", school_code: "demo-school", lifecycle: { external_eligibility: "active" } }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "学校列表" }));

    expect(screen.getByRole("heading", { name: "学校范围" })).toBeInTheDocument();
    expect(screen.getByText("demo-school")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "模型与 Provider" })).not.toBeInTheDocument();
  });

  it("OMS 学校列表分列展示学校名称和学校代码且列表不显示学校 ID", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.tenants.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{
        school_id: "school-1",
        school_code: "71001",
        school_name: "晋元高级中学",
        external_binding: { status: { code: "verified", label: "已核验" } },
        lifecycle: { external_eligibility: { code: "allowed", label: "学校订阅有效" }, provisioning_status: "ready", recovery_state: "normal" },
        service_entitlements: [],
        quota_grants: [],
        usage: [],
      }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "学校列表" }));

    expect(screen.getByText("学校名称")).toBeInTheDocument();
    expect(screen.getByText("学校代码")).toBeInTheDocument();
    expect(screen.getByText("晋元高级中学")).toBeInTheDocument();
    expect(screen.getByText("71001")).toBeInTheDocument();
    expect(screen.queryByText(/ID school-1/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看 晋元高级中学 详情" }));
    const dialog = screen.getByRole("dialog", { name: "详情 · 晋元高级中学" });
    expect(within(dialog).getByText("学校名称")).toBeInTheDocument();
    expect(within(dialog).getAllByText("晋元高级中学").length).toBeGreaterThanOrEqual(1);
    expect(within(dialog).getByText("学校代码")).toBeInTheDocument();
    expect(within(dialog).getAllByText("71001").length).toBeGreaterThanOrEqual(1);
    expect(within(dialog).getByText("学校 ID")).toBeInTheDocument();
    expect(within(dialog).getByText("school-1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /学校后台开通|发起开通/ })).not.toBeInTheDocument();
  });

  it("OMS 正式入口无 Skill 权限时不读取 Skill DTO 且学校列表仍可用", async () => {
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.tenants.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", school_code: "demo-school", lifecycle: { external_eligibility: "active" } }] });
      if (url.endsWith("/api/v1/oms/skills")) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "Permission denied" }), { status: 403, headers: { "content-type": "application/json" } }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByRole("heading", { name: "平台智能体运营后台" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "学校列表" }));

    expect(screen.getByRole("heading", { name: "学校范围" })).toBeInTheDocument();
    expect(screen.getByText("demo-school")).toBeInTheDocument();
    expect(requests.some(url => url.endsWith("/api/v1/oms/skills"))).toBe(false);
  });

  it("OMS 正式入口不会把学校范围供给授权当作全局供给预取权限", async () => {
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "school-scoped-operator" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({
        platform_actions: [],
        school_actions: [{
          school_id: "school-1",
          actions: [
            "ops.oms.access",
            "ops.tenants.read",
            "ops.supply.read",
            "ops.supply.manage",
            "ops.entitlements.read",
            "ops.quotas.read",
          ],
        }],
        scopes: [{ kind: "school", school_id: "school-1" }],
      });
      if (url.endsWith("/api/v1/oms/status/catalog")) return ok({ statuses: [] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({
        tenants: [{
          school_id: "school-1",
          school_code: "jygjzx",
          lifecycle: { external_eligibility: "active" },
        }],
      });
      if (url.endsWith("/api/v1/oms/schools/school-1/quota")) return ok({ entitlements: [], grants: [] });
      if (url.endsWith("/api/v1/oms/supply")) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "Permission denied" }), { status: 403, headers: { "content-type": "application/json" } }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByRole("heading", { name: "平台智能体运营后台" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "学校列表" }));

    expect(screen.getByRole("heading", { name: "学校范围" })).toBeInTheDocument();
    expect(screen.getByText("jygjzx")).toBeInTheDocument();
    expect(requests.some(url => url.endsWith("/api/v1/oms/supply"))).toBe(false);
    expect(screen.queryByRole("button", { name: "撤销供给批次" })).not.toBeInTheDocument();
  });

  it("OMS 正式入口按资源导航过滤资源并展示知识基础能力安全字段", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.providers.read", "ops.skills.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 4, notices: [] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/oms/models/draft")) return ok({ version: 1, models: [{ id: "model-1", model_id: "qwen-plus", provider: "dashscope" }] });
      if (url.endsWith("/api/v1/oms/provider-settings")) return ok({ version: 1, status: "active", settings: { connections: {} } });
      if (url.endsWith("/api/v1/oms/resources/status")) return ok({ resources: [
        { id: "model:chat:qwen", display_name: "Qwen Chat", category: "model_external", status: { label: "就绪" }, safe_fields: { provider: "dashscope" } },
        { id: "knowledge:lightrag", display_name: "LightRAG", category: "knowledge_content", kind: "rag", status: { label: "就绪" }, managed: true, safe_fields: { workspace_binding: "workspace-a", index_version: "iv-20260929", api_key: "sk-hidden" } },
        { id: "tool:mcp", display_name: "MCP 工具", category: "tool_integration", status: "not_configured" },
        { id: "runtime:postgres", display_name: "PostgreSQL", category: "runtime", status: "ready" },
      ] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "知识基础能力" }));

    expect(screen.getByRole("heading", { name: "平台资源状态" })).toBeInTheDocument();
    expect(screen.getByText("LightRAG")).toBeInTheDocument();
    expect(screen.queryByText("Qwen Chat")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /查看 LightRAG 详情/ }));
    const dialog = screen.getByRole("dialog", { name: "详情 · LightRAG" });
    expect(within(dialog).getByText("workspace_binding")).toBeInTheDocument();
    expect(within(dialog).getByText("workspace-a")).toBeInTheDocument();
    expect(screen.queryByText("sk-hidden")).not.toBeInTheDocument();
  });

  it("OMS 未登录时自动发起 eduplus-platform-admin 授权码登录", async () => {
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "https://deeptutor.lfun.pub/oms", pathname: "/oms" },
    });
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "Authentication required" }), { status: 401, headers: { "content-type": "application/json" } }));
      }
      if (url.endsWith("/api/v1/oms/auth/refresh")) throw new Error("refresh must not run without a csrf session hint");
      throw new Error(`unexpected fetch ${url}`);
    });

    try {
      render(<OmsFormalApp/>);

      expect(await screen.findByText("正在跳转到 eduplus-platform-admin 登录")).toBeInTheDocument();
      expect(window.location.href).toBe("/api/v1/oms/auth/start?return_to=https%3A%2F%2Fdeeptutor.lfun.pub%2Foms");
      expect(screen.queryByText("正式入口未开放")).not.toBeInTheDocument();
      expect(screen.queryByText("等待的验收证据")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "使用 eduplus-platform-admin 登录" })).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
    }
  });

  it("OMS 会话 access token 过期时使用 HttpOnly refresh cookie 刷新后重试", async () => {
    document.cookie = "dt_oms_csrf=csrf-token; path=/";
    let meAttempts = 0;
    const requests: { url: string; method: string; csrf: string | null }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      requests.push({ url, method: init?.method ?? "GET", csrf: headers.get("x-csrf-token") });
      if (url.endsWith("/api/v1/oms/me")) {
        meAttempts += 1;
        if (meAttempts === 1) {
          return Promise.resolve(new Response(JSON.stringify({ detail: "Authentication required" }), { status: 401, headers: { "content-type": "application/json" } }));
        }
        return ok({ principal_id: "p-oms", subject: "ops-user" });
      }
      if (url.endsWith("/api/v1/oms/auth/refresh")) return ok({ authenticated: true });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByRole("heading", { name: "平台智能体运营后台" })).toBeInTheDocument();
    expect(requests.filter(request => request.url.endsWith("/api/v1/oms/me")).length).toBe(2);
    const refresh = requests.find(request => request.url.endsWith("/api/v1/oms/auth/refresh"));
    expect(refresh).toEqual(expect.objectContaining({ method: "POST", csrf: "csrf-token" }));
  });

  it("OMS 首位平台管理员本地授权自动初始化，不再要求手动激活", async () => {
    document.cookie = "dt_oms_csrf=csrf-token; path=/";
    let meAttempts = 0;
    const requests: { url: string; method: string; csrf: string | null }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      requests.push({ url, method: init?.method ?? "GET", csrf: headers.get("x-csrf-token") });
      if (url.endsWith("/api/v1/oms/me")) {
        meAttempts += 1;
        if (meAttempts === 1) {
          return Promise.resolve(new Response(JSON.stringify({ detail: "platform identity missing" }), { status: 403, headers: { "content-type": "application/json" } }));
        }
        return ok({ principal_id: "p-oms", subject: "ops-user" });
      }
      if (url.endsWith("/api/v1/oms/bootstrap/first-admin")) return ok({ application: "oms", replayed: false });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByRole("heading", { name: "平台智能体运营后台" })).toBeInTheDocument();
    expect(requests.filter(request => request.url.endsWith("/api/v1/oms/me")).length).toBe(2);
    expect(requests.find(request => request.url.endsWith("/api/v1/oms/bootstrap/first-admin"))).toEqual(expect.objectContaining({
      method: "POST",
      csrf: "csrf-token",
    }));
    expect(screen.queryByRole("button", { name: "激活首位 OMS 管理员" })).not.toBeInTheDocument();
  });

  it("OMS 已登录但本地授权未通过时失败关闭", async () => {
    document.cookie = "dt_oms_csrf=csrf-token; path=/";
    const requests: { url: string; method: string }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, method: init?.method ?? "GET" });
      if (url.endsWith("/api/v1/oms/me")) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "platform identity missing" }), { status: 403, headers: { "content-type": "application/json" } }));
      }
      if (url.endsWith("/api/v1/oms/bootstrap/first-admin")) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "First administrator already initialized" }), { status: 409, headers: { "content-type": "application/json" } }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByText("无权访问 OMS")).toBeInTheDocument();
    expect(screen.getByText(/当前账号已完成 eduplus-platform-admin 登录/)).toBeInTheDocument();
    expect(screen.getByText(/当前环境已存在 OMS 管理员/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新登录 eduplus-platform-admin" })).toBeInTheDocument();
    expect(requests.find(request => request.url.endsWith("/api/v1/oms/bootstrap/first-admin"))).toEqual(expect.objectContaining({ method: "POST" }));
    expect(screen.queryByRole("button", { name: "激活首位 OMS 管理员" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /新增|授予|发布|审批/ })).not.toBeInTheDocument();
  });

  it("OMS API 请求挂起时退出 loading 并失败关闭", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(() => {}));
    try {
      render(<OmsFormalApp/>);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_001);
      });

      expect(screen.getByText("OMS 暂不可用")).toBeInTheDocument();
      expect(screen.getByText(/request timeout/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("TMS 正式入口接入当前学校 DTO，区分目录未启用且不显示合成目录", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active", actor_candidate: null });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "not_enabled", reason_code: "external_directory_contract_missing", message: "外部目录合同缺失", users: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [{ id: "m-1", display_name: "林老师", status: "active", assignments: [{ role_key: "school_admin", status: "active" }] }] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [{ id: "ap-1", status: "approved", operation: "school_activation" }] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [{ id: "ev-1", action: "tenant.permissions.manage", result: "allow" }] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [{ id: "sk-1", name: "解题 Agent", status: "active" }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    expect(await screen.findByRole("heading", { name: "学校智能体管理后台" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "学校智能体管理后台导航" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "成员列表" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "可用服务" })).toBeInTheDocument();
    expect(screen.getAllByText("正式受控入口").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("正式入口 · 安全 DTO")).toBeInTheDocument();
    expect(screen.getByText("demo-school")).toBeInTheDocument();
    expect(screen.getByText("林老师")).toBeInTheDocument();
    expect(screen.getByText("外部目录合同缺失")).toBeInTheDocument();
    expect(screen.queryByText("赵老师")).not.toBeInTheDocument();
    expect(screen.getByText("解题 Agent")).toBeInTheDocument();
    expect(within(screen.getByLabelText("TMS 审批与审计")).getByText("approved")).toBeInTheDocument();
  });

  it("TMS 正式入口使用 EduPlus2 登录结果 bearer 读取当前学校安全 DTO", async () => {
    window.history.replaceState(null, "", "/tms/demo-school?demo_session=session-1");
    const requests: { url: string; authorization: string | null }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const authorization = new Headers(init?.headers).get("authorization");
      requests.push({ url, authorization });
      if (url.endsWith("/api/v1/auth/eduplus2/demo/result?demo_session=session-1")) {
        return ok({ ok: true, dt_token: "dt-token", expires_at: Math.floor(Date.now() / 1000) + 600 });
      }
      if (url.includes("/api/v1/tms/") && authorization !== "Bearer dt-token") {
        return Promise.resolve(new Response(JSON.stringify({ detail: "missing bearer" }), { status: 401, headers: { "content-type": "application/json" } }));
      }
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active", actor_candidate: null });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "not_enabled", reason_code: "external_directory_contract_missing", message: "外部目录合同缺失", users: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [{ id: "m-1", display_name: "林老师", status: "active", assignments: [{ role_key: "school_admin", status: "active" }] }] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    expect(await screen.findByRole("heading", { name: "学校智能体管理后台" })).toBeInTheDocument();
    expect(screen.getByText("林老师")).toBeInTheDocument();
    expect(requests.some(request => request.url.endsWith("/api/v1/auth/eduplus2/demo/result?demo_session=session-1"))).toBe(true);
    expect(requests.filter(request => request.url.includes("/api/v1/tms/")).every(request => request.authorization === "Bearer dt-token")).toBe(true);
  });

  it("TMS 正式入口按原型导航切换到配额清单页", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read", "tenant.quotas.read", "tenant.usage.read"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "not_enabled", reason_code: "external_directory_contract_missing", message: "外部目录合同缺失", users: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/tms/quotas")) return ok({ grants: [{ grant_id: "q-1", service_id: "llm", unit_code: "token", quantity: "100", status: "active" }], usage_details: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    await screen.findByRole("heading", { name: "学校智能体管理后台" });
    fireEvent.click(screen.getByRole("button", { name: "配额清单" }));

    expect(screen.getByRole("heading", { name: "额度与用量" })).toBeInTheDocument();
    expect(screen.getByText("100 token")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "学校目录" })).not.toBeInTheDocument();
  });

  it("TMS 当前学校身份或本地 tenant 授权失败时不展示管理按钮", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ detail: "school binding unavailable" }), { status: 403, headers: { "content-type": "application/json" } })));

    render(<TmsFormalApp schoolCode="demo-school"/>);

    expect(await screen.findByText("学校入口未开放")).toBeInTheDocument();
    expect(screen.getByText(/当前学校登录、Webhook 学校绑定或 tenant\.\* 本地授权未通过/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /授予|撤销|审批|新增/ })).not.toBeInTheDocument();
  });

  it("TMS 正式入口拒绝 URL 学校码与安全 DTO 学校不一致", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({
        school_id: "school-1",
        school_code: "trusted-school",
        actions: ["tenant.tms.access", "tenant.members.read"],
        scopes: [{ kind: "school", school_id: "school-1" }],
      });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="tampered-school"/>);

    expect(await screen.findByText("学校入口未开放")).toBeInTheDocument();
    expect(screen.getByText(/学校码与当前登录学校不一致/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /授予|撤销|审批|新增/ })).not.toBeInTheDocument();
  });

  it("TMS 正式入口拒绝缺失可信学校码的权限摘要", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({
        school_id: "school-1",
        actions: ["tenant.tms.access", "tenant.members.read"],
        scopes: [{ kind: "school", school_id: "school-1" }],
      });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    expect(await screen.findByText("学校入口未开放")).toBeInTheDocument();
    expect(screen.getByText(/未返回可信学校码/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /授予|撤销|审批|新增/ })).not.toBeInTheDocument();
  });

  it("TMS 正式入口把低风险授予、撤权和审批 apply 接到安全写 API", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST") return ok({ status: "ok" });
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read", "tenant.permissions.manage"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "not_enabled", reason_code: "external_directory_contract_missing", message: "外部目录合同缺失", users: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [
        { principal_id: "11111111-1111-4111-8111-111111111111", subject: "teacher-a", status: "active", policy_version: 7, roles: [] },
        { principal_id: "22222222-2222-4222-8222-222222222222", subject: "teacher-b", status: "active", policy_version: 5, roles: [{ assignment_id: "33333333-3333-4333-8333-333333333333", role_key: "school_auditor", role_version: 1, status: "active", version: 2 }] },
      ] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [{ approval_id: "44444444-4444-4444-8444-444444444444", status: "approved", operation: "school_activation", expected_target_policy_version: 6 }] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    await screen.findByText("teacher-a");
    fireEvent.click(screen.getByRole("button", { name: "授予只读角色" }));
    fireEvent.click(screen.getByRole("button", { name: "撤销 school_auditor" }));
    fireEvent.click(screen.getByRole("button", { name: "应用审批" }));

    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(3));
    const grant = requests.find(item => item.url.includes("/members/11111111-1111-4111-8111-111111111111/roles"));
    expect(grant?.init?.method).toBe("POST");
    expect(JSON.parse(String(grant?.init?.body))).toEqual(expect.objectContaining({ role_key: "school_auditor", role_version: 1, expected_target_policy_version: 7 }));
    const revoke = requests.find(item => item.url.includes("/assignments/33333333-3333-4333-8333-333333333333/revoke"));
    expect(JSON.parse(String(revoke?.init?.body))).toEqual(expect.objectContaining({ expected_assignment_version: 2, expected_target_policy_version: 5 }));
    const apply = requests.find(item => item.url.includes("/approvals/44444444-4444-4444-8444-444444444444/apply"));
    expect(JSON.parse(String(apply?.init?.body))).toEqual(expect.objectContaining({ expected_target_policy_version: 6 }));
  });

  it("TMS 正式入口学校角色页接入权限目录安全 DTO 且只展示 tenant 动作", async () => {
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read", "tenant.permissions.manage"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "empty", reason_code: "empty", message: "学校目录暂无匹配用户", users: [] });
      if (url.endsWith("/api/v1/tms/permissions")) return ok({
        actions: [
          { action_key: "tenant.members.read", allowed_scope: "school", sensitive: false, status: "active", version: 1 },
          { action_key: "tenant.permissions.manage", allowed_scope: "school", sensitive: true, status: "active", version: 1 },
          { action_key: "ops.providers.manage", allowed_scope: "platform", sensitive: true, status: "active", version: 1 },
        ],
        roles: [
          { role_key: "school_auditor", version: 1, scope_kind: "school", is_template: true, actions: ["tenant.members.read"] },
          { role_key: "custom_reader", version: 2, scope_kind: "school", is_template: false, owner_school_id: "school-1", actions: ["tenant.members.read"] },
        ],
        principals: [{ principal_id: "11111111-1111-4111-8111-111111111111", subject: "teacher-a", status: "active", policy_version: 7 }],
        assignments: [{ assignment_id: "22222222-2222-4222-8222-222222222222", principal_id: "11111111-1111-4111-8111-111111111111", subject: "teacher-a", role_key: "school_auditor", role_version: 1, status: "active", version: 2 }],
      });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    await screen.findByRole("heading", { name: "学校智能体管理后台" });
    fireEvent.click(screen.getByRole("button", { name: "学校角色" }));

    await waitFor(() => expect(requests.some(url => url.endsWith("/api/v1/tms/permissions"))).toBe(true));
    expect(screen.getByRole("heading", { name: "学校角色" })).toBeInTheDocument();
    expect((await screen.findAllByText("school_auditor v1")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("custom_reader v2")).toBeInTheDocument();
    expect(screen.getAllByText("tenant.members.read").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("tenant.permissions.manage")).toBeInTheDocument();
    expect(screen.getAllByText("teacher-a").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("ops.providers.manage")).not.toBeInTheDocument();
  });

  it("TMS 正式入口可打开授权审批详情并保留 apply 写按钮", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST") return ok({ status: "applied" });
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read", "tenant.permissions.manage"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "empty", reason_code: "empty", message: "学校目录暂无匹配用户", users: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [{ approval_id: "44444444-4444-4444-8444-444444444444", status: "approved", operation: "school_admin_grant", expected_target_policy_version: 6 }] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    await screen.findByRole("heading", { name: "学校智能体管理后台" });
    fireEvent.click(screen.getByRole("button", { name: "授权记录" }));
    fireEvent.click(screen.getByRole("button", { name: "查看审批详情" }));

    const dialog = screen.getByRole("dialog", { name: "详情 · school_admin_grant" });
    expect(within(dialog).getByRole("heading", { name: "授权审批详情" })).toBeInTheDocument();
    expect(within(dialog).getByText("44444444-4444-4444-8444-444444444444")).toBeInTheDocument();
    expect(within(dialog).getByText("Policy v6")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "应用审批" })).toBeInTheDocument();
  });

  it("TMS 正式入口在 access.manage 下接入服务访问 grant/revoke 写 API 且不写额度", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST" && url.endsWith("/api/v1/tms/service-access")) {
        return ok({ grant_id: "66666666-6666-4666-8666-666666666666", service_id: "llm", subject_kind: "member", subject_id: "11111111-1111-4111-8111-111111111111", status: "active", sync_status: "local_ready", version: 1 });
      }
      if (init?.method === "POST" && url.endsWith("/api/v1/tms/service-access/55555555-5555-4555-8555-555555555555/revoke")) {
        return ok({ grant_id: "55555555-5555-4555-8555-555555555555", service_id: "llm", subject_kind: "member", subject_id: "22222222-2222-4222-8222-222222222222", status: "revoked", sync_status: "synced", version: 3 });
      }
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read", "tenant.access.manage", "tenant.quotas.read", "tenant.usage.read"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "empty", reason_code: "empty", message: "学校目录暂无匹配用户", users: [] });
      if (url.endsWith("/api/v1/tms/quotas")) return ok({
        entitlements: [{ service_id: "llm", status: "active", version: 5, starts_at: "2026-01-01T00:00:00Z", expires_at: "9998-01-01T00:00:00Z" }],
        grants: [],
        usage_details: [],
      });
      if (url.endsWith("/api/v1/tms/service-access")) return ok({ service_access_grants: [{ grant_id: "55555555-5555-4555-8555-555555555555", service_id: "llm", subject_kind: "member", subject_id: "22222222-2222-4222-8222-222222222222", status: "active", sync_status: "synced", version: 2, entitlement_version: 5 }] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [
        { principal_id: "11111111-1111-4111-8111-111111111111", subject: "teacher-a", status: "active", policy_version: 7, roles: [] },
        { principal_id: "22222222-2222-4222-8222-222222222222", subject: "teacher-b", status: "active", policy_version: 5, roles: [] },
      ] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    await screen.findByText("teacher-a");
    fireEvent.click(screen.getByRole("button", { name: "授予首个服务访问" }));
    fireEvent.click(screen.getByRole("button", { name: "撤销服务访问" }));

    await waitFor(() => expect(requests.filter(item => item.init?.method === "POST")).toHaveLength(2));
    const grant = requests.find(item => item.url.endsWith("/api/v1/tms/service-access") && item.init?.method === "POST");
    const grantBody = JSON.parse(String(grant?.init?.body));
    expect(grantBody).toEqual(expect.objectContaining({
      service_id: "llm",
      subject_kind: "member",
      subject_id: "11111111-1111-4111-8111-111111111111",
      expected_entitlement_version: 5,
    }));
    expect(grantBody.reason).toContain("正式 TMS");
    expect(grantBody).not.toHaveProperty("quantity");
    expect(grantBody).not.toHaveProperty("unit_code");
    const revoke = requests.find(item => item.url.endsWith("/api/v1/tms/service-access/55555555-5555-4555-8555-555555555555/revoke"));
    const revokeBody = JSON.parse(String(revoke?.init?.body));
    expect(revokeBody).toEqual(expect.objectContaining({ expected_version: 2 }));
    expect(revokeBody.reason).toContain("正式 TMS");
  });

  it("TMS 正式入口只读展示学校额度、用量和服务访问 DTO", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read", "tenant.quotas.read", "tenant.usage.read", "tenant.access.manage"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "not_enabled", reason_code: "external_directory_contract_missing", message: "外部目录合同缺失", users: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/tms/quotas")) return ok({ grants: [{ grant_id: "q-1", service_id: "llm", unit_code: "token", quantity: "100", status: "active" }], usage: [{ service_id: "llm", unit_code: "token", status: "settled", settled_units: "12", reserved_units: "0" }], usage_details: [{ attempt_id: "a-1", service_id: "llm", unit_code: "token", status: "settled", settled_units: "12", reserved_units: "0" }] });
      if (url.endsWith("/api/v1/tms/service-access")) return ok({ service_access_grants: [{ grant_id: "g-1", service_id: "llm", subject_kind: "member", subject_id: "teacher-a", status: "active", sync_status: "synced" }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    expect(await screen.findByRole("heading", { name: "额度与用量" })).toBeInTheDocument();
    expect(screen.getByText("100 token")).toBeInTheDocument();
    expect(screen.getByText("12 token")).toBeInTheDocument();
    expect(screen.getByText("teacher-a")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /授予额度|调整额度|查看成本|Secret/ })).not.toBeInTheDocument();
  });

  it.each([
    ["empty_scope", "当前账号没有可搜索的学校目录范围", "目录空范围"],
    ["empty", "学校目录暂无匹配用户", "目录空结果"],
    ["failed", "学校目录服务暂不可用", "目录外部失败"],
  ])("TMS 正式入口区分目录状态：%s", async (status, message, label) => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status, reason_code: status, message, users: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    expect(await screen.findByRole("heading", { name: "学校目录" })).toBeInTheDocument();
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.queryByText("赵老师")).not.toBeInTheDocument();
  });

  it("OMS 正式入口只读展示模型与服务目录和供应商连接且不泄露 Secret", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.skills.read", "ops.providers.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/oms/models/draft")) return ok({ version: 2, status: "saved", models: [{ profile_id: "chat", model_id: "qwen-plus", model: "qwen-plus", provider: "dashscope", status: "not_active" }] });
      if (url.endsWith("/api/v1/oms/provider-settings")) return ok({ version: 3, status: "active", settings: { connections: { dashscope: { provider: "dashscope", base_url: "https://dashscope.example/v1", api_key: "<redacted>" } } } });
      if (url.endsWith("/api/v1/oms/resources/status")) return ok({ categories: ["model_external"], resources: [] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 0, notices: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });

    fireEvent.click(screen.getByRole("button", { name: "模型与服务" }));
    expect(await screen.findByRole("heading", { name: "模型与服务" })).toBeInTheDocument();
    expect(screen.getByText("按基座服务语义管理平台目录；配置与实际生效分离。")).toBeInTheDocument();
    expect(screen.getByText(/模型草稿 v2/)).toBeInTheDocument();
    expect(screen.getByText("对话模型")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索服务" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "模型与 Provider" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "供应商连接" }));
    expect(await screen.findByRole("heading", { name: "供应商连接" })).toBeInTheDocument();
    expect(screen.getByText("连接与服务配置分层维护；凭据由高权限角色处理。")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索连接" })).toBeInTheDocument();
    expect(screen.getAllByText("dashscope").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("<redacted>").length).toBeGreaterThanOrEqual(1);
    expect(document.body).not.toHaveTextContent("env:");
    expect(document.body).not.toHaveTextContent("sk-");
    expect(screen.queryByRole("button", { name: /保存|发布|回滚|测试/ })).not.toBeInTheDocument();
  });

  it("OMS 模型与服务和供应商连接保留原型交互骨架且始终脱敏凭据引用", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.providers.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/status/catalog")) return ok({ statuses: [
        { code: "draft", label: "草稿待发布", description: "配置草稿尚未发布", tone: "warning" },
        { code: "ready", label: "可用", tone: "success" },
      ] });
      if (url.endsWith("/api/v1/oms/models/draft")) return ok({
        version: 7,
        status: "draft",
        models: [{ id: "chat-main", profile_id: "chat", model_id: "qwen-plus", provider: "dashscope", status: "draft", source: "global-draft" }],
      });
      if (url.endsWith("/api/v1/oms/provider-settings")) return ok({
        version: 9,
        status: "draft",
        settings: { connections: { dashscope: { provider: "dashscope", base_url: "https://dashscope.example/v1", api_key: "env:DASHSCOPE_API_KEY" } } },
      });
      if (url.endsWith("/api/v1/oms/resources/status")) return ok({ resources: [] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 0, notices: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });

    fireEvent.click(screen.getByRole("button", { name: "模型与服务" }));
    expect(await screen.findByRole("heading", { name: "模型与服务" })).toBeInTheDocument();
    expect(screen.getByText("按基座服务语义管理平台目录；配置与实际生效分离。")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "全部服务" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "文档识别与解析" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索服务" })).toBeInTheDocument();
    expect(screen.getByText(/模型草稿 v7/)).toBeInTheDocument();
    expect(screen.getByText(/Provider 设置 v9/)).toBeInTheDocument();
    expect(screen.getAllByText(/草稿待发布/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("对话模型")).toBeInTheDocument();
    for (const action of ["服务概况", "服务配置", "Provider 配置", "模型清单", "关联记录", "发布记录"]) {
      expect(screen.getByRole("button", { name: action })).toBeInTheDocument();
    }
    expect(document.body).not.toHaveTextContent("env:DASHSCOPE_API_KEY");

    fireEvent.click(screen.getByRole("button", { name: "供应商连接" }));
    expect(await screen.findByRole("heading", { name: "供应商连接" })).toBeInTheDocument();
    expect(screen.getByText("连接与服务配置分层维护；凭据由高权限角色处理。")).toBeInTheDocument();
    expect(screen.getByText(/供应商连接配置版本 v9/)).toBeInTheDocument();
    expect(screen.getByText("适用服务")).toBeInTheDocument();
    expect(screen.getByText("凭据状态")).toBeInTheDocument();
    expect(screen.getAllByText("<redacted>").length).toBeGreaterThanOrEqual(1);
    const providerSearch = screen.getByRole("searchbox", { name: "搜索连接" });
    fireEvent.change(providerSearch, { target: { value: "DASHSCOPE_API_KEY" } });
    expect(screen.getByText("没有符合条件的记录")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "连接资料" })).not.toBeInTheDocument();
    fireEvent.change(providerSearch, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "连接资料" }));

    expect(await screen.findByRole("heading", { name: "dashscope" })).toBeInTheDocument();
    expect(screen.getByText("连接元数据与凭据维护分开操作；凭据明文不在详情回显。")).toBeInTheDocument();
    expect(screen.getAllByText(/Secret 明文不可见/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("<redacted>").length).toBeGreaterThanOrEqual(1);
    expect(document.body).not.toHaveTextContent("env:DASHSCOPE_API_KEY");
  });

  it("OMS 正式入口聚合资源、学校、供给、审计和成本只读 DTO", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.providers.read", "ops.tenants.read", "ops.supply.read", "ops.audit.read", "ops.cost.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/oms/models/draft")) return ok({ models: [] });
      if (url.endsWith("/api/v1/oms/provider-settings")) return ok({ status: "active", settings: { connections: {} } });
      if (url.endsWith("/api/v1/oms/resources/status")) return ok({ categories: ["model_external"], resources: [{ id: "model:chat:qwen", category: "model_external", display_name: "Qwen Chat", status: "ready", managed: true }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 1, notices: [{ code: "oms_scope_is_explicit", label: "OMS 仅显示已授权学校范围" }] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ count: 1, tenants: [{ school_id: "school-1", school_code: "demo-school", external_binding: { status: { label: "已核验" } }, lifecycle: { external_eligibility: { label: "学校订阅有效" } } }] });
      if (url.endsWith("/api/v1/oms/supply")) return ok({ service_definitions: [{ service_id: "llm", unit_code: "token", resource_category: "model_external", enabled: true, version: 1 }], supply_lots: [{ service_id: "llm", provider_id: "dashscope", pool_id: "pool-a", unit_code: "token", status: { label: "生效" }, hard_ceiling: "1000", committed_unspent: "300", reserved_inflight: "0" }] });
      if (url.endsWith("/api/v1/oms/audit")) return ok({ management_events: [{ action: "ops.supply.read", result: { label: "成功" }, request_id: "req-1" }], oms_events: [] });
      if (url.endsWith("/api/v1/oms/cost")) return ok({ costs: [], status: { label: "未配置" }, notice: "当前没有已核实供应商成本源" });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByRole("heading", { name: "OMS 总览" })).toBeInTheDocument();
    expect(screen.getByText("OMS 仅显示已授权学校范围")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "平台资源状态" })).toBeInTheDocument();
    expect(screen.getByText("Qwen Chat")).toBeInTheDocument();
    expect(screen.getByText("demo-school")).toBeInTheDocument();
    expect(screen.getByText("学校订阅有效")).toBeInTheDocument();
    expect(screen.getByText("dashscope")).toBeInTheDocument();
    expect(screen.getByText("当前没有已核实供应商成本源")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /补充|调整|导出成本|查看密钥|授予额度|授权学校服务/ })).not.toBeInTheDocument();
  });

  it("OMS 正式入口按首个已授权学校展示用量 attempt 与待核对任务只读 DTO", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.tenants.read", "ops.usage.read", "ops.jobs.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", lifecycle: { external_eligibility: { label: "学校订阅有效" } } }] });
      if (url.endsWith("/api/v1/oms/schools/school-1/usage")) return ok({ details: [{ attempt_id: "attempt-1", operation_id: "op-1", service_id: "llm", unit_code: "token", status: { label: "已结算" }, reserved_units: "12", settled_units: "10" }] });
      if (url.endsWith("/api/v1/oms/schools/school-1/jobs")) return ok({ jobs: [{ attempt_id: "attempt-2", operation_id: "op-2", service_id: "video", status: { label: "远端结果未知" }, reserved_units: "1", settled_units: "0" }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByRole("heading", { name: "学校用量与任务" })).toBeInTheDocument();
    expect(screen.getByText("attempt-1")).toBeInTheDocument();
    expect(screen.getByText("已结算")).toBeInTheDocument();
    expect(screen.getByText("attempt-2")).toBeInTheDocument();
    expect(screen.getByText("远端结果未知")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("学生原文");
    expect(screen.queryByRole("button", { name: /结算|释放|核销|强制完成/ })).not.toBeInTheDocument();
  });

  it("OMS 正式入口在 manage 权限下接入模型与 Provider 写入 API 并回读审计", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST") return ok({ status: "queued" });
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.providers.read", "ops.providers.manage", "ops.audit.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/oms/models/draft")) return ok({ version: 4, status: "tested", models: [{ profile_id: "chat", model_id: "qwen-plus", provider: "dashscope", status: "not_active" }] });
      if (url.endsWith("/api/v1/oms/provider-settings")) return ok({ version: 3, status: "draft", settings: { connections: { dashscope: { provider: "dashscope", api_key: "<redacted>" } } } });
      if (url.endsWith("/api/v1/oms/resources/status")) return ok({ resources: [] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/audit")) return ok({ management_events: [{ action: "ops.providers.manage", result: "success", request_id: "write-1" }], oms_events: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "模型与服务" }));
    await screen.findByRole("heading", { name: "模型与服务" });
    fireEvent.click(screen.getByRole("button", { name: "服务配置" }));
    await screen.findByRole("heading", { name: "配置概况" });
    fireEvent.click(screen.getByRole("button", { name: "测试模型草稿" }));
    fireEvent.click(screen.getByRole("button", { name: "发布模型草稿" }));
    fireEvent.click(screen.getByRole("button", { name: "回滚 Provider 草稿" }));

    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(3));
    const modelTest = requests.find(item => item.url.endsWith("/api/v1/oms/models/test"));
    expect(JSON.parse(String(modelTest?.init?.body))).toEqual(expect.objectContaining({ expected_version: 4, reason: expect.stringContaining("正式 OMS") }));
    const modelPublish = requests.find(item => item.url.endsWith("/api/v1/oms/models/publish"));
    expect(JSON.parse(String(modelPublish?.init?.body))).toEqual(expect.objectContaining({ expected_version: 4 }));
    const providerRollback = requests.find(item => item.url.endsWith("/api/v1/oms/provider-settings/rollback"));
    expect(JSON.parse(String(providerRollback?.init?.body))).toEqual(expect.objectContaining({ expected_version: 3 }));
    expect(screen.getByText(/回滚 Provider 草稿 已提交/)).toBeInTheDocument();
  });

  it("OMS 模型与服务支持通过正式 JSON 保存模型草稿", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST") return ok({ version: 5, status: "saved" });
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.providers.read", "ops.providers.manage"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/models/draft")) return ok({ version: 4, status: "saved", models: [{ id: "chat-main", profile_id: "chat", model_id: "qwen-plus", model: "qwen-plus", provider: "openai", status: "saved" }] });
      if (url.endsWith("/api/v1/oms/provider-settings")) return ok({ version: 3, status: "active", settings: { connections: { dashscope: { provider: "openai", base_url: "https://dashscope.example/v1", api_key: "<redacted>" } } } });
      if (url.endsWith("/api/v1/oms/resources/status")) return ok({ resources: [] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 0, notices: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "模型与服务" }));
    await screen.findByRole("heading", { name: "模型与服务" });
    fireEvent.click(screen.getByRole("button", { name: "保存模型草稿 JSON" }));
    const dialog = await screen.findByRole("dialog", { name: "保存模型草稿 JSON" });
    const modelsJson = within(dialog).getByRole("textbox", { name: "模型草稿 JSON" });
    fireEvent.change(modelsJson, { target: { value: JSON.stringify([{
      profile_id: "chat",
      model_id: "qwen-max",
      model: "qwen-max",
      base_url: "https://dashscope.example/v1",
      secret: "env:DASHSCOPE_API_KEY",
      provider: "openai",
      max_tokens: 4096,
      context_window: 32768,
    }]) } });
    fireEvent.click(within(dialog).getByRole("button", { name: "保存模型草稿" }));

    await waitFor(() => expect(requests.some(item => item.url.endsWith("/api/v1/oms/models/draft") && item.init?.method === "POST")).toBe(true));
    const draftRequest = requests.find(item => item.url.endsWith("/api/v1/oms/models/draft") && item.init?.method === "POST");
    expect(JSON.parse(String(draftRequest?.init?.body))).toEqual(expect.objectContaining({
      expected_version: 4,
      reason: expect.stringContaining("正式 OMS"),
      models: [expect.objectContaining({ profile_id: "chat", model_id: "qwen-max", secret: "env:DASHSCOPE_API_KEY" })],
    }));
    expect(await screen.findByText(/保存模型草稿 已提交/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("sk-");
  });

  it("OMS 供应商连接支持 Provider 设置 dry-run 与草稿保存并使用正式版本", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST" && url.endsWith("/api/v1/oms/provider-settings/dry-run")) return ok({
        id: "dry-run-1",
        recognized_sections: ["connections"],
        unsupported_sections: [],
        secret_paths: ["connections.dashscope.api_key"],
        result: { write_ready: true },
      });
      if (init?.method === "POST" && url.endsWith("/api/v1/oms/provider-settings/draft")) return ok({ version: 10, status: "saved" });
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.providers.read", "ops.providers.manage"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/models/draft")) return ok({ version: 7, status: "saved", models: [] });
      if (url.endsWith("/api/v1/oms/provider-settings")) return ok({ version: 9, status: "tested", settings: { connections: { dashscope: { provider: "openai", base_url: "https://dashscope.example/v1", api_key: "<redacted>" } } } });
      if (url.endsWith("/api/v1/oms/resources/status")) return ok({ resources: [] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 0, notices: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "供应商连接" }));
    await screen.findByRole("heading", { name: "供应商连接" });
    fireEvent.click(screen.getByRole("button", { name: "轮换凭据" }));
    const dialog = await screen.findByRole("dialog", { name: "导入 Provider 设置 JSON" });
    const settingsJson = within(dialog).getByRole("textbox", { name: "Provider 设置 JSON" });
    fireEvent.change(settingsJson, { target: { value: JSON.stringify({
      connections: {
        dashscope: {
          provider: "openai",
          base_url: "https://dashscope.example/v1",
          api_key: "env:DASHSCOPE_API_KEY",
        },
      },
    }) } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Dry-run Provider 设置" }));
    await screen.findByText(/Provider 设置 dry-run 完成/);
    fireEvent.click(within(dialog).getByRole("button", { name: "保存 Provider 草稿" }));

    await waitFor(() => expect(requests.some(item => item.url.endsWith("/api/v1/oms/provider-settings/draft") && item.init?.method === "POST")).toBe(true));
    const dryRunRequest = requests.find(item => item.url.endsWith("/api/v1/oms/provider-settings/dry-run"));
    expect(JSON.parse(String(dryRunRequest?.init?.body))).toEqual(expect.objectContaining({
      source_kind: "oms-formal-ui",
      settings: expect.objectContaining({ connections: expect.any(Object) }),
    }));
    const draftRequest = requests.find(item => item.url.endsWith("/api/v1/oms/provider-settings/draft"));
    expect(JSON.parse(String(draftRequest?.init?.body))).toEqual(expect.objectContaining({
      expected_version: 9,
      reason: expect.stringContaining("正式 OMS"),
      settings: expect.objectContaining({ connections: expect.any(Object) }),
    }));
    expect(await screen.findByText(/保存 Provider 草稿 已提交/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("sk-");
  });

  it("OMS 正式入口在 Skill 权限下接入 review/publish/grant 写 API", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    const revisionId = "55555555-5555-4555-8555-555555555555";
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST") return ok({ status: "queued" });
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.skills.read", "ops.skills.review", "ops.skills.publish", "ops.skills.grant", "ops.tenants.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [{ name: "agent-skill", status: "approved", revision_id: revisionId, latest_version: 2, published_version: 0, sha256: "a".repeat(64), description: "待发布 Skill" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", lifecycle: { external_eligibility: "allowed" } }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByText("agent-skill");
    fireEvent.click(screen.getByRole("button", { name: "批准 Skill" }));
    fireEvent.click(screen.getByRole("button", { name: "发布 Skill" }));
    fireEvent.click(screen.getByRole("button", { name: "授权首个学校 Skill" }));

    await waitFor(() => expect(requests.filter(item => item.init?.method === "POST")).toHaveLength(3));
    const review = requests.find(item => item.url.endsWith(`/api/v1/oms/skills/revisions/${revisionId}/review`));
    expect(JSON.parse(String(review?.init?.body))).toEqual(expect.objectContaining({ expected_sha256: "a".repeat(64), approved: true }));
    const publish = requests.find(item => item.url.endsWith(`/api/v1/oms/skills/revisions/${revisionId}/publish`));
    expect(JSON.parse(String(publish?.init?.body))).toEqual(expect.objectContaining({ expected_version: 2 }));
    const grant = requests.find(item => item.url.endsWith("/api/v1/oms/skills/agent-skill/schools/school-1/grant"));
    expect(JSON.parse(String(grant?.init?.body))).toEqual(expect.objectContaining({ expected_grant_version: 0, reason: expect.stringContaining("正式 OMS") }));
  });

  it("OMS 正式入口接入平台人员、角色、学校范围和审批写入 API", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    const pendingPrincipal = "11111111-1111-4111-8111-111111111111";
    const activePrincipal = "22222222-2222-4222-8222-222222222222";
    const approvalId = "33333333-3333-4333-8333-333333333333";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST") return ok({ status: "queued" });
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "security-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.permissions.manage", "ops.tenants.read", "ops.audit.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", lifecycle: { external_eligibility: "allowed" } }] });
      if (url.endsWith("/api/v1/oms/audit")) return ok({ management_events: [{ action: "ops.permissions.manage", result: "success", request_id: "authz-1" }], oms_events: [] });
      if (url.endsWith("/api/v1/oms/permissions")) return ok({
        actions: [{ action_key: "ops.permissions.manage", allowed_scope: "platform", sensitive: true }],
        roles: [
          { role_key: "platform_config_admin", version: 2, scope_kind: "platform", actions: ["ops.providers.manage"] },
          { role_key: "platform_auditor", version: 1, scope_kind: "school", actions: ["ops.tenants.read"] },
        ],
        principals: [
          { principal_id: pendingPrincipal, subject: "pending-config", status: "pending", policy_version: 1 },
          { principal_id: activePrincipal, subject: "school-auditor", status: "active", policy_version: 4 },
        ],
        assignments: [{ assignment_id: "as-1", principal_id: activePrincipal, role_key: "platform_auditor", scope_kind: "school", school_id: "school-1", status: "active", version: 1 }],
      });
      if (url.endsWith("/api/v1/oms/approvals")) return ok({ approvals: [
        { approval_id: approvalId, operation: "platform_grant", target_principal_id: pendingPrincipal, status: "approved", expected_target_policy_version: 1, target_role_key: "platform_config_admin", target_role_version: 2 },
        { approval_id: "44444444-4444-4444-8444-444444444444", operation: "platform_grant", target_principal_id: pendingPrincipal, status: "pending", expected_target_policy_version: 1, target_role_key: "platform_config_admin", target_role_version: 2 },
      ] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台授权治理" });
    expect(screen.getByText("pending-config")).toBeInTheDocument();
    expect(screen.getAllByText("platform_config_admin").length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByRole("button", { name: "提交平台授权审批" }));
    fireEvent.click(screen.getByRole("button", { name: "授予学校只读范围" }));
    fireEvent.click(screen.getByRole("button", { name: "撤销 OMS 授权" }));
    fireEvent.click(screen.getByRole("button", { name: "批准授权审批" }));
    fireEvent.click(screen.getByRole("button", { name: "应用授权审批" }));
    fireEvent.click(screen.getByRole("button", { name: "停用平台主体" }));

    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(6));
    const createApproval = requests.find(item => item.url.endsWith("/api/v1/oms/approvals") && item.init?.method === "POST");
    expect(JSON.parse(String(createApproval?.init?.body))).toEqual(expect.objectContaining({
      operation: "platform_grant",
      target_principal_id: pendingPrincipal,
      target_role_key: "platform_config_admin",
      target_role_version: 2,
      confirmed_role_version: 2,
    }));
    const schoolGrant = requests.find(item => item.url.endsWith(`/api/v1/oms/principals/${activePrincipal}/roles`));
    expect(JSON.parse(String(schoolGrant?.init?.body))).toEqual(expect.objectContaining({
      role_key: "platform_auditor",
      role_version: 1,
      target_school_id: "school-1",
      expected_target_policy_version: 4,
    }));
    const revoke = requests.find(item => item.url.endsWith("/api/v1/oms/assignments/as-1/revoke"));
    expect(JSON.parse(String(revoke?.init?.body))).toEqual(expect.objectContaining({
      target_school_id: "school-1",
      expected_assignment_version: 1,
      expected_target_policy_version: 4,
    }));
    const review = requests.find(item => item.url.endsWith("/api/v1/oms/approvals/44444444-4444-4444-8444-444444444444/review"));
    expect(JSON.parse(String(review?.init?.body))).toEqual(expect.objectContaining({ decision: "approved", expected_target_policy_version: 1 }));
    const apply = requests.find(item => item.url.endsWith(`/api/v1/oms/approvals/${approvalId}/apply`));
    expect(JSON.parse(String(apply?.init?.body))).toEqual(expect.objectContaining({ expected_target_policy_version: 1 }));
    const disable = requests.find(item => item.url.endsWith(`/api/v1/oms/principals/${activePrincipal}/disable`));
    expect(JSON.parse(String(disable?.init?.body))).toEqual(expect.objectContaining({ expected_target_policy_version: 4 }));
  });

  it("OMS 正式入口提供平台授权治理详情抽屉和审批回读", async () => {
    const pendingPrincipal = "11111111-1111-4111-8111-111111111111";
    const activePrincipal = "22222222-2222-4222-8222-222222222222";
    const approvalId = "33333333-3333-4333-8333-333333333333";
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "security-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.permissions.manage", "ops.tenants.read", "ops.audit.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", lifecycle: { external_eligibility: "allowed" } }] });
      if (url.endsWith("/api/v1/oms/audit")) return ok({ management_events: [{ action: "ops.permissions.manage", result: "success", request_id: "authz-1" }], oms_events: [] });
      if (url.endsWith("/api/v1/oms/permissions")) return ok({
        actions: [{ action_key: "ops.permissions.manage", allowed_scope: "platform", sensitive: true }],
        roles: [
          { role_key: "platform_config_admin", version: 2, scope_kind: "platform", actions: ["ops.providers.manage"] },
          { role_key: "platform_auditor", version: 1, scope_kind: "school", actions: ["ops.tenants.read"] },
        ],
        principals: [
          { principal_id: pendingPrincipal, subject: "pending-config", status: "pending", policy_version: 1 },
          { principal_id: activePrincipal, subject: "school-auditor", status: "active", policy_version: 4 },
        ],
        assignments: [{ assignment_id: "as-1", principal_id: activePrincipal, role_key: "platform_auditor", role_version: 1, scope_kind: "school", school_id: "school-1", status: "active", version: 1 }],
      });
      if (url.endsWith("/api/v1/oms/approvals")) return ok({ approvals: [
        { approval_id: approvalId, operation: "platform_grant", target_principal_id: pendingPrincipal, status: "approved", expected_target_policy_version: 1, target_role_key: "platform_config_admin", target_role_version: 2 },
      ] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台授权治理" });
    fireEvent.click(screen.getAllByRole("button", { name: "查看平台主体详情" })[0]);
    expect(await screen.findByRole("dialog", { name: "详情 · pending-config" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "平台主体详情" })).toBeInTheDocument();
    expect(screen.getByText(pendingPrincipal)).toBeInTheDocument();
    expect(screen.getByText("可信 OMS 登录登记 / DeepTutor Enterprise 本地事实")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));

    fireEvent.click(screen.getAllByRole("button", { name: "查看角色模板详情" })[0]);
    expect(await screen.findByRole("heading", { name: "角色模板详情" })).toBeInTheDocument();
    expect(screen.getAllByText("platform_config_admin").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("ops.providers.manage").length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));

    fireEvent.click(screen.getByRole("button", { name: "查看授权范围详情" }));
    expect(await screen.findByRole("heading", { name: "授权范围详情" })).toBeInTheDocument();
    expect(screen.getByText("as-1")).toBeInTheDocument();
    expect(screen.getAllByText("学校 school-1").length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));

    fireEvent.click(screen.getByRole("button", { name: "查看审批详情" }));
    expect(await screen.findByRole("heading", { name: "授权审批详情" })).toBeInTheDocument();
    expect(screen.getByText(approvalId)).toBeInTheDocument();
    expect(screen.getAllByText("platform_config_admin v2").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("button", { name: "应用此审批" })).toBeInTheDocument();
  });

  it.each([1280, 390])("OMS 正式入口在 %dpx 视口保留语义导航、命名按钮和键盘触发", async (width) => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    window.dispatchEvent(new Event("resize"));
    const user = userEvent.setup();
    const requests: { url: string; init?: RequestInit }[] = [];
    const pendingPrincipal = "11111111-1111-4111-8111-111111111111";
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST") return ok({ status: "queued" });
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "security-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.permissions.manage", "ops.providers.read", "ops.providers.manage", "ops.skills.read", "ops.skills.review", "ops.skills.publish", "ops.skills.grant", "ops.tenants.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [{ name: "agent-skill", status: "approved", revision_id: "55555555-5555-4555-8555-555555555555", latest_version: 2, sha256: "a".repeat(64) }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", lifecycle: { external_eligibility: "allowed" } }] });
      if (url.endsWith("/api/v1/oms/permissions")) return ok({
        actions: [{ action_key: "ops.permissions.manage", allowed_scope: "platform", sensitive: true }],
        roles: [
          { role_key: "platform_config_admin", version: 2, scope_kind: "platform", actions: ["ops.providers.manage"] },
          { role_key: "platform_auditor", version: 1, scope_kind: "school", actions: ["ops.tenants.read"] },
        ],
        principals: [{ principal_id: pendingPrincipal, subject: "pending-config", status: "pending", policy_version: 1 }],
        assignments: [],
      });
      if (url.endsWith("/api/v1/oms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/oms/models/draft")) return ok({ version: 4, models: [{ profile_id: "chat", model_id: "qwen-plus", provider: "dashscope" }] });
      if (url.endsWith("/api/v1/oms/provider-settings")) return ok({ version: 3, status: "draft", settings: { connections: { dashscope: { provider: "dashscope", api_key: "<redacted>" } } } });
      if (url.endsWith("/api/v1/oms/resources/status")) return ok({ resources: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByRole("main", { name: "OMS 正式管理入口" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "平台授权治理" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "模型与 Provider" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Skill 清单" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索平台人员" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索模型" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索 Skill" })).toBeInTheDocument();

    const approvalButton = screen.getByRole("button", { name: "提交平台授权审批" });
    approvalButton.focus();
    expect(approvalButton).toHaveFocus();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(requests.some(item => item.url.endsWith("/api/v1/oms/approvals") && item.init?.method === "POST")).toBe(true));
  });

  it.each([1280, 390])("TMS 正式入口在 %dpx 视口保留语义导航、命名按钮和键盘触发", async (width) => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    window.dispatchEvent(new Event("resize"));
    const user = userEvent.setup();
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST") return ok({ status: "queued" });
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read", "tenant.permissions.manage", "tenant.quotas.read", "tenant.usage.read", "tenant.access.manage"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "empty", reason_code: "empty", message: "学校目录暂无匹配用户", users: [] });
      if (url.endsWith("/api/v1/tms/quotas")) return ok({ grants: [], usage_details: [] });
      if (url.endsWith("/api/v1/tms/service-access")) return ok({ service_access_grants: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [{ principal_id: "11111111-1111-4111-8111-111111111111", subject: "teacher-a", status: "active", policy_version: 7, roles: [] }] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [{ approval_id: "22222222-2222-4222-8222-222222222222", status: "approved", operation: "school_activation", expected_target_policy_version: 6 }] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    expect(await screen.findByRole("main", { name: "TMS 正式管理入口" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "当前学校权限" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "学校目录" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "成员列表" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "审批与审计" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索学校目录" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索成员" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "搜索审批" })).toBeInTheDocument();

    const grantButton = screen.getByRole("button", { name: "授予只读角色" });
    grantButton.focus();
    expect(grantButton).toHaveFocus();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(requests.some(item => item.url.includes("/api/v1/tms/members/11111111-1111-4111-8111-111111111111/roles") && item.init?.method === "POST")).toBe(true));
  });


  it("OMS 正式入口沿用原型的列表到详情抽屉交互", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.skills.read", "ops.tenants.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", external_binding: { status: { label: "已绑定" } }, lifecycle: { external_eligibility: { label: "订阅有效" }, provisioning_status: { label: "资源就绪" } } }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "学校列表" }));
    fireEvent.click(screen.getByRole("button", { name: /查看 school-1 详情/ }));

    expect(screen.getByRole("dialog", { name: "详情 · school-1" })).toBeInTheDocument();
    expect(within(screen.getByRole("dialog", { name: "详情 · school-1" })).getByRole("heading", { name: "学校详情" })).toBeInTheDocument();
    expect(screen.getByText("OMS 不管理学校账号或 TMS tenant.* 角色；这里只展示平台人员 school-scope 可见的学校投影。")).toBeInTheDocument();
  });

  it("OMS 学校详情展示服务授权、额度和用量安全摘要", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.tenants.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({
        tenants: [{
          school_id: "school-1",
          external_binding: { status: { label: "已绑定" } },
          lifecycle: { external_eligibility: { label: "订阅有效" }, provisioning_status: { label: "资源就绪" } },
          service_entitlements: [{ status: { label: "生效" }, count: 2 }],
          quota_grants: [{ status: { label: "生效" }, units: "300" }],
          usage: [{ status: { label: "已结算" }, attempts: 5, settled_units: "120" }],
        }],
      });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "学校列表" }));
    fireEvent.click(screen.getByRole("button", { name: /查看 school-1 详情/ }));

    const dialog = screen.getByRole("dialog", { name: "详情 · school-1" });
    expect(within(dialog).getByRole("heading", { name: "服务授权与额度摘要" })).toBeInTheDocument();
    expect(within(dialog).getByText("服务授权")).toBeInTheDocument();
    expect(within(dialog).getByText("生效 × 2")).toBeInTheDocument();
    expect(within(dialog).getByText("额度")).toBeInTheDocument();
    expect(within(dialog).getByText("生效 300")).toBeInTheDocument();
    expect(within(dialog).getByText("用量")).toBeInTheDocument();
    expect(within(dialog).getByText("已结算 5 次 / 120")).toBeInTheDocument();
  });

  it("OMS 正式入口接入学校服务授权和额度 grant/adjust/revoke/expire 写 API", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    const grantId = "44444444-4444-4444-8444-444444444444";
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST" || init?.method === "PATCH") return ok({ status: "queued" });
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: [
        "ops.oms.access",
        "ops.tenants.read",
        "ops.supply.read",
        "ops.supply.manage",
        "ops.entitlements.read",
        "ops.entitlements.manage",
        "ops.quotas.read",
        "ops.quotas.manage",
      ], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/status/catalog")) return ok({ descriptor_version: 1, statuses: [
        { code: "active", label: "生效", tone: "success", description: "当前事实处于可用状态。" },
      ] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", lifecycle: { external_eligibility: "allowed" } }] });
      if (url.endsWith("/api/v1/oms/supply")) return ok({
        service_definitions: [{ service_id: "llm", unit_code: "token", resource_category: "model_external", enabled: true, version: 3 }],
        supply_lots: [{ lot_id: "33333333-3333-4333-8333-333333333333", service_id: "llm", provider_id: "dashscope", pool_id: "pool-a", unit_code: "token", status: "active", committed_unspent: "100", version: 4 }],
      });
      if (url.endsWith("/api/v1/oms/schools/school-1/quota")) return ok({
        school_id: "school-1",
        entitlements: [{ service_id: "llm", status: "active", starts_at: "2026-01-01T00:00:00Z", expires_at: "9998-01-01T00:00:00Z", version: 5 }],
        grants: [{ grant_id: grantId, service_id: "llm", unit_code: "token", acquisition_method: "gift", quantity: "20", adjustment_released: "0", status: "active", version: 7, source_ref_hash: "hash" }],
      });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "服务供给" }));
    fireEvent.click(screen.getByRole("button", { name: "撤销供给批次" }));
    fireEvent.click(screen.getByRole("button", { name: "授权当前学校服务" }));
    fireEvent.click(screen.getByRole("button", { name: "赠送当前学校额度" }));
    fireEvent.click(screen.getByRole("button", { name: "调整当前额度" }));
    fireEvent.click(screen.getByRole("button", { name: "撤销当前额度" }));
    fireEvent.click(screen.getByRole("button", { name: "过期当前额度" }));

    await waitFor(() => expect(requests.filter(item => item.init?.method === "POST" || item.init?.method === "PATCH").length).toBe(6));
    expect(JSON.parse(String(requests.find(item => item.url.endsWith("/api/v1/oms/supply/lots/33333333-3333-4333-8333-333333333333/revoke"))?.init?.body))).toEqual(expect.objectContaining({
      expected_version: 4,
      reason: expect.stringContaining("正式 OMS"),
    }));
    const entitlement = requests.find(item => item.url.endsWith("/api/v1/oms/schools/school-1/entitlements/llm"));
    expect(JSON.parse(String(entitlement?.init?.body))).toEqual(expect.objectContaining({
      status: "active",
      expected_version: 5,
      reason: expect.stringContaining("正式 OMS"),
    }));
    const quotaGrant = requests.find(item => item.url.endsWith("/api/v1/oms/schools/school-1/quota-grants"));
    expect(JSON.parse(String(quotaGrant?.init?.body))).toEqual(expect.objectContaining({
      service_id: "llm",
      unit_code: "token",
      acquisition_method: "gift",
      quantity: "1",
      provider_id: "dashscope",
      pool_id: "pool-a",
      expected_entitlement_version: 5,
      reason: expect.stringContaining("正式 OMS"),
    }));
    const quotaAdjust = requests.find(item => item.url.endsWith(`/api/v1/oms/schools/school-1/quota-grants/${grantId}`));
    expect(quotaAdjust?.init?.method).toBe("PATCH");
    expect(JSON.parse(String(quotaAdjust?.init?.body))).toEqual(expect.objectContaining({
      expected_version: 7,
      new_quantity: "20",
      reason: expect.stringContaining("正式 OMS"),
    }));
    expect(JSON.parse(String(requests.find(item => item.url.endsWith(`/api/v1/oms/schools/school-1/quota-grants/${grantId}/revoke`))?.init?.body))).toEqual(expect.objectContaining({ expected_version: 7 }));
    expect(JSON.parse(String(requests.find(item => item.url.endsWith(`/api/v1/oms/schools/school-1/quota-grants/${grantId}/expire`))?.init?.body))).toEqual(expect.objectContaining({ expected_version: 7 }));
    expect(requests.some(item => item.url.includes("api_key"))).toBe(false);
  });

  it("OMS 用量页按学校深链读取对应学校 usage/jobs", async () => {
    window.history.replaceState(null, "", "/oms/usage/school/school-2");
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.tenants.read", "ops.usage.read", "ops.jobs.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 2, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [
        { school_id: "school-1", lifecycle: { external_eligibility: "allowed" } },
        { school_id: "school-2", lifecycle: { external_eligibility: "allowed" } },
      ] });
      if (url.endsWith("/api/v1/oms/schools/school-2/usage")) return ok({ details: [{ attempt_id: "attempt-school-2", operation_id: "op-2", service_id: "llm", unit_code: "token", status: { label: "已结算" }, reserved_units: "20", settled_units: "18" }] });
      if (url.endsWith("/api/v1/oms/schools/school-2/jobs")) return ok({ jobs: [{ attempt_id: "job-school-2", operation_id: "op-job-2", service_id: "video", unit_code: "frame", status: { label: "需要人工核对" }, reserved_units: "1", settled_units: "0" }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByRole("heading", { name: "学校用量与任务" })).toBeInTheDocument();
    expect(screen.getAllByText(/school-2/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("attempt-school-2")).toBeInTheDocument();
    expect(screen.getByText("job-school-2")).toBeInTheDocument();
    expect(requests.some(url => url.endsWith("/api/v1/oms/schools/school-2/usage"))).toBe(true);
    expect(requests.some(url => url.endsWith("/api/v1/oms/schools/school-1/usage"))).toBe(false);
  });

  it("OMS 状态展示复用后端 display catalog 并在详情说明待核对动作", async () => {
    window.history.replaceState(null, "", "/oms/usage/school/school-1/attempt-unknown");
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.tenants.read", "ops.usage.read", "ops.jobs.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/status/catalog")) return ok({
        descriptor_version: 1,
        statuses: [
          { code: "remote_unknown", label: "远端结果未知", tone: "warning", description: "远端调用可能已经发生，必须核对后才能释放或结算。" },
          { code: "settled", label: "已结算", tone: "success", description: "已按可信 usage evidence 写入实际消耗。" },
        ],
      });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", lifecycle: { external_eligibility: "allowed" } }] });
      if (url.endsWith("/api/v1/oms/schools/school-1/usage")) return ok({ details: [{ attempt_id: "attempt-unknown", operation_id: "op-unknown", service_id: "llm", unit_code: "token", status: "remote_unknown", reserved_units: "20", settled_units: "0" }] });
      if (url.endsWith("/api/v1/oms/schools/school-1/jobs")) return ok({ jobs: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByRole("dialog", { name: "详情 · attempt-unknown" })).toBeInTheDocument();
    const dialog = screen.getByRole("dialog", { name: "详情 · attempt-unknown" });
    expect(within(dialog).getByText("远端结果未知")).toBeInTheDocument();
    expect(within(dialog).getByText("远端调用可能已经发生，必须核对后才能释放或结算。")).toBeInTheDocument();
    expect(screen.queryByText("remote_unknown")).not.toBeInTheDocument();
    expect(requests.some(url => url.endsWith("/api/v1/oms/status/catalog"))).toBe(true);
  });

  it("OMS Skill 写权限下仍可打开 Skill 详情并保留写按钮", async () => {
    const revisionId = "55555555-5555-4555-8555-555555555555";
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST") return ok({ status: "queued" });
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.skills.read", "ops.skills.publish"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [{ name: "agent-skill", status: "approved", revision_id: revisionId, latest_version: 2, published_version: 0, sha256: "a".repeat(64), description: "待发布 Skill" }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByText("agent-skill");
    fireEvent.click(screen.getByRole("button", { name: "查看 Skill 详情" }));

    expect(screen.getByRole("dialog", { name: "详情 · agent-skill" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Skill 详情" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发布 Skill" })).toBeInTheDocument();
  });

  it("TMS 正式入口沿用原型的成员详情抽屉和未启用页面状态", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "not_enabled", reason_code: "external_directory_contract_missing", message: "外部目录合同缺失", users: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [{ principal_id: "11111111-1111-4111-8111-111111111111", subject: "teacher-a", status: "active", policy_version: 7, roles: [{ assignment_id: "as-1", role_key: "school_auditor", role_version: 1, status: "active", version: 1 }] }] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TmsFormalApp schoolCode="demo-school"/>);

    await screen.findByRole("heading", { name: "学校智能体管理后台" });
    fireEvent.click(screen.getByRole("button", { name: "成员列表" }));
    fireEvent.click(screen.getByRole("button", { name: "成员资料" }));

    expect(screen.getByRole("dialog", { name: "详情 · teacher-a" })).toBeInTheDocument();
    expect(within(screen.getByRole("dialog", { name: "详情 · teacher-a" })).getByRole("heading", { name: "成员详情" })).toBeInTheDocument();
    expect(screen.getByText("school_auditor")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    fireEvent.click(screen.getByRole("button", { name: "知识库列表" }));
    expect(screen.getByRole("heading", { name: "知识与内容" })).toBeInTheDocument();
    expect(screen.getByText("知识库正式 DTO 尚未启用；当前不会回退到原型合成数据，也不会读取私有正文。")) .toBeInTheDocument();
  });


  it("OMS/TMS 正式入口原型导航下的审计深链不出现空白页", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.audit.read", "ops.cost.read", "ops.skills.read"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 0, resource_count: 0, notices: [] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [] });
      if (url.endsWith("/api/v1/oms/audit")) return ok({ management_events: [{ id: "audit-1", action: "ops.audit.read", result: { label: "允许" }, request_id: "req-1" }], oms_events: [] });
      if (url.endsWith("/api/v1/oms/cost")) return ok({ status: { label: "成本只读" }, costs: [] });
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "not_enabled", reason_code: "external_directory_contract_missing", message: "外部目录合同缺失", users: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [{ id: "ev-1", action: "tenant.permissions.manage", result: "allow" }] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [] });
      throw new Error(`unexpected fetch ${url}`);
    });

    const { unmount } = render(<OmsFormalApp/>);
    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "授权审计" }));
    expect(screen.getByRole("heading", { name: "审计与成本" })).toBeInTheDocument();
    expect(screen.getByText("ops.audit.read")).toBeInTheDocument();
    unmount();
    fetchMock.mockClear();
    window.history.replaceState(null, "", "/");

    render(<TmsFormalApp schoolCode="demo-school"/>);
    await screen.findByRole("heading", { name: "学校智能体管理后台" });
    fireEvent.click(screen.getByRole("button", { name: "管理事件" }));
    expect(screen.getByRole("heading", { name: "管理事件" })).toBeInTheDocument();
    expect(screen.getByText("tenant.permissions.manage")).toBeInTheDocument();
  });


  it("OMS/TMS 正式入口保留原型完整导航骨架且每个入口都有安全内容区", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/oms/me")) return ok({ principal_id: "p-oms", subject: "ops-user" });
      if (url.endsWith("/api/v1/oms/me/permissions")) return ok({ actions: ["ops.oms.access", "ops.skills.read", "ops.skills.review", "ops.skills.publish", "ops.skills.grant", "ops.tenants.read", "ops.providers.read", "ops.providers.manage", "ops.supply.read", "ops.usage.read", "ops.jobs.read", "ops.audit.read", "ops.cost.read", "ops.permissions.manage"], scopes: [{ kind: "platform" }] });
      if (url.endsWith("/api/v1/oms/summary")) return ok({ authorized_school_count: 1, resource_count: 1, notices: [] });
      if (url.endsWith("/api/v1/oms/skills")) return ok({ skills: [{ id: "skill-1", name: "agent-skill", status: "approved" }] });
      if (url.endsWith("/api/v1/oms/models/draft")) return ok({ version: 1, models: [{ id: "model-1", model_id: "qwen-plus", provider: "dashscope" }] });
      if (url.endsWith("/api/v1/oms/provider-settings")) return ok({ version: 1, status: "active", settings: { connections: { dashscope: { provider: "dashscope", api_key: "<redacted>" } } } });
      if (url.endsWith("/api/v1/oms/resources/status")) return ok({ resources: [{ id: "res-1", display_name: "执行资源", category: "runtime", status: { label: "就绪" } }] });
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", lifecycle: { external_eligibility: "active" } }] });
      if (url.endsWith("/api/v1/oms/schools/school-1/usage")) return ok({ details: [{ attempt_id: "attempt-1", service_id: "llm", unit_code: "token", status: "settled", settled_units: "1", reserved_units: "1" }] });
      if (url.endsWith("/api/v1/oms/schools/school-1/jobs")) return ok({ jobs: [] });
      if (url.endsWith("/api/v1/oms/supply")) return ok({ service_definitions: [{ service_id: "llm", unit_code: "token", enabled: true }], supply_lots: [] });
      if (url.endsWith("/api/v1/oms/audit")) return ok({ management_events: [{ id: "audit-1", action: "ops.permissions.manage", result: "allow" }], oms_events: [] });
      if (url.endsWith("/api/v1/oms/cost")) return ok({ status: "ready", costs: [] });
      if (url.endsWith("/api/v1/oms/permissions")) return ok({ roles: [{ role_key: "platform_config_admin", version: 2, scope_kind: "platform", actions: ["ops.providers.manage"] }], principals: [], assignments: [] });
      if (url.endsWith("/api/v1/oms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/tms/me/permissions")) return ok({ school_id: "school-1", school_code: "demo-school", actions: ["tenant.tms.access", "tenant.members.read", "tenant.permissions.manage", "tenant.quotas.read", "tenant.usage.read", "tenant.access.manage"], scopes: [{ kind: "school", school_id: "school-1" }] });
      if (url.endsWith("/api/v1/tms/school-bootstrap/status")) return ok({ status: "active" });
      if (url.endsWith("/api/v1/tms/directory/users")) return ok({ status: "empty", reason_code: "empty", message: "学校目录暂无匹配用户", users: [] });
      if (url.endsWith("/api/v1/tms/members")) return ok({ members: [{ principal_id: "member-1", subject: "teacher-a", status: "active", policy_version: 1, roles: [] }] });
      if (url.endsWith("/api/v1/tms/approvals")) return ok({ approvals: [] });
      if (url.endsWith("/api/v1/tms/authz-audit")) return ok({ events: [{ id: "event-1", action: "tenant.permissions.manage", result: "allow" }] });
      if (url.endsWith("/api/v1/tms/skills")) return ok({ skills: [{ id: "skill-1", name: "school-skill", status: "active" }] });
      if (url.endsWith("/api/v1/tms/quotas")) return ok({ grants: [{ grant_id: "quota-1", service_id: "llm", quantity: "10", unit_code: "token", status: "active" }], usage_details: [{ attempt_id: "usage-1", service_id: "llm", settled_units: "1", unit_code: "token", status: "settled" }] });
      if (url.endsWith("/api/v1/tms/service-access")) return ok({ service_access_grants: [{ grant_id: "access-1", service_id: "llm", subject_kind: "member", subject_id: "member-1", status: "active" }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    const { unmount } = render(<OmsFormalApp/>);
    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    for (const [label, heading] of [
      ["运营概览", "当前平台身份"],
      ["学校列表", "学校范围"],
      ["模型与服务", "模型与服务"],
      ["供应商连接", "供应商连接"],
      ["Agent 与能力", "平台资源状态"],
      ["工具与集成", "平台资源状态"],
      ["Skills", "Skill 清单"],
      ["知识基础能力", "平台资源状态"],
      ["运行资源", "平台资源状态"],
      ["服务供给", "供给与额度底座"],
      ["用量与运行", "学校用量与任务"],
      ["审计与治理", "审计与成本"],
      ["平台人员", "平台授权治理"],
      ["角色与动作", "平台授权治理"],
      ["平台人员学校范围", "平台授权治理"],
      ["授权审计", "平台授权治理"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    unmount();
    window.history.replaceState(null, "", "/");

    render(<TmsFormalApp schoolCode="demo-school"/>);
    await screen.findByRole("heading", { name: "学校智能体管理后台" });
    for (const [label, heading] of [
      ["学校概览", "当前学校权限"],
      ["成员列表", "成员列表"],
      ["学校角色", "学校角色"],
      ["访问关系", "服务访问"],
      ["授权记录", "审批与审计"],
      ["应用列表", "服务访问"],
      ["可用服务", "服务访问"],
      ["配额清单", "额度与用量"],
      ["Skills", "Skill 授权"],
      ["知识库列表", "知识与内容"],
      ["调用用量", "额度与用量"],
      ["管理事件", "管理事件"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
  });

});
