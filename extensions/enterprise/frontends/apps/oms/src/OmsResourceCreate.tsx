"use client";

import { useState } from "react";
import { Button, Notice } from "@deeptutor/admin-ui";

export type ResourceKind = "services" | "agents" | "tools" | "knowledge" | "runtime";
export type ResourceDraft = { id: string; name: string; type: string; status: string; dependency: string; detail: string; unit?: string };
const choices: Record<Exclude<ResourceKind, "services">, { type: string; field: string; hint: string }[]> = {
  agents: [{ type: "外部 Agent 接入", field: "外部端点", hint: "HTTPS 端点；草稿不会发起连接" }, { type: "共享 Agent 模板", field: "依赖服务", hint: "例如：对话模型" }, { type: "角色模板", field: "可用范围", hint: "例如：获授权学校" }],
  tools: [{ type: "MCP 接入", field: "接入地址", hint: "HTTPS 地址；不会自动安装" }, { type: "CLI 工具接入", field: "执行环境", hint: "受控沙箱或运行环境" }, { type: "外部工具接入", field: "接入地址", hint: "HTTPS 地址" }],
  knowledge: [{ type: "解析配置", field: "依赖服务", hint: "现有解析引擎" }, { type: "检索配置", field: "依赖服务", hint: "受控检索服务" }, { type: "存储策略", field: "依赖服务", hint: "对象存储" }],
  runtime: [{ type: "沙箱策略", field: "运行环境", hint: "受控沙箱" }, { type: "工作空间策略", field: "运行环境", hint: "隔离工作空间" }, { type: "调度策略", field: "运行环境", hint: "任务调度环境" }],
};

export default function OmsResourceCreate({ kind, existingIds, onSave, onCancel }: {
  kind: ResourceKind; existingIds: string[]; onSave: (row: ResourceDraft) => void; onCancel: () => void;
}) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState(kind === "services" ? "外部服务接入" : choices[kind][0].type);
  const [detail, setDetail] = useState("");
  const [unit, setUnit] = useState("");
  const [error, setError] = useState("");
  const option = kind === "services" ? null : choices[kind].find(item => item.type === type) ?? choices[kind][0];
  const save = () => {
    const cleanId = id.trim();
    if (!/^[a-z][a-z0-9-]{1,63}$/.test(cleanId)) { setError("资源标识须为 2–64 位小写字母、数字或连字符，且以字母开头。"); return; }
    if (existingIds.includes(cleanId)) { setError("同一平台目录已有相同资源标识。"); return; }
    if (name.trim().length < 2) { setError("资源名称至少需要 2 个字符。"); return; }
    if (!detail.trim()) { setError(kind === "services" ? "请填写适配器方案。" : `请填写${option?.field}。`); return; }
    if (kind === "services" && !unit.trim()) { setError("请填写原生计量单位；未知单位不能上线服务。"); return; }
    if (kind !== "services" && ["外部 Agent 接入", "MCP 接入", "外部工具接入"].includes(type) && !/^https:\/\//.test(detail.trim())) { setError("外部接入地址必须使用 HTTPS。"); return; }
    onSave({ id: cleanId, name: name.trim(), type, status: "草稿", dependency: kind === "services" ? `适配器待开发 · ${unit.trim()}` : detail.trim(), detail: detail.trim(), unit: kind === "services" ? unit.trim() : undefined });
  };
  return <div className="side-panel"><Notice tone="warn">仅新增平台目录草稿。内置注册表代码、真实执行者、供应商凭据及运行态均不会变更。</Notice>
    <div className="form-grid"><label className="form-field">资源标识<input value={id} onChange={event => setId(event.target.value)} placeholder="例如 course-agent"/></label><label className="form-field">资源名称<input value={name} onChange={event => setName(event.target.value)}/></label>
      {kind !== "services" && <label className="form-field">新增类型<select value={type} onChange={event => { setType(event.target.value); setDetail(""); setError(""); }}>{choices[kind].map(item => <option key={item.type}>{item.type}</option>)}</select></label>}
      <label className="form-field">{kind === "services" ? "适配器方案" : option?.field}<input value={detail} onChange={event => setDetail(event.target.value)} placeholder={kind === "services" ? "说明后续接入方式，不会创建执行者" : option?.hint}/></label>
      {kind === "services" && <label className="form-field">计量单位<input value={unit} onChange={event => setUnit(event.target.value)} placeholder="例如 Token、页、分钟"/></label>}
    </div>{error && <Notice tone="bad">{error}</Notice>}<div className="form-actions"><Button variant="primary" onClick={save}>保存草稿</Button><Button onClick={onCancel}>取消</Button></div>
  </div>;
}
