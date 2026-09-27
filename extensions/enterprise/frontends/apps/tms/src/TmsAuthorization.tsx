"use client";

import { useState } from "react";
import { createPortal } from "react-dom";
import { Button, ConfirmModal, DataTable, DetailGrid, Drawer, FormModal, Notice, PageHead, Section, StatePanel } from "@deeptutor/admin-ui";
import { apps, members, services, tenant } from "./fixtures";

type TmsRole = { id: string; name: string; version: number; actions: string[]; custom?: boolean };
type TmsAssignment = { id: string; memberId: string; roleId: string; expires: string; status: string; version: number };
type TmsAudit = { id: string; action: string; target: string; actor: string; reason: string; status: string };
export type TmsAuthState = { roles: TmsRole[]; assignments: TmsAssignment[]; audits: TmsAudit[] };

const actionCatalog = [
  { key: "tenant.tms.access", label: "进入学校后台" },
  { key: "tenant.members.read", label: "查看成员" },
  { key: "tenant.permissions.manage", label: "管理学校角色", protected: true, sensitive: true },
  { key: "tenant.clients.manage", label: "管理本校应用", sensitive: true },
  { key: "tenant.access.manage", label: "管理应用与服务访问", sensitive: true },
  { key: "tenant.quotas.read", label: "查看本校额度" },
  { key: "tenant.usage.read", label: "查看本校用量" },
];
const allowedActions = new Set(actionCatalog.map(item => item.key));
const isDirectGrantRole = (role: TmsRole) => role.id !== "school-admin" && role.actions.length > 0 && role.actions.every(key => actionCatalog.some(action => action.key === key && !action.sensitive));
const roleName = (roles: TmsRole[], id: string) => roles.find(item => item.id === id)?.name ?? "未知角色";
const memberName = (id: string) => members.find(item => item.id === id)?.name ?? "未知成员";
const isFuture = (date: string) => !!date && date >= new Date().toISOString().slice(0, 10);

export const initialTmsAuth: TmsAuthState = {
  roles: [
    { id: "school-admin", name: "学校管理员", version: 2, actions: actionCatalog.map(item => item.key) },
    { id: "school-operator", name: "学校运营", version: 1, actions: ["tenant.tms.access", "tenant.members.read", "tenant.clients.manage", "tenant.access.manage", "tenant.quotas.read", "tenant.usage.read"] },
    { id: "school-auditor", name: "学校只读审计", version: 1, actions: ["tenant.tms.access", "tenant.members.read", "tenant.quotas.read", "tenant.usage.read"] },
  ],
  assignments: [
    { id: "ta-01", memberId: "m-01", roleId: "school-admin", expires: "2027-12-31", status: "有效（演示）", version: 2 },
  ],
  audits: [{ id: "t-authz-001", action: "首位学校管理员开通", target: "林老师", actor: "订阅事件 actor 本人（演示）", reason: "本人身份匹配后由 Enterprise 程序激活", status: "演示记录" }],
};

