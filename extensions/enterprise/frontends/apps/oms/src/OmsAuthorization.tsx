"use client";

import { useState } from "react";
import { Button, ConfirmModal, DataTable, DetailGrid, Drawer, FormModal, Notice, PageHead, Section, StatePanel, StatusBadge } from "@deeptutor/admin-ui";
import { tenants } from "./fixtures";

type Scope = "platform" | "school";
type ActionScope = Scope | "both";
type Principal = { id: string; name: string; external: string; status: string; verified: boolean };
type Role = { id: string; name: string; version: number; scope: Scope; actions: string[]; sensitive?: boolean; custom?: boolean; status?: string; proposerId?: string; reviewerId?: string };
type Assignment = { id: string; principalId: string; roleId: string; scope: Scope; schoolId?: string; proposerId?: string; reviewerId?: string; expires: string; status: string; version: number };
type Audit = { id: string; action: string; target: string; actor: string; status: string; version: number };
export type OmsAuthState = { principals: Principal[]; roles: Role[]; assignments: Assignment[]; audits: Audit[] };

const actionCatalog = [
  { key: "ops.oms.access", label: "进入平台后台", scope: "both" as ActionScope },
  { key: "ops.permissions.manage", label: "管理人员与角色", scope: "platform" as Scope, sensitive: true },
  { key: "ops.providers.manage", label: "配置服务", scope: "platform" as Scope, sensitive: true },
  { key: "ops.credentials.manage", label: "管理凭据", scope: "platform" as Scope, sensitive: true },
  { key: "ops.tenants.read", label: "查看目标学校", scope: "school" as Scope },
  { key: "ops.entitlements.manage", label: "管理服务权益", scope: "school" as Scope, sensitive: true },
  { key: "ops.quotas.manage", label: "管理额度", scope: "school" as Scope, sensitive: true },
  { key: "ops.supply.manage", label: "管理定向供给", scope: "both" as ActionScope, sensitive: true },
];
const actionAllowsScope = (action: (typeof actionCatalog)[number], scope: Scope) => action.scope === "both" || action.scope === scope;
const schoolName = (id?: string) => tenants.find(item => item.id === id)?.name ?? "未核验学校";
const actorNames: Record<string, string> = { "sec-a": "安全管理员甲", "sec-b": "安全管理员乙" };
const roleName = (roles: Role[], id: string) => roles.find(item => item.id === id)?.name ?? "未知角色";
const personName = (principals: Principal[], id: string) => principals.find(item => item.id === id)?.name ?? "未知主体";
const isSchoolReady = (id: string) => id !== "north";
const isFuture = (date: string) => !!date && date >= new Date().toISOString().slice(0, 10);

export const initialOmsAuth: OmsAuthState = {
  principals: [
    { id: "sec-a", name: "安全管理员甲", external: "已完成平台登录 · 演示主体", status: "有效", verified: true },
    { id: "sec-b", name: "安全管理员乙", external: "已完成平台登录 · 演示主体", status: "有效", verified: true },
    { id: "op-lin", name: "平台运营林", external: "已完成平台登录 · 演示主体", status: "有效", verified: true },
    { id: "aud-xu", name: "审计员许", external: "已完成平台登录 · 演示主体", status: "有效", verified: true },
    { id: "wait-chen", name: "待授权周", external: "已完成平台登录 · 演示主体", status: "待授权", verified: true },
    { id: "unverified", name: "外部状态待核验", external: "账号在线状态不可用", status: "待核验", verified: false },
  ],
  roles: [
    { id: "security", name: "平台安全管理员", version: 2, scope: "platform", actions: ["ops.oms.access", "ops.permissions.manage"], sensitive: true },
    { id: "config", name: "平台配置管理员", version: 1, scope: "platform", actions: ["ops.oms.access", "ops.providers.manage", "ops.credentials.manage"], sensitive: true },
    { id: "operator", name: "学校权益运营", version: 1, scope: "school", actions: ["ops.tenants.read", "ops.entitlements.manage", "ops.quotas.manage", "ops.supply.manage"], sensitive: true },
    { id: "auditor", name: "学校只读审计", version: 1, scope: "school", actions: ["ops.tenants.read"] },
  ],
  assignments: [
    { id: "as-sec-a", principalId: "sec-a", roleId: "security", scope: "platform", expires: "2027-12-31", status: "有效（演示）", version: 2 },
    { id: "as-sec-b", principalId: "sec-b", roleId: "security", scope: "platform", expires: "2027-12-31", status: "有效（演示）", version: 2 },
    { id: "as-op-lin", principalId: "op-lin", roleId: "operator", scope: "school", schoolId: "aurora", expires: "2027-12-31", status: "有效（演示）", version: 1 },
    { id: "as-aud-xu", principalId: "aud-xu", roleId: "auditor", scope: "school", schoolId: "harbor", expires: "2027-12-31", status: "有效（演示）", version: 1 },
  ],
  audits: [{ id: "authz-001", action: "演示授权登记", target: "星河实验学校 · 平台运营林", actor: "安全管理员甲", status: "演示记录", version: 1 }],
};

