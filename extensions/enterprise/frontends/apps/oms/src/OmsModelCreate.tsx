"use client";

import { useState } from "react";
import { Button, Notice } from "@deeptutor/admin-ui";
import { demoEmbeddingDimensions, demoModelCandidates, demoReasoningOptions, providerOption } from "./providerDescriptors";

export type ProfileDraft = {
  id: string; serviceId: string; name: string; provider: string; status: "草稿";
  fields: {
    credential_source?: "own" | "connection";
    connection_id?: string;
    base_url?: string;
    api_format?: string;
    api_version?: string;
    proxy?: string;
    extra_headers?: Record<string, string>;
  };
};
export type ModelDraft = {
  id: string; serviceId: string; profileId: string; name: string; model: string; detail: string; status: "草稿";
  fields: {
    context_window?: number;
    reasoning_effort?: string;
    dimension?: number;
    send_dimensions?: boolean;
    voice?: string;
    response_format?: string;
    size?: string;
    quality?: string;
    style?: string;
    aspect_ratio?: string;
    duration?: string;
    resolution?: string;
    capabilities?: Partial<Record<"tools" | "vision" | "json_output" | "reasoning", boolean>>;
  };
};

const capabilityLabels: Record<string, string> = { tools: "工具调用能力", vision: "图像输入能力", json_output: "JSON 输出能力", reasoning: "推理控制能力" };
const audioFormats = ["mp3", "wav", "opus", "aac", "flac", "pcm"];
const emptyModelFields = { context_window: "", reasoning_effort: "", dimension: "", send_dimensions: "true", voice: "", response_format: "mp3", size: "", quality: "", style: "", aspect_ratio: "", duration: "", resolution: "", tools: "auto", vision: "auto", json_output: "auto", reasoning: "auto" };

