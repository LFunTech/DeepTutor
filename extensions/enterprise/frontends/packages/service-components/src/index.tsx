"use client";

import { useState } from "react";
import type { ServiceView, SkillView, DisplayState } from "@deeptutor/api-contracts";
import { DataTable, DetailGrid, Notice, Section, StatusBadge } from "@deeptutor/admin-ui";
import type { SkillPackageInspection } from "./skill-package";
export { inspectSkillPackage } from "./skill-package";
export type { SkillPackageInspection, SkillPackageRevision } from "./skill-package";

export function SkillPackageField({ file, inspection, error, inspecting, onSelect }: {
  file: File | null; inspection: SkillPackageInspection | null; error?: string; inspecting?: boolean; onSelect: (file: File | null) => void;
}) {
  return <div className="side-panel">
    <label className="form-field">Skill ZIP 包<input type="file" accept=".zip,application/zip" onChange={event => onSelect(event.target.files?.[0] ?? null)}/></label>
    <p className="cell-sub">仅接收完整 ZIP 包。SKILL.md 可位于包根或唯一顶层目录；正文、说明、标签、运行条件均从包内读取，不在此处手填。</p>
    {file && <p>已选文件：{file.name}</p>}
    {inspecting && <Notice>正在检查 Skill 包…</Notice>}
    {error && <Notice tone={/安全限制|膨胀限制/.test(error) ? "bad" : "warn"}>{error}</Notice>}
    {inspection && <><DetailGrid rows={[
      { label: "Skill 名称", value: inspection.name }, { label: "说明", value: inspection.description },
      { label: "作者版本", value: inspection.authorVersion || "未声明" }, { label: "标签", value: inspection.tags.join("、") || "未标记" },
      { label: "运行条件", value: inspection.requires }, { label: "许可", value: inspection.license || "未声明" },
      { label: "兼容性", value: inspection.compatibility || "未声明" }, { label: "允许工具", value: inspection.allowedTools || "未声明" },
    ]}/><details><summary>查看 SKILL.md 正文与资源文件</summary><pre>{inspection.body}</pre><ul>{inspection.files.map(path => <li key={path}>{path}</li>)}</ul></details><details><summary>查看 SKILL.md 完整元数据</summary><pre>{JSON.stringify(inspection.frontmatter, null, 2)}</pre></details></>}
  </div>;
}

const labels = { available: ["可使用", "good"], limited: ["需关注", "warn"], unavailable: ["暂不可用", "bad"] } as const;
function skillTone(status: string): "good" | "warn" {
  if (status.includes("暂不可用") || status.includes("待") || status.includes("撤销") || status.includes("覆盖") || status.includes("草稿")) return "warn";
  return status.includes("可用") || status.includes("优先") || status === "已发布" ? "good" : "warn";
}

export function ServiceList({ services, onOpen, state = "ready", title = "服务目录", categories }: {
  services: ServiceView[]; onOpen: (id: string) => void; state?: DisplayState; title?: string; categories?: string[];
}) {
  const [category, setCategory] = useState("all");
  const values = categories ?? [...new Set(services.map(item => item.category))];
  return <Section title={title} subtitle="选择服务查看配置、授权与使用情况">
    <DataTable rows={services.filter(item => category === "all" || item.category === category)} searchLabel="搜索服务" searchText={row => `${row.name} ${row.description}`}
      filters={[{ label: "类别", value: category, options: [{ value: "all", label: "全部类别" }, ...values.map(value => ({ value, label: value }))], onChange: setCategory }]}
      state={state} onOpen={row => onOpen(row.id)} openLabel={row => `查看${row.name}详情`} persistKey={`services:${title}`} columns={[
        { key: "name", label: "服务", render: row => <><span className="cell-title">{row.name}</span><span className="cell-sub">{row.description}</span></> },
        { key: "category", label: "类别", render: row => row.category },
        { key: "unit", label: "计量单位", render: row => row.unit },
        { key: "status", label: "状态", render: row => <StatusBadge tone={labels[row.status][1]}>{labels[row.status][0]}</StatusBadge> },
      ]}/>
  </Section>;
}

export function OcrServiceList(props: { services: ServiceView[]; onOpen: (id: string) => void; state?: DisplayState }) {
  return <ServiceList {...props} title="文档识别与解析" categories={["知识处理"]}/>;
}

export function ServiceDetail({ service, children }: { service: ServiceView; children?: React.ReactNode }) {
  return <><DetailGrid rows={[
    { label: "服务类别", value: service.category },
    { label: "状态", value: <StatusBadge tone={labels[service.status][1]}>{labels[service.status][0]}</StatusBadge> },
    { label: "计量单位", value: service.unit },
  ]}/><Notice>{service.id === "ocr" ? "文档 OCR 当前属于 DeepTutor 解析引擎能力；原型不宣称已有独立 OCR Provider 或真实配置已生效。" : "此服务信息来自原型演示数据，不代表真实配置已发布或执行者已生效。"}</Notice>{children}</>;
}

export function SkillList({ skills, onOpen, state = "ready", persistKey = "skills:list" }: { skills: SkillView[]; onOpen: (id: string) => void; state?: DisplayState; persistKey?: string }) {
  const [owner, setOwner] = useState("all");
  return <Section title="Skills 清单" subtitle="选择 Skill 查看来源、版本与可用状态">
    <DataTable rows={skills.filter(row => owner === "all" || row.owner === owner)} state={state} persistKey={persistKey}
      searchLabel="搜索 Skill" searchText={row => `${row.name} ${row.description} ${row.tags.join(" ")}`}
      filters={[{ label: "归属", value: owner, onChange: setOwner, options: [{ label: "全部归属", value: "all" }, { label: "平台", value: "global" }, { label: "本学校", value: "tenant" }] }]}
      onOpen={row => onOpen(row.id)} openLabel={row => `查看${row.name}详情`}
      columns={[
        { key: "name", label: "Skill", render: row => <><span className="cell-title">{row.name}</span><span className="cell-sub">{row.description}</span></> },
        { key: "owner", label: "归属", render: row => row.owner === "global" ? "平台" : "本学校" },
        { key: "source", label: "来源", render: row => ({ builtin: "DeepTutor 内置", created: "人工创建", hub: "Hub 导入", upload: "文件上传" })[row.source] },
        { key: "version", label: "版本", render: row => row.version },
        { key: "status", label: "状态", render: row => <StatusBadge tone={skillTone(row.status)}>{row.status}</StatusBadge> },
      ]}/>
  </Section>;
}
