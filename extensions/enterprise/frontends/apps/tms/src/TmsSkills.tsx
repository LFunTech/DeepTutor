"use client";

import { useRef, useState } from "react";
import type { DisplayState, SkillSource } from "@deeptutor/api-contracts";
import { projectSkill, resolveSkillForTenant } from "@deeptutor/api-contracts";
import { Button, ConfirmModal, DetailGrid, Drawer, FormModal, Notice, PageHead, Section, StatePanel, StatusBadge } from "@deeptutor/admin-ui";
import { inspectSkillPackage, SkillList, SkillPackageField, type SkillPackageInspection } from "@deeptutor/service-components";
import { initialTenantSkills, type TenantSkill } from "./skill-fixtures";
import { tenant } from "./fixtures";

type Mode = "hub" | "upload" | "edit" | null;
export default function TmsSkills({ selectedId, onOpen, onClose, state }: { selectedId?: string; onOpen: (id: string) => void; onClose: () => void; state: DisplayState }) {
  const [rows, setRows] = useState<TenantSkill[]>(initialTenantSkills);
  const [mode, setMode] = useState<Mode>(null);
  const [confirm, setConfirm] = useState<{ title: string; description: string; action: () => void } | null>(null);
  const [hubRef, setHubRef] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [inspection, setInspection] = useState<SkillPackageInspection | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const inspectionTicket = useRef(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const visibleRows = rows.filter(row => row.owner === "tenant" ? row.tenantId === tenant.id : row.published && row.authorized);
  const selected = visibleRows.find(row => row.id === selectedId);
  const resolution = selected ? resolveSkillForTenant(visibleRows, selected.name, tenant.id) : undefined;
  const displayRows = visibleRows.map(row => {
    const winner = resolveSkillForTenant(visibleRows, row.name, tenant.id);
    return projectSkill({ ...row, status: winner?.id !== row.id && row.owner === "global" ? "已被本学校版本覆盖" : winner?.id === row.id && row.owner === "tenant" ? "本学校版本优先" : row.status });
  });
  const openForm = (next: Mode) => {
    inspectionTicket.current++;
    setMode(next); setHubRef(""); setFile(null); setInspection(null); setInspecting(false); setError("");
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
  const persist = (source: SkillSource, parsed: SkillPackageInspection, archive: File, origin: string) => {
    const update = { name: parsed.name, description: parsed.description, tags: parsed.tags, body: parsed.body, requires: parsed.requires, version: parsed.authorVersion || "未声明", license: parsed.license, compatibility: parsed.compatibility, allowedTools: parsed.allowedTools, frontmatter: parsed.frontmatter, archive, packageFiles: parsed.files, reference: parsed.files.filter(path => path !== "SKILL.md").join("、") || "无参考文件" };
    if (mode === "edit" && selected) {
      setRows(current => current.map(row => row.id === selected.id ? { ...row, ...update, revision: (row.revision ?? 1) + 1, history: [...(row.history ?? []), { archive: row.archive, name: row.name, description: row.description, version: row.version, body: row.body, files: row.packageFiles ?? [], reference: row.reference, origin: row.origin, frontmatter: row.frontmatter }], status: "草稿", published: false, ready: false, readiness: "未就绪", review: "新包待重新审查" } : row));
    } else {
      setRows(current => [...current, { id: `tenant:${tenant.id}:${update.name}`, tenantId: tenant.id, owner: "tenant", source, origin: source === "hub" ? origin : undefined, revision: 1, history: [], status: "待安全审查", readiness: "未就绪", review: "ZIP 包待安全审查", published: false, authorized: true, ready: false, ...update }]);
    }
    setMode(null); setMessage("本学校演示草稿已保存；审核发布前不可使用，不影响 OMS 配额或服务授权。");
  };
  const save = () => {
    if (!file) { setError("请先选择并通过预检的 Skill ZIP 包。"); return; }
    if (!inspection || inspecting) { if (!error) setError("请等待 Skill ZIP 包预检完成。"); return; }
    if (mode === "edit" && !selected) { setError("当前 Skill 已不可访问，请关闭后重新打开。"); return; }
    if (mode === "edit" && selected && inspection.name !== selected.name) { setError("更新版本的 SKILL.md 名称必须与当前 Skill 相同。"); return; }
    if (mode !== "edit" && rows.some(row => row.owner === "tenant" && row.name === inspection.name)) { setError("本学校已存在同名 Skill，请从详情上传新版本。"); return; }
    if (mode === "hub" && !/^https:\/\//.test(hubRef.trim())) { setError("请填写 HTTPS Hub 地址并提供从该来源获取的 ZIP 包。"); return; }
    const source: SkillSource = mode === "hub" ? "hub" : "upload";
    const origin = hubRef.trim();
    const global = rows.find(row => row.owner === "global" && row.name === inspection.name && row.published && row.authorized);
    if (mode !== "edit" && global) {
      const parsed = inspection, archive = file;
      setConfirm({ title: "同名 Skill 上传确认", description: `当前学校已获授权平台 Skill「${parsed.name}」。本学校版本发布后将优先于平台版本用于清单、正文与参考文件读取；平台版本不会删除。确认前不保存草稿。`, action: () => persist(source, parsed, archive, origin) });
      return;
    }
    persist(source, inspection, file, origin);
  };
  const changeStatus = (status: string, published = false) => {
    if (!selected || selected.owner !== "tenant") return;
    setRows(current => current.map(row => row.id === selected.id ? { ...row, status, published, ready: published, review: status === "审核通过" || published ? "学校管理员演示审查通过；真实安全扫描待实施" : status === "审核中" ? "等待内容与安全审查" : "尚未审核", readiness: published ? "已就绪（演示）" : "未就绪" } : row));
    setMessage("只更新本学校原型状态；真实云端 Skill 执行能力尚未接入。");
  };
  if (selectedId && !selected) return <StatePanel state="forbidden" message="当前学校不能访问此 Skill。"/>;
  return <>
    <PageHead eyebrow="TENANT SKILLS" title="Skills" description="查看平台授权 Skill，维护仅本学校使用的 Skill；不另分配给成员或应用。"
      actions={!selectedId && <div className="inline-list"><Button variant="primary" onClick={() => openForm("upload")}>上传 Skill</Button><Button onClick={() => openForm("hub")}>从 Hub 导入</Button></div>}/>
    <SkillList skills={state === "empty" ? [] : displayRows} state={state} onOpen={onOpen} persistKey="tms:skills"/>
    {message && <Notice>{message}</Notice>}
    {selectedId && <Drawer title={`详情 · ${selected?.name ?? "未找到"}`} onClose={onClose} suspended={!!mode || !!confirm}>
      {selected ? <>
        <PageHead eyebrow="SKILL DETAIL" title={selected.name} description={selected.description} breadcrumbs={[{ label: "Skills", onClick: onClose }, { label: selected.name }]}
          actions={selected.owner === "tenant" ? <div className="inline-list"><Button onClick={() => selected.published ? setConfirm({ title: "编辑已发布 Skill", description: rows.some(row => row.owner === "global" && row.name === selected.name) ? "保存编辑草稿后，当前本学校版本暂停发布；同名平台版本将重新成为候选。" : "保存编辑草稿后，当前本学校版本暂停发布，待重新审核。", action: () => openForm("edit") }) : openForm("edit")}>编辑 Skill</Button>
            {!selected.published ? <>
              {(selected.status === "草稿" || selected.status === "待安全审查") && <Button onClick={() => setConfirm({ title: "提交 Skill 审查", description: "导入/上传内容须进行真实服务端安全检查；这里只登记演示审查流程。", action: () => changeStatus("审核中") })}>提交审查</Button>}
              {selected.status === "审核中" && <Button onClick={() => setConfirm({ title: "记录演示审查通过", description: "仅记录原型审查通过，不代表真实安全扫描已经执行；生产环境必须阻止未审查内容发布。", action: () => changeStatus("审核通过") })}>记录演示审查通过</Button>}
              {selected.status === "审核通过" && <Button variant="primary" onClick={() => setConfirm({ title: "发布本学校 Skill", description: "仅原型模拟本学校发布；真实执行者仍未接入。发布后不改变平台服务授权或额度。", action: () => changeStatus("本学校可用", true) })}>发布（演示）</Button>}
            </>
              : <Button onClick={() => setConfirm({ title: "撤销本学校 Skill", description: rows.some(row => row.owner === "global" && row.name === selected.name) ? "撤销后，同名已授权平台 Skill 将重新成为运行候选；请先核对影响。" : "撤销后本学校将无法继续使用此 Skill。", action: () => changeStatus("已撤销", false) })}>撤销发布</Button>}</div> : undefined}/>
        <DetailGrid rows={[{ label: "归属", value: selected.owner === "global" ? "平台授权 · 只读" : tenant.name }, { label: "来源", value: ({ builtin: "DeepTutor 内置", created: "人工创建", hub: "Hub 导入", upload: "ZIP 上传" })[selected.source] }, { label: "状态", value: <StatusBadge tone={selected.ready ? "good" : "warn"}>{selected.status}</StatusBadge> }, { label: "作者版本", value: selected.version }, { label: "平台修订", value: selected.revision ? `第 ${selected.revision} 版` : "打包条目" }, { label: "ZIP 包", value: selected.archive?.name || "打包条目" }, { label: "Hub 地址", value: selected.origin ? `${selected.origin}（未核验）` : "无" }, { label: "标签", value: selected.tags.join("、") || "未标记" }, { label: "运行条件", value: selected.requires }, { label: "许可", value: selected.license || "未声明" }, { label: "兼容性", value: selected.compatibility || "未声明" }, { label: "可用工具", value: selected.allowedTools || "未声明" }, { label: "就绪状态", value: selected.readiness }, { label: "审核", value: selected.owner === "global" ? "OMS 已发布并授权（配对演示）" : selected.review }, { label: "同名运行候选", value: resolution?.id === selected.id ? "当前条目优先" : resolution ? `${resolution.owner === "tenant" ? "本学校" : "平台"}版本优先` : "尚无可用候选" }]}/>
        <Notice tone="warn">已授权不代表运行条件满足。Skill 不单独计 Token；底层服务按可信用量扣减。</Notice>
        <Section title="正文与参考文件解析（演示）"><p>{resolution ? resolution.ready ? `当前候选：${resolution.name} · ${resolution.owner === "tenant" ? "本学校" : "平台"}` : "当前候选运行条件不足，不回退同名平台版本。" : "未发布或未授权，不可读取。"}</p>{resolution?.ready && <DetailGrid rows={[{ label: "正文", value: resolution.body }, { label: "参考文件", value: resolution.reference }]}/>}</Section>
        {selected.owner === "tenant" && selected.frontmatter && <Section title="包内元数据"><details><summary>查看 SKILL.md 原始声明</summary><pre>{JSON.stringify(selected.frontmatter, null, 2)}</pre></details></Section>}
        {!!selected.history?.length && <Section title="历史包版本" subtitle="仅在当前原型会话内保留；正式审计需服务端不可变包记录。"><ul>{selected.history.map((item, index) => <li key={`${index}:${item.version}`}>第 {index + 1} 版 · {item.archive?.name || "演示条目"} · 作者版本 {item.version} · {item.description}</li>)}</ul></Section>}
      </> : <Notice tone="bad">Skill 不存在或不可访问。</Notice>}
    </Drawer>}
    {mode && <FormModal title={mode === "edit" ? "编辑 Skill" : mode === "hub" ? "从 Hub 导入" : "上传 Skill"} onClose={() => setMode(null)} suspended={!!confirm}>
      <div className="side-panel"><Notice tone="warn">仅本学校草稿；完整 ZIP 包须经过服务端安全审查后方可真实发布。Hub 需同时提供地址与包，浏览器无法核验真实来源；不调用本地用户级 Skill API。</Notice>{mode === "edit" && <Notice>请上传 {selected?.name ?? "当前 Skill"} 的完整 ZIP 新版本；名称必须一致。</Notice>}{mode === "hub" && <label className="form-field">Hub HTTPS 地址<input value={hubRef} onChange={event => setHubRef(event.target.value)}/></label>}<SkillPackageField file={file} inspection={inspection} error={error} inspecting={inspecting} onSelect={next => { void selectFile(next); }}/><div className="form-actions"><Button variant="primary" onClick={save} disabled={inspecting}>保存草稿</Button><Button onClick={() => setMode(null)}>取消</Button></div></div>
    </FormModal>}
    {confirm && <ConfirmModal title={confirm.title} description={confirm.description} onCancel={() => setConfirm(null)} onConfirm={() => { confirm.action(); setConfirm(null); }}/ >}
  </>;
}
