"use client";

import { useState } from "react";
import { Button, Notice } from "@deeptutor/admin-ui";
import type { ModelDraft, ProfileDraft } from "./OmsModelCreate";
import { connectionService, providerOption, providerOptions } from "./providerDescriptors";

const modelServices = new Set(["llm", "task", "embedding", "tts", "stt", "imagegen", "videogen"]);
type ConnectionOption = { id: string; name: string; provider: string; serviceIds: string[] };
type Option = { value: string; label: string };

export default function ServiceConfigForm({ serviceId, initialValues, onSave, onCancel, requireProvider = false, existingNames = [], connections = [], profiles = [], models = [] }: {
  serviceId: string;
  initialValues?: Record<string, string>;
  onSave: (values: Record<string, string>) => void;
  onCancel: () => void;
  requireProvider?: boolean;
  existingNames?: string[];
  connections?: ConnectionOption[];
  profiles?: ProfileDraft[];
  models?: ModelDraft[];
}) {
  const [values, setValues] = useState<Record<string, string>>({
    name: "", provider: "", credential_source: "own", connection_id: "", base_url: "", api_base_url: "", api_version: "", extra_headers: "", proxy: "", api_format: "",
    active_profile_id: "", active_model_id: "", engine: "text_only", mode: "local", model_version: "pipeline", language: "auto", is_ocr: "false", enable_table: "false", enable_formula: "false", do_ocr: "false", do_table_structure: "true", allow_local_model_download: "false", image_mode: "placeholder", write_images: "false", image_format: "png", image_dpi: "150", extract_links: "true", extract_images: "false", max_pages: "0", video_source: "youtube", transcript_provider: "youtube_transcript_api", ...initialValues,
  });
  const [error, setError] = useState("");
  const update = (name: string, value: string) => { setValues(current => ({ ...current, [name]: value })); setError(""); };
  const field = (name: string, label: string, hint = "", type = "text", min?: number, max?: number) => <label key={name} className="form-field">{label}<input name={name} type={type} min={min} max={max} value={values[name] ?? ""} onChange={event => update(name, event.target.value)} placeholder={hint}/></label>;
  const select = (name: string, label: string, options: Option[], onSelect?: (value: string) => void) => <label key={name} className="form-field">{label}<select value={values[name] ?? ""} onChange={event => onSelect ? onSelect(event.target.value) : update(name, event.target.value)}>{options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>;
  const check = (name: string, label: string) => <label key={name} className="form-field form-check"><input type="checkbox" checked={values[name] === "true"} onChange={event => update(name, String(event.target.checked))}/>{label}</label>;
  const compatibleConnections = connections.filter(row => row.serviceIds.includes(serviceId) && Boolean(connectionService(row.provider, serviceId)));
  const option = providerOption(serviceId, values.provider);
  const isOAuth = option?.auth_mode === "oauth";
  const isParsing = serviceId === "ocr" || serviceId === "rag";
  const serviceProfiles = profiles.filter(row => row.serviceId === serviceId);
  const serviceModels = models.filter(row => row.serviceId === serviceId && row.profileId === values.active_profile_id);
  const selectProvider = (next: string) => {
    const previous = providerOption(serviceId, values.provider);
    const selected = providerOption(serviceId, next);
    setValues(current => ({ ...current, provider: next, api_format: selected?.default_api_format ?? "", credential_source: selected?.auth_mode === "oauth" ? "own" : current.credential_source, connection_id: selected?.auth_mode === "oauth" ? "" : current.connection_id, api_version: selected?.auth_mode === "oauth" ? "" : current.api_version, extra_headers: selected?.auth_mode === "oauth" ? "" : current.extra_headers, base_url: selected?.auth_mode === "oauth" ? "" : !current.base_url || current.base_url === (previous?.base_url ?? "") ? selected?.base_url ?? "" : current.base_url }));
    setError("");
  };
  const selectFormat = (next: string) => {
    const previousDefault = option?.base_urls?.[values.api_format] ?? option?.base_url ?? "";
    const nextDefault = option?.base_urls?.[next] ?? option?.base_url ?? "";
    setValues(current => ({ ...current, api_format: next, base_url: !current.base_url || current.base_url === previousDefault ? nextDefault : current.base_url }));
    setError("");
  };
  const save = () => {
    if (!values.name.trim()) { setError("请先填写配置名称。"); return; }
    if (requireProvider && existingNames.includes(values.name.trim())) { setError("本服务已存在同名 Profile。"); return; }
    if (requireProvider && values.credential_source === "connection" && !compatibleConnections.some(row => row.id === values.connection_id && connectionService(row.provider, serviceId)?.provider === values.provider)) { setError("请选择本服务适用的供应商连接。"); return; }
    if (requireProvider && !providerOption(serviceId, values.provider)) { setError("请从当前服务的供应商候选中选择。"); return; }
    if (requireProvider && isOAuth && (values.credential_source === "connection" || values.base_url || values.extra_headers)) { setError("OAuth Profile 不能配置 API Key、连接地址或额外请求头。"); return; }
    if (requireProvider && serviceId === "search" && option?.requires_base_url && !values.base_url.trim()) { setError("该搜索供应商需要服务地址。"); return; }
    if (requireProvider && serviceId !== "search" && values.extra_headers.trim()) {
      try {
        const headers: unknown = JSON.parse(values.extra_headers);
        if (!headers || typeof headers !== "object" || Array.isArray(headers) || Object.entries(headers).some(([key, value]) => !key.trim() || typeof value !== "string")) throw new Error("invalid headers");
        if (Object.keys(headers).some(key => /^(authorization|cookie|x-api-key|api-key)$/i.test(key))) { setError("演示草稿不可保存认证请求头；请使用受控凭据操作。"); return; }
      } catch { setError("额外请求头须为 JSON 对象。"); return; }
    }
    if (!requireProvider && modelServices.has(serviceId) && serviceId !== "task" && (!values.active_profile_id || !values.active_model_id || !serviceModels.some(row => row.id === values.active_model_id))) { setError("请先选用本服务的 Profile 和模型；草稿仍不会生效。"); return; }
    if (!requireProvider && serviceId === "search" && !serviceProfiles.some(row => row.id === values.active_profile_id)) { setError("请先选用搜索 Profile；草稿仍不会生效。"); return; }
    if (!requireProvider && serviceId === "task" && values.active_profile_id && !serviceModels.some(row => row.id === values.active_model_id)) { setError("已选任务 Profile 时请选择对应模型，或清空 Profile 走对话模型回退。"); return; }
    if (values.engine === "pymupdf4llm" && values.write_images === "true" && (!Number.isSafeInteger(Number(values.image_dpi)) || Number(values.image_dpi) < 72 || Number(values.image_dpi) > 600)) { setError("图片分辨率须为 72–600 的整数。"); return; }
    if (values.engine === "liteparse" && (!Number.isSafeInteger(Number(values.max_pages)) || Number(values.max_pages) < 0)) { setError("最大页数须为非负整数。"); return; }
    onSave({ ...values, name: values.name.trim() });
  };

  return <div className="side-panel"><h3>{requireProvider ? "供应商配置草稿" : "服务配置草稿"} · 本地演示</h3>
    <Notice tone="warn">供应商候选来自基座设置 descriptor 离线快照；模型发现、检测与执行者状态不在此原型实时调用。保存不会发布或改变运行态。</Notice>
    {isParsing ? <>
      <div className="form-grid">{field("name", "解析配置名称")}{select("engine", "解析引擎", [
        { value: "text_only", label: "纯文本" }, { value: "mineru", label: "MinerU" }, { value: "docling", label: "Docling" }, { value: "markitdown", label: "MarkItDown" }, { value: "pymupdf4llm", label: "PyMuPDF4LLM" }, { value: "liteparse", label: "LiteParse" }, { value: "tika", label: "Tika" },
      ], next => setValues(current => ({ ...current, engine: next, mode: current.engine === next ? current.mode : "local" })))}</div>
      {values.engine === "text_only" && <Notice>纯文本引擎不支持 OCR、表格结构或远端解析设置。</Notice>}
      {values.engine === "mineru" && <><h4 className="form-subhead">MinerU 选项</h4><div className="form-grid">
        {select("mode", "运行方式", [{ value: "local", label: "本地 CLI" }, { value: "cloud", label: "云端 API" }])}
        {values.mode === "cloud" ? field("api_base_url", "云端 API 地址") : field("local_cli_path", "本地 CLI 路径", "留空自动检测")}
        {select("model_version", "解析模型", [{ value: "pipeline", label: "Pipeline" }, { value: "vlm", label: "VLM" }])}
        {field("language", "文档语言", "auto")}{check("is_ocr", "OCR 识别")}{check("enable_table", "表格提取")}{check("enable_formula", "公式提取")}
      </div><Notice>云端 Token 仅通过受控 Secret 关联；本地模型下载不会由草稿自动触发。</Notice></>}
      {values.engine === "docling" && <><h4 className="form-subhead">Docling 选项</h4><div className="form-grid">
        {select("mode", "运行方式", [{ value: "local", label: "本地解析" }, { value: "remote", label: "远端 Docling Serve" }])}
        {values.mode === "remote" && field("api_base_url", "服务地址")}
        {check("do_ocr", "OCR 识别")}{check("do_table_structure", "表格结构识别")}
        {values.mode === "local" && check("allow_local_model_download", "允许自动下载模型")}
      </div><Notice>远端 API Key 仅通过受控 Secret 引用关联；草稿不会自动安装组件或下载模型。</Notice></>}
      {values.engine === "tika" && <div className="form-grid">{field("api_base_url", "Tika 服务地址")}</div>}
      {values.engine === "pymupdf4llm" && <div className="form-grid">{check("write_images", "提取图片")}{values.write_images === "true" && <>{select("image_format", "图片格式", ["png", "jpg", "jpeg", "webp"].map(value => ({ value, label: value })))}{field("image_dpi", "图片分辨率（DPI）", "72–600", "number", 72, 600)}</>}</div>}
      {values.engine === "liteparse" && <div className="form-grid">{select("image_mode", "图片输出方式", ["placeholder", "off", "embed"].map(value => ({ value, label: value })))}{check("extract_links", "提取链接")}{check("extract_images", "提取图片")}{field("max_pages", "最大页数", "0 表示不限", "number", 0)}</div>}
      <Notice>引擎 ID 与基座当前设置一致；实际 available_engines/readiness 由后端返回，未确认前不展示可用。</Notice>
    </> : serviceId === "video-learning" ? <div className="form-grid">{field("name", "接入配置名称")}{select("video_source", "视频来源", [{ value: "youtube", label: "YouTube" }, { value: "invidious", label: "Invidious" }])}{values.video_source === "invidious" ? <>{field("api_base_url", "Invidious API 地址")}{field("public_base_url", "Invidious 公共地址")}</> : select("transcript_provider", "字幕来源", [{ value: "youtube_transcript_api", label: "youtube-transcript-api" }, { value: "none", label: "不使用字幕服务" }])}</div> : requireProvider ? <div className="form-grid">
      {field("name", serviceId === "search" ? "搜索配置名称" : "配置名称")}
      {serviceId !== "search" && !isOAuth && compatibleConnections.length > 0 && select("credential_source", "凭据来源", [{ value: "own", label: "Profile 自有凭据" }, { value: "connection", label: "供应商连接" }], source => {
        const selected = source === "connection" ? compatibleConnections[0] : undefined;
        setValues(current => ({ ...current, credential_source: source, connection_id: selected?.id ?? "", provider: selected ? connectionService(selected.provider, serviceId)?.provider ?? "" : current.provider }));
      })}
      {serviceId !== "search" && !isOAuth && compatibleConnections.length === 0 && <Notice>当前服务尚无可绑定的连接；请使用 Profile 自有凭据，或先创建兼容连接。</Notice>}
      {values.credential_source === "connection" && serviceId !== "search" ? <>
        {select("connection_id", "供应商连接", [{ value: "", label: "请选择" }, ...compatibleConnections.map(row => ({ value: row.id, label: `${row.name} · ${row.provider}` }))], id => {
          const row = compatibleConnections.find(item => item.id === id);
          setValues(current => ({ ...current, connection_id: id, provider: row ? connectionService(row.provider, serviceId)?.provider ?? "" : "" }));
        })}
        <label className="form-field">供应商<input value={values.provider} readOnly/></label>
      </> : select("provider", "供应商", [{ value: "", label: "请选择供应商" }, ...providerOptions(serviceId).map(item => ({ value: item.value, label: item.label }))], selectProvider)}
      {values.credential_source !== "connection" && serviceId !== "search" && !isOAuth && field("base_url", "服务地址", option?.base_url ?? "留空使用供应商默认端点")}
      {serviceId === "search" && option?.requires_base_url && <label className="form-field">服务地址<input name="base_url" required value={values.base_url} onChange={event => update("base_url", event.target.value)} placeholder={option.base_url ?? ""}/></label>}
      {values.provider && (option?.api_formats?.length ?? 0) > 1 && select("api_format", "API 格式", (option?.api_formats ?? []).map(value => ({ value, label: value })), selectFormat)}
      {serviceId === "search" && values.provider && <><Notice>{option?.requires_api_key ? "该供应商需单独配置凭据。" : "该供应商不要求 API Key。"}</Notice><details><summary>高级网络选项</summary>{field("api_version", "API 版本")}{field("proxy", "代理地址")}</details></>}
      {serviceId !== "search" && !isOAuth && <details><summary>高级请求选项</summary>{field("api_version", "API 版本")}<label className="form-field">额外请求头（JSON）<textarea value={values.extra_headers ?? ""} onChange={event => update("extra_headers", event.target.value)} placeholder='{"X-Trace":"demo"}'/></label><Notice>只填写普通请求头；认证信息请在凭据操作中维护，勿写入演示草稿。</Notice></details>}
      {isOAuth && <Notice tone="warn">OAuth 授权流程待接入；此原型不提供 API Key、连接地址或令牌模拟录入。</Notice>}
    </div> : serviceId === "search" ? <div className="form-grid">{field("name", "搜索配置名称")}{select("active_profile_id", "选用搜索 Profile", [{ value: "", label: "请选择 Profile" }, ...serviceProfiles.map(row => ({ value: row.id, label: `${row.name} · ${row.provider}` }))])}{!serviceProfiles.length && <Notice tone="warn">请先新增搜索 Provider Profile；当前保存仅是未生效草稿。</Notice>}</div> : modelServices.has(serviceId) ? <div className="form-grid">
      {field("name", "配置名称")}
      {select("active_profile_id", "选用 Profile", [{ value: "", label: "请选择 Profile" }, ...serviceProfiles.map(row => ({ value: row.id, label: `${row.name} · ${row.provider}` }))], id => setValues(current => ({ ...current, active_profile_id: id, active_model_id: "" })))}
      {select("active_model_id", "选用模型", [{ value: "", label: "请选择模型" }, ...serviceModels.map(row => ({ value: row.id, label: `${row.name} · ${row.model}` }))])}
      {serviceId === "task" && <Notice>任务模型未单独选用时，基座回退对话模型；此处不会复制对话模型配置。</Notice>}
      {!serviceProfiles.length && <Notice tone="warn">请先在本服务的 Provider 配置中新增 Profile，再新增模型。</Notice>}
    </div> : <div className="form-grid">{field("name", "配置名称")}</div>}
    {requireProvider && <Notice>绑定连接的 Profile 不重复维护 API Key；自有凭据在 Profile 详情单独配置。联网搜索始终使用独立 Profile。</Notice>}
    {error && <Notice tone="bad">{error}</Notice>}
    <div className="form-actions"><Button variant="primary" onClick={save}>保存演示草稿</Button><Button onClick={onCancel}>取消</Button></div>
  </div>;
}
