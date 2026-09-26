"use client";

import { useState } from "react";
import { Button, Notice } from "@deeptutor/admin-ui";

export type ProfileDraft = { id: string; serviceId: string; name: string; provider: string; fields: Record<string, string>; status: "草稿" };
export type ModelDraft = { id: string; serviceId: string; profileId: string; name: string; model: string; detail: string; status: "草稿" };

export default function OmsModelCreate({ serviceId, profiles, models, onSave, onCancel }: {
  serviceId: string; profiles: ProfileDraft[]; models: ModelDraft[]; onSave: (row: ModelDraft) => void; onCancel: () => void;
}) {
  const [profileId, setProfileId] = useState(profiles[0]?.id ?? "");
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [detail, setDetail] = useState("");
  const [error, setError] = useState("");
  const special = serviceId === "llm" ? { label: "上下文窗口", placeholder: "正整数（可留空，待后端检测）" }
    : serviceId === "embedding" ? { label: "向量维度", placeholder: "正整数（按供应商能力）" }
    : serviceId === "tts" ? { label: "音色", placeholder: "供应商支持的音色（可留空）" }
    : serviceId === "imagegen" ? { label: "尺寸", placeholder: "供应商支持的尺寸（可留空）" }
    : serviceId === "videogen" ? { label: "宽高比", placeholder: "供应商支持的比例（可留空）" } : null;
  const save = () => {
    if (!profiles.some(row => row.id === profileId)) { setError("请先创建本服务的 Provider profile。"); return; }
    if (name.trim().length < 2 || !model.trim()) { setError("请填写模型名称与模型标识。"); return; }
    if (models.some(row => row.serviceId === serviceId && row.profileId === profileId && row.model === model.trim())) { setError("该 Profile 下已存在相同模型标识。"); return; }
    if (["llm", "embedding"].includes(serviceId) && detail.trim() && (!Number.isSafeInteger(Number(detail)) || Number(detail) <= 0)) { setError(`${special?.label}须为正整数。`); return; }
    onSave({ id: `model-${Date.now()}`, serviceId, profileId, name: name.trim(), model: model.trim(), detail: detail.trim(), status: "草稿" });
  };
  return <div className="side-panel"><Notice tone="warn">模型只能归属本服务已有 Profile。候选标识与能力以 DeepTutor 服务端 descriptor 为准；保存不发布。</Notice><div className="form-grid"><label className="form-field">所属 Profile<select value={profileId} onChange={event => setProfileId(event.target.value)}><option value="">请选择</option>{profiles.map(row => <option key={row.id} value={row.id}>{row.name} · {row.provider}</option>)}</select></label><label className="form-field">模型名称<input value={name} onChange={event => setName(event.target.value)}/></label><label className="form-field">模型标识<input value={model} onChange={event => setModel(event.target.value)}/></label>{special && <label className="form-field">{special.label}<input value={detail} onChange={event => setDetail(event.target.value)} placeholder={special.placeholder}/></label>}</div>{error && <Notice tone="bad">{error}</Notice>}<div className="form-actions"><Button variant="primary" onClick={save}>保存模型草稿</Button><Button onClick={onCancel}>取消</Button></div></div>;
}
