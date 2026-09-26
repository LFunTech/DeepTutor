"use client";

import { useState } from "react";
import { Button, Notice } from "@deeptutor/admin-ui";

const modelServices = new Set(["llm", "task", "embedding", "tts", "stt", "imagegen", "videogen"]);

function Field({ label, name, value, onChange, hint, type = "text" }: { label: string; name: string; value: string; onChange: (name: string, value: string) => void; hint?: string; type?: string }) {
  return <label className="form-field">{label}<input name={name} type={type} value={value} onChange={e => onChange(name, e.target.value)} placeholder={hint || "按供应商描述填写"}/></label>;
}

export default function ServiceConfigForm({ serviceId, initialValues, onSave, onCancel, requireProvider = false, existingNames = [] }: { serviceId: string; initialValues?: Record<string, string>; onSave: (values: Record<string, string>) => void; onCancel: () => void; requireProvider?: boolean; existingNames?: string[] }) {
  const [values, setValues] = useState<Record<string, string>>({ name: "", model: "", provider: "", base_url: "", api_base_url: "", api_version: "", proxy: "", dimension: "", send_dimensions: "true", voice: "", response_format: "mp3", size: "", quality: "", style: "", aspect_ratio: "", duration: "", resolution: "", context_window: "", engine: "text_only", mode: "local", model_version: "pipeline", is_ocr: "false", enable_table: "false", do_ocr: "false", do_table_structure: "true", allow_local_model_download: "false", image_mode: "placeholder", video_source: "youtube", transcript_provider: "youtube_transcript_api", ...initialValues });
  const [error, setError] = useState("");
  const update = (name: string, value: string) => { setValues(current => ({ ...current, [name]: value })); setError(""); };
  const field = (name: string, label: string, hint?: string) => <Field key={name} name={name} label={label} value={values[name] ?? ""} onChange={update} hint={hint}/>;
  const select = (name: string, label: string, options: { value: string; label: string }[]) => <label className="form-field" key={name}>{label}<select value={values[name] ?? options[0]?.value} onChange={event => update(name, event.target.value)}>{options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>;
  const bool = (name: string, label: string) => select(name, label, [{ value: "false", label: "不启用" }, { value: "true", label: "启用" }]);
  const isParsing = serviceId === "ocr" || serviceId === "rag";
  const isVideoLearning = serviceId === "video-learning";
  return <div className="side-panel"><h3>服务配置草稿 · 本地演示</h3>
    <Notice tone="warn">字段遵循 DeepTutor 现有设置语义；真实候选、必填与条件显隐以服务端 descriptor 为准。保存不会发布或改变运行态。</Notice>
    {isParsing ? <>
      <div className="form-grid">{field("name", "解析配置名称")}{select("engine", "解析引擎", [
        { value: "text_only", label: "纯文本" }, { value: "mineru", label: "MinerU" }, { value: "docling", label: "Docling" },
        { value: "markitdown", label: "MarkItDown" }, { value: "pymupdf4llm", label: "PyMuPDF4LLM" }, { value: "liteparse", label: "LiteParse" }, { value: "tika", label: "Tika" },
      ])}</div>
      {values.engine === "text_only" && <Notice>纯文本引擎不支持 OCR、表格结构或远端解析设置。</Notice>}
      {values.engine === "mineru" && <><h4 className="form-subhead">MinerU 选项</h4><div className="form-grid">
        {select("mode", "运行方式", [{ value: "local", label: "本地 CLI" }, { value: "cloud", label: "云端 API" }])}
        {values.mode === "cloud" ? field("api_base_url", "云端 API 地址") : field("local_cli_path", "本地 CLI 路径", "留空自动检测")}
        {select("model_version", "解析模型", [{ value: "pipeline", label: "Pipeline" }, { value: "vlm", label: "VLM" }])}
        {field("language", "文档语言", "auto")}{bool("is_ocr", "OCR 识别")}{bool("enable_table", "表格提取")}{bool("enable_formula", "公式提取")}
      </div><Notice>云端 Token 仅通过受控 Secret 关联；本地模型下载不会由草稿自动触发。</Notice></>}
      {values.engine === "docling" && <><h4 className="form-subhead">Docling 选项</h4><div className="form-grid">
        {select("mode", "运行方式", [{ value: "local", label: "本地解析" }, { value: "remote", label: "远端 Docling Serve" }])}
        {values.mode === "remote" && field("api_base_url", "服务地址")}
        {bool("do_ocr", "OCR 识别")}{bool("do_table_structure", "表格结构识别")}
        {values.mode === "local" && bool("allow_local_model_download", "允许自动下载模型")}
      </div><Notice>远端 API Key 仅通过受控 Secret 引用关联；草稿不会自动安装组件或下载模型。</Notice></>}
      {values.engine === "tika" && <div className="form-grid">{field("api_base_url", "Tika 服务地址")}</div>}
      {values.engine === "liteparse" && <div className="form-grid">{select("image_mode", "图片输出方式", [{ value: "placeholder", label: "占位" }, { value: "off", label: "关闭" }, { value: "embed", label: "嵌入" }])}</div>}
      {["markitdown", "pymupdf4llm"].includes(values.engine) && <Notice>当前引擎没有通用 OCR 开关；附加选项以执行者返回的能力为准。</Notice>}
      <Notice>引擎 ID 与 DeepTutor 当前设置一致；实际 available_engines/readiness 由后端返回。</Notice>
    </> : isVideoLearning ? <><div className="form-grid">{field("name", "接入配置名称")}{select("video_source", "视频来源", [{ value: "youtube", label: "YouTube" }, { value: "invidious", label: "Invidious" }])}{values.video_source === "invidious" ? <>{field("api_base_url", "Invidious API 地址")}{field("public_base_url", "Invidious 公共地址")}</> : select("transcript_provider", "字幕来源", [{ value: "youtube_transcript_api", label: "youtube-transcript-api" }, { value: "none", label: "不使用字幕服务" }])}</div><Notice>视频学习接入与视频生成模型不同，不默认有 Token 计量。</Notice></> : <>
      <div className="form-grid">{field("name", serviceId === "search" ? "搜索配置名称" : "配置名称")}{field("provider", "供应商标识", "由后端 descriptor 给出候选")}
        {modelServices.has(serviceId) && field("model", "模型标识")}
        {serviceId === "llm" && field("context_window", "上下文窗口", "按供应商窗口检测结果")}
        {serviceId === "embedding" && <>{field("dimension", "向量维度", "按供应商能力")}{select("send_dimensions", "是否发送维度参数", [{ value: "true", label: "发送" }, { value: "false", label: "不发送" }])}</>}
        {serviceId === "tts" && <>{field("voice", "音色", "供应商相关自由文本")}<label className="form-field">音频格式<select value={values.response_format} onChange={e => update("response_format", e.target.value)}>{["mp3", "wav", "opus", "aac", "flac", "pcm"].map(option => <option key={option}>{option}</option>)}</select></label></>}
        {serviceId === "imagegen" && <>{field("size", "尺寸", "留空使用供应商默认")}{field("quality", "质量", "留空使用供应商默认")}{field("style", "风格", "留空使用供应商默认")}</>}
        {serviceId === "videogen" && <>{field("aspect_ratio", "宽高比")}{field("duration", "时长")}{field("resolution", "分辨率")}</>}
        {serviceId === "search" && <>{field("base_url", "服务地址", "按供应商条件显示")}{field("api_version", "API 版本", "按供应商条件显示")}{field("proxy", "代理地址", "按供应商条件显示")}</>}
      </div><details style={{ marginTop: 15 }}><summary className="detail-link">连接与高级条件字段</summary><p className="muted" style={{ fontSize: 11 }}>连接可绑定 provider、name、base_url 与受控凭据引用；api_version、extra_headers、LLM/task API 格式、search proxy/API Key 等只在 descriptor 条件满足时显示。关联连接的凭据不得在 profile 中重复编辑。</p><p className="muted" style={{ fontSize: 11 }}>任务模型未配置时回退对话模型；联网搜索不设模型列表；语音识别当前没有 language 控件。</p></details>
    </>}
    {error && <Notice tone="bad">{error}</Notice>}
    <div className="form-actions"><Button variant="primary" onClick={() => { if (!values.name.trim()) { setError("请先填写配置名称。"); return; } if (existingNames.includes(values.name.trim())) { setError("本服务已存在同名 Profile。"); return; } if (requireProvider && !values.provider.trim()) { setError("请填写供应商标识。"); return; } onSave({ ...values, name: values.name.trim() }); }}>保存演示草稿</Button><Button onClick={onCancel}>取消</Button></div>
  </div>;
}
