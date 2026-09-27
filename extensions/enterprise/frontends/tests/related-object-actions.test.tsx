import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import TmsPrototype from "../apps/tms/src/TmsPrototype";

let path = "/oms/prototype";
vi.mock("next/navigation", () => ({ usePathname: () => path }));
beforeEach(() => {
  sessionStorage.clear();
  path = "/oms/prototype";
  window.history.replaceState({}, "", path);
});

describe("OMS 关联对象", () => {
  it("服务配置不再把全量供给与全量用量当关联操作", () => {
    path = "/oms/prototype/services/llm/config";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /对话模型/ });
    expect(within(drawer).queryByRole("button", { name: "服务供给" })).not.toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "关联供给" })).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "关联供给" }));
    expect(window.location.pathname).toBe("/oms/prototype/services/llm/supply");
    expect(within(screen.getByRole("dialog", { name: /对话模型/ })).getByText("对话模型资源")).toBeInTheDocument();
    expect(screen.queryByText("文档解析资源")).not.toBeInTheDocument();
  });

  it("服务列表用单一关联入口避免堆满行按钮，入口再分流到具体关系", () => {
    path = "/oms/prototype/services";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const row = screen.getByText("对话模型").closest("tr")!;
    expect(within(row).getByRole("button", { name: "关联记录" })).toBeInTheDocument();
    expect(within(row).getAllByRole("button").length).toBeLessThanOrEqual(6);
    fireEvent.click(within(row).getByRole("button", { name: "关联记录" }));
    const drawer = screen.getByRole("dialog", { name: /对话模型/ });
    expect(within(drawer).getByRole("button", { name: "关联供给" })).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "授权学校" })).toBeInTheDocument();
  });

  it("Agent 依赖列具体服务，学校范围无可信关系时不跳全量学校", () => {
    path = "/oms/prototype/agents/deep-solve/dependencies";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /深度解题/ });
    expect(within(drawer).getByText("对话模型")).toBeInTheDocument();
    expect(within(drawer).getByText("任务模型")).toBeInTheDocument();
    expect(within(drawer).getAllByRole("button", { name: "服务资料" })).toHaveLength(2);
    expect(within(drawer).queryByRole("button", { name: "学校可用范围" })).not.toBeInTheDocument();
  });

  it("学校服务授权可从当前关联行直接撤销，额度约束仍生效", () => {
    path = "/oms/prototype/tenants/aurora/access";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /星河实验学校/ });
    const row = within(drawer).getByText("对话模型").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "撤销授权" }));
    expect(within(drawer).getByText(/仍有关联有效或待核对额度/)).toBeInTheDocument();
  });

  it("Provider 只提供当前服务适用连接，不显示其他服务连接", () => {
    path = "/oms/prototype/services/llm/provider";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    fireEvent.click(within(screen.getByRole("dialog", { name: /对话模型/ })).getByRole("button", { name: "适用连接" }));
    const drawer = screen.getByRole("dialog", { name: /对话模型/ });
    expect(within(drawer).getByText("演示模型连接")).toBeInTheDocument();
    expect(within(drawer).queryByText("演示语音连接")).not.toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "编辑连接" })).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "编辑连接" }));
    expect(screen.getByRole("dialog", { name: /编辑演示模型连接/ })).toBeInTheDocument();
  });

  it("审计角色在适用连接关系中只能查看不能维护", () => {
    path = "/oms/prototype/services/llm/connections";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "auditor" } });
    const drawer = screen.getByRole("dialog", { name: /对话模型/ });
    expect(within(drawer).getByRole("button", { name: "连接资料" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "编辑连接" })).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "新增适用连接" })).not.toBeInTheDocument();
  });

  it("供给方案可直接查看关联服务并预选登记批次", () => {
    path = "/oms/prototype/supply/plans/plan-s-llm";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /对话模型资源方案/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "登记该方案批次" }));
    const form = screen.getByRole("dialog", { name: "新增供给批次" });
    expect(within(form).getByRole("combobox", { name: "资源方案" })).toHaveValue("plan-s-llm");
    expect(within(form).getByText(/不代表真实采购或平台可授予量增加/)).toBeInTheDocument();
  });

  it("从批次进入关联方案后关闭回到原批次而非全量供给", () => {
    path = "/oms/prototype/supply";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("tab", { name: "供给批次" }));
    fireEvent.click(screen.getByRole("button", { name: "新增供给批次" }));
    const form = screen.getByRole("dialog", { name: "新增供给批次" });
    fireEvent.change(within(form).getByRole("textbox", { name: "批次标识" }), { target: { value: "batch-test" } });
    fireEvent.change(within(form).getByRole("spinbutton", { name: "取得数量" }), { target: { value: "10" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "来源凭证" }), { target: { value: "演示凭证" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存草稿" }));
    fireEvent.click(within(screen.getByText("batch-test").closest("tr")!).getByRole("button", { name: /查看详情/ }));
    fireEvent.click(within(screen.getByRole("dialog", { name: /batch-test/ })).getByRole("button", { name: "查看关联方案" }));
    expect(window.location.pathname).toBe("/oms/prototype/supply/plans/plan-s-llm");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/oms/prototype/supply/batches/batch-test");
  });

  it("方案的关联批次专题只列本方案批次并可逐条查看", () => {
    path = "/oms/prototype/supply";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("tab", { name: "供给批次" }));
    fireEvent.click(screen.getByRole("button", { name: "新增供给批次" }));
    const form = screen.getByRole("dialog", { name: "新增供给批次" });
    fireEvent.change(within(form).getByRole("textbox", { name: "批次标识" }), { target: { value: "batch-linked" } });
    fireEvent.change(within(form).getByRole("spinbutton", { name: "取得数量" }), { target: { value: "10" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "来源凭证" }), { target: { value: "演示凭证" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存草稿" }));
    fireEvent.click(screen.getByRole("tab", { name: "资源方案" }));
    fireEvent.click(within(screen.getByText("对话模型资源方案").closest("tr")!).getByRole("button", { name: /查看详情/ }));
    fireEvent.click(within(screen.getByRole("dialog", { name: /对话模型资源方案/ })).getByRole("button", { name: "关联批次" }));
    expect(window.location.pathname).toBe("/oms/prototype/supply/plans/plan-s-llm/batches");
    const drawer = screen.getByRole("dialog", { name: /对话模型资源方案/ });
    const row = within(drawer).getByText("batch-linked").closest("tr")!;
    expect(within(row).getByRole("button", { name: "批次资料" })).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "批次资料" }));
    expect(window.location.pathname).toBe("/oms/prototype/supply/batches/batch-linked");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/oms/prototype/supply/plans/plan-s-llm/batches");
  });

  it("Skill 学校授权逐条可查看学校并撤销，审计员只能查看", () => {
    path = "/oms/prototype/skills/global%3Apdf/grants";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /pdf/ });
    expect(within(drawer).getByText("星河实验学校")).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "学校资料" })).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "撤销授权" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "auditor" } });
    expect(within(drawer).getByText("星河实验学校")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "撤销授权" })).not.toBeInTheDocument();
  });

  it("额度消耗用明确 grantId 关联，不把待核对或相似编号当成消费", () => {
    path = "/oms/prototype/usage";
    window.history.replaceState({}, "", `${path}?grant=q-101`);
    render(<OmsPrototype/>);
    expect(screen.getByText("use-7429")).toBeInTheDocument();
    expect(screen.queryByText("use-7427")).not.toBeInTheDocument();
    expect(screen.queryByText("use-7426")).not.toBeInTheDocument();
  });

  it("供给的已承诺额度和实际消耗列具体记录与追溯动作", () => {
    path = "/oms/prototype/supply/s-llm/commitments";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    let drawer = screen.getByRole("dialog", { name: /对话模型资源/ });
    expect(within(drawer).getAllByRole("button", { name: "额度详情" })).toHaveLength(3);
    expect(within(drawer).getAllByRole("button", { name: "消耗明细" })).toHaveLength(3);
    fireEvent.click(within(drawer).getByRole("button", { name: "关闭抽屉" }));
    path = "/oms/prototype/supply/s-llm/usage";
    window.history.replaceState({}, "", path);
    // 路由切换后重建组件，避免从关闭后的页面沿用状态。
    render(<OmsPrototype/>);
    drawer = screen.getByRole("dialog", { name: /对话模型资源/ });
    expect(within(drawer).getByText("use-7429")).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "调用详情" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "查看服务调用明细" })).not.toBeInTheDocument();
  });

  it("供给列表的实际消耗入口只打开当前供给的调用专题", () => {
    path = "/oms/prototype/supply";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const row = screen.getByText("对话模型资源").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "实际消耗" }));
    expect(window.location.pathname).toBe("/oms/prototype/supply/s-llm/usage");
    const drawer = screen.getByRole("dialog", { name: /对话模型资源/ });
    expect(within(drawer).getByText("use-7429")).toBeInTheDocument();
    expect(within(drawer).queryByText("use-7428")).not.toBeInTheDocument();
  });

  it("单次调用可追溯到具体额度和供给，待核对调用不伪造关联", () => {
    path = "/oms/prototype/usage/use-7429";
    window.history.replaceState({}, "", path);
    const view = render(<OmsPrototype/>);
    let drawer = screen.getByRole("dialog", { name: /调用 use-7429/ });
    expect(within(drawer).getByRole("button", { name: "额度 q-101" })).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "查看供给记录" })).toBeInTheDocument();
    view.unmount();
    path = "/oms/prototype/usage/use-7427";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    drawer = screen.getByRole("dialog", { name: /调用 use-7427/ });
    expect(within(drawer).queryByRole("button", { name: /额度 q-/ })).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "查看供给记录" })).not.toBeInTheDocument();
  });
});

