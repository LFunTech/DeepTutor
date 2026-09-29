import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import TmsPrototype from "../apps/tms/src/TmsPrototype";

let path = "/oms/prototype/platform-people";
vi.mock("next/navigation", () => ({ usePathname: () => path }));
beforeEach(() => { path = "/oms/prototype/platform-people"; window.history.replaceState({}, "", path); sessionStorage.clear(); });

describe("OMS 本产品管理授权原型", () => {
  it("平台人员身份抽屉标明指定 Client，但不冒充真实登录", () => {
    render(<OmsPrototype/>);
    const candidate = screen.getByText("待授权周").closest("tr")!;
    fireEvent.click(within(candidate).getByRole("button", { name: "身份与核验" }));
    const drawer = screen.getByRole("dialog", { name: /待授权周/ });
    expect(within(drawer).getByText("eduplus-platform-admin")).toBeInTheDocument();
    expect(within(drawer).getByText(/仅指定对接 Client，未验证真实换票/)).toBeInTheDocument();
  });

  it("OMS 只提供平台人员及其学校范围授权，不提供学校账号管理", () => {
    render(<OmsPrototype/>);
    for (const label of ["平台人员", "角色与动作", "平台人员学校范围", "授权审计"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "学校后台开通" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "平台人员" })).toBeInTheDocument();
    expect(screen.getByText(/合成演示.*不代表真实授权/)).toBeInTheDocument();
  });

  it("学校范围自定义角色可选择后端同时允许平台及学校范围的入口动作", () => {
    path = "/oms/prototype/platform-roles";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增自定义角色" }));
    const form = screen.getByRole("dialog", { name: "新增自定义角色" });
    expect(within(form).getByText(/进入平台后台 · ops\.oms\.access/)).toBeInTheDocument();
  });

  it("旧学校管理员开通深链不再可操作", () => {
    path = "/oms/prototype/tms-bootstrap";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    expect(screen.getByText("该原型页面不存在。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /发起开通|复核开通/ })).not.toBeInTheDocument();
  });

  it("学校范围只展示平台人员的 OMS 授权，不展示本校账号", () => {
    path = "/oms/prototype/school-permissions";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const row = screen.getByText("星河实验学校").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "平台人员范围" }));
    const drawer = screen.getByRole("dialog", { name: /星河实验学校/ });
    expect(within(drawer).getByText("平台运营林")).toBeInTheDocument();
    expect(within(drawer).queryByText("林老师")).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /学校账号|首位管理员/ })).not.toBeInTheDocument();
  });

  it("人员授权通过独立弹窗选择平台人员，不能选择本人或未核验人员", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "授予平台角色" }));
    const form = screen.getByRole("dialog", { name: "授予平台角色" });
    expect(within(form).getByRole("button", { name: "选择平台人员" })).toBeInTheDocument();
    expect(within(form).queryByRole("combobox", { name: "已核验候选人" })).not.toBeInTheDocument();
    expect(within(form).queryByRole("textbox", { name: /主体|sub/ })).not.toBeInTheDocument();
    expect(within(form).getByText(/有效权限预览/)).toBeInTheDocument();
    expect(within(form).getByRole("combobox", { name: "授权范围" })).toBeInTheDocument();
    expect(within(form).getByLabelText("有效期")).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "选择平台人员" }));
    const chooser = screen.getByRole("dialog", { name: "选择平台人员" });
    expect(screen.queryByRole("dialog", { name: "授予平台角色" })).not.toBeInTheDocument();
    expect(within(chooser).queryByText("林老师")).not.toBeInTheDocument();
    expect(within(within(chooser).getByText("安全管理员甲").closest("tr")!).getByRole("button", { name: "不可选择本人" })).toBeDisabled();
    expect(within(within(chooser).getByText("外部状态待核验").closest("tr")!).getByRole("button", { name: "身份待核验" })).toBeDisabled();
    fireEvent.change(within(chooser).getByRole("searchbox", { name: "搜索平台人员" }), { target: { value: "待授权周" } });
    expect(within(chooser).getByText("待授权周")).toBeInTheDocument();
    expect(within(chooser).queryByText("平台运营林")).not.toBeInTheDocument();
  });

  it("选人或取消选人均保留授权范围及原因，不会擅自提交授权", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "授予平台角色" }));
    const form = screen.getByRole("dialog", { name: "授予平台角色" });
    fireEvent.change(within(form).getByRole("combobox", { name: "授权范围" }), { target: { value: "platform" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "授权原因" }), { target: { value: "平台配置轮值" } });
    fireEvent.click(within(form).getByRole("button", { name: "选择平台人员" }));
    let chooser = screen.getByRole("dialog", { name: "选择平台人员" });
    fireEvent.click(within(chooser).getByRole("button", { name: "取消" }));
    expect(within(form).getByRole("combobox", { name: "授权范围" })).toHaveValue("platform");
    expect(within(form).getByRole("textbox", { name: "授权原因" })).toHaveValue("平台配置轮值");
    expect(within(form).getByText("尚未选择")).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "选择平台人员" }));
    chooser = screen.getByRole("dialog", { name: "选择平台人员" });
    fireEvent.click(within(within(chooser).getByText("待授权周").closest("tr")!).getByRole("button", { name: "选用" }));
    expect(within(form).getByText("待授权周")).toBeInTheDocument();
    expect(within(form).getByRole("combobox", { name: "授权范围" })).toHaveValue("platform");
    expect(within(form).getByRole("textbox", { name: "授权原因" })).toHaveValue("平台配置轮值");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("高风险平台角色由另一名安全管理员复核后才生效，并留下审计", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "授予平台角色" }));
    const form = screen.getByRole("dialog", { name: "授予平台角色" });
    fireEvent.click(within(form).getByRole("button", { name: "选择平台人员" }));
    const chooser = screen.getByRole("dialog", { name: "选择平台人员" });
    fireEvent.click(within(within(chooser).getByText("待授权周").closest("tr")!).getByRole("button", { name: "选用" }));
    fireEvent.change(within(form).getByRole("combobox", { name: "授权范围" }), { target: { value: "platform" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "授权原因" }), { target: { value: "平台配置轮值" } });
    fireEvent.click(within(form).getByRole("button", { name: "提交授权" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认平台角色授权" })).getByRole("button", { name: "确认" }));
    const row = screen.getByText("待授权周").closest("tr")!;
    expect(within(row).getByText("0 项")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "角色与范围" }));
    const drawer = screen.getByRole("dialog", { name: /待授权周/ });
    expect(within(drawer).getByText("待第二人复核")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "复核授权" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示审批人" }), { target: { value: "sec-b" } });
    fireEvent.click(within(drawer).getByRole("button", { name: "复核授权" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认批准授权" })).getByRole("button", { name: "确认" }));
    expect(within(row).getByText("1 项")).toBeInTheDocument();
  });

  it("含敏感学校动作的 OMS 运营角色不得单人直授", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "授予平台角色" }));
    const form = screen.getByRole("dialog", { name: "授予平台角色" });
    fireEvent.click(within(form).getByRole("button", { name: "选择平台人员" }));
    const chooser = screen.getByRole("dialog", { name: "选择平台人员" });
    fireEvent.click(within(within(chooser).getByText("待授权周").closest("tr")!).getByRole("button", { name: "选用" }));
    fireEvent.change(within(form).getByRole("textbox", { name: "授权原因" }), { target: { value: "指定学校运营" } });
    fireEvent.click(within(form).getByRole("button", { name: "提交授权" }));
    expect(screen.getByRole("alertdialog", { name: "确认平台角色授权" })).toHaveTextContent("高风险授权需另一名安全管理员复核");
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认平台角色授权" })).getByRole("button", { name: "确认" }));
    expect(within(screen.getByText("待授权周").closest("tr")!).getByText("0 项")).toBeInTheDocument();
  });

  it("平台人员的外部失效与角色过期可演示，失效授权不再计入有效权限", () => {
    render(<OmsPrototype/>);
    const actor = screen.getByText("平台运营林").closest("tr")!;
    expect(within(actor).getByText("1 项")).toBeInTheDocument();
    const scenario = screen.getByRole("combobox", { name: "演示平台人员状态" });

    fireEvent.change(scenario, { target: { value: "external-unavailable" } });
    expect(within(actor).getByText("外部账号不可用")).toBeInTheDocument();
    expect(within(actor).getByText("0 项")).toBeInTheDocument();
    fireEvent.click(within(actor).getByRole("button", { name: "角色与范围" }));
    let drawer = screen.getByRole("dialog", { name: /平台运营林/ });
    expect(within(drawer).getByText("外部账号不可用")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "授予角色" })).not.toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "关闭抽屉" }));

    fireEvent.change(scenario, { target: { value: "expired" } });
    expect(within(actor).getByText("0 项")).toBeInTheDocument();
    fireEvent.click(within(actor).getByRole("button", { name: "角色与范围" }));
    drawer = screen.getByRole("dialog", { name: /平台运营林/ });
    expect(within(drawer).getByText("已过期")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "关闭抽屉" }));

    fireEvent.change(scenario, { target: { value: "normal" } });
    expect(within(actor).getByText("1 项")).toBeInTheDocument();
  });


  it("撤销平台角色后立即移除有效授权，但保留角色与审计记录", () => {
    render(<OmsPrototype/>);
    const actor = screen.getByText("平台运营林").closest("tr")!;
    fireEvent.click(within(actor).getByRole("button", { name: "角色与范围" }));
    const drawer = screen.getByRole("dialog", { name: /平台运营林/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "撤销角色" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认撤销平台角色" })).getByRole("button", { name: "确认" }));
    expect(within(actor).getByText("0 项")).toBeInTheDocument();
    expect(within(drawer).getByText("已撤权")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "关闭抽屉" }));
    fireEvent.click(screen.getByRole("button", { name: "授权审计" }));
    expect(screen.getByText("角色撤权")).toBeInTheDocument();
  });

  it("重复学校范围授权显示冲突且不会弹出确认或新增记录", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "授予平台角色" }));
    const form = screen.getByRole("dialog", { name: "授予平台角色" });
    fireEvent.click(within(form).getByRole("button", { name: "选择平台人员" }));
    const chooser = screen.getByRole("dialog", { name: "选择平台人员" });
    fireEvent.click(within(within(chooser).getByText("平台运营林").closest("tr")!).getByRole("button", { name: "选用" }));
    fireEvent.change(within(form).getByRole("textbox", { name: "授权原因" }), { target: { value: "重复授权演练" } });
    fireEvent.click(within(form).getByRole("button", { name: "提交授权" }));
    expect(within(form).getByText(/已有相同有效或待复核角色/)).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("新增含高风险动作的角色模板在复核前不可授予", () => {
    path = "/oms/prototype/platform-roles";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增自定义角色" }));
    const form = screen.getByRole("dialog", { name: "新增自定义角色" });
    fireEvent.change(within(form).getByRole("textbox", { name: "角色名称" }), { target: { value: "凭据轮值" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "角色范围" }), { target: { value: "platform" } });
    fireEvent.click(within(form).getByRole("checkbox", { name: /管理凭据/ }));
    fireEvent.click(within(form).getByRole("button", { name: "保存角色模板" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认新增自定义角色" })).getByRole("button", { name: "确认" }));
    const row = screen.getByText("凭据轮值").closest("tr")!;
    expect(within(row).getByText("待第二人复核")).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "复核角色" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示审批人" }), { target: { value: "sec-b" } });
    fireEvent.click(within(row).getByRole("button", { name: "复核角色" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认批准角色模板" })).getByRole("button", { name: "确认" }));
    expect(within(row).getByText("有效（演示）")).toBeInTheDocument();
  });

  it("只读审计角色不能打开人员授权表单", () => {
    render(<OmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "auditor" } });
    expect(screen.queryByRole("button", { name: "授予平台角色" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "平台人员" })).toBeInTheDocument();
  });
});

describe("TMS 本学校管理授权原型", () => {
  it("本校账号查询只用于定位，未登录基座的账号不能直接授权", () => {
    path = "/tms/prototype/demo-school/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    expect(screen.queryByText(/查看 EduPlus2 同步成员/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查找本校账号" }));
    const lookup = screen.getByRole("dialog", { name: "查找本校账号" });
    expect(within(lookup).getByText("赵老师")).toBeInTheDocument();
    expect(within(lookup).queryByText("外校账号")).not.toBeInTheDocument();
    expect(within(lookup).getByText(/请本人先登录基座/)).toBeInTheDocument();
    expect(within(lookup).queryByRole("button", { name: /授予.*角色/ })).not.toBeInTheDocument();
    fireEvent.change(within(lookup).getByRole("searchbox", { name: "搜索可见账号" }), { target: { value: "周老师" } });
    const row = within(lookup).getByText("周老师").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "查看成员资料" }));
    expect(screen.queryByRole("dialog", { name: "查找本校账号" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: /周老师/ })).toBeInTheDocument();
  });

  it("目录无权、策略空范围、空结果和故障不伪装成学校没有用户", () => {
    path = "/tms/prototype/demo-school/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "查找本校账号" }));
    const lookup = screen.getByRole("dialog", { name: "查找本校账号" });
    const scenario = within(lookup).getByRole("combobox", { name: "演示目录响应" });
    for (const [value, message] of [
      ["forbidden", /没有账号目录访问权限/],
      ["policy-empty", /数据策略未开放可见范围/],
      ["empty", /当前关键词没有匹配账号/],
      ["token-expired", /用户登录凭证已失效/],
      ["subscription-expired", /学校应用订阅已失效/],
      ["error", /账号目录暂不可用/],
    ]) {
      fireEvent.change(scenario, { target: { value } });
      expect(within(lookup).getByText(message)).toBeInTheDocument();
      expect(within(lookup).queryByText("赵老师")).not.toBeInTheDocument();
    }
  });

  it("权限状态改变后关闭账号目录，不在恢复角色时重开旧弹窗", () => {
    path = "/tms/prototype/demo-school/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "查找本校账号" }));
    expect(screen.getByRole("dialog", { name: "查找本校账号" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示权限状态" }), { target: { value: "revoked" } });
    expect(screen.queryByRole("dialog", { name: "查找本校账号" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示权限状态" }), { target: { value: "active" } });
    expect(screen.queryByRole("dialog", { name: "查找本校账号" })).not.toBeInTheDocument();
  });

  it("身份待核验成员不能从成员或应用入口获得访问关系", () => {
    path = "/tms/prototype/demo-school/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const pending = screen.getByText("陈同学").closest("tr")!;
    fireEvent.click(within(pending).getByRole("button", { name: "应用访问" }));
    const drawer = screen.getByRole("dialog", { name: /陈同学/ });
    expect(within(drawer).getByRole("button", { name: "授予应用访问（演示）" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "应用列表" }));
    const app = screen.getByText("校园学习助手").closest("tr")!;
    fireEvent.click(within(app).getByRole("button", { name: "成员访问" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: /校园学习助手/ })).getByRole("button", { name: "授予成员访问" }));
    expect(within(screen.getByRole("dialog", { name: "授予成员访问" })).queryByRole("option", { name: "陈同学" })).not.toBeInTheDocument();
  });

  it("成员与权限分为成员、学校角色、访问关系、授权记录", () => {
    path = "/tms/prototype/demo-school/roles";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    for (const label of ["成员列表", "学校角色", "访问关系", "授权记录"]) expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "学校角色" })).toBeInTheDocument();
    expect(screen.queryByText(/ops\.permissions/)).not.toBeInTheDocument();
  });

  it("首位管理员由真实订阅 Webhook 即时开启，mock 与缺失 actor 不授权", () => {
    path = "/tms/prototype/demo-school/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "演示权限状态" }), { target: { value: "bootstrap-pending" } });
    expect(screen.getByRole("heading", { name: "等待订阅 Webhook" })).toBeInTheDocument();
    expect(screen.getByText(/学校管理员无需单独开通/)).toBeInTheDocument();
    expect(screen.queryByText("林老师")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "学校侧复核" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示订阅 actor 状态" }), { target: { value: "mock" } });
    expect(screen.getByText("控制台 mock（不登记身份）")).toBeInTheDocument();
    expect(screen.getByText("无可开启身份")).toBeInTheDocument();
    expect(screen.queryByText(/已验签真实 subscription\.created\.actor\.user_id/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "模拟接收订阅 Webhook" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示订阅 actor 状态" }), { target: { value: "missing" } });
    expect(screen.getByText("真实事件缺失有效 actor（待核对）")).toBeInTheDocument();
    expect(screen.getByText("无可开启身份")).toBeInTheDocument();
    expect(screen.queryByText(/已验签真实 subscription\.created\.actor\.user_id/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "模拟接收订阅 Webhook" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示订阅 actor 状态" }), { target: { value: "different" } });
    expect(screen.queryByRole("button", { name: "模拟接收订阅 Webhook" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示权限状态" }), { target: { value: "active" } });
    expect(screen.getByRole("heading", { name: "等待订阅 Webhook" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示订阅 actor 状态" }), { target: { value: "matched" } });
    fireEvent.click(screen.getByRole("button", { name: "模拟接收订阅 Webhook" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认 Webhook 开启" })).getByRole("button", { name: "确认" }));
    expect(screen.getByRole("heading", { name: "成员与权限" })).toBeInTheDocument();
  });

  it("成员角色授予与撤销使用独立操作框，拒绝自授并回读审计", () => {
    path = "/tms/prototype/demo-school/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const own = screen.getByText("林老师").closest("tr")!;
    expect(within(own).queryByRole("button", { name: "授予学校角色" })).not.toBeInTheDocument();
    const candidate = screen.getByText("周老师").closest("tr")!;
    fireEvent.click(within(candidate).getByRole("button", { name: "学校角色" }));
    const drawer = screen.getByRole("dialog", { name: /周老师/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "授予学校角色" }));
    const form = screen.getByRole("dialog", { name: "授予学校角色" });
    expect(within(form).getByText(/有效权限预览/)).toBeInTheDocument();
    fireEvent.change(within(form).getByRole("textbox", { name: "授权原因" }), { target: { value: "负责校内资源" } });
    fireEvent.click(within(form).getByRole("button", { name: "提交授权" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认学校角色授权" })).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByRole("heading", { name: "授权记录" })).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "授予学校角色" }));
    const repeated = screen.getByRole("dialog", { name: "授予学校角色" });
    fireEvent.change(within(repeated).getByRole("textbox", { name: "授权原因" }), { target: { value: "重复授权演练" } });
    fireEvent.click(within(repeated).getByRole("button", { name: "提交授权" }));
    expect(within(repeated).getByText(/当前成员已拥有该角色/)).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("学校成员直授表单不提供管理员与敏感运营角色", () => {
    path = "/tms/prototype/demo-school/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    fireEvent.click(within(screen.getByText("周老师").closest("tr")!).getByRole("button", { name: "学校角色" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: /周老师/ })).getByRole("button", { name: "授予学校角色" }));
    const form = screen.getByRole("dialog", { name: "授予学校角色" });
    expect(within(form).queryByRole("option", { name: /学校管理员/ })).not.toBeInTheDocument();
    expect(within(form).queryByRole("option", { name: /学校运营/ })).not.toBeInTheDocument();
    expect(within(form).getByRole("option", { name: /学校只读审计/ })).toBeInTheDocument();
  });

  it("学校角色只允许 tenant 动作，访问关系新增后在本校清单回读", () => {
    path = "/tms/prototype/demo-school/roles";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增学校角色" }));
    const form = screen.getByRole("dialog", { name: "新增学校角色" });
    expect(within(form).queryByText(/ops\.quotas\.manage/)).not.toBeInTheDocument();
    fireEvent.change(within(form).getByRole("textbox", { name: "角色名称" }), { target: { value: "课程审计" } });
    fireEvent.click(within(form).getByRole("checkbox", { name: /查看成员/ }));
    fireEvent.click(within(form).getByRole("button", { name: "保存学校角色" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认新增学校角色" })).getByRole("button", { name: "确认" }));
    expect(screen.getByText("课程审计")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "访问关系" }));
    fireEvent.click(screen.getByRole("button", { name: "新增访问关系" }));
    const accessForm = screen.getByRole("dialog", { name: "新增访问关系" });
    fireEvent.change(within(accessForm).getByRole("combobox", { name: "成员" }), { target: { value: "m-02" } });
    fireEvent.change(within(accessForm).getByRole("combobox", { name: "应用" }), { target: { value: "app-01" } });
    fireEvent.change(within(accessForm).getByRole("textbox", { name: "变更原因" }), { target: { value: "负责课程应用" } });
    fireEvent.click(within(accessForm).getByRole("button", { name: "提交新增" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认新增访问关系" })).getByRole("button", { name: "确认" }));
    expect(screen.getByText("周老师 → 校园学习助手")).toBeInTheDocument();
  });
});
