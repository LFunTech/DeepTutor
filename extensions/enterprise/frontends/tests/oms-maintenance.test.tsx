import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";

let path = "/oms/prototype";
const push = vi.fn((next: string) => { path = next; });
vi.mock("next/navigation", () => ({ usePathname: () => path, useRouter: () => ({ push }) }));

beforeEach(() => { path = "/oms/prototype"; push.mockClear(); sessionStorage.clear(); });

describe("OMS 抽屉式维护", () => {
  it("额度操作弹出独立模态框，不在详情抽屉中撑开表单", () => {
    path = "/oms/prototype/tenants/aurora";
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /详情.*星河实验学校/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "授予额度（演示）" }));
    const form = screen.getByRole("dialog", { name: "授予额度" });
    expect(form.parentElement?.parentElement).toBe(document.body);
    expect(form).toHaveFocus();
    expect(within(form).getByRole("spinbutton", { name: "授予数量" })).toBeInTheDocument();
    expect(drawer).not.toContainElement(form);
    expect(drawer).not.toHaveTextContent("新增授予 · 本地演示");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "授予额度" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: /详情.*星河实验学校/ })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
  });

  it("复核取消后返回原操作模态框并保留填写内容", () => {
    path = "/oms/prototype/tenants/aurora";
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "授予额度（演示）" }));
    const form = screen.getByRole("dialog", { name: "授予额度" });
    fireEvent.change(within(form).getByRole("spinbutton", { name: "授予数量" }), { target: { value: "123" } });
    fireEvent.click(within(form).getByRole("button", { name: "确认演示授予" }));
    expect(screen.queryByRole("dialog", { name: "授予额度" })).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "取消" }));
    expect(within(screen.getByRole("dialog", { name: "授予额度" })).getByRole("spinbutton", { name: "授予数量" })).toHaveValue(123);
  });

  it("从服务列表打开详情抽屉，关闭后保留列表", () => {
    path = "/oms/prototype/services";
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "查看对话模型详情" }));
    expect(screen.getByRole("dialog", { name: /详情.*对话模型/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "模型与服务" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "模型与服务" })).toBeInTheDocument();
  });

  it("未知详情深链不把列表伪装成对象详情", () => {
    path = "/oms/prototype/services/not-found";
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: "详情 · 未找到" });
    expect(within(drawer).getByText("对象不存在或不可访问")).toBeInTheDocument();
    expect(within(drawer).queryByRole("heading", { name: "模型与服务" })).not.toBeInTheDocument();
  });

  it("关闭详情抽屉后保留服务列表搜索条件", () => {
    path = "/oms/prototype/services";
    render(<OmsPrototype/>);
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索服务" }), { target: { value: "OCR" } });
    fireEvent.click(screen.getByRole("button", { name: "查看文档 OCR详情" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: /文档 OCR/ })).getByRole("button", { name: "关闭抽屉" }));
    expect(screen.getByRole("searchbox", { name: "搜索服务" })).toHaveValue("OCR");
    expect(screen.getByText("文档 OCR")).toBeInTheDocument();
  });

  it("关闭额度详情返回学校详情，而不是直接丢失上级上下文", () => {
    path = "/oms/prototype/tenants/aurora";
    render(<OmsPrototype/>);
    const tenantDrawer = screen.getByRole("dialog", { name: /星河实验学校/ });
    fireEvent.click(within(tenantDrawer).getAllByRole("button", { name: /查看详情/ })[0]);
    expect(screen.getByRole("dialog", { name: /额度 q-101/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(screen.getByRole("dialog", { name: /星河实验学校/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "额度清单" })).toHaveAttribute("aria-selected", "true");
  });

  it("服务草稿在模态框保存，详情抽屉不变且可回读", () => {
    path = "/oms/prototype/services/ocr";
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /详情.*文档 OCR/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "编辑配置草稿" }));
    const form = screen.getByRole("dialog", { name: /编辑文档 OCR配置/ });
    expect(within(drawer).queryByRole("textbox", { name: "解析配置名称" })).not.toBeInTheDocument();
    fireEvent.change(within(form).getByRole("textbox", { name: "解析配置名称" }), { target: { value: "扫描文档配置" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "解析引擎" }), { target: { value: "docling" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    expect(within(drawer).getByText("扫描文档配置")).toBeInTheDocument();
    expect(within(drawer).getByText(/未发布|待确认/)).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "编辑配置草稿" }));
    expect(within(screen.getByRole("dialog", { name: /编辑文档 OCR配置/ })).getByRole("combobox", { name: "解析引擎" })).toHaveValue("docling");
  });

  it("服务发布申请经过复核且不伪装执行者已生效", () => {
    path = "/oms/prototype/services/search";
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /联网搜索/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "编辑配置草稿" }));
    const form = screen.getByRole("dialog", { name: /编辑联网搜索配置/ });
    fireEvent.change(within(form).getByRole("textbox", { name: "搜索配置名称" }), { target: { value: "演示搜索配置 B" } });
    expect(within(form).queryByRole("textbox", { name: "模型标识" })).not.toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "提交发布申请（演示）" }));
    expect(screen.getByRole("alertdialog", { name: "确认提交发布申请" })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "确认" }));
    fireEvent.click(within(drawer).getByRole("tab", { name: "发布记录" }));
    expect(within(drawer).getByText("待执行者确认")).toBeInTheDocument();
    expect(within(drawer).queryByText("已生效")).not.toBeInTheDocument();
  });

  it.each(["agents", "tools", "knowledge", "runtime"])("%s 资源有可回读的策略维护入口", root => {
    path = `/oms/prototype/${root}`;
    render(<OmsPrototype/>);
    fireEvent.click(screen.getAllByRole("button", { name: /查看详情/ })[0]);
    const drawer = screen.getByRole("dialog", { name: /详情/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "管理平台策略" }));
    const form = screen.getByRole("dialog", { name: /管理.*策略/ });
    fireEvent.change(within(form).getByRole("textbox", { name: "策略说明" }), { target: { value: "仅供已授权学校使用" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存策略草稿" }));
    expect(within(drawer).getByText("仅供已授权学校使用")).toBeInTheDocument();
  });

  it("供应商连接可从列表新增，且保存后列表可见", () => {
    path = "/oms/prototype/connections";
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增连接" }));
    const form = screen.getByRole("dialog", { name: "新增连接" });
    expect(form.parentElement?.parentElement).toBe(document.body);
    expect(screen.getByRole("heading", { name: "供应商连接" })).toBeInTheDocument();
    fireEvent.change(within(form).getByRole("textbox", { name: "名称" }), { target: { value: "新供应商连接" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "供应商" }), { target: { value: "演示供应商 D" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("新供应商连接")).toBeInTheDocument();
  });

  it("编辑供应商连接保留并可调整多个 DeepTutor 服务目标", () => {
    path = "/oms/prototype/connections/c-model";
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /演示模型连接/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "编辑连接草稿" }));
    const form = screen.getByRole("dialog", { name: /编辑演示模型连接/ });
    expect(within(form).getByRole("checkbox", { name: "对话模型" })).toBeChecked();
    expect(within(form).getByRole("checkbox", { name: "任务模型" })).toBeChecked();
    expect(within(form).getByRole("checkbox", { name: "向量服务" })).toBeChecked();
    fireEvent.click(within(form).getByRole("checkbox", { name: "任务模型" }));
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    expect(within(drawer).getByText("llm / embedding")).toBeInTheDocument();
  });

  it("额度授予先确认，可取消；审计员没有维护入口", () => {
    path = "/oms/prototype/tenants/aurora";
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "授予额度（演示）" }));
    fireEvent.click(screen.getByRole("button", { name: "确认演示授予" }));
    expect(screen.getByRole("alertdialog", { name: /确认授予额度/ })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "auditor" } });
    expect(screen.queryByRole("button", { name: "授予额度（演示）" })).not.toBeInTheDocument();
  });

  it("授予额度使用实际填写的有效期，不能绕过服务授权", () => {
    const future = new Date();
    future.setFullYear(future.getFullYear() + 1);
    const expiry = `${future.getFullYear()}-${String(future.getMonth() + 1).padStart(2, "0")}-${String(future.getDate()).padStart(2, "0")}`;
    path = "/oms/prototype/tenants/harbor";
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /海港职业学院/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "授予额度（演示）" }));
    const form = screen.getByRole("dialog", { name: "授予额度" });
    fireEvent.change(within(form).getByRole("combobox", { name: "服务" }), { target: { value: "ocr" } });
    fireEvent.click(within(form).getByRole("button", { name: "确认演示授予" }));
    expect(within(form).getByText(/请先授权该服务/)).toBeInTheDocument();
    fireEvent.change(within(form).getByRole("combobox", { name: "服务" }), { target: { value: "llm" } });
    fireEvent.change(within(form).getByLabelText("有效期"), { target: { value: expiry } });
    fireEvent.click(within(form).getByRole("button", { name: "确认演示授予" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(expiry);
  });

  it("待核对额度不能通过撤销服务授权绕过预留", () => {
    path = "/oms/prototype/tenants/north";
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /北辰研究院/ });
    fireEvent.click(within(drawer).getByRole("tab", { name: "服务授权" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "撤销服务授权" }));
    const form = screen.getByRole("dialog", { name: "撤销服务授权" });
    fireEvent.change(within(form).getByRole("combobox", { name: "服务" }), { target: { value: "llm" } });
    fireEvent.click(within(form).getByRole("button", { name: "继续撤销" }));
    expect(within(form).getByText(/仍有关联有效或待核对额度/)).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("服务授权后学校清单与详情显示一致的授权数量", () => {
    path = "/oms/prototype/tenants/harbor";
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /海港职业学院/ });
    fireEvent.click(within(drawer).getByRole("tab", { name: "服务授权" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "授权服务（演示）" }));
    const form = screen.getByRole("dialog", { name: "授权服务" });
    fireEvent.change(within(form).getByRole("combobox", { name: "服务" }), { target: { value: "video-learning" } });
    fireEvent.click(within(form).getByRole("button", { name: "确认演示授权" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByText("视频学习接入")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "关闭抽屉" }));
    const row = screen.getByRole("row", { name: /海港职业学院/ });
    expect(within(row).getByText("7 项")).toBeInTheDocument();
  });

  it("平台运营可维护权益但不能编辑高权限服务配置", () => {
    path = "/oms/prototype/services/ocr";
    render(<OmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "operator" } });
    expect(screen.queryByRole("button", { name: "编辑配置草稿" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "学校列表" }));
    fireEvent.click(screen.getAllByRole("button", { name: "查看详情" })[0]);
    expect(screen.getByRole("button", { name: "授予额度（演示）" })).toBeInTheDocument();
  });

  it("确认框 Escape 返回表单，详情抽屉仍保留", () => {
    path = "/oms/prototype/tenants/aurora";
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "授予额度（演示）" }));
    fireEvent.click(screen.getByRole("button", { name: "确认演示授予" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "授予额度" })).toBeInTheDocument();
    expect(document.querySelector('[aria-label="详情 · 星河实验学校"]')).toBeInTheDocument();
  });

  it("额度调整与撤销只影响未使用额度，并经过确认", () => {
    path = "/oms/prototype/tenants/aurora/grants/q-101";
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /额度 q-101/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "调整额度" }));
    const form = screen.getByRole("dialog", { name: "调整额度" });
    fireEvent.change(within(form).getByRole("spinbutton", { name: /增加额度/ }), { target: { value: "100" } });
    fireEvent.click(within(form).getByRole("button", { name: "提交调整" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认调整额度" })).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByText("180,100 Token")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "撤销未使用额度" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认撤销额度" })).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByText("0 Token")).toBeInTheDocument();
    expect(within(drawer).getByText("120,000 Token")).toBeInTheDocument();
  });

  it("供给补充有确认框，确认后可回读供给数量", () => {
    path = "/oms/prototype/supply/s-ocr";
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /文档解析资源/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "补充供给（演示）" }));
    const form = screen.getByRole("dialog", { name: "补充服务供给" });
    fireEvent.change(within(form).getByRole("spinbutton", { name: /补充数量/ }), { target: { value: "100" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "来源说明" }), { target: { value: "采购单 DEMO-8" } });
    fireEvent.click(within(form).getByRole("button", { name: "确认演示补充" }));
    expect(screen.getByRole("alertdialog", { name: "确认补充供给" })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByText("700")).toBeInTheDocument();
    expect(within(drawer).getByText("采购单 DEMO-8")).toBeInTheDocument();
  });
});
