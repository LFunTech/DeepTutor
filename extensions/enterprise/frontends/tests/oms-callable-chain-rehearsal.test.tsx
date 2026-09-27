import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";

let path = "/oms/prototype";
vi.mock("next/navigation", () => ({ usePathname: () => path }));

beforeEach(() => {
  path = "/oms/prototype";
  window.history.replaceState({}, "", path);
  sessionStorage.clear();
});

function serviceAction(service: string, action: string) {
  fireEvent.click(within(screen.getByText(service).closest("tr")!).getByRole("button", { name: action }));
}

function closeDrawer() {
  fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
}

function recordUnverifiedSupply(serviceId: "s-llm" | "s-ocr", planId: string, batchId: string) {
  fireEvent.click(screen.getByRole("button", { name: "服务供给" }));
  fireEvent.click(screen.getByRole("tab", { name: "资源方案" }));
  fireEvent.click(screen.getByRole("button", { name: "新增供给方案" }));
  let form = screen.getByRole("dialog", { name: "新增供给方案" });
  fireEvent.change(within(form).getByRole("textbox", { name: "方案标识" }), { target: { value: planId } });
  fireEvent.change(within(form).getByRole("textbox", { name: "方案名称" }), { target: { value: `${serviceId} 演示方案` } });
  fireEvent.change(within(form).getByRole("combobox", { name: "关联服务" }), { target: { value: serviceId } });
  fireEvent.change(within(form).getByRole("textbox", { name: "供应商" }), { target: { value: "演示供应来源" } });
  fireEvent.change(within(form).getByRole("textbox", { name: "资源说明" }), { target: { value: "待核对的外部资源" } });
  fireEvent.click(within(form).getByRole("button", { name: "保存草稿" }));
  expect(screen.getByText(`${serviceId} 演示方案`)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "供给批次" }));
  fireEvent.click(screen.getByRole("button", { name: "新增供给批次" }));
  form = screen.getByRole("dialog", { name: "新增供给批次" });
  fireEvent.change(within(form).getByRole("textbox", { name: "批次标识" }), { target: { value: batchId } });
  fireEvent.change(within(form).getByRole("combobox", { name: "资源方案" }), { target: { value: planId } });
  fireEvent.change(within(form).getByRole("spinbutton", { name: "取得数量" }), { target: { value: "1000" } });
  fireEvent.change(within(form).getByRole("textbox", { name: "来源凭证" }), { target: { value: "演示来源凭证" } });
  fireEvent.click(within(form).getByRole("button", { name: "保存草稿" }));
  expect(within(screen.getByText(batchId).closest("tr")!).getByText("待核对")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "供给概览" }));
  expect(screen.getByText(serviceId === "s-llm" ? "520,000 Token" : "600 页")).toBeInTheDocument();
}