export default function OmsModelCreate({ serviceId, profiles, models, onSave, onCancel }: {
  serviceId: string; profiles: ProfileDraft[]; models: ModelDraft[]; onSave: (row: ModelDraft) => void; onCancel: () => void;
}) {
  const [profileId, setProfileId] = useState(profiles[0]?.id ?? "");
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [manual, setManual] = useState(false);
  const [candidateState, setCandidateState] = useState<"sample" | "empty" | "error">("sample");
  const [fields, setFields] = useState<Record<string, string>>({ ...emptyModelFields });
  const [customDimension, setCustomDimension] = useState(false);
  const [error, setError] = useState("");
  const profile = profiles.find(row => row.id === profileId);
  const provider = profile?.provider ?? "";
  const candidates = candidateState === "sample" ? demoModelCandidates(serviceId, provider) : [];
  const dimensions = demoEmbeddingDimensions(provider, model);
  const modelOption = providerOption(serviceId, provider);
  const reasoningOptions = serviceId === "llm" && modelOption?.auth_mode !== "oauth" ? demoReasoningOptions(provider, model, fields.reasoning) : [];
  const update = (key: string, value: string) => { setFields(current => ({ ...current, [key]: value })); setError(""); };
  const changeModel = (value: string) => { setModel(value); setCustomDimension(false); setFields(current => ({ ...current, dimension: "", reasoning_effort: "" })); setError(""); };
  const textField = (key: string, label: string, placeholder = "", type = "text") => <label className="form-field" key={key}>{label}<input type={type} value={fields[key] ?? ""} onChange={event => update(key, event.target.value)} placeholder={placeholder}/></label>;
  const selectField = (key: string, label: string, options: { value: string; label: string }[]) => <label className="form-field" key={key}>{label}<select value={fields[key] ?? ""} onChange={event => update(key, event.target.value)}>{options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>;
  const save = () => {
    if (!profile) { setError("请先创建本服务的 Provider Profile。"); return; }
    if (name.trim().length < 2 || !model.trim()) { setError("请填写模型名称与模型标识。"); return; }
    if (candidates.length && !manual && !candidates.includes(model)) { setError("请选择候选模型或切换到手动填写。"); return; }
    if (models.some(row => row.serviceId === serviceId && row.profileId === profileId && row.model === model.trim())) { setError("该 Profile 下已存在相同模型标识。"); return; }
    for (const key of ["context_window", "dimension"]) {
      const value = fields[key]?.trim();
      if (value && (!Number.isSafeInteger(Number(value)) || Number(value) <= 0)) { setError(`${key === "dimension" ? "向量维度" : "上下文窗口"}须为正整数。`); return; }
    }
    const detail = serviceId === "llm" ? fields.context_window : serviceId === "embedding" ? fields.dimension : serviceId === "tts" ? fields.voice : serviceId === "imagegen" ? fields.size : serviceId === "videogen" ? fields.aspect_ratio : "";
    const config: ModelDraft["fields"] = {};
    if (serviceId === "llm") {
      if (fields.context_window) config.context_window = Number(fields.context_window);
      if (fields.reasoning_effort && reasoningOptions.some(option => option.value === fields.reasoning_effort)) config.reasoning_effort = fields.reasoning_effort;
    }
    if (serviceId === "llm" || serviceId === "task") {
      const declared = Object.keys(capabilityLabels).filter(key => fields[key] !== "auto");
      if (declared.length) config.capabilities = Object.fromEntries(declared.map(key => [key, fields[key] === "yes"]));
    }
    if (serviceId === "embedding") {
      if (fields.dimension) config.dimension = Number(fields.dimension);
      config.send_dimensions = fields.send_dimensions === "true";
    }
    if (serviceId === "tts") { if (fields.voice) config.voice = fields.voice; config.response_format = fields.response_format; }
    if (serviceId === "imagegen") for (const key of ["size", "quality", "style"] as const) { if (fields[key]) config[key] = fields[key]; }
    if (serviceId === "videogen") for (const key of ["aspect_ratio", "duration", "resolution"] as const) { if (fields[key]) config[key] = fields[key]; }
    return { serviceId, profileId, name: name.trim(), model: model.trim(), detail: detail ?? "", fields: config, status: "草稿" as const };
  };
  return <div className="side-panel">
    <Notice tone="warn">模型归属本服务 Profile。模型列表仅演示基座已知示例，非实时供应商发现；草稿未发布，不可调用。</Notice>
    <div className="form-grid">
      <label className="form-field">所属 Profile<select value={profileId} onChange={event => { setProfileId(event.target.value); setModel(""); setManual(false); setCustomDimension(false); setFields({ ...emptyModelFields }); setError(""); }}><option value="">请选择</option>{profiles.map(row => <option key={row.id} value={row.id}>{row.name} · {row.provider}</option>)}</select></label>
      <label className="form-field">模型名称<input value={name} onChange={event => setName(event.target.value)}/></label>
      {(serviceId === "llm" || serviceId === "task") && <details><summary>演示不同候选结果</summary><label className="form-field">候选状态演示<select value={candidateState} onChange={event => { setCandidateState(event.target.value as "sample" | "empty" | "error"); changeModel(""); setManual(false); }}><option value="sample">离线样例</option><option value="empty">无候选</option><option value="error">获取失败（演示）</option></select></label><Notice>仅供审计表单状态；不会向供应商发送请求。</Notice></details>}
      {(serviceId === "llm" || serviceId === "task") && candidates.length > 0 && !manual ? <>
        <label className="form-field">模型候选<select value={model} onChange={event => changeModel(event.target.value)}><option value="">请选择模型</option>{candidates.map(id => <option key={id} value={id}>{id}</option>)}</select></label>
        <Button onClick={() => { setManual(true); changeModel(""); }}>手动填写模型标识</Button>
      </> : <>
        <label className="form-field">模型标识<input value={model} onChange={event => changeModel(event.target.value)} placeholder={modelOption?.label ? `按 ${modelOption.label} 支持的模型填写` : "供应商模型 ID"}/></label>
        {(serviceId === "llm" || serviceId === "task") && <Notice>{candidateState === "error" ? "模型候选获取失败（演示）；原型没有发起真实请求，请手动填写模型 ID。" : manual ? "已切换手动输入；保存前请核对供应商模型 ID。" : "当前无可信模型候选；原型不调用真实供应商，请手动填写模型 ID。"}</Notice>}
        {manual && candidates.length > 0 && <Button onClick={() => { setManual(false); changeModel(""); }}>返回候选列表</Button>}
      </>}
      {serviceId === "llm" && <>{textField("context_window", "上下文窗口", "可留空，待执行者检测", "number")}{reasoningOptions.length > 0 && selectField("reasoning_effort", "推理档位", reasoningOptions)}</>}
      {(serviceId === "llm" || serviceId === "task") && Object.entries(capabilityLabels).map(([key, label]) => selectField(key, label, [{ value: "auto", label: "自动（由基座判定）" }, { value: "yes", label: "支持" }, { value: "no", label: "不支持" }]))}
      {serviceId === "embedding" && <>
        {dimensions.length > 1 && !customDimension ? <label className="form-field">向量维度<select value={fields.dimension} onChange={event => { if (event.target.value === "custom") { setCustomDimension(true); update("dimension", ""); } else update("dimension", event.target.value); }}><option value="">自动（待检测）</option>{dimensions.map(value => <option key={value} value={String(value)}>{value}</option>)}<option value="custom">自定义…</option></select></label> : textField("dimension", "向量维度", "正整数（可留空）", "number")}
        {customDimension && <Button onClick={() => { setCustomDimension(false); update("dimension", ""); }}>使用支持的维度</Button>}
        <label className="form-field form-check"><input type="checkbox" checked={fields.send_dimensions === "true"} onChange={event => update("send_dimensions", String(event.target.checked))}/>发送维度参数</label>
      </>}
      {serviceId === "tts" && <>{textField("voice", "音色", "供应商相关自由文本")}{selectField("response_format", "音频格式", audioFormats.map(value => ({ value, label: value })))}</>}
      {serviceId === "imagegen" && <>{textField("size", "尺寸")}{textField("quality", "质量")}{textField("style", "风格")}</>}
      {serviceId === "videogen" && <>{textField("aspect_ratio", "宽高比")}{textField("duration", "时长")}{textField("resolution", "分辨率")}</>}
    </div>
    {serviceId === "task" && <Notice>不单独选用任务模型时，基座回退对话模型。</Notice>}
    {error && <Notice tone="bad">{error}</Notice>}
    <div className="form-actions"><Button variant="primary" onClick={() => { const draft = save(); if (draft) onSave({ id: `model-${Date.now()}`, ...draft }); }}>保存模型草稿</Button><Button onClick={onCancel}>取消</Button></div>
  </div>;
}
