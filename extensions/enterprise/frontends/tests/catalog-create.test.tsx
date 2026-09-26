import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";

let path = "/oms/prototype/services";
vi.mock("next/navigation", () => ({ usePathname: () => path, useRouter: () => ({ push: (target: string) => { path = target; } }) }));
beforeEach(() => { path = "/oms/prototype/services"; sessionStorage.clear(); });

describe("OMS 类型化资源新增", () => {
  it.each([
    ["agents", "新增 Agent 与能力", "外部 Agent 接入", "外部端点"],
    ["tools", "新增 工具与集成", "MCP 接入", "接入地址"],
    ["knowledge", "新增 知识基础能力", "解析配置", "依赖服务"],
    ["runtime", "新增 运行资源", "沙箱策略", "运行环境"],
  ])("%s 从专用模态框新增草稿并可回读", (route, button, kind, field) => {
    path = `/oms/prototype/${route}`;
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: button }));
    const modal = screen.getByRole("dialog", { name: button });
    expect(within(modal).getByRole("combobox", { name: "新增类型" })).toBeInTheDocument();
    fireEvent.change(within(modal).getByRole("textbox", { name: "资源标识" }), { target: { value: `demo-${route}` } });
    fireEvent.change(within(modal).getByRole("textbox", { name: "资源名称" }), { target: { value: `演示${kind}` } });
    fireEvent.change(within(modal).getByRole("textbox", { name: field }), { target: { value: ["agents", "tools"].includes(route) ? "https://example.test/endpoint" : "演示依赖" } });
    fireEvent.click(within(modal).getByRole("button", { name: "保存草稿" }));
    expect(screen.getByText(`演示${kind}`)).toBeInTheDocument();
    expect(screen.getAllByText("草稿").length).toBeGreaterThan(0);
  });

  it("外部服务草稿必须声明适配器与计量单位，不会显示为可调用", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增服务接入" }));
    const modal = screen.getByRole("dialog", { name: "新增服务接入" });
    fireEvent.change(within(modal).getByRole("textbox", { name: "资源标识" }), { target: { value: "demo-transcription" } });
    fireEvent.change(within(modal).getByRole("textbox", { name: "资源名称" }), { target: { value: "演示转录" } });
    fireEvent.click(within(modal).getByRole("button", { name: "保存草稿" }));
    expect(within(modal).getByRole("textbox", { name: "适配器方案" })).toBeInTheDocument();
    fireEvent.change(within(modal).getByRole("textbox", { name: "适配器方案" }), { target: { value: "待开发独立服务适配器" } });
    fireEvent.change(within(modal).getByRole("textbox", { name: "计量单位" }), { target: { value: "分钟" } });
    fireEvent.click(within(modal).getByRole("button", { name: "保存草稿" }));
    expect(screen.getByText("演示转录")).toBeInTheDocument();
    expect(screen.getAllByText("暂不可用").length).toBeGreaterThan(0);
  });

  it("供给方案与批次新增不直接增加可授予量", () => {
    path = "/oms/prototype/supply";
    render(<OmsPrototype/>);
    const before = screen.getByText("520,000 Token");
    expect(before).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "新增供给方案" }));
    expect(screen.getByRole("dialog", { name: "新增供给方案" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(screen.getByRole("button", { name: "新增供给批次" }));
    expect(screen.getByRole("dialog", { name: "新增供给批次" })).toBeInTheDocument();
    expect(screen.getByText("520,000 Token")).toBeInTheDocument();
  });

  it("供给方案与批次保存后可从列表回读，待核对量不进入平台可授予量", () => {
    path = "/oms/prototype/supply";
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增供给方案" }));
    const plan = screen.getByRole("dialog", { name: "新增供给方案" });
    fireEvent.change(within(plan).getByRole("textbox", { name: "方案标识" }), { target: { value: "demo-plan" } });
    fireEvent.change(within(plan).getByRole("textbox", { name: "方案名称" }), { target: { value: "演示模型资源方案" } });
    fireEvent.change(within(plan).getByRole("textbox", { name: "供应商" }), { target: { value: "演示供应商" } });
    fireEvent.change(within(plan).getByRole("textbox", { name: "资源说明" }), { target: { value: "采购方案待确认" } });
    fireEvent.click(within(plan).getByRole("button", { name: "保存草稿" }));
    expect(screen.getByText("演示模型资源方案")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "新增供给批次" }));
    const batch = screen.getByRole("dialog", { name: "新增供给批次" });
    fireEvent.change(within(batch).getByRole("textbox", { name: "批次标识" }), { target: { value: "demo-batch" } });
    fireEvent.change(within(batch).getByRole("combobox", { name: "资源方案" }), { target: { value: "demo-plan" } });
    fireEvent.change(within(batch).getByRole("spinbutton", { name: "取得数量" }), { target: { value: "1000" } });
    fireEvent.change(within(batch).getByRole("textbox", { name: "来源凭证" }), { target: { value: "演示单号" } });
    fireEvent.click(within(batch).getByRole("button", { name: "保存草稿" }));
    expect(screen.getByText("demo-batch")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    expect(screen.getByText("未增加")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    fireEvent.click(screen.getByRole("tab", { name: "供给概览" }));
    expect(screen.getByText("520,000 Token")).toBeInTheDocument();
  });

  it("资源标识重复被拒绝；取消新增不写入列表", () => {
    path = "/oms/prototype/agents";
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增 Agent 与能力" }));
    const modal = screen.getByRole("dialog", { name: "新增 Agent 与能力" });
    fireEvent.change(within(modal).getByRole("textbox", { name: "资源标识" }), { target: { value: "deep-solve" } });
    fireEvent.change(within(modal).getByRole("textbox", { name: "资源名称" }), { target: { value: "重复 Agent" } });
    fireEvent.change(within(modal).getByRole("textbox", { name: "外部端点" }), { target: { value: "https://example.test/agent" } });
    fireEvent.click(within(modal).getByRole("button", { name: "保存草稿" }));
    expect(within(modal).getByText(/已有相同资源标识/)).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "取消" }));
    expect(screen.queryByText("重复 Agent")).not.toBeInTheDocument();
  });

  it("现有服务可分别新增 Provider profile 与模型草稿；搜索服务不出现模型入口", () => {
    path = "/oms/prototype/services/llm";
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("tab", { name: "供应商配置" }));
    fireEvent.click(screen.getByRole("button", { name: "新增 Provider profile" }));
    const profile = screen.getByRole("dialog", { name: "新增 Provider profile" });
    fireEvent.change(within(profile).getByRole("textbox", { name: "配置名称" }), { target: { value: "演示 profile" } });
    fireEvent.change(within(profile).getByRole("textbox", { name: "供应商标识" }), { target: { value: "demo-provider" } });
    fireEvent.click(within(profile).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(screen.getByRole("button", { name: "新增模型" }));
    const model = screen.getByRole("dialog", { name: "新增模型" });
    expect(within(model).getByRole("combobox", { name: "所属 Profile" })).toBeInTheDocument();
    fireEvent.change(within(model).getByRole("textbox", { name: "模型名称" }), { target: { value: "演示模型" } });
    fireEvent.change(within(model).getByRole("textbox", { name: "模型标识" }), { target: { value: "demo-model" } });
    fireEvent.click(within(model).getByRole("button", { name: "保存模型草稿" }));
    expect(screen.getByText("演示模型")).toBeInTheDocument();
  });

  it("审计员不能新增资源；学校/用量/审计无新增入口", () => {
    path = "/oms/prototype/agents";
    render(<OmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "auditor" } });
    expect(screen.queryByRole("button", { name: "新增 Agent 与能力" })).not.toBeInTheDocument();
  });
});
