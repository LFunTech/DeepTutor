"use client";

import { useRef, useState } from "react";
import type { DisplayState, SkillSource } from "@deeptutor/api-contracts";
import { projectSkill } from "@deeptutor/api-contracts";
import { Button, ConfirmModal, DetailGrid, Drawer, FormModal, Notice, PageHead, Section, StatusBadge } from "@deeptutor/admin-ui";
import { inspectSkillPackage, SkillList, SkillPackageField, type SkillPackageInspection } from "@deeptutor/service-components";
import { tenants } from "./fixtures";
import { initialPlatformSkills, tenantSkillNames, type PlatformSkill } from "./skill-fixtures";

type Mode = "create" | "hub" | "edit" | "grant" | null;

export default function OmsSkills({ selectedId, onOpen, onClose, canConfigure, state }: {
  selectedId?: string; onOpen: (id: string) => void; onClose: () => void; canConfigure: boolean; state: DisplayState;
}) {
  const [rows, setRows] = useState<PlatformSkill[]>(initialPlatformSkills);
  const [mode, setMode] = useState<Mode>(null);
  const [confirm, setConfirm] = useState<{ title: string; description: string; action: () => void } | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [inspection, setInspection] = useState<SkillPackageInspection | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const inspectionTicket = useRef(0);
  const [hubRef, setHubRef] = useState("");
  const [tenantId, setTenantId] = useState(tenants[0].id);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const selected = rows.find(row => row.id === selectedId);
  const openForm = (next: Mode) => {
    inspectionTicket.current++;
    setMode(next); setFile(null); setInspection(null); setInspecting(false); setHubRef(""); setError("");
  };
  const selectFile = async (next: File | null) => {
    const ticket = ++inspectionTicket.current;
    setFile(next); setInspection(null); setError(""); setInspecting(!!next);
    if (!next) return;
    try {
      const parsed = await inspectSkillPackage(next);
      if (ticket === inspectionTicket.current) setInspection(parsed);
    } catch (cause) {
      if (ticket === inspectionTicket.current) setError(cause instanceof Error ? cause.message : "无法读取 Skill ZIP 包。");
    } finally { if (ticket === inspectionTicket.current) setInspecting(false); }
  };
  const save = () => {
    if (!file) { setError("请先选择并通过预检的 Skill ZIP 包。"); return; }
    if (!inspection || inspecting) { if (!error) setError("请等待 Skill ZIP 包预检完成。"); return; }
    if (mode === "edit" && !selected) { setError("当前 Skill 已不可访问，请关闭后重新打开。"); return; }
    if (mode === "hub" && !/^https:\/\//.test(hubRef.trim())) { setError("请填写 HTTPS Hub 地址并提供从该来源获取的 ZIP 包。"); return; }
    if (mode === "edit" && selected && inspection.name !== selected.name) { setError("更新版本的 SKILL.md 名称必须与当前 Skill 相同。"); return; }
    if (mode !== "edit" && rows.some(row => row.name === inspection.name)) { setError("平台作用域已存在同名 Skill；请从详情上传新版本。"); return; }
    const update = { name: inspection.name, description: inspection.description, tags: inspection.tags, body: inspection.body, requires: inspection.requires, version: inspection.authorVersion || "未声明", license: inspection.license, compatibility: inspection.compatibility, allowedTools: inspection.allowedTools, frontmatter: inspection.frontmatter, archive: file, packageFiles: inspection.files, reference: inspection.files.filter(path => path !== "SKILL.md").join("、") || "无参考文件" };
    if (mode === "edit" && selected) {
      setRows(current => current.map(row => row.id === selected.id ? { ...row, ...update, revision: (row.revision ?? 1) + 1, history: [...(row.history ?? []), { archive: row.archive, name: row.name, description: row.description, version: row.version, body: row.body, files: row.packageFiles ?? [], reference: row.reference, origin: row.origin, digest: row.digest, grants: [...row.grants], frontmatter: row.frontmatter }], digest: "浏览器预检 · 服务端摘要待生成", status: "草稿", review: "新包待重新审查" } : row));
    } else {
      const source: SkillSource = mode === "hub" ? "hub" : "created";
      setRows(current => [...current, { id: `global:${inspection.name}`, owner: "global", source, origin: mode === "hub" ? hubRef.trim() : undefined, revision: 1, history: [], status: mode === "hub" ? "待安全审查" : "草稿", review: "尚未审查", readiness: "未就绪", digest: "浏览器预检 · 服务端摘要待生成", grants: [], ...update }]);
    }
    setMode(null); setMessage("本地 Skill 草稿已保存；未发布、未授权、不可在 DeepTutor 中运行。");
  };
  const updateStatus = (status: string, review: string) => {
    if (!selected) return;
    setRows(current => current.map(row => row.id === selected.id ? { ...row, status, review } : row));
    setMessage(`已登记“${status}”演示状态；真实执行者与运行态不变。`);
  };
  const grant = () => {
    if (!selected || selected.status !== "已发布") { setError("只有已发布的 Skill 才能授权学校。"); return; }
    const tenantName = tenants.find(row => row.id === tenantId)?.name ?? tenantId;
    const collision = (tenantSkillNames[tenantId] ?? []).includes(selected.name);
    setConfirm({ title: "确认学校 Skill 授权", description: `${tenantName} · ${selected.name}\n${collision ? "该学校已有同名自有 Skill；本学校版本在运行时仍优先，平台版本不会覆盖它。\n" : ""}仅更新 OMS 本地演示授权；TMS 配对数据不会实时同步。`, action: () => {
      setRows(current => current.map(row => row.id === selected.id ? { ...row, grants: [...new Set([...row.grants, tenantId])] } : row));
      setMode(null); setMessage("演示授权已记录；真实运行授权尚未接入。");
    } });
  };
  return <>
    <PageHead eyebrow="SKILL CATALOG" title="Skills" description="平台 Skill 与 DeepTutor 内置 Skill 分层维护；授权不等于运行条件已就绪。"
      actions={canConfigure && !selectedId ? <div className="inline-list"><Button variant="primary" onClick={() => openForm("create")}>新增平台 Skill</Button><Button onClick={() => openForm("hub")}>从 Hub 导入</Button></div> : undefined}/>
    <SkillList skills={state === "empty" ? [] : rows.map(projectSkill)} state={state} onOpen={onOpen} persistKey="oms:skills"/>
    {message && <Notice>{message}</Notice>}
    {selectedId && <Drawer title={`详情 · ${selected?.name ?? "未找到"}`} onClose={onClose} suspended={!!mode || !!confirm}>
      {selected ? <>
        <PageHead eyebrow="SKILL DETAIL" title={selected.name} description={selected.description} breadcrumbs={[{ label: "Skills", onClick: onClose }, { label: selected.name }]}
          actions={canConfigure ? <div className="inline-list">
            {selected.source !== "builtin" && selected.status !== "已发布" && <Button onClick={() => openForm("edit")}>编辑 Skill</Button>}
            {(selected.status === "草稿" || selected.status === "待安全审查") && <Button onClick={() => setConfirm({ title: "提交 Skill 审查", description: "导入与创建内容须经安全审查；此操作仅变更本地演示状态。", action: () => updateStatus("待审核", "等待安全与内容审查") })}>提交审查</Button>}
            {selected.status === "待审核" && <Button onClick={() => setConfirm({ title: "确认演示审查", description: "仅在原型中记录审查通过；不代表已执行真实安全扫描。", action: () => updateStatus("审核通过", "演示审查通过 · 真实安全检查待实施") })}>记录审查通过</Button>}
            {selected.status === "审核通过" && <Button onClick={() => setConfirm({ title: "提交发布申请", description: "申请交给真实执行者验证；原型不会把该 Skill 变为已发布或可运行。", action: () => updateStatus("待发布确认", "执行者测试与发布待确认") })}>提交发布申请</Button>}
            {selected.status === "已发布" && <Button variant="primary" onClick={() => { setTenantId(tenants[0].id); setError(""); setMode("grant"); }}>管理学校授权</Button>}
          </div> : undefined}/>
        <DetailGrid rows={[{ label: "归属", value: "global · 平台" }, { label: "来源", value: selected.source === "builtin" ? "DeepTutor 内置 · 只读" : selected.source === "hub" ? "Hub 导入" : "ZIP 包创建" }, { label: "状态", value: <StatusBadge tone={selected.status === "已发布" ? "good" : "warn"}>{selected.status}</StatusBadge> }, { label: "作者版本", value: selected.version }, { label: "平台修订", value: selected.revision ? `第 ${selected.revision} 版` : "打包条目" }, { label: "ZIP 包", value: selected.archive?.name || "打包条目" }, { label: "Hub 地址", value: selected.origin ? `${selected.origin}（未核验）` : "无" }, { label: "内容摘要", value: selected.digest }, { label: "标签", value: selected.tags.join("、") || "未标记" }, { label: "运行条件", value: selected.requires }, { label: "许可", value: selected.license || "未声明" }, { label: "兼容性", value: selected.compatibility || "未声明" }, { label: "可用工具", value: selected.allowedTools || "未声明" }, { label: "就绪状态", value: selected.readiness }, { label: "审查", value: selected.review }, { label: "学校授权", value: selected.grants.length ? selected.grants.map(id => tenants.find(t => t.id === id)?.name ?? id).join("、") : "尚无学校授权" }]}/>
        <Notice tone="warn">内置内容不能在线改写；云端未授权者不可查看或运行。Skill 本身不单独设置 Token 配额。</Notice>
        {selected.source !== "builtin" && <Section title="SKILL.md 与资源"><pre>{selected.body}</pre><p>{selected.reference}</p>{selected.frontmatter && <details><summary>查看完整包内元数据</summary><pre>{JSON.stringify(selected.frontmatter, null, 2)}</pre></details>}</Section>}
        {!!selected.history?.length && <Section title="历史包版本" subtitle="仅在当前原型会话内保留；正式审计需服务端不可变包记录。"><ul>{selected.history.map((item, index) => <li key={`${index}:${item.version}`}>第 {index + 1} 版 · {item.archive?.name || "演示条目"} · 作者版本 {item.version} · {item.description}</li>)}</ul></Section>}
        {selected.grants.length > 0 && canConfigure && <Section title="已授权学校"><div className="inline-list">{selected.grants.map(id => <Button key={id} onClick={() => setConfirm({ title: "撤销 Skill 授权", description: `${tenants.find(t => t.id === id)?.name ?? id} 将不再获得此 global Skill。仅更新原型本地状态。`, action: () => { setRows(current => current.map(row => row.id === selected.id ? { ...row, grants: row.grants.filter(grant => grant !== id) } : row)); setMessage("演示授权已撤销。"); } })}>{tenants.find(t => t.id === id)?.name ?? id} · 撤销</Button>)}</div></Section>}
      </> : <Notice tone="bad">Skill 不存在或不可访问。</Notice>}
    </Drawer>}
    {mode && canConfigure && <FormModal title={mode === "grant" ? "管理学校授权" : mode === "edit" ? "编辑 Skill" : mode === "hub" ? "从 Hub 导入" : "新增平台 Skill"} onClose={() => setMode(null)} suspended={!!confirm}>
      {mode === "grant" ? <div className="side-panel"><Notice>仅已发布 Skill 可授权；builtin 授权与运行条件分别核对。</Notice><label className="form-field">目标学校<select value={tenantId} onChange={event => setTenantId(event.target.value)}>{tenants.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>{error && <Notice tone="bad">{error}</Notice>}<div className="form-actions"><Button variant="primary" onClick={grant}>提交授权</Button><Button onClick={() => setMode(null)}>取消</Button></div></div>
        : <div className="side-panel"><Notice tone="warn">{mode === "hub" ? "需提供完整 ZIP 包与 Hub 地址。浏览器不直接拉取，也无法验证包的真实来源；须经服务端核对与审查后才能发布。" : mode === "edit" ? `请上传 ${selected?.name ?? "当前 Skill"} 的完整 ZIP 新版本；保存后需重新审查。` : "仅保存本地 ZIP 包草稿，不调用用户级 /api/skills。"}</Notice>{mode === "hub" && <label className="form-field">Hub HTTPS 地址<input value={hubRef} onChange={event => setHubRef(event.target.value)}/></label>}<SkillPackageField file={file} inspection={inspection} error={error} inspecting={inspecting} onSelect={next => { void selectFile(next); }}/><div className="form-actions"><Button variant="primary" onClick={save} disabled={inspecting}>保存草稿</Button><Button onClick={() => setMode(null)}>取消</Button></div></div>}
    </FormModal>}
    {confirm && <ConfirmModal title={confirm.title} description={confirm.description} onCancel={() => setConfirm(null)} onConfirm={() => { confirm.action(); setConfirm(null); }}/>}
  </>;
}