describe("OMS 可调用链路原型演练", () => {
  it("百炼 Qwen：连接、Profile、模型、配置、发布申请、额度；止于本地草稿", () => {
    render(<OmsPrototype/>);

    fireEvent.click(screen.getByRole("button", { name: "供应商连接" }));
    fireEvent.click(screen.getByRole("button", { name: "新增连接" }));
    let form = screen.getByRole("dialog", { name: "新增连接" });
    fireEvent.change(within(form).getByRole("textbox", { name: "名称" }), { target: { value: "百炼对话连接" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "供应商" }), { target: { value: "dashscope" } });
    expect(within(form).getByRole("checkbox", { name: "对话模型" })).toBeChecked();
    expect(within(form).queryByRole("textbox", { name: "凭据引用" })).not.toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    expect(screen.getByText("百炼对话连接")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "模型与服务" }));
    serviceAction("对话模型", "Provider 配置");
    fireEvent.click(within(screen.getByRole("dialog", { name: /对话模型/ })).getByRole("button", { name: "新增 Provider profile" }));
    form = screen.getByRole("dialog", { name: "新增 Provider profile" });
    fireEvent.change(within(form).getByRole("textbox", { name: "配置名称" }), { target: { value: "百炼 Qwen Profile" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "供应商" }), { target: { value: "dashscope" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    expect(within(screen.getByRole("dialog", { name: /对话模型/ })).getByText("百炼 Qwen Profile")).toBeInTheDocument();

    closeDrawer();
    serviceAction("对话模型", "模型清单");
    fireEvent.click(within(screen.getByRole("dialog", { name: /对话模型/ })).getByRole("button", { name: "新增模型" }));
    form = screen.getByRole("dialog", { name: "新增模型" });
    expect(within(form).getByRole("combobox", { name: "所属 Profile" })).toHaveTextContent("百炼 Qwen Profile");
    fireEvent.change(within(form).getByRole("textbox", { name: "模型名称" }), { target: { value: "Qwen Plus" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "模型候选" }), { target: { value: "qwen-plus" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存模型草稿" }));
    expect(within(screen.getByRole("dialog", { name: /对话模型/ })).getByText("Qwen Plus")).toBeInTheDocument();

    closeDrawer();
    serviceAction("对话模型", "服务配置");
    fireEvent.click(within(screen.getByRole("dialog", { name: /对话模型/ })).getByRole("button", { name: "编辑配置草稿" }));
    form = screen.getByRole("dialog", { name: "编辑对话模型配置" });
    fireEvent.change(within(form).getByRole("textbox", { name: "配置名称" }), { target: { value: "百炼 Qwen 配置" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "选用 Profile" }), { target: { value: within(form).getByRole("option", { name: /百炼 Qwen Profile/ }).getAttribute("value") } });
    fireEvent.change(within(form).getByRole("combobox", { name: "选用模型" }), { target: { value: within(form).getByRole("option", { name: /Qwen Plus/ }).getAttribute("value") } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    expect(within(screen.getByRole("dialog", { name: /对话模型/ })).getByText("未发布 · 待确认")).toBeInTheDocument();

    closeDrawer();
    serviceAction("对话模型", "发布记录");
    fireEvent.click(within(screen.getByRole("dialog", { name: /对话模型/ })).getByRole("button", { name: "提交发布申请（演示）" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认提交发布申请" })).getByRole("button", { name: "确认" }));
    expect(within(screen.getByRole("dialog", { name: /对话模型/ })).getByText("待执行者确认")).toBeInTheDocument();

    recordUnverifiedSupply("s-llm", "plan-qwen", "batch-qwen");
    fireEvent.click(screen.getByRole("button", { name: "学校列表" }));
    fireEvent.click(within(screen.getByText("海港职业学院").closest("tr")!).getByRole("button", { name: "额度清单" }));
    const drawer = screen.getByRole("dialog", { name: /海港职业学院/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "授予额度（演示）" }));
    form = screen.getByRole("dialog", { name: "授予额度" });
    expect(within(form).getByRole("combobox", { name: "服务" })).toHaveValue("llm");
    fireEvent.click(within(form).getByRole("button", { name: "确认演示授予" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认授予额度" })).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByText(/q-demo-/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "用量与运行" }));
    expect(screen.queryByText("Qwen Plus")).not.toBeInTheDocument();
    expect(screen.queryByText("百炼 Qwen 配置")).not.toBeInTheDocument();
  });

  it("OCR：解析引擎、发布申请、学校授权与页数额度；止于本地草稿", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "模型与服务" }));
    fireEvent.click(screen.getByRole("tab", { name: "文档识别与解析" }));
    serviceAction("文档 OCR", "服务配置");
    fireEvent.click(within(screen.getByRole("dialog", { name: /文档 OCR/ })).getByRole("button", { name: "编辑配置草稿" }));
    let form = screen.getByRole("dialog", { name: "编辑文档 OCR配置" });
    fireEvent.change(within(form).getByRole("textbox", { name: "解析配置名称" }), { target: { value: "Docling OCR 配置" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "解析引擎" }), { target: { value: "docling" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "运行方式" }), { target: { value: "remote" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "服务地址" }), { target: { value: "https://docling.example.test" } });
    fireEvent.click(within(form).getByRole("checkbox", { name: "OCR 识别" }));
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    expect(within(screen.getByRole("dialog", { name: /文档 OCR/ })).getByText("未发布 · 待确认")).toBeInTheDocument();

    closeDrawer();
    serviceAction("文档 OCR", "发布记录");
    fireEvent.click(within(screen.getByRole("dialog", { name: /文档 OCR/ })).getByRole("button", { name: "提交发布申请（演示）" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认提交发布申请" })).getByRole("button", { name: "确认" }));
    expect(within(screen.getByRole("dialog", { name: /文档 OCR/ })).getByText("待执行者确认")).toBeInTheDocument();

    recordUnverifiedSupply("s-ocr", "plan-docling", "batch-docling");
    fireEvent.click(screen.getByRole("button", { name: "学校列表" }));
    fireEvent.click(within(screen.getByText("海港职业学院").closest("tr")!).getByRole("button", { name: "服务授权" }));
    let drawer = screen.getByRole("dialog", { name: /海港职业学院/ });
    expect(within(drawer).queryByText("文档 OCR")).not.toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "授权服务（演示）" }));
    form = screen.getByRole("dialog", { name: "授权服务" });
    fireEvent.change(within(form).getByRole("combobox", { name: "服务" }), { target: { value: "ocr" } });
    fireEvent.click(within(form).getByRole("button", { name: "确认演示授权" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认服务授权" })).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByText("文档 OCR")).toBeInTheDocument();

    closeDrawer();
    fireEvent.click(within(screen.getByText("海港职业学院").closest("tr")!).getByRole("button", { name: "额度清单" }));
    drawer = screen.getByRole("dialog", { name: /海港职业学院/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "授予额度（演示）" }));
    form = screen.getByRole("dialog", { name: "授予额度" });
    fireEvent.change(within(form).getByRole("combobox", { name: "服务" }), { target: { value: "ocr" } });
    fireEvent.change(within(form).getByRole("spinbutton", { name: "授予数量" }), { target: { value: "100" } });
    fireEvent.click(within(form).getByRole("button", { name: "确认演示授予" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认授予额度" })).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByText("100 页")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "用量与运行" }));
    expect(screen.queryByText("Docling OCR 配置")).not.toBeInTheDocument();
  });
});