describe("TMS 关联对象", () => {
  it("应用服务与成员访问表单应就地展示失效候选的校验错误", () => {
    path = "/tms/prototype/demo-school/apps/app-01/services";
    window.history.replaceState({}, "", path);
    const view = render(<TmsPrototype/>);
    fireEvent.click(within(screen.getByRole("dialog", { name: /校园学习助手/ })).getByRole("button", { name: "添加服务" }));
    let form = screen.getByRole("dialog", { name: "添加应用服务" });
    fireEvent.change(within(form).getByRole("combobox", { name: "服务" }), { target: { value: "llm" } });
    fireEvent.click(within(form).getByRole("button", { name: "提交添加" }));
    expect(within(form).getByText("该服务不可加入当前应用。" )).toBeInTheDocument();
    view.unmount();

    path = "/tms/prototype/demo-school/apps/app-01/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    fireEvent.click(within(screen.getByRole("dialog", { name: /校园学习助手/ })).getByRole("button", { name: "授予成员访问" }));
    form = screen.getByRole("dialog", { name: "授予成员访问" });
    fireEvent.change(within(form).getByRole("combobox", { name: "成员" }), { target: { value: "m-04" } });
    fireEvent.click(within(form).getByRole("button", { name: "提交授权" }));
    expect(within(form).getByText("当前成员或应用不具备可授予条件。" )).toBeInTheDocument();
  });

  it("应用服务范围以明确关系维护，服务反向清单同步", () => {
    path = "/tms/prototype/demo-school/apps/app-01/services";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /校园学习助手/ });
    expect(within(drawer).getByText("文档 OCR")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "添加服务" }));
    const form = screen.getByRole("dialog", { name: "添加应用服务" });
    expect(within(form).getByRole("option", { name: "联网搜索" })).toBeInTheDocument();
    fireEvent.change(within(form).getByRole("combobox", { name: "服务" }), { target: { value: "search" } });
    fireEvent.click(within(form).getByRole("button", { name: "提交添加" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认添加应用服务" })).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByText("联网搜索")).toBeInTheDocument();
    const row = within(drawer).getByText("联网搜索").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "移除服务" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认移除应用服务" })).getByRole("button", { name: "确认" }));
    expect(within(drawer).queryByText("联网搜索")).not.toBeInTheDocument();
  });

  it("普通成员直达应用关联维护路径也不能访问", () => {
    path = "/tms/prototype/demo-school/apps/app-01/services";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "member" } });
    expect(screen.getByText(/当前主体不能访问/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "添加服务" })).not.toBeInTheDocument();
  });

  it("应用成员访问可直接授予并与成员侧回读同一关系", () => {
    path = "/tms/prototype/demo-school/apps/app-01/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /校园学习助手/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "授予成员访问" }));
    const form = screen.getByRole("dialog", { name: "授予成员访问" });
    fireEvent.change(within(form).getByRole("combobox", { name: "成员" }), { target: { value: "m-02" } });
    fireEvent.click(within(form).getByRole("button", { name: "提交授权" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认授予应用访问" })).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByText("周老师")).toBeInTheDocument();
  });

  it("服务配额有逐条只读操作，知识库任务有具体申请入口", () => {
    path = "/tms/prototype/demo-school/services/llm/quotas";
    window.history.replaceState({}, "", path);
    const view = render(<TmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /对话模型/ });
    expect(within(drawer).getAllByRole("button", { name: "查看配额" })).toHaveLength(2);
    expect(within(drawer).getAllByRole("button", { name: "消耗明细" })).toHaveLength(2);
    expect(within(drawer).queryByRole("button", { name: /调整配额/ })).not.toBeInTheDocument();
    view.unmount();
    path = "/tms/prototype/demo-school/knowledge/kb-03/tasks";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    expect(within(screen.getByRole("dialog", { name: /历史试题归档/ })).getByRole("button", { name: "申请重试" })).toBeInTheDocument();
  });

  it("应用服务变更取消复核不写关系，服务反向清单只列关联应用", () => {
    path = "/tms/prototype/demo-school/apps/app-01/services";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /校园学习助手/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "添加服务" }));
    const form = screen.getByRole("dialog", { name: "添加应用服务" });
    fireEvent.change(within(form).getByRole("combobox", { name: "服务" }), { target: { value: "search" } });
    fireEvent.click(within(form).getByRole("button", { name: "提交添加" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认添加应用服务" })).getByRole("button", { name: "取消" }));
    expect(within(form).getByRole("combobox", { name: "服务" })).toHaveValue("search");
    expect(within(drawer).queryByText("联网搜索")).not.toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "取消" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "关闭抽屉" }));
    fireEvent.click(screen.getByRole("button", { name: "可用服务" }));
    const row = screen.getByText("联网搜索").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "使用应用" }));
    const serviceDrawer = screen.getByRole("dialog", { name: /联网搜索/ });
    expect(within(serviceDrawer).getByText("数学教研工作台")).toBeInTheDocument();
    expect(within(serviceDrawer).queryByText("校园学习助手")).not.toBeInTheDocument();
  });

  it("应用调用入口仅显示该应用的明确调用 ID 关系", () => {
    path = "/tms/prototype/demo-school/apps/app-01/info";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    fireEvent.click(within(screen.getByRole("dialog", { name: /校园学习助手/ })).getByRole("button", { name: "查看应用调用" }));
    expect(window.location.search).toBe("?app=app-01");
    expect(screen.getByText("use-7429")).toBeInTheDocument();
    expect(screen.queryByText("use-7426")).not.toBeInTheDocument();
  });

  it("新应用默认无服务，但归口待接入时仍可配置学校已授权服务", () => {
    path = "/tms/prototype/demo-school/apps";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增应用（演示）" }));
    const form = screen.getByRole("dialog", { name: "新增应用" });
    fireEvent.change(within(form).getByRole("textbox", { name: "应用名称" }), { target: { value: "新教研应用" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示应用" }));
    const row = screen.getByText("新教研应用").closest("tr")!;
    expect(within(row).getByText("未分配")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "服务范围" }));
    expect(within(screen.getByRole("dialog", { name: /新教研应用/ })).getByRole("button", { name: "添加服务" })).toBeInTheDocument();
  });

  it("知识库关联文档以单层详情抽屉呈现并返回原专题", () => {
    path = "/tms/prototype/demo-school/knowledge/kb-01/documents";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /高二数学课程资料/ });
    const row = within(drawer).getByText("函数与导数教学讲义.pdf").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "文档资料" }));
    expect(window.location.pathname).toBe("/tms/prototype/demo-school/knowledge/kb-01/documents/doc-101");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/tms/prototype/demo-school/knowledge/kb-01/documents");
  });

  it("学校调用详情只追溯本校成员、应用、服务与只读配额", () => {
    path = "/tms/prototype/demo-school/usage/use-7429";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /调用 use-7429/ });
    expect(within(drawer).getByRole("button", { name: "成员资料" })).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "应用资料" })).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "配额 q-101" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /供给|采购/ })).not.toBeInTheDocument();
  });
});