type SectionName = "platform-people" | "platform-roles" | "school-permissions" | "authz-audit";
type Form = "grant" | "role" | null;
type Confirm = { title: string; description: string; action: () => void };

export default function OmsAuthorization({ section, selectedId, view = "info", state, onChange, onOpen, onClose, role }: {
  section: SectionName; selectedId?: string; view?: string; state: OmsAuthState; onChange: (state: OmsAuthState) => void;
  onOpen: (id: string, view?: string) => void; onClose: () => void; role: string;
}) {
  const [actorId, setActorId] = useState("sec-a");
  const [personScenario, setPersonScenario] = useState<"normal" | "external-unavailable" | "expired">("normal");
  const [form, setForm] = useState<Form>(null);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [choosingPrincipal, setChoosingPrincipal] = useState(false);
  const [targetId, setTargetId] = useState("");
  const [roleId, setRoleId] = useState("operator");
  const [scope, setScope] = useState<Scope>("school");
  const [schoolId, setSchoolId] = useState("aurora");
  const [expires, setExpires] = useState("2027-12-31");
  const [reason, setReason] = useState("");
  const [newRoleName, setNewRoleName] = useState("");
  const [newActions, setNewActions] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const canGovern = role === "admin" && personScenario === "normal";
  const principalVerified = (principal: Principal) => principal.verified && !(personScenario === "external-unavailable" && principal.id === "op-lin");
  const principalStatus = (principal: Principal) => personScenario === "external-unavailable" && principal.id === "op-lin" ? "外部账号不可用" : principal.status;
  const assignmentStatus = (assignment: Assignment) => {
    if (!assignment.status.startsWith("有效")) return assignment.status;
    if (assignment.principalId === "op-lin" && personScenario === "external-unavailable") return "外部账号不可用";
    if (!isFuture(assignment.expires) || assignment.principalId === "op-lin" && personScenario === "expired") return "已过期";
    return assignment.status;
  };
  const canReview = state.assignments.some(item => item.principalId === actorId && item.roleId === "security" && item.scope === "platform" && item.status.startsWith("有效") && isFuture(item.expires));
  const person = state.principals.find(item => item.id === selectedId);
  const selectedRole = state.roles.find(item => item.id === selectedId);
  const selectedSchool = tenants.find(item => item.id === selectedId);
  const selectedAudit = state.audits.find(item => item.id === selectedId);
  const selected = section === "platform-people" ? person : section === "platform-roles" ? selectedRole : section === "school-permissions" ? selectedSchool : selectedAudit;
  const appendAudit = (action: string, target: string, status = "演示记录"): Audit => ({ id: `authz-${state.audits.length + 1}`, action, target, actor: actorNames[actorId], status, version: state.audits.length + 1 });
  const update = (next: OmsAuthState, success: string) => { onChange(next); setForm(null); setConfirm(null); setChoosingPrincipal(false); setMessage(success); };
  const beginGrant = (principalId = "", fixedSchool?: string) => { setTargetId(principalId); setRoleId("operator"); setScope("school"); setSchoolId(fixedSchool ?? "aurora"); setReason(""); setChoosingPrincipal(false); setForm("grant"); setMessage(""); };
  const roleChoice = state.roles.find(item => item.id === roleId && item.status !== "待第二人复核" && item.status !== "已拒绝");
  const assignmentRows = state.assignments.filter(item => assignmentStatus(item).startsWith("有效"));

  const grant = () => {
    const principal = state.principals.find(item => item.id === targetId && principalVerified(item));
    if (!principal || principal.id === actorId || !roleChoice || roleChoice.scope !== scope || (scope === "school" && !isSchoolReady(schoolId)) || !isFuture(expires) || !reason.trim()) { setMessage("请选择已核验且非本人的候选、匹配的角色与范围，并填写有效期和原因。"); return; }
    if (state.assignments.some(item => item.principalId === targetId && item.roleId === roleId && item.scope === scope && item.schoolId === (scope === "school" ? schoolId : undefined) && (item.status.startsWith("有效") || item.status === "待第二人复核"))) { setMessage("该范围内已有相同有效或待复核角色，不重复授权。"); return; }
    const assignment: Assignment = { id: `as-demo-${state.assignments.length + 1}`, principalId: targetId, roleId, scope, schoolId: scope === "school" ? schoolId : undefined, proposerId: actorId, expires, status: roleChoice.sensitive ? "待第二人复核" : "有效（演示）", version: roleChoice.version };
    setConfirm({ title: "确认平台角色授权", description: `${principal.name} · ${roleChoice.name} v${roleChoice.version} · ${scope === "school" ? schoolName(schoolId) : "平台范围"} · 至 ${expires}；${roleChoice.sensitive ? "高风险授权需另一名安全管理员复核。" : "确认后仅更新原型演示。"}原因：${reason}`, action: () => update({ ...state, assignments: [...state.assignments, assignment], audits: [...state.audits, appendAudit("角色授权", principal.name, assignment.status)] }, "已保存本地演示授权；不代表真实权限已生效。") });
  };
  const reviewAssignment = (item: Assignment, approve: boolean) => {
    const principal = state.principals.find(row => row.id === item.principalId);
    const definition = state.roles.find(row => row.id === item.roleId);
    if (!canReview || item.proposerId === actorId || item.status !== "待第二人复核" || !principal || !principalVerified(principal) || !definition || definition.version !== item.version || !isFuture(item.expires) || (item.scope === "school" && !isSchoolReady(item.schoolId ?? ""))) { setMessage("不能自批；候选身份、学校绑定、角色版本或有效期已失效。"); return; }
    const status = approve ? "有效（演示）" : "已拒绝";
    setConfirm({ title: approve ? "确认批准授权" : "确认拒绝授权", description: `${principal.name} · ${definition.name} v${item.version} · ${item.scope === "school" ? schoolName(item.schoolId) : "平台范围"}；${actorNames[item.proposerId ?? ""]}提议，${actorNames[actorId]}复核。`, action: () => update({ ...state, assignments: state.assignments.map(row => row.id === item.id ? { ...row, status, reviewerId: actorId } : row), audits: [...state.audits, appendAudit(approve ? "高风险授权批准" : "高风险授权拒绝", principal.name, status)] }, approve ? "演示高风险授权已通过第二人复核。" : "演示高风险授权已拒绝；未产生有效权限。") });
  };
  const revoke = (item: Assignment) => {
    if (item.roleId === "security" && assignmentRows.filter(row => row.roleId === "security" && row.scope === "platform").length <= 1) { setMessage("不能撤销最后一名可用平台安全管理员。"); return; }
    setConfirm({ title: "确认撤销平台角色", description: `${personName(state.principals, item.principalId)} · ${roleName(state.roles, item.roleId)}；对应菜单和操作立即失效（仅演示），历史审计保留。`, action: () => update({ ...state, assignments: state.assignments.map(row => row.id === item.id ? { ...row, status: "已撤权" } : row), audits: [...state.audits, appendAudit("角色撤权", personName(state.principals, item.principalId))] }, "演示授权已撤销；旧页面不得继续模拟成功。") });
  };
  const createRole = () => {
    if (newRoleName.trim().length < 2 || !newActions.length || state.roles.some(item => item.name === newRoleName.trim()) || newActions.some(key => !actionCatalog.some(item => item.key === key && actionAllowsScope(item, scope)))) { setMessage("角色名至少 2 字且不能重复；动作必须属于当前 OMS 应用域与所选范围。"); return; }
    const sensitive = newActions.some(key => actionCatalog.some(item => item.key === key && item.sensitive));
    const next: Role = { id: `custom-${state.roles.length + 1}`, name: newRoleName.trim(), scope, version: 1, actions: newActions, sensitive, custom: true, status: sensitive ? "待第二人复核" : "有效（演示）", proposerId: actorId };
    setConfirm({ title: "确认新增自定义角色", description: `${next.name} · ${scope === "platform" ? "平台" : "学校"}范围 · ${next.actions.join("、")}；${sensitive ? "高风险模板须另一名安全管理员复核后方可授权。" : "不会静默扩展既有授权。"}`, action: () => update({ ...state, roles: [...state.roles, next], audits: [...state.audits, appendAudit("新增角色模板", next.name, next.status)] }, sensitive ? "演示角色模板待第二人复核；不能用于授权。" : "演示角色模板已新增；没有自动授予任何主体。") });
  };
  const reviewRole = (item: Role, approve: boolean) => {
    if (!canReview || item.status !== "待第二人复核" || item.proposerId === actorId) { setMessage("高风险模板须由不同的有效平台安全管理员复核。"); return; }
    const status = approve ? "有效（演示）" : "已拒绝";
    setConfirm({ title: approve ? "确认批准角色模板" : "确认拒绝角色模板", description: `${item.name} · ${item.actions.join("、")}；${actorNames[item.proposerId ?? ""]}提议，${actorNames[actorId]}复核。`, action: () => update({ ...state, roles: state.roles.map(row => row.id === item.id ? { ...row, status, reviewerId: actorId, version: row.version + 1 } : row), audits: [...state.audits, appendAudit(approve ? "高风险角色模板批准" : "高风险角色模板拒绝", item.name, status)] }, approve ? "高风险模板已通过演示复核，可用于新授权；既有授权不自动扩权。" : "高风险模板已拒绝，不可用于授权。") });
  };
  const heading: Record<SectionName, string> = { "platform-people": "平台人员", "platform-roles": "角色与动作", "school-permissions": "平台人员学校范围", "authz-audit": "授权审计" };
  const desc: Record<SectionName, string> = { "platform-people": "只管理已登录的平台人员及本产品 OMS 角色，不管理学校账号。", "platform-roles": "角色模板只包含 OMS 动作；委托上界与业务执行权分开。", "school-permissions": "逐校核对平台运营人员的 OMS 操作范围；不列出或管理学校账号。", "authz-audit": "只读追溯平台人员授权与审批，不记录凭据或私有正文。" };
  const rows = section === "platform-people" ? state.principals : section === "platform-roles" ? state.roles : section === "school-permissions" ? tenants : state.audits;
  const columns = section === "platform-people" ? [
    { key: "name", label: "人员", render: (row: Principal) => row.name }, { key: "status", label: "状态", render: (row: Principal) => principalStatus(row) }, { key: "roles", label: "有效授权", render: (row: Principal) => `${assignmentRows.filter(item => item.principalId === row.id).length} 项` },
  ] : section === "platform-roles" ? [
    { key: "name", label: "角色", render: (row: Role) => row.name }, { key: "scope", label: "范围", render: (row: Role) => row.scope === "platform" ? "平台" : "指定学校" }, { key: "version", label: "版本", render: (row: Role) => `v${row.version}` }, { key: "status", label: "状态", render: (row: Role) => row.status ?? "有效（默认模板）" },
  ] : section === "school-permissions" ? [
    { key: "name", label: "学校", render: (row: (typeof tenants)[number]) => row.name }, { key: "status", label: "绑定", render: (row: (typeof tenants)[number]) => isSchoolReady(row.id) ? "已核验（演示）" : "待核验" }, { key: "count", label: "平台人员授权", render: (row: (typeof tenants)[number]) => `${assignmentRows.filter(item => item.schoolId === row.id).length} 项` },
  ] : [
    { key: "action", label: "事件", render: (row: Audit) => row.action }, { key: "target", label: "目标", render: (row: Audit) => row.target }, { key: "status", label: "状态", render: (row: Audit) => row.status },
  ];

  return <>
    <PageHead eyebrow="审计与治理" title={heading[section]} description={desc[section]} actions={canGovern && !selectedId && section === "platform-people" ? <Button variant="primary" onClick={() => beginGrant()}>授予平台角色</Button> : canGovern && !selectedId && section === "platform-roles" ? <Button variant="primary" onClick={() => { setNewRoleName(""); setNewActions([]); setScope("school"); setForm("role"); }}>新增自定义角色</Button> : undefined}/>
    <Notice tone="warn">合成演示数据，不代表真实授权；不请求 EduPlus2 或权限 API。</Notice>
    {role === "admin" && ["platform-people", "platform-roles", "school-permissions"].includes(section) && <div className="scenario-bar">
      <label className="form-field">演示审批人<select value={actorId} onChange={event => setActorId(event.target.value)}><option value="sec-a">安全管理员甲</option><option value="sec-b">安全管理员乙</option></select></label>
      <label className="form-field">演示平台人员状态<select value={personScenario} onChange={event => setPersonScenario(event.target.value as typeof personScenario)}><option value="normal">正常</option><option value="external-unavailable">平台运营林 · 外部账号不可用</option><option value="expired">平台运营林 · 授权已过期</option></select></label>
    </div>}
    {personScenario !== "normal" && <Notice tone="warn">仅演示平台运营林的失效状态：已停止计入有效授权。请切回“正常”再演练授权写入；此处不会修改外部账号或真实期限。</Notice>}
    {message && <Notice tone={message.includes("不能") || message.includes("请") || message.includes("未核验") ? "bad" : "info"}>{message}</Notice>}
    <Section><DataTable rows={rows as { id: string }[]} searchLabel={`搜索${heading[section]}`} columns={columns as never} rowActions={row => {
      const id = row.id;
      if (section === "platform-people") return [{ label: "身份与核验", onClick: () => onOpen(id, "identity") }, { label: "角色与范围", onClick: () => onOpen(id, "roles") }];
      if (section === "platform-roles") { const definition = state.roles.find(item => item.id === id); return [{ label: "角色动作", onClick: () => onOpen(id, "actions") }, ...(canGovern && definition?.status === "待第二人复核" && definition.proposerId !== actorId && canReview ? [{ label: "复核角色", onClick: () => reviewRole(definition, true) }, { label: "拒绝角色", onClick: () => reviewRole(definition, false) }] : [])]; }
      if (section === "school-permissions") return [{ label: "平台人员范围", onClick: () => onOpen(id, "grants") }];
      return [{ label: "事件详情", onClick: () => onOpen(id, "info") }];
    }}/></Section>
    {selectedId && <Drawer title={`详情 · ${selected && "name" in selected ? selected.name : selectedId}`} onClose={onClose} suspended={!!form || !!confirm}>
      {!selected ? <StatePanel state="empty" message="记录不存在或不在当前授权范围。"/> : section === "platform-people" && person ? <>
        <PageHead title={person.name} breadcrumbs={[{ label: heading[section], onClick: onClose }, { label: person.name }]}/>
        {view === "identity" && <DetailGrid rows={[{ label: "外部身份", value: principalVerified(person) ? person.external : "账号在线状态不可用" }, { label: "预期登录 Client", value: "eduplus-platform-admin" }, { label: "接入状态", value: "仅指定对接 Client，未验证真实换票" }, { label: "核验状态", value: principalVerified(person) ? "已核验（演示）" : "暂不可操作" }, { label: "本产品状态", value: principalStatus(person) }]}/>}
        {view === "roles" && <><Section title="当前角色与范围"><DataTable rows={state.assignments.filter(item => item.principalId === person.id)} searchLabel="搜索人员授权" columns={[{ key: "role", label: "角色", render: row => roleName(state.roles, row.roleId) }, { key: "scope", label: "有效范围", render: row => row.scope === "school" ? schoolName(row.schoolId) : "平台范围" }, { key: "expires", label: "有效期", render: row => row.expires }, { key: "status", label: "状态", render: row => assignmentStatus(row) }]} rowActions={row => canGovern && row.status === "待第二人复核" && canReview && row.proposerId !== actorId ? [{ label: "复核授权", onClick: () => reviewAssignment(row, true) }, { label: "拒绝授权", onClick: () => reviewAssignment(row, false) }] : canGovern && row.status.startsWith("有效") ? [{ label: "撤销角色", onClick: () => revoke(row) }] : []}/></Section>{canGovern && principalVerified(person) && person.id !== actorId && <Button onClick={() => beginGrant(person.id)}>授予角色</Button>}</>}
      </> : section === "platform-roles" && selectedRole ? <><PageHead title={selectedRole.name} breadcrumbs={[{ label: heading[section], onClick: onClose }, { label: selectedRole.name }]}/><DetailGrid rows={[{ label: "角色版本", value: `v${selectedRole.version}` }, { label: "作用范围", value: selectedRole.scope === "platform" ? "平台" : "指定学校" }, { label: "来源", value: selectedRole.custom ? "演示自定义模板" : "默认模板（不自动授权）" }, { label: "状态", value: selectedRole.status ?? "有效（默认模板）" }, { label: "敏感操作", value: selectedRole.sensitive ? "需双人复核" : "普通授权" }]}/><Section title="角色动作"><div className="inline-list">{selectedRole.actions.map(key => <span className="mini-pill" key={key}>{actionCatalog.find(item => item.key === key)?.label ?? key} · {key}</span>)}</div></Section></> : section === "school-permissions" && selectedSchool ? <><PageHead title={selectedSchool.name} breadcrumbs={[{ label: heading[section], onClick: onClose }, { label: selectedSchool.name }]}/><Notice>{isSchoolReady(selectedSchool.id) ? "学校绑定已核验（演示），仅显示该校本产品平台人员授权。" : "学校绑定待核验，不能发放学校范围授权。"}</Notice><Section title="获授权平台人员"><DataTable rows={state.assignments.filter(item => item.schoolId === selectedSchool.id)} searchLabel="搜索学校人员授权" columns={[{ key: "person", label: "人员", render: row => personName(state.principals, row.principalId) }, { key: "role", label: "角色", render: row => roleName(state.roles, row.roleId) }, { key: "expires", label: "有效期", render: row => row.expires }, { key: "status", label: "状态", render: row => assignmentStatus(row) }]} rowActions={row => canGovern && row.status === "待第二人复核" && canReview && row.proposerId !== actorId ? [{ label: "复核授权", onClick: () => reviewAssignment(row, true) }, { label: "拒绝授权", onClick: () => reviewAssignment(row, false) }] : canGovern && row.status.startsWith("有效") ? [{ label: "撤销学校授权", onClick: () => revoke(row) }] : []}/></Section>{canGovern && isSchoolReady(selectedSchool.id) && <Button onClick={() => beginGrant("", selectedSchool.id)}>授予学校范围角色</Button>}</> : section === "authz-audit" && selectedAudit ? <><PageHead title={selectedAudit.action} breadcrumbs={[{ label: heading[section], onClick: onClose }, { label: selectedAudit.action }]}/><DetailGrid rows={[{ label: "审计编号", value: selectedAudit.id }, { label: "目标", value: selectedAudit.target }, { label: "操作者", value: selectedAudit.actor }, { label: "结果", value: selectedAudit.status }, { label: "版本", value: `v${selectedAudit.version}` }]}/></> : null}
    </Drawer>}
    {form === "grant" && canGovern && <FormModal title="授予平台角色" onClose={() => { setChoosingPrincipal(false); setForm(null); }} suspended={!!confirm || choosingPrincipal}>
      <div className="form-grid">
        <div className="form-field">
          <span>平台人员</span>
          <div className="principal-picker-current">
            <strong>{state.principals.find(item => item.id === targetId)?.name ?? "尚未选择"}</strong>
            <Button onClick={() => setChoosingPrincipal(true)}>选择平台人员</Button>
          </div>
        </div>
        <label className="form-field">授权范围<select value={scope} onChange={event => { const next = event.target.value as Scope; setScope(next); setRoleId(next === "platform" ? "config" : "operator"); }}><option value="school">指定学校</option><option value="platform">平台</option></select></label>
        {scope === "school" && <label className="form-field">目标学校<select value={schoolId} onChange={event => setSchoolId(event.target.value)}>{tenants.map(item => <option key={item.id} value={item.id} disabled={!isSchoolReady(item.id)}>{item.name}{!isSchoolReady(item.id) ? " · 待核验" : ""}</option>)}</select></label>}
        <label className="form-field">角色<select value={roleId} onChange={event => setRoleId(event.target.value)}>{state.roles.filter(item => item.scope === scope && item.status !== "待第二人复核" && item.status !== "已拒绝").map(item => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select></label>
        <label className="form-field">有效期<input type="date" value={expires} onChange={event => setExpires(event.target.value)}/></label>
        <label className="form-field">授权原因<input value={reason} onChange={event => setReason(event.target.value)} placeholder="说明授权用途"/></label>
      </div>
      <Section title="有效权限预览"><p>{roleChoice?.actions.map(key => actionCatalog.find(item => item.key === key)?.label ?? key).join("、") || "请选择角色"} · {scope === "school" ? schoolName(schoolId) : "平台范围"} · 至 {expires}</p></Section>
      <Notice tone="warn">仅使用已登录且已核验的演示主体；高风险角色需要第二人复核。委托上界不等于业务执行权。</Notice>
      {message && <Notice tone="bad">{message}</Notice>}
      <div className="form-actions"><Button onClick={() => setForm(null)}>取消</Button><Button variant="primary" onClick={grant}>提交授权</Button></div>
    </FormModal>}
    {form === "grant" && choosingPrincipal && canGovern && <FormModal title="选择平台人员" onClose={() => setChoosingPrincipal(false)}>
      <Notice>仅选择已登记且身份已核验的平台人员；不查询或授权学校账号。当前为本地演示，尚未接入 eduplus-platform-admin 真实登录登记。</Notice>
      <div className="principal-chooser"><DataTable
        rows={state.principals}
        searchLabel="搜索平台人员"
        searchText={item => `${item.name} ${item.status} ${item.external}`}
        columns={[
          { key: "name", label: "人员", render: item => item.name },
          { key: "status", label: "状态", render: item => item.status },
          { key: "verified", label: "身份核验", render: item => principalVerified(item) ? "已核验（演示）" : "待核验" },
        ]}
        rowActions={item => [{ label: item.id === actorId ? "不可选择本人" : !principalVerified(item) ? "身份待核验" : "选用", disabled: item.id === actorId || !principalVerified(item), onClick: () => { setTargetId(item.id); setChoosingPrincipal(false); } }]}
      /></div>
      <div className="form-actions"><Button onClick={() => setChoosingPrincipal(false)}>取消</Button></div>
    </FormModal>}
    {form === "role" && canGovern && <FormModal title="新增自定义角色" onClose={() => setForm(null)} suspended={!!confirm}><label className="form-field">角色名称<input value={newRoleName} onChange={event => setNewRoleName(event.target.value)}/></label><label className="form-field">角色范围<select value={scope} onChange={event => { setScope(event.target.value as Scope); setNewActions([]); }}><option value="school">指定学校</option><option value="platform">平台</option></select></label><Section title="可选动作">{actionCatalog.filter(item => actionAllowsScope(item, scope)).map(item => <label className="checkbox-field" key={item.key}><input type="checkbox" checked={newActions.includes(item.key)} onChange={event => setNewActions(current => event.target.checked ? [...current, item.key] : current.filter(key => key !== item.key))}/>{item.label} · {item.key}{item.sensitive ? " · 高风险" : ""}</label>)}</Section><Notice>自定义角色仅属于 OMS；新增模板不会自动扩权或授予已有人员。</Notice>{message && <Notice tone="bad">{message}</Notice>}<div className="form-actions"><Button onClick={() => setForm(null)}>取消</Button><Button variant="primary" onClick={createRole}>保存角色模板</Button></div></FormModal>}
    {confirm && <ConfirmModal title={confirm.title} description={confirm.description} onCancel={() => setConfirm(null)} onConfirm={confirm.action}/>}
  </>;
}
