import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import ServiceConfigForm from "../apps/oms/src/ServiceConfigForm";
import OmsModelCreate from "../apps/oms/src/OmsModelCreate";
import { demoReasoningOptions, descriptorSource, descriptorSourceRevision, reasoningSourceRevision } from "../apps/oms/src/providerDescriptors";
import { reasoningEffortOptions } from "../../../../web/lib/reasoning-effort";

let path = "/oms/prototype/connections";
vi.mock("next/navigation", () => ({ usePathname: () => path }));
beforeEach(() => { path = "/oms/prototype/connections"; window.history.replaceState({}, "", path); sessionStorage.clear(); });

describe("OMS 设置控件与 DeepTutor 语义", () => {
  it("离线供应商候选记录 DeepTutor 来源与源码版本，不冒充实时发现", () => {
    expect(descriptorSource).toContain("deeptutor.api.routers.settings");
    expect(descriptorSourceRevision).toMatch(/^[a-f0-9]{12}$/);
    expect(reasoningSourceRevision).toMatch(/^[a-f0-9]{12}$/);
  });
  it("连接供应商使用候选，适用服务由供应商能力过滤", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增连接" }));
    const form = screen.getByRole("dialog", { name: "新增连接" });
    const provider = within(form).getByRole("combobox", { name: "供应商" });
    fireEvent.change(provider, { target: { value: "dashscope" } });
    expect(within(form).getByRole("checkbox", { name: "对话模型" })).toBeInTheDocument();
    expect(within(form).queryByRole("checkbox", { name: "任务模型" })).not.toBeInTheDocument();
    expect(within(form).queryByRole("checkbox", { name: "联网搜索" })).not.toBeInTheDocument();
  });

  it("Profile 仅维护供应商与连接/API 格式，不再包含模型属性", () => {
    render(<ServiceConfigForm serviceId="llm" requireProvider onSave={vi.fn()} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("combobox", { name: "供应商" }), { target: { value: "dashscope" } });
    expect(screen.getByRole("combobox", { name: "API 格式" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "模型标识" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "上下文窗口" })).not.toBeInTheDocument();
  });

  it("搜索 Profile 按供应商显示地址条件", () => {
    render(<ServiceConfigForm serviceId="search" requireProvider onSave={vi.fn()} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("combobox", { name: "供应商" }), { target: { value: "none" } });
    expect(screen.queryByRole("textbox", { name: "服务地址" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "供应商" }), { target: { value: "searxng" } });
    expect(screen.getByRole("textbox", { name: "服务地址" })).toBeRequired();
  });

  it("模型能力为三态选择，向量维度与开关在模型层", () => {
    const profiles = [{ id: "p1", serviceId: "llm", name: "百炼", provider: "dashscope", fields: {}, status: "草稿" as const }];
    render(<OmsModelCreate serviceId="llm" profiles={profiles} models={[]} onSave={vi.fn()} onCancel={vi.fn()}/>);
    expect(screen.getByRole("combobox", { name: "工具调用能力" })).toBeInTheDocument();
    expect(within(screen.getByRole("combobox", { name: "工具调用能力" })).getAllByRole("option")).toHaveLength(3);
    expect(screen.getByRole("combobox", { name: "模型候选" })).toBeInTheDocument();
  });

  it.each([
    ["tts", "音频格式", "音色", "response_format", "wav"],
    ["stt", null, null, null, null],
    ["imagegen", null, "尺寸", "size", "1024x1024"],
    ["videogen", null, "宽高比", "aspect_ratio", "16:9"],
  ])("%s 模型表单只展示对应服务字段并保存模型层属性", (serviceId, selectLabel, fieldLabel, savedKey, value) => {
    const save = vi.fn();
    const profiles = [{ id: `p-${serviceId}`, serviceId, name: "百炼", provider: "dashscope", fields: {}, status: "草稿" as const }];
    render(<OmsModelCreate serviceId={serviceId!} profiles={profiles} models={[]} onSave={save} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("textbox", { name: "模型名称" }), { target: { value: "演示模型" } });
    fireEvent.change(screen.getByRole("textbox", { name: "模型标识" }), { target: { value: `demo-${serviceId}` } });
    if (selectLabel) fireEvent.change(screen.getByRole("combobox", { name: selectLabel }), { target: { value } });
    else if (fieldLabel) fireEvent.change(screen.getByRole("textbox", { name: fieldLabel }), { target: { value } });
    expect(screen.queryByRole("combobox", { name: "工具调用能力" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "向量维度" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存模型草稿" }));
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ serviceId, fields: savedKey ? expect.objectContaining({ [savedKey]: value }) : {} }));
  });

  it.each(["tts", "stt", "imagegen", "videogen"])("%s Profile 供应商由该服务候选控制", serviceId => {
    render(<ServiceConfigForm serviceId={serviceId} requireProvider onSave={vi.fn()} onCancel={vi.fn()}/>);
    const provider = screen.getByRole("combobox", { name: "供应商" });
    expect(within(provider).getByRole("option", { name: /dashscope|百炼/i })).toBeInTheDocument();
    expect(within(provider).queryByRole("option", { name: "MinerU" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "模型标识" })).not.toBeInTheDocument();
  });

  it("向量模型按已知能力选择维度，保存布尔和数字而不是文本枚举", () => {
    const save = vi.fn();
    const profiles = [{ id: "p2", serviceId: "embedding", name: "百炼向量", provider: "aliyun", fields: {}, status: "草稿" as const }];
    render(<OmsModelCreate serviceId="embedding" profiles={profiles} models={[]} onSave={save} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("textbox", { name: "模型名称" }), { target: { value: "百炼视觉向量" } });
    fireEvent.change(screen.getByRole("textbox", { name: "模型标识" }), { target: { value: "qwen3-vl-embedding" } });
    fireEvent.change(screen.getByRole("combobox", { name: "向量维度" }), { target: { value: "1536" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "发送维度参数" }));
    fireEvent.click(screen.getByRole("button", { name: "保存模型草稿" }));
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ fields: expect.objectContaining({ dimension: 1536, send_dimensions: false }) }));
  });

  it("任务模型不显示尚未由后端连接 descriptor 提供的连接维护入口", () => {
    path = "/oms/prototype/services/task/provider";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    expect(screen.queryByRole("button", { name: "适用连接" })).not.toBeInTheDocument();
  });

  it("解析引擎展示对应开关、格式与数字边界，而非通用说明", () => {
    render(<ServiceConfigForm serviceId="ocr" onSave={vi.fn()} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("combobox", { name: "解析引擎" }), { target: { value: "pymupdf4llm" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "提取图片" }));
    expect(screen.getByRole("combobox", { name: "图片格式" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "图片分辨率（DPI）" })).toHaveAttribute("min", "72");
    fireEvent.change(screen.getByRole("combobox", { name: "解析引擎" }), { target: { value: "liteparse" } });
    expect(screen.getByRole("checkbox", { name: "提取链接" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "最大页数" })).toHaveAttribute("min", "0");
  });

  it("非搜索 Profile 的高级字段保留 API 版本与结构化请求头，并拒绝无效 JSON", () => {
    const save = vi.fn();
    render(<ServiceConfigForm serviceId="llm" requireProvider onSave={save} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("textbox", { name: "配置名称" }), { target: { value: "百炼" } });
    fireEvent.change(screen.getByRole("combobox", { name: "供应商" }), { target: { value: "dashscope" } });
    fireEvent.click(screen.getByText("高级请求选项"));
    expect(screen.getByRole("textbox", { name: "API 版本" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "额外请求头（JSON）" }), { target: { value: "{broken" } });
    fireEvent.click(screen.getByRole("button", { name: "保存演示草稿" }));
    expect(save).not.toHaveBeenCalled();
    expect(screen.getByText("额外请求头须为 JSON 对象。" )).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "额外请求头（JSON）" }), { target: { value: '{"X-Trace":"demo"}' } });
    fireEvent.click(screen.getByRole("button", { name: "保存演示草稿" }));
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ api_version: "", extra_headers: '{"X-Trace":"demo"}' }));
  });

  it("没有兼容连接的服务不提供无法完成的连接凭据来源", () => {
    render(<ServiceConfigForm serviceId="task" requireProvider onSave={vi.fn()} onCancel={vi.fn()}/>);
    expect(screen.queryByRole("combobox", { name: "凭据来源" })).not.toBeInTheDocument();
    expect(screen.getByText(/当前服务尚无可绑定的连接/)).toBeInTheDocument();
  });

  it("Agent 与工具的平台策略不会被误认为可维护全部 DeepTutor 运行参数", () => {
    path = "/oms/prototype/agents/deep-solve/policy";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    expect(screen.getByText(/Agent 运行参数待接入/)).toBeInTheDocument();
  });

  it("不要求 API Key 的搜索 Profile 不提供虚假的密钥维护操作", () => {
    path = "/oms/prototype/services/search/provider";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增 Provider profile" }));
    const form = screen.getByRole("dialog", { name: "新增 Provider profile" });
    fireEvent.change(within(form).getByRole("textbox", { name: "搜索配置名称" }), { target: { value: "无搜索" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "供应商" }), { target: { value: "none" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(within(screen.getByText("无搜索").closest("tr")!).getByRole("button", { name: "查看详情" }));
    expect(screen.queryByRole("button", { name: "配置凭据" })).not.toBeInTheDocument();
  });

  it("OAuth Profile 不按 API Key 表单配置凭据", () => {
    path = "/oms/prototype/services/llm/provider";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增 Provider profile" }));
    const form = screen.getByRole("dialog", { name: "新增 Provider profile" });
    fireEvent.change(within(form).getByRole("textbox", { name: "配置名称" }), { target: { value: "OAuth Profile" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "供应商" }), { target: { value: "openai_codex" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(within(screen.getByText("OAuth Profile").closest("tr")!).getByRole("button", { name: "查看详情" }));
    expect(screen.queryByRole("button", { name: "配置凭据" })).not.toBeInTheDocument();
    expect(screen.getByText(/OAuth 授权流程待接入/)).toBeInTheDocument();
  });

  it("OAuth 供应商的 Profile 表单不显示误导性的凭据来源与请求头", () => {
    render(<ServiceConfigForm serviceId="llm" requireProvider connections={[{ id: "c1", name: "连接", provider: "dashscope", serviceIds: ["llm"] }]} onSave={vi.fn()} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("combobox", { name: "供应商" }), { target: { value: "openai_codex" } });
    expect(screen.queryByRole("combobox", { name: "凭据来源" })).not.toBeInTheDocument();
    expect(screen.queryByText("高级请求选项")).not.toBeInTheDocument();
    expect(screen.getByText(/OAuth 授权流程待接入/)).toBeInTheDocument();
  });

  it("API 格式切换只联动供应商默认地址，不覆盖运营手填地址", () => {
    render(<ServiceConfigForm serviceId="llm" requireProvider onSave={vi.fn()} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("combobox", { name: "供应商" }), { target: { value: "minimax" } });
    expect(screen.getByRole("textbox", { name: "服务地址" })).toHaveValue("https://api.minimax.io/v1");
    fireEvent.change(screen.getByRole("combobox", { name: "API 格式" }), { target: { value: "anthropic" } });
    expect(screen.getByRole("textbox", { name: "服务地址" })).toHaveValue("https://api.minimax.io/anthropic");
    fireEvent.change(screen.getByRole("textbox", { name: "服务地址" }), { target: { value: "https://custom.example.test" } });
    fireEvent.change(screen.getByRole("combobox", { name: "API 格式" }), { target: { value: "openai_chat" } });
    expect(screen.getByRole("textbox", { name: "服务地址" })).toHaveValue("https://custom.example.test");
  });

  it("推理档位遵循 DeepTutor 的模型族条件，不局限于百炼 Qwen", () => {
    const profiles = [{ id: "p1", serviceId: "llm", name: "Gemini", provider: "gemini", fields: {}, status: "草稿" as const }];
    render(<OmsModelCreate serviceId="llm" profiles={profiles} models={[]} onSave={vi.fn()} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("textbox", { name: "模型标识" }), { target: { value: "gemini-2.5-pro" } });
    const effort = screen.getByRole("combobox", { name: "推理档位" });
    expect(within(effort).getByRole("option", { name: /minimal/ })).toBeInTheDocument();
    expect(within(effort).queryByRole("option", { name: /none/ })).not.toBeInTheDocument();
  });

  it("离线推理档位与 DeepTutor 源码的代表性模型族保持一致", () => {
    for (const [provider, model] of [["dashscope", "qwen-plus"], ["dashscope", "qwen-3-32b"], ["gemini", "gemini-2.5-pro"], ["anthropic", "claude-sonnet-4"], ["openai", "gpt-5.6-sol"], ["minimax", "MiniMax-M2"], ["custom", "private-model"], ["deepseek", "deepseek-reasoner"]]) {
      expect(demoReasoningOptions(provider, model).map(option => option.value)).toEqual(reasoningEffortOptions(provider, model).map(option => option.value));
    }
  });

  it("模型候选失败演示会转为手动输入，并明确不是实际供应商故障", () => {
    const profiles = [{ id: "p1", serviceId: "llm", name: "百炼", provider: "dashscope", fields: {}, status: "草稿" as const }];
    render(<OmsModelCreate serviceId="llm" profiles={profiles} models={[]} onSave={vi.fn()} onCancel={vi.fn()}/>);
    expect(screen.getByRole("combobox", { name: "模型候选" })).toBeInTheDocument();
    fireEvent.click(screen.getByText("演示不同候选结果"));
    fireEvent.change(screen.getByRole("combobox", { name: "候选状态演示" }), { target: { value: "error" } });
    expect(screen.queryByRole("combobox", { name: "模型候选" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "模型标识" })).toBeInTheDocument();
    expect(screen.getByText(/模型候选获取失败（演示）/)).toBeInTheDocument();
  });

  it("切换所属 Profile 后清空旧供应商的模型条件字段", () => {
    const save = vi.fn();
    const profiles = [
      { id: "p1", serviceId: "embedding", name: "百炼", provider: "aliyun", fields: {}, status: "草稿" as const },
      { id: "p2", serviceId: "embedding", name: "其他供应商", provider: "openai", fields: {}, status: "草稿" as const },
    ];
    render(<OmsModelCreate serviceId="embedding" profiles={profiles} models={[]} onSave={save} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("textbox", { name: "模型名称" }), { target: { value: "向量模型" } });
    fireEvent.change(screen.getByRole("textbox", { name: "模型标识" }), { target: { value: "qwen3-vl-embedding" } });
    fireEvent.change(screen.getByRole("combobox", { name: "向量维度" }), { target: { value: "1536" } });
    fireEvent.change(screen.getByRole("combobox", { name: "所属 Profile" }), { target: { value: "p2" } });
    expect(screen.getByRole("spinbutton", { name: "向量维度" })).toHaveValue(null);
    fireEvent.change(screen.getByRole("textbox", { name: "模型标识" }), { target: { value: "text-embedding-custom" } });
    fireEvent.click(screen.getByRole("button", { name: "保存模型草稿" }));
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ fields: expect.not.objectContaining({ dimension: 1536 }) }));
  });

  it("Profile 高级请求头按结构化字段保存，详情只显示数量而不暴露内容", () => {
    path = "/oms/prototype/services/llm/provider";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增 Provider profile" }));
    const form = screen.getByRole("dialog", { name: "新增 Provider profile" });
    fireEvent.change(within(form).getByRole("textbox", { name: "配置名称" }), { target: { value: "结构化 Profile" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "供应商" }), { target: { value: "dashscope" } });
    fireEvent.click(within(form).getByText("高级请求选项"));
    fireEvent.change(within(form).getByRole("textbox", { name: "额外请求头（JSON）" }), { target: { value: '{"X-Trace":"trace-42"}' } });
    fireEvent.click(within(form).getByRole("button", { name: "保存演示草稿" }));
    fireEvent.click(within(screen.getByText("结构化 Profile").closest("tr")!).getByRole("button", { name: "查看详情" }));
    expect(screen.getByText("1 个普通请求头")).toBeInTheDocument();
    expect(screen.queryByText("trace-42")).not.toBeInTheDocument();
  });

  it("已知模型候选可退回手动 ID，且无效数值不得保存", () => {
    const save = vi.fn();
    const profiles = [{ id: "p1", serviceId: "llm", name: "百炼", provider: "dashscope", fields: {}, status: "草稿" as const }];
    render(<OmsModelCreate serviceId="llm" profiles={profiles} models={[]} onSave={save} onCancel={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: "手动填写模型标识" }));
    expect(screen.getByRole("textbox", { name: "模型标识" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "模型名称" }), { target: { value: "自定义模型" } });
    fireEvent.change(screen.getByRole("textbox", { name: "模型标识" }), { target: { value: "qwen-custom" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "上下文窗口" }), { target: { value: "-1" } });
    fireEvent.click(screen.getByRole("button", { name: "保存模型草稿" }));
    expect(save).not.toHaveBeenCalled();
    expect(screen.getByText("上下文窗口须为正整数。")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("spinbutton", { name: "上下文窗口" }), { target: { value: "32768" } });
    fireEvent.click(screen.getByRole("button", { name: "保存模型草稿" }));
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ model: "qwen-custom", fields: expect.objectContaining({ context_window: 32768 }) }));
  });

  it("搜索配置必须明确选用 Profile，不生成虚构模型；任务模型未选时清楚走对话回退", () => {
    const save = vi.fn();
    const profiles = [{ id: "search-p", serviceId: "search", name: "SearXNG", provider: "searxng", fields: {}, status: "草稿" as const }];
    const view = render(<ServiceConfigForm serviceId="search" profiles={profiles} onSave={save} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("textbox", { name: "搜索配置名称" }), { target: { value: "校内搜索" } });
    fireEvent.click(screen.getByRole("button", { name: "保存演示草稿" }));
    expect(save).not.toHaveBeenCalled();
    expect(screen.getByText(/请先选用搜索 Profile/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "选用模型" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "选用搜索 Profile" }), { target: { value: "search-p" } });
    fireEvent.click(screen.getByRole("button", { name: "保存演示草稿" }));
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ active_profile_id: "search-p" }));
    view.unmount();
    const taskSave = vi.fn();
    render(<ServiceConfigForm serviceId="task" onSave={taskSave} onCancel={vi.fn()}/>);
    fireEvent.change(screen.getByRole("textbox", { name: "配置名称" }), { target: { value: "任务回退" } });
    fireEvent.click(screen.getByRole("button", { name: "保存演示草稿" }));
    expect(taskSave).toHaveBeenCalledWith(expect.objectContaining({ active_profile_id: "", active_model_id: "" }));
  });
});
