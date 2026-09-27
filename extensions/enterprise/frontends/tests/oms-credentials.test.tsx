import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import ServiceConfigForm from "../apps/oms/src/ServiceConfigForm";

let path = "/oms/prototype/connections";
vi.mock("next/navigation", () => ({ usePathname: () => path }));

beforeEach(() => {
  path = "/oms/prototype/connections";
  window.history.replaceState({}, "", path);
  sessionStorage.clear();
});

function closeDrawer() {
  fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
}

describe("OMS 演示凭据交互", () => {
  it("切换解析引擎时重置不兼容的运行方式，避免错误凭据条件", () => {
    const saved = vi.fn();
    render(<ServiceConfigForm serviceId="ocr" onSave={saved} onCancel={() => {}}/>);
    fireEvent.change(screen.getByRole("textbox", { name: "解析配置名称" }), { target: { value: "解析方案" } });
    fireEvent.change(screen.getByRole("combobox", { name: "解析引擎" }), { target: { value: "docling" } });
    fireEvent.change(screen.getByRole("combobox", { name: "运行方式" }), { target: { value: "remote" } });
    fireEvent.change(screen.getByRole("combobox", { name: "解析引擎" }), { target: { value: "mineru" } });
    expect(screen.getByRole("combobox", { name: "运行方式" })).toHaveValue("local");
    fireEvent.click(screen.getByRole("button", { name: "保存演示草稿" }));
    expect(saved).toHaveBeenLastCalledWith(expect.objectContaining({ engine: "mineru", mode: "local" }));
    fireEvent.change(screen.getByRole("combobox", { name: "运行方式" }), { target: { value: "cloud" } });
    fireEvent.change(screen.getByRole("combobox", { name: "解析引擎" }), { target: { value: "docling" } });
    expect(screen.getByRole("combobox", { name: "运行方式" })).toHaveValue("local");
    fireEvent.click(screen.getByRole("button", { name: "保存演示草稿" }));
    expect(saved).toHaveBeenLastCalledWith(expect.objectContaining({ engine: "docling", mode: "local" }));
  });

  it("连接凭据由独立模态框录入演示值，不接受真实 Key，不回显或持久化", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增连接" }));
    const create = screen.getByRole("dialog", { name: "新增连接" });
    fireEvent.change(within(create).getByRole("textbox", { name: "名称" }), { target: { value: "百炼连接" } });
    fireEvent.change(within(create).getByRole("combobox", { name: "供应商" }), { target: { value: "dashscope" } });
    fireEvent.click(within(create).getByRole("button", { name: "保存演示草稿" }));
    const row = screen.getByText("百炼连接").closest("tr")!;
    expect(within(row).getByRole("button", { name: "配置凭据" })).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "连接资料" }));
    const drawer = screen.getByRole("dialog", { name: /百炼连接/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "配置凭据" }));
    let form = screen.getByRole("dialog", { name: "配置连接凭据" });
    const secret = within(form).getByLabelText("API Key") as HTMLInputElement;
    expect(secret.type).toBe("password");
    fireEvent.change(secret, { target: { value: "sk-real-key" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示凭据" }));
    expect(within(form).getByText(/仅接受 demo-/)).toBeInTheDocument();
    fireEvent.change(secret, { target: { value: "demo-qwen-1234" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示凭据" }));
    expect(screen.queryByRole("dialog", { name: "配置连接凭据" })).not.toBeInTheDocument();
    expect(within(drawer).getByText("已录入演示值 · 未验证")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("demo-qwen-1234");
    fireEvent.click(within(drawer).getByRole("button", { name: "轮换凭据" }));
    form = screen.getByRole("dialog", { name: "轮换连接凭据" });
    expect(within(form).getByLabelText("API Key")).toHaveValue("");
    fireEvent.click(within(form).getByRole("button", { name: "取消" }));
    expect(within(drawer).getByText("已录入演示值 · 未验证")).toBeInTheDocument();
  });

  it("Profile 可按明确 ID 绑定适用连接，绑定时不能重复维护 API Key", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增连接" }));
    const create = screen.getByRole("dialog", { name: "新增连接" });
    fireEvent.change(within(create).getByRole("textbox", { name: "名称" }), { target: { value: "百炼连接" } });
    fireEvent.change(within(create).getByRole("combobox", { name: "供应商" }), { target: { value: "dashscope" } });
    fireEvent.click(within(create).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(screen.getByRole("button", { name: "模型与服务" }));
    fireEvent.click(within(screen.getByText("对话模型").closest("tr")!).getByRole("button", { name: "Provider 配置" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: /对话模型/ })).getByRole("button", { name: "新增 Provider profile" }));
    const form = screen.getByRole("dialog", { name: "新增 Provider profile" });
    fireEvent.change(within(form).getByRole("textbox", { name: "配置名称" }), { target: { value: "百炼 Profile" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "凭据来源" }), { target: { value: "connection" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "供应商连接" }), { target: { value: screen.getByRole("option", { name: /百炼连接/ }).getAttribute("value") } });
    expect(within(form).getByRole("textbox", { name: "供应商" })).toHaveValue("dashscope");
    expect(within(form).getByRole("textbox", { name: "供应商" })).toHaveAttribute("readonly");
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: /对话模型/ })).getByRole("button", { name: /查看详情/ }));
    const drawer = screen.getByRole("dialog", { name: /对话模型/ });
    expect(within(drawer).getByText("百炼连接")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "配置凭据" })).not.toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "查看供应商连接" })).toBeInTheDocument();
  });

  it("独立 Profile 可配置演示凭据；运营和审计角色没有凭据入口", () => {
    path = "/oms/prototype/services/llm/provider";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增 Provider profile" }));
    const form = screen.getByRole("dialog", { name: "新增 Provider profile" });
    fireEvent.change(within(form).getByRole("textbox", { name: "配置名称" }), { target: { value: "独立百炼 Profile" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "供应商" }), { target: { value: "dashscope" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: /对话模型/ })).getByRole("button", { name: /查看详情/ }));
    let drawer = screen.getByRole("dialog", { name: /对话模型/ });
    fireEvent.click(within(drawer).getByRole("button", { name: "配置凭据" }));
    const secretForm = screen.getByRole("dialog", { name: "配置 Profile 凭据" });
    fireEvent.change(within(secretForm).getByLabelText("API Key"), { target: { value: "demo-profile-1234" } });
    fireEvent.click(within(secretForm).getByRole("button", { name: "保存演示凭据" }));
    expect(within(drawer).getByText("已录入演示值 · 未验证")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "operator" } });
    expect(within(drawer).queryByRole("button", { name: /凭据/ })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "auditor" } });
    expect(within(drawer).queryByRole("button", { name: /凭据/ })).not.toBeInTheDocument();
    closeDrawer();
  });

  it("OCR 仅 MinerU 云端与 Docling 远端出现对应凭据入口，本地模式不出现", () => {
    path = "/oms/prototype/services/ocr/config";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /文档 OCR/ });
    expect(within(drawer).queryByRole("button", { name: /凭据|Token|API Key/ })).not.toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "编辑配置草稿" }));
    let form = screen.getByRole("dialog", { name: "编辑文档 OCR配置" });
    fireEvent.change(within(form).getByRole("textbox", { name: "解析配置名称" }), { target: { value: "Docling 解析" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "解析引擎" }), { target: { value: "docling" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "运行方式" }), { target: { value: "remote" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "配置远端 API Key" }));
    let secretForm = screen.getByRole("dialog", { name: "配置 Docling 凭据" });
    expect(within(secretForm).getByLabelText("API Key")).toBeInTheDocument();
    fireEvent.change(within(secretForm).getByLabelText("API Key"), { target: { value: "demo-docling-1234" } });
    fireEvent.click(within(secretForm).getByRole("button", { name: "保存演示凭据" }));
    expect(within(drawer).getByText("已录入演示值 · 未验证")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "编辑配置草稿" }));
    form = screen.getByRole("dialog", { name: "编辑文档 OCR配置" });
    fireEvent.change(within(form).getByRole("combobox", { name: "解析引擎" }), { target: { value: "mineru" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "运行方式" }), { target: { value: "cloud" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "配置云端 Token" }));
    secretForm = screen.getByRole("dialog", { name: "配置 MinerU 凭据" });
    expect(within(secretForm).getByLabelText("API Token")).toBeInTheDocument();
    fireEvent.click(within(secretForm).getByRole("button", { name: "取消" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "编辑配置草稿" }));
    form = screen.getByRole("dialog", { name: "编辑文档 OCR配置" });
    fireEvent.change(within(form).getByRole("combobox", { name: "运行方式" }), { target: { value: "local" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    expect(within(drawer).queryByRole("button", { name: /凭据|Token|API Key/ })).not.toBeInTheDocument();
  });

  it("连接已绑定 Profile 时，不能把所需服务从连接目标中移除", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "模型与服务" }));
    fireEvent.click(within(screen.getByText("对话模型").closest("tr")!).getByRole("button", { name: "Provider 配置" }));
    fireEvent.click(screen.getByRole("button", { name: "新增 Provider profile" }));
    const profile = screen.getByRole("dialog", { name: "新增 Provider profile" });
    fireEvent.change(within(profile).getByRole("textbox", { name: "配置名称" }), { target: { value: "模型连接 Profile" } });
    fireEvent.change(within(profile).getByRole("combobox", { name: "凭据来源" }), { target: { value: "connection" } });
    fireEvent.click(within(profile).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(screen.getByRole("button", { name: "供应商连接" }));
    const row = screen.getByText("演示模型连接").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "连接资料" }));
    fireEvent.click(screen.getByRole("button", { name: "编辑连接草稿" }));
    const edit = screen.getByRole("dialog", { name: /编辑演示模型连接/ });
    fireEvent.click(within(edit).getByRole("checkbox", { name: "对话模型" }));
    fireEvent.click(within(edit).getByRole("button", { name: "保存演示草稿" }));
    expect(within(edit).getByText(/已有 Profile 使用此连接的对话模型/)).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: /演示模型连接/ })).toBeInTheDocument();
  });
});
