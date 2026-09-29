import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsFormalApp from "../apps/oms/src/OmsFormalApp";
import TmsFormalApp from "../apps/tms/src/TmsFormalApp";

function ok(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } }));
}

beforeEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("正式 OMS/TMS 管理入口", () => {
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
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ tenants: [{ school_id: "school-1", lifecycle: { external_eligibility: "active" } }] });
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<OmsFormalApp/>);

    await screen.findByRole("heading", { name: "平台智能体运营后台" });
    fireEvent.click(screen.getByRole("button", { name: "学校列表" }));

    expect(screen.getByRole("heading", { name: "学校范围" })).toBeInTheDocument();
    expect(screen.getByText("school-1")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "模型与 Provider" })).not.toBeInTheDocument();
  });

  it("OMS 未取得真实平台登录或本地授权时失败关闭", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      return Promise.resolve(new Response(JSON.stringify({ detail: "platform identity missing" }), { status: url.endsWith("/api/v1/oms/me") ? 403 : 200, headers: { "content-type": "application/json" } }));
    });

    render(<OmsFormalApp/>);

    expect(await screen.findByText("正式入口未开放")).toBeInTheDocument();
    expect(screen.getByText(/eduplus-platform-admin 授权码登录、账号状态或 ops\.\* 本地授权未通过/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "使用 eduplus-platform-admin 登录" })).toBeInTheDocument();
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

      expect(screen.getByText("正式入口未开放")).toBeInTheDocument();
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

  it("OMS 正式入口只读展示模型草稿和 Provider 设置 DTO 且不泄露 Secret", async () => {
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

    expect(await screen.findByRole("heading", { name: "模型与 Provider" })).toBeInTheDocument();
    expect(screen.getByText("qwen-plus")).toBeInTheDocument();
    expect(screen.getByText("dashscope")).toBeInTheDocument();
    expect(screen.getByText("<redacted>")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("env:");
    expect(document.body).not.toHaveTextContent("sk-");
    expect(screen.queryByRole("button", { name: /保存|发布|回滚|测试/ })).not.toBeInTheDocument();
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
      if (url.endsWith("/api/v1/oms/tenants")) return ok({ count: 1, tenants: [{ school_id: "school-1", external_binding: { status: { label: "已核验" } }, lifecycle: { external_eligibility: { label: "学校订阅有效" } } }] });
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
    expect(screen.getByText("school-1")).toBeInTheDocument();
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

    await screen.findByRole("heading", { name: "模型与 Provider" });
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
    expect(screen.getByText("ops.providers.manage")).toBeInTheDocument();
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
    expect(screen.getByText("platform_config_admin")).toBeInTheDocument();
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
      ["模型与服务", "模型与 Provider"],
      ["供应商连接", "模型与 Provider"],
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