export function TmsMemberRoles({ memberId, state, onChange, role, onModalChange }: {
  memberId: string; state: TmsAuthState; onChange: (state: TmsAuthState) => void; role: string; onModalChange?: (open: boolean) => void;
}) {
  const [formOpen, setFormOpen] = useState(false);
  const [confirm, setConfirm] = useState<{ title: string; description: string; action: () => void } | null>(null);
  const [roleId, setRoleId] = useState("school-auditor");
  const [expires, setExpires] = useState("2027-12-31");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const actorId = "m-01";
  const person = members.find(item => item.id === memberId);
  const canManage = role === "admin";
  const assignments = state.assignments.filter(item => item.memberId === memberId);
  const open = () => { setFormOpen(true); setReason(""); setMessage(""); onModalChange?.(true); };
  const close = () => { setFormOpen(false); setConfirm(null); onModalChange?.(false); };
  const appendAudit = (action: string, target: string, why: string): TmsAudit => ({ id: `t-authz-${state.audits.length + 1}`, action, target, actor: "林老师（演示学校管理员）", reason: why, status: "演示记录" });
  const grant = () => {
    const definition = state.roles.find(item => item.id === roleId);
    if (!person || person.id === actorId || person.status !== "正常" || !definition || !isDirectGrantRole(definition) || !definition.actions.every(key => allowedActions.has(key)) || !isFuture(expires) || !reason.trim()) { setMessage("只能为已核验的本校其他成员授予低风险角色，并填写有效期与原因；管理员与敏感角色须独立复核。"); return; }
    if (assignments.some(item => item.roleId === roleId && item.status.startsWith("有效"))) { setMessage("当前成员已拥有该角色。"); return; }
    const next: TmsAssignment = { id: `ta-${state.assignments.length + 1}`, memberId, roleId, expires, status: "有效（演示）", version: definition.version };
    setConfirm({ title: "确认学校角色授权", description: `${person.name} · ${definition.name} v${definition.version} · 仅${tenant.name} · 至 ${expires}；动作：${definition.actions.join("、")}。原因：${reason}。仅本地演示，不写入真实授权服务。`, action: () => { onChange({ ...state, assignments: [...state.assignments, next], audits: [...state.audits, appendAudit("学校角色授权", person.name, reason)] }); close(); setMessage(`演示授权记录 ${next.id} 已回读；真实权限未变更。`); } });
  };
  const revoke = (item: TmsAssignment) => {
    if (item.roleId === "school-admin" && state.assignments.filter(row => row.roleId === "school-admin" && row.status.startsWith("有效")).length <= 1) { setMessage("不能撤销最后一名可用学校管理员。"); return; }
    setConfirm({ title: "确认撤销学校角色", description: `${memberName(item.memberId)} · ${roleName(state.roles, item.roleId)}；将失去相应学校菜单、应用和服务管理动作，历史审计保留。`, action: () => { onChange({ ...state, assignments: state.assignments.map(row => row.id === item.id ? { ...row, status: "已撤权" } : row), audits: [...state.audits, appendAudit("学校角色撤权", memberName(item.memberId), "管理员确认撤权")] }); setConfirm(null); onModalChange?.(false); setMessage("演示角色已撤销；旧页面不得继续执行管理操作。"); } });
    onModalChange?.(true);
  };
  return <>
    <Section title="学校角色" action={canManage && person?.id !== actorId && person?.status === "正常" ? <Button onClick={open}>授予学校角色</Button> : undefined}>
      <Notice>当前学校：{tenant.name}；外部身份由 EduPlus2 提供，本产品角色来自基座授权（演示）。</Notice>
      <DataTable rows={assignments} searchLabel="搜索成员角色" columns={[{ key: "role", label: "学校角色", render: row => roleName(state.roles, row.roleId) }, { key: "expires", label: "有效期", render: row => row.expires }, { key: "status", label: "状态", render: row => row.status }, { key: "version", label: "模板版本", render: row => `v${row.version}` }]} rowActions={row => canManage && row.status.startsWith("有效") && row.memberId !== actorId ? [{ label: "撤销角色", onClick: () => revoke(row) }] : []}/>
    </Section>
    {message && <Notice tone={message.startsWith("不能") || message.startsWith("只能") || message.includes("已拥有") ? "bad" : "info"}>{message}</Notice>}
    <Section title="授权记录"><DataTable rows={state.audits.filter(item => item.target === person?.name)} searchLabel="搜索授权记录" columns={[{ key: "action", label: "操作", render: row => row.action }, { key: "reason", label: "原因", render: row => row.reason }, { key: "status", label: "状态", render: row => row.status }]}/></Section>
    {formOpen && <FormModal title="授予学校角色" onClose={close} suspended={!!confirm}><label className="form-field">角色<select value={roleId} onChange={event => setRoleId(event.target.value)}>{state.roles.filter(isDirectGrantRole).map(item => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select></label><label className="form-field">有效期<input type="date" value={expires} onChange={event => setExpires(event.target.value)}/></label><label className="form-field">授权原因<input value={reason} onChange={event => setReason(event.target.value)}/></label><Section title="有效权限预览"><p>{state.roles.find(item => item.id === roleId)?.actions.map(key => actionCatalog.find(item => item.key === key)?.label ?? key).join("、")} · 仅{tenant.name} · 至 {expires}</p></Section><Notice tone="warn">仅低风险角色可在此演示直授；管理员和敏感动作须独立复核。不能自授或跨校授权，真实权限由服务端再次校验。</Notice>{message && <Notice tone="bad">{message}</Notice>}<div className="form-actions"><Button onClick={close}>取消</Button><Button variant="primary" onClick={grant}>提交授权</Button></div></FormModal>}
    {confirm && typeof document !== "undefined" && createPortal(<ConfirmModal title={confirm.title} description={confirm.description} onCancel={() => { setConfirm(null); if (!formOpen) onModalChange?.(false); }} onConfirm={confirm.action}/>, document.body)}
  </>;
}

type SectionName = "roles" | "access-grants" | "authz-records";
type AccessRow = { id: string; kind: "member-app" | "app-service"; memberId?: string; appId: string; serviceId?: string; target: string; source: string };

export default function TmsAuthorization({ section, selectedId, state, onChange, memberAccess, serviceAccess, onMemberAccess, onServiceAccess, onOpen, onClose, role }: {
  section: SectionName; selectedId?: string; state: TmsAuthState; onChange: (state: TmsAuthState) => void;
  memberAccess: Record<string, string[]>; serviceAccess: Record<string, string[]>;
  onMemberAccess: (memberId: string, appId: string, add: boolean) => void;
  onServiceAccess: (appId: string, serviceId: string, add: boolean) => void;
  onOpen: (id: string) => void; onClose: () => void; role: string;
}) {
  const [form, setForm] = useState<"role" | "access" | null>(null);
  const [confirm, setConfirm] = useState<{ title: string; description: string; action: () => void } | null>(null);
  const [name, setName] = useState("");
  const [actions, setActions] = useState<string[]>([]);
  const [kind, setKind] = useState<"member-app" | "app-service">("member-app");
  const [memberId, setMemberId] = useState("m-02");
  const [appId, setAppId] = useState("app-01");
  const [serviceId, setServiceId] = useState("llm");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const canManage = role === "admin";
  const accessRows: AccessRow[] = [
    ...Object.entries(memberAccess).flatMap(([memberId, appIds]) => appIds.filter(appId => apps.some(item => item.id === appId)).map(appId => ({ id: `member-app:${memberId}:${appId}`, kind: "member-app" as const, memberId, appId, target: `${memberName(memberId)} → ${apps.find(item => item.id === appId)?.name}`, source: "成员—应用显式关系（演示）" }))),
    ...Object.entries(serviceAccess).flatMap(([appId, serviceIds]) => serviceIds.filter(serviceId => services.some(item => item.id === serviceId)).map(serviceId => ({ id: `app-service:${appId}:${serviceId}`, kind: "app-service" as const, appId, serviceId, target: `${apps.find(item => item.id === appId)?.name} → ${services.find(item => item.id === serviceId)?.name}`, source: "应用—OMS 已授权服务（演示）" }))),
  ];
  const selected = section === "roles" ? state.roles.find(item => item.id === selectedId) : section === "access-grants" ? accessRows.find(item => item.id === selectedId) : state.audits.find(item => item.id === selectedId);
  const createRole = () => {
    if (name.trim().length < 2 || state.roles.some(item => item.name === name.trim()) || !actions.length || actions.some(key => !allowedActions.has(key))) { setMessage("角色名称至少 2 字、不能重复，动作仅可选择本产品学校范围权限。"); return; }
    const next: TmsRole = { id: `custom-${state.roles.length + 1}`, name: name.trim(), version: 1, actions, custom: true };
    setConfirm({ title: "确认新增学校角色", description: `${next.name} · 仅${tenant.name} · ${actions.join("、")}；不会自动扩展既有成员权限。`, action: () => { onChange({ ...state, roles: [...state.roles, next], audits: [...state.audits, { id: `t-authz-${state.audits.length + 1}`, action: "新增学校角色", target: next.name, actor: "林老师（演示）", reason: "新增自定义模板", status: "演示记录" }] }); setForm(null); setConfirm(null); setMessage("自定义角色已加入本地演示目录，尚未授予成员。"); } });
  };
  const saveAccess = () => {
    const valid = kind === "member-app" ? members.some(item => item.id === memberId && item.status === "正常" && item.id !== "m-01") && apps.some(item => item.id === appId && item.status === "运行中") && !(memberAccess[memberId] ?? []).includes(appId)
      : apps.some(item => item.id === appId && item.status === "运行中") && services.some(item => item.id === serviceId) && !(serviceAccess[appId] ?? []).includes(serviceId);
    if (!valid || !reason.trim()) { setMessage("请选择本校可用且尚未关联的成员、应用或 OMS 已授权服务，并填写原因。"); return; }
    const target = kind === "member-app" ? `${memberName(memberId)} → ${apps.find(item => item.id === appId)?.name}` : `${apps.find(item => item.id === appId)?.name} → ${services.find(item => item.id === serviceId)?.name}`;
    setConfirm({ title: "确认新增访问关系", description: `${target}；仅当前学校本地演示，不改变 OMS 服务授权或额度。原因：${reason}`, action: () => { if (kind === "member-app") onMemberAccess(memberId, appId, true); else onServiceAccess(appId, serviceId, true); onChange({ ...state, audits: [...state.audits, { id: `t-authz-${state.audits.length + 1}`, action: "新增访问关系", target, actor: "林老师（演示）", reason, status: "演示记录" }] }); setForm(null); setConfirm(null); setMessage("演示访问关系已更新，可在双方对象专题回读。"); } });
  };
  const revokeAccess = (row: AccessRow) => setConfirm({ title: "确认撤销访问关系", description: `${row.target}；仅撤销当前关系，不修改学校配额或其他成员访问。`, action: () => { if (row.kind === "member-app") onMemberAccess(row.memberId!, row.appId, false); else onServiceAccess(row.appId, row.serviceId!, false); onChange({ ...state, audits: [...state.audits, { id: `t-authz-${state.audits.length + 1}`, action: "撤销访问关系", target: row.target, actor: "林老师（演示）", reason: "管理员确认撤销", status: "演示记录" }] }); setConfirm(null); setMessage("演示访问关系已撤销；旧页面不应继续显示授权。"); } });
  const heading = section === "roles" ? "学校角色" : section === "access-grants" ? "访问关系" : "授权记录";
  return <>
    <PageHead eyebrow="成员与权限" title={heading} description={section === "roles" ? "本学校角色与动作版本；模板不自动赋权。" : section === "access-grants" ? "逐条查看并维护成员—应用、应用—服务关系；不修改平台权益。" : "仅当前学校的本产品授权变更记录。"} actions={canManage && !selectedId && section === "roles" ? <Button variant="primary" onClick={() => { setName(""); setActions([]); setMessage(""); setForm("role"); }}>新增学校角色</Button> : canManage && !selectedId && section === "access-grants" ? <Button variant="primary" onClick={() => { setReason(""); setMessage(""); setForm("access"); }}>新增访问关系</Button> : undefined}/>
    <Notice tone="warn">合成演示数据，不代表真实授权；当前学校为 {tenant.name}，TMS 不接收 OMS 平台权限。</Notice>
    {message && <Notice>{message}</Notice>}
    <Section>{section === "roles" ? <DataTable rows={state.roles} searchLabel="搜索学校角色" columns={[{ key: "name", label: "学校角色", render: row => row.name }, { key: "version", label: "版本", render: row => `v${row.version}` }, { key: "source", label: "来源", render: row => row.custom ? "自定义模板" : "默认模板（不自动授予）" }]} rowActions={row => [{ label: "角色动作", onClick: () => onOpen(row.id) }]}/> : section === "access-grants" ? <DataTable rows={accessRows} searchLabel="搜索访问关系" columns={[{ key: "target", label: "关联对象", render: row => row.target }, { key: "kind", label: "关系类别", render: row => row.kind === "member-app" ? "成员—应用" : "应用—服务" }, { key: "source", label: "来源", render: row => row.source }]} rowActions={row => [{ label: "关系资料", onClick: () => onOpen(row.id) }, ...(canManage ? [{ label: "撤销关系", onClick: () => revokeAccess(row) }] : [])]}/> : <DataTable rows={state.audits} searchLabel="搜索授权记录" columns={[{ key: "action", label: "事件", render: row => row.action }, { key: "target", label: "目标", render: row => row.target }, { key: "status", label: "状态", render: row => row.status }]} rowActions={row => [{ label: "记录详情", onClick: () => onOpen(row.id) }]}/>}</Section>
    {selectedId && <Drawer title={`详情 · ${selected && "name" in selected ? selected.name : selectedId}`} onClose={onClose} suspended={!!form || !!confirm}>{!selected ? <StatePanel state="empty" message="授权对象不存在或不属于当前学校。"/> : section === "roles" && "actions" in selected ? <><PageHead title={selected.name}/><DetailGrid rows={[{ label: "版本", value: `v${selected.version}` }, { label: "作用范围", value: tenant.name }, { label: "来源", value: selected.custom ? "自定义演示模板" : "默认模板，不自动授予" }]}/><Section title="角色动作"><div className="inline-list">{selected.actions.map(key => <span className="mini-pill" key={key}>{actionCatalog.find(item => item.key === key)?.label} · {key}</span>)}</div></Section></> : section === "access-grants" && "kind" in selected ? <><PageHead title={selected.target}/><DetailGrid rows={[{ label: "来源", value: selected.source }, { label: "当前学校", value: tenant.name }, { label: "服务上界", value: "仅 OMS 已授权服务；不包含额度数量" }]}/></> : section === "authz-records" && "action" in selected ? <><PageHead title={selected.action}/><DetailGrid rows={[{ label: "审计编号", value: selected.id }, { label: "目标", value: selected.target }, { label: "操作者", value: selected.actor }, { label: "原因", value: selected.reason }, { label: "结果", value: selected.status }]}/></> : null}</Drawer>}
    {form === "role" && <FormModal title="新增学校角色" onClose={() => setForm(null)} suspended={!!confirm}><label className="form-field">角色名称<input value={name} onChange={event => setName(event.target.value)}/></label><Section title="可授予动作">{actionCatalog.map(item => <label className="checkbox-field" key={item.key}><input type="checkbox" checked={actions.includes(item.key)} onChange={event => setActions(current => event.target.checked ? [...current, item.key] : current.filter(key => key !== item.key))}/>{item.label} · {item.key}{item.protected ? " · 高权限" : ""}</label>)}</Section><Notice>自定义角色只含本产品当前学校动作，不包含平台 `ops.*` 或额度写入。</Notice>{message && <Notice tone="bad">{message}</Notice>}<div className="form-actions"><Button onClick={() => setForm(null)}>取消</Button><Button variant="primary" onClick={createRole}>保存学校角色</Button></div></FormModal>}
    {form === "access" && <FormModal title="新增访问关系" onClose={() => setForm(null)} suspended={!!confirm}><label className="form-field">关系类别<select value={kind} onChange={event => setKind(event.target.value as "member-app" | "app-service")}><option value="member-app">成员—应用</option><option value="app-service">应用—服务</option></select></label>{kind === "member-app" && <label className="form-field">成员<select value={memberId} onChange={event => setMemberId(event.target.value)}>{members.filter(item => item.status === "正常" && item.id !== "m-01").map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}<label className="form-field">应用<select value={appId} onChange={event => setAppId(event.target.value)}>{apps.filter(item => item.status === "运行中").map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{kind === "app-service" && <label className="form-field">OMS 已授权服务<select value={serviceId} onChange={event => setServiceId(event.target.value)}>{services.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}<label className="form-field">变更原因<input value={reason} onChange={event => setReason(event.target.value)}/></label><Notice>关系仅更新本学校演示数据，不发放服务权益或额度。</Notice>{message && <Notice tone="bad">{message}</Notice>}<div className="form-actions"><Button onClick={() => setForm(null)}>取消</Button><Button variant="primary" onClick={saveAccess}>提交新增</Button></div></FormModal>}
    {confirm && <ConfirmModal title={confirm.title} description={confirm.description} onCancel={() => setConfirm(null)} onConfirm={confirm.action}/>}
  </>;
}
