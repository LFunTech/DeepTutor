import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import TmsPrototype from "../apps/tms/src/TmsPrototype";

let path = "/oms/prototype";
const push = vi.fn((target: string) => { path = target; });
vi.mock("next/navigation", () => ({ usePathname: () => path, useRouter: () => ({ push }) }));

beforeEach(() => { path = "/oms/prototype"; push.mockClear(); sessionStorage.clear(); });
afterEach(() => vi.restoreAllMocks());

describe("OMS 原型边界", () => {
  it("学校详情只读生命周期，但可本地演示授予；供给不足被拒绝", () => {
    path = "/oms/prototype/tenants/aurora";
    render(<OmsPrototype/>);
    expect(screen.getByText(/只能由 EduPlus2 生命周期事件触发/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /暂停学校/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "授予额度（演示）" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: /授予数量/ }), { target: { value: "999999999" } });
    fireEvent.click(screen.getByRole("button", { name: "确认演示授予" }));
    expect(screen.getByText(/平台可授予额度不足/)).toBeInTheDocument();
  });

  it("只读审计角色不出现供给补充动作", () => {
    path = "/oms/prototype/supply/s-ocr";
    render(<OmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "auditor" } });
    expect(screen.queryByRole("button", { name: "补充供给（演示）" })).not.toBeInTheDocument();
  });

  it("文档 OCR 配置沿用解析引擎语义，不伪造独立 OCR 模型", () => {
    path = "/oms/prototype/services/ocr";
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "编辑配置草稿" }));
    expect(screen.getByRole("combobox", { name: "解析引擎" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "OCR 识别" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "解析引擎" }), { target: { value: "docling" } });
    expect(screen.getByRole("combobox", { name: "OCR 识别" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "模型标识" })).not.toBeInTheDocument();
  });

  it("演示写动作不发起网络请求", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    path = "/oms/prototype/tenants/aurora";
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "授予额度（演示）" }));
    fireEvent.click(screen.getByRole("button", { name: "确认演示授予" }));
    expect(fetch).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("未知真实用量显示待核对而非零", () => {
    path = "/oms/prototype/tenants/north/grants/q-105";
    render(<OmsPrototype/>);
    expect(screen.getByText("额度 q-105")).toBeInTheDocument();
    expect(screen.getAllByText("待核对").length).toBeGreaterThan(0);
    expect(screen.queryByText("0 Token")).not.toBeInTheDocument();
  });
});

describe("TMS 原型边界", () => {
  it("配额清单仅查询、筛选赠送与充值，没有配额写动作", () => {
    path = "/tms/prototype/demo-school/quotas";
    render(<TmsPrototype/>);
    const main = screen.getByRole("main");
    expect(within(main).getByRole("heading", { name: "配额清单" })).toBeInTheDocument();
    expect(within(main).queryByRole("button", { name: /新增|调整|充值|赠送|撤销/ })).not.toBeInTheDocument();
    expect(within(main).getByText("q-101")).toBeInTheDocument();
    expect(within(main).getByText("q-102")).toBeInTheDocument();
    fireEvent.change(within(main).getByRole("combobox", { name: "获取方式" }), { target: { value: "赠送" } });
    expect(within(main).getByText("q-101")).toBeInTheDocument();
    expect(within(main).queryByText("q-102")).not.toBeInTheDocument();
  });

  it("从详情返回后恢复配额获取方式筛选", async () => {
    path = "/tms/prototype/demo-school/quotas";
    const view = render(<TmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "获取方式" }), { target: { value: "充值" } });
    view.unmount();
    render(<TmsPrototype/>);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "获取方式" })).toHaveValue("充值"));
    expect(screen.queryByText("q-101")).not.toBeInTheDocument();
  });

  it("普通成员直达学校管理时拒绝", () => {
    path = "/tms/prototype/demo-school/quotas/q-101";
    render(<TmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "member" } });
    expect(screen.getByText("没有访问权限")).toBeInTheDocument();
    expect(screen.queryByText("300,000 Token")).not.toBeInTheDocument();
  });

  it("越界服务及配额写入深链均拒绝", () => {
    path = "/tms/prototype/demo-school/services/videogen";
    const view = render(<TmsPrototype/>);
    expect(screen.getByText("没有访问权限")).toBeInTheDocument();
    path = "/tms/prototype/demo-school/quotas/q-101/edit";
    view.rerender(<TmsPrototype/>);
    expect(screen.getByText("没有访问权限")).toBeInTheDocument();
    expect(screen.queryByText("300,000 Token")).not.toBeInTheDocument();
  });

  it("知识库详情有文档和处理任务元数据，不暴露正文", () => {
    path = "/tms/prototype/demo-school/knowledge/kb-03";
    render(<TmsPrototype/>);
    expect(screen.getByText("历史试题扫描件.pdf")).toBeInTheDocument();
    expect(screen.getByText(/不加载私有文件正文/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "处理任务" }));
    expect(screen.getByText("扫描件索引")).toBeInTheDocument();
  });

  it("加载、空记录和读取失败分别呈现", () => {
    path = "/tms/prototype/demo-school";
    render(<TmsPrototype/>);
    const selector = screen.getByRole("combobox", { name: "审计场景" });
    fireEvent.change(selector, { target: { value: "loading" } });
    expect(screen.getByText("正在载入")).toBeInTheDocument();
    fireEvent.change(selector, { target: { value: "empty" } });
    expect(screen.getByText("暂无记录")).toBeInTheDocument();
    fireEvent.change(selector, { target: { value: "error" } });
    expect(screen.getByText("暂时无法读取")).toBeInTheDocument();
  });
});
