"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, AppWindow, BookOpenCheck, ClipboardList, LayoutDashboard, ScrollText, ShieldCheck, UsersRound, Sparkles } from "lucide-react";
import type { DisplayState } from "@deeptutor/api-contracts";
import { AdminShell, Button, DataTable, DetailGrid, Drawer, FormModal, MetricStrip, Notice, PageHead, Section, StatePanel, StatusBadge, Tabs, useSessionFilter } from "@deeptutor/admin-ui";
import { OcrServiceList, ServiceDetail, ServiceList } from "@deeptutor/service-components";
import { apps as initialApps, calls, documents, events, grants, knowledge, members, processingTasks, services, tenant } from "./fixtures";
import TmsSkills from "./TmsSkills";

const demoBase = "/tms/prototype/demo-school";
const navigation = (base: string) => [
  { label: "工作台", items: [{ label: "学校概览", href: base, icon: <LayoutDashboard/> }] },
  { label: "成员与权限", items: [{ label: "成员列表", href: `${base}/members`, icon: <UsersRound/> }] },
  { label: "应用与接入", items: [{ label: "应用列表", href: `${base}/apps`, icon: <AppWindow/> }] },
  { label: "服务与配额", items: [{ label: "可用服务", href: `${base}/services`, icon: <ClipboardList/> }, { label: "配额清单", href: `${base}/quotas`, icon: <ShieldCheck/> }, { label: "Skills", href: `${base}/skills`, icon: <Sparkles/> }] },
  { label: "知识与内容", items: [{ label: "知识库列表", href: `${base}/knowledge`, icon: <BookOpenCheck/> }] },
  { label: "用量与记录", items: [{ label: "调用用量", href: `${base}/usage`, icon: <Activity/> }, { label: "管理事件", href: `${base}/events`, icon: <ScrollText/> }] },
];
function badge(value: string) {
  const tone = value.includes("失败") || value.includes("用尽") ? "bad" : value.includes("待") || value.includes("处理") || value.includes("核对") ? "warn" : "good";
  return <StatusBadge tone={tone}>{value}</StatusBadge>;
}
function title(value: string, sub?: string) { return <><span className="cell-title">{value}</span>{sub && <span className="cell-sub">{sub}</span>}</>; }

export default function TmsPrototype({ schoolCode = "demo-school" }: { schoolCode?: string }) {
  const base = schoolCode === "demo-school" ? demoBase : `/tms/prototype/${encodeURIComponent(schoolCode)}`;
  const nav = navigation(base);
  const pathname = usePathname();
  const [route, setRoute] = useState(pathname);
  useEffect(() => { const onPopState = () => setRoute(window.location.pathname); window.addEventListener("popstate", onPopState); return () => window.removeEventListener("popstate", onPopState); }, []);
  const segments = route === base ? [] : route.startsWith(`${base}/`) ? route.slice(base.length + 1).split("/").filter(Boolean) : ["invalid"];
  const root = segments[0] || "home";
  const go = (path: string) => { setRoute(path); if (window.location.pathname !== path) window.history.pushState(null, "", path); };
  const [role, setRole] = useState("admin");
  const [scenario, setScenario] = useState("normal");
  const [tab, setTab] = useState("概览");
  const [method, setMethod] = useSessionFilter("tms:quota-method", "all");
  const [apps, setApps] = useState(initialApps);
  const [formOpen, setFormOpen] = useState(false);
  const [appName, setAppName] = useState("");
  const [appOwner, setAppOwner] = useState("教务处");
  const [message, setMessage] = useState("");
  const [catalogTab, setCatalogTab] = useState("全部服务");
  const [memberAccess, setMemberAccess] = useState<Record<string, string[]>>({});
  const [accessApp, setAccessApp] = useState("app-01");
  const eligibleApps = apps.filter(item => item.status === "运行中" && item.services !== "未授权");
  const viewState: DisplayState = role === "member" || scenario === "forbidden" ? "forbidden" : scenario === "loading" ? "loading" : scenario === "error" ? "error" : scenario === "empty" ? "empty" : "ready";
  const crumbs = (section: string, parent: string, detail?: string) => [{ label: "工作台", onClick: () => go(base) }, { label: section, onClick: () => go(parent) }, ...(detail ? [{ label: detail }] : [])];
  const list = <T extends { id: string }>(rows: T[], columns: { key: string; label: string; render: (row: T) => React.ReactNode }[], route: (row: T) => string, searchLabel: string) => <Section title="记录列表"><DataTable rows={viewState === "empty" ? [] : rows} columns={columns} searchLabel={searchLabel} persistKey={`tms:${root}`} onOpen={row => go(route(row))} state={viewState}/></Section>;
  const renderContent = (segments: string[]): React.ReactNode => {
  let content: React.ReactNode;

  if (segments[1] && root === "tenants") {
    content = <StatePanel state="forbidden" message="TMS 只能访问可信身份绑定的当前学校。"/>;
  } else if (root === "home") {
    const tasks = [
      { id: "t-1", task: "文档 OCR 额度已用尽", context: "新的 OCR 调用暂不可用；登录和管理不受影响", status: "需关注", path: `${base}/quotas/q-103` },
      { id: "t-2", task: "历史试题归档索引失败", context: "查看知识库详情与处理记录", status: "待处理", path: `${base}/knowledge/kb-03` },
      { id: "t-3", task: "一条模型用量待核对", context: "未知用量不显示为零", status: "待核对", path: `${base}/usage/use-7422` },
    ];
    content = <><PageHead eyebrow="TENANT OVERVIEW" title="工作台" description={`${tenant.name} · 学校状态来自 ${tenant.source}，最近同步 ${tenant.synced}`} actions={<div className="scenario-bar"><label htmlFor="scenario">审计场景</label><select id="scenario" value={scenario} onChange={e => setScenario(e.target.value)}><option value="normal">正常</option><option value="loading">加载中</option><option value="empty">空记录</option><option value="error">读取失败</option><option value="forbidden">无权限</option></select></div>}/>
      <MetricStrip items={[{ label: "成员", value: `${members.length}`, note: "由 EduPlus2 同步" }, { label: "应用", value: `${apps.length}`, note: "本学校归口" }, { label: "可用服务", value: `${services.length}`, note: "由 OMS 授权" }, { label: "待处理事项", value: "3", note: "配额、知识与用量", tone: "warning" }]}/>
      <Section title="待处理事项" subtitle="只展示当前学校需要关注的记录"><DataTable rows={viewState === "empty" ? [] : tasks} state={viewState} searchLabel="搜索事项" onOpen={row => go(row.path)} columns={[{ key: "task", label: "事项", render: row => title(row.task, row.context) }, { key: "status", label: "状态", render: row => badge(row.status) }]}/></Section><div className="audit-note">演示环境不接入真实身份、额度、知识库或调用总账。</div></>;
  } else if (root === "members") {
    const member = members.find(item => item.id === segments[1]);
    content = member ? <><PageHead eyebrow="MEMBER DETAIL" title={member.name} breadcrumbs={crumbs("成员与权限", `${base}/members`, member.name)} description="成员身份与组织归属来自 EduPlus2；TMS 仅管理获授权的资源访问关系。"/>
      <DetailGrid rows={[{ label: "角色", value: member.role }, { label: "部门", value: member.department }, { label: "同步状态", value: badge(member.status) }, { label: "身份来源", value: member.source }, { label: "当前学校", value: tenant.name }, { label: "资源授权", value: "按应用与服务资格生效" }]}/>
      <Tabs tabs={["应用访问", "服务资格", "使用记录"]} active={tab === "概览" ? "应用访问" : tab} onChange={setTab}/>
      {(tab === "概览" || tab === "应用访问") && <><div className="section-head"><h2>应用访问</h2><Button onClick={() => { setMessage(""); setFormOpen(!formOpen); }}>授予应用访问（演示）</Button></div>{formOpen && <FormModal title="授予应用访问" onClose={() => setFormOpen(false)}><div className="side-panel"><Notice>只能在 OMS 已授权的服务范围内安排访问，不能调整配额总量或余额。</Notice><label className="form-field">应用<select value={accessApp} onChange={e => setAccessApp(e.target.value)}>{eligibleApps.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{formOpen && message && <Notice tone="bad">{message}</Notice>}<div className="form-actions"><Button variant="primary" onClick={() => { if (!eligibleApps.some(item => item.id === accessApp)) { setMessage("只能授权已运行且使用 OMS 获授权服务的应用。"); return; } setMemberAccess({ ...memberAccess, [member.id]: [...new Set([...(memberAccess[member.id] ?? ["app-01", "app-02"]), accessApp])] }); setMessage("演示访问关系已更新；未写入真实授权服务。" ); setFormOpen(false); }}>确认演示授权</Button><Button onClick={() => setFormOpen(false)}>取消</Button></div></div></FormModal>}{!formOpen && message && <Notice>{message}</Notice>}<DataTable rows={apps.filter(item => (memberAccess[member.id] ?? ["app-01", "app-02"]).includes(item.id))} searchLabel="搜索应用" onOpen={row => go(`${base}/apps/${row.id}`)} columns={[{ key: "name", label: "应用", render: row => row.name }, { key: "status", label: "状态", render: row => badge(row.status) }]}/></>}
      {tab === "服务资格" && <ServiceList services={services} onOpen={id => go(`${base}/services/${id}`)}/>}
      {tab === "使用记录" && <DataTable rows={calls.filter(c => c.member === member.name)} searchLabel="搜索调用" onOpen={row => go(`${base}/usage/${row.id}`)} columns={[{ key: "id", label: "调用", render: row => row.id }, { key: "service", label: "服务", render: row => row.service }, { key: "usage", label: "用量", render: row => row.usage }]}/>}
      </> : <><PageHead eyebrow="PEOPLE & ACCESS" title="成员与权限" description="查看 EduPlus2 同步成员，按学校授权管理资源访问，不修改外部身份。"/>{list(members, [{ key: "name", label: "成员", render: row => title(row.name, row.department) }, { key: "role", label: "角色", render: row => row.role }, { key: "source", label: "来源", render: row => row.source }, { key: "status", label: "状态", render: row => badge(row.status) }], row => `${base}/members/${row.id}`, "搜索成员")}</>;
  } else if (root === "apps") {
    const app = apps.find(item => item.id === segments[1]);
    content = app ? <><PageHead eyebrow="APPLICATION DETAIL" title={app.name} breadcrumbs={crumbs("应用与接入", `${base}/apps`, app.name)} description="应用接入与成员访问属于当前学校；平台服务范围由 OMS 决定。"/>
      <DetailGrid rows={[{ label: "应用归口", value: app.owner }, { label: "状态", value: badge(app.status) }, { label: "可用服务", value: app.services }, { label: "最近调用", value: app.last }, { label: "学校", value: tenant.name }, { label: "接入记录", value: "演示环境" }]}/>
      {app.id === "app-04" && <Notice tone="warn">EduPlus2 client 归口尚未与当前学校匹配。此应用不能激活接入或调用服务，且不会显示其他学校的信息。</Notice>}
      <Tabs tabs={["可用服务", "成员权限", "接入记录", "调用记录"]} active={tab === "概览" ? "可用服务" : tab} onChange={setTab}/>
      {(tab === "概览" || tab === "可用服务") && <ServiceList services={services.filter(s => app.services.includes(s.name))} onOpen={id => go(`${base}/services/${id}`)}/>}
      {tab === "成员权限" && <DataTable rows={members.filter(item => (memberAccess[item.id] ?? ["app-01", "app-02"]).includes(app.id))} searchLabel="搜索成员" onOpen={row => go(`${base}/members/${row.id}`)} columns={[{ key: "name", label: "成员", render: row => row.name }, { key: "role", label: "角色", render: row => row.role }]}/>}
      {tab === "接入记录" && <DetailGrid rows={[{ label: "应用标识", value: app.id }, { label: "归口部门", value: app.owner }, { label: "外部身份来源", value: "EduPlus2" }, { label: "归口校验", value: app.id === "app-04" ? badge("待核对") : badge("正常") }, { label: "当前学校", value: tenant.name }, { label: "密钥", value: "不在演示界面展示" }]}/>}
      {tab === "调用记录" && <DataTable rows={calls.filter(c => c.app === app.name)} searchLabel="搜索调用" onOpen={row => go(`${base}/usage/${row.id}`)} columns={[{ key: "id", label: "调用", render: row => row.id }, { key: "service", label: "服务", render: row => row.service }, { key: "usage", label: "用量", render: row => row.usage }]}/>}
      </> : <><PageHead eyebrow="APPLICATIONS" title="应用与接入" description="在本学校范围内管理应用归口与访问；不自行扩大服务配额。" actions={role === "admin" ? <Button variant="primary" onClick={() => { setMessage(""); setFormOpen(!formOpen); }}>新增应用（演示）</Button> : undefined}/>
        {formOpen && <FormModal title="新增应用" onClose={() => setFormOpen(false)}><div className="side-panel"><Notice>仅修改当前页面本地数据，不向 EduPlus2 或 DeepTutor 发送请求。</Notice><div className="form-grid"><label className="form-field">应用名称<input value={appName} onChange={e => setAppName(e.target.value)} placeholder="例如：教研助手"/></label><label className="form-field">归口部门<select value={appOwner} onChange={event => setAppOwner(event.target.value)}><option>教务处</option><option>数学教研组</option></select></label></div>{formOpen && message && <Notice tone="bad">{message}</Notice>}<div className="form-actions"><Button variant="primary" onClick={() => { if (appName.trim().length < 2) { setMessage("应用名称至少需要 2 个字符。"); return; } setApps([...apps, { id: `app-demo-${Date.now()}`, name: appName.trim(), owner: appOwner, status: "待接入", services: "未授权", last: "尚无调用" }]); setAppName(""); setFormOpen(false); setMessage("演示应用已加入当前学校列表；未创建真实 client。" ); }}>保存演示应用</Button><Button onClick={() => setFormOpen(false)}>取消</Button></div></div></FormModal>}{!formOpen && message && <Notice>{message}</Notice>}
        {list(apps, [{ key: "name", label: "应用", render: row => title(row.name, row.owner) }, { key: "services", label: "可用服务", render: row => row.services }, { key: "last", label: "最近调用", render: row => row.last }, { key: "status", label: "状态", render: row => badge(row.status) }], row => `${base}/apps/${row.id}`, "搜索应用")}</>;
  } else if (root === "skills") {
    content = <TmsSkills selectedId={segments[1] ? decodeURIComponent(segments[1]) : undefined} onOpen={id => go(`${base}/skills/${encodeURIComponent(id)}`)} onClose={() => go(`${base}/skills`)} state={viewState}/>;
  } else if (root === "services") {
    const service = services.find(item => item.id === segments[1]);
    content = service ? <><PageHead eyebrow="SERVICE DETAIL" title={service.name} breadcrumbs={crumbs("可用服务", `${base}/services`, service.name)} description="只显示本学校获授权服务；服务配置由 OMS 维护。"/><ServiceDetail service={service}/>
      {service.id === "ocr" && <Notice tone="warn">文档 OCR 赠送额度已用尽；仅此服务的新调用受限，登录、管理和其他服务仍可使用。</Notice>}
      <Tabs tabs={["关联配额", "使用对象", "调用明细"]} active={tab === "概览" ? "关联配额" : tab} onChange={setTab}/>
      {(tab === "概览" || tab === "关联配额") && <DataTable rows={grants.filter(g => g.serviceId === service.id)} searchLabel="搜索配额" onOpen={row => go(`${base}/quotas/${row.id}`)} columns={[{ key: "id", label: "配额记录", render: row => title(row.id, row.method) }, { key: "remaining", label: "剩余", render: row => `${row.remaining} ${row.unit}` }, { key: "status", label: "状态", render: row => badge(row.status) }]}/>}
      {tab === "使用对象" && <DataTable rows={apps.filter(a => a.services.includes(service.name))} searchLabel="搜索应用" onOpen={row => go(`${base}/apps/${row.id}`)} columns={[{ key: "name", label: "应用", render: row => row.name }, { key: "owner", label: "归口", render: row => row.owner }]}/>}
      {tab === "调用明细" && <DataTable rows={calls.filter(c => c.service === service.name)} searchLabel="搜索调用" onOpen={row => go(`${base}/usage/${row.id}`)} columns={[{ key: "id", label: "调用", render: row => row.id }, { key: "usage", label: "用量", render: row => row.usage }, { key: "status", label: "状态", render: row => badge(row.status) }]}/>}
      </> : <><PageHead eyebrow="AVAILABLE SERVICES" title="可用服务" description="按 OMS 授权范围查看模型、Agent、工具与知识处理服务。"/><Tabs tabs={["全部服务", "文档识别与解析"]} active={catalogTab} onChange={setCatalogTab}/>{catalogTab === "全部服务" ? <ServiceList services={viewState === "empty" ? [] : services} state={viewState} onOpen={id => { setTab("概览"); go(`${base}/services/${id}`); }}/> : <OcrServiceList services={services.filter(item => item.category === "知识处理")} state={viewState} onOpen={id => { setTab("概览"); go(`${base}/services/${id}`); }}/>}</>;
  } else if (root === "quotas") {
    const quota = grants.find(item => item.id === segments[1]);
    content = quota ? <><PageHead eyebrow="READ-ONLY QUOTA DETAIL" title={`配额 ${quota.id}`} breadcrumbs={crumbs("配额清单", `${base}/quotas`, quota.id)} description="由 OMS 配置与授予；这里仅可查看。"/>
      <DetailGrid rows={[{ label: "服务", value: quota.service }, { label: "获取方式", value: quota.method }, { label: "状态", value: badge(quota.status) }, { label: "授予总量", value: `${quota.total} ${quota.unit}` }, { label: "已消耗", value: `${quota.used} ${quota.unit}` }, { label: "剩余额度", value: `${quota.remaining} ${quota.unit}` }, { label: "有效期", value: quota.valid }, { label: "授予方", value: "OMS 平台运营" }, { label: "所属学校", value: tenant.name }]}/>
      <Notice>配额创建、赠送、充值、调整和撤销均只能由 OMS 完成。当前页面没有任何配额写入能力。</Notice>
      <Section title="关联服务"><button className="detail-link" onClick={() => go(`${base}/services/${quota.serviceId}`)}>{quota.service} →</button></Section>
      <Section title="实际消耗明细" subtitle="用量未知时显示待核对，不显示为零"><DataTable rows={calls.filter(c => c.service === quota.service)} searchLabel="搜索调用" onOpen={row => go(`${base}/usage/${row.id}`)} columns={[{ key: "id", label: "调用", render: row => title(row.id, row.time) }, { key: "usage", label: "用量", render: row => row.usage }, { key: "grant", label: "额度消耗", render: row => row.grant }, { key: "status", label: "状态", render: row => badge(row.status) }]}/></Section></> : <><PageHead eyebrow="READ-ONLY ENTITLEMENTS" title="配额清单" description="同一清单展示赠送与充值；额度由 OMS 授予，您只能查询。"/><Notice>配额用尽只限制对应服务的新调用，登录、管理和其他服务不受影响。</Notice>
        <Section title="本学校全部配额"><DataTable rows={viewState === "empty" ? [] : grants.filter(q => method === "all" || q.method === method)} searchLabel="搜索配额" persistKey="tms:quotas" state={viewState} filters={[{ label: "获取方式", value: method, onChange: setMethod, options: [{ label: "全部方式", value: "all" }, { label: "赠送", value: "赠送" }, { label: "充值", value: "充值" }] }]} onOpen={row => go(`${base}/quotas/${row.id}`)} columns={[{ key: "service", label: "服务", render: row => title(row.service, row.id) }, { key: "method", label: "获取方式", render: row => row.method }, { key: "remaining", label: "剩余", render: row => `${row.remaining} ${row.unit}` }, { key: "valid", label: "有效期", render: row => row.valid }, { key: "status", label: "状态", render: row => badge(row.status) }]}/></Section></>;
  } else if (root === "knowledge") {
    const kb = knowledge.find(item => item.id === segments[1]);
    content = kb ? <><PageHead eyebrow="KNOWLEDGE DETAIL" title={kb.name} breadcrumbs={crumbs("知识与内容", `${base}/knowledge`, kb.name)} description="学校知识资源的归属、文档与索引状态。"/><DetailGrid rows={[{ label: "归口", value: kb.owner }, { label: "文档数量", value: kb.files }, { label: "索引状态", value: badge(kb.index) }, { label: "最近更新", value: kb.updated }, { label: "所属学校", value: tenant.name }, { label: "正文访问", value: "仅资源 owner / 获授权成员" }]}/>
      {kb.index === "索引失败" && <Notice tone="bad">该知识库索引失败，需要资源管理员检查文档处理任务；其他知识库仍可使用。</Notice>}
      <Tabs tabs={["文档状态", "处理任务", "访问成员"]} active={tab === "概览" ? "文档状态" : tab} onChange={setTab}/>
      {(tab === "概览" || tab === "文档状态") && <><Notice>仅显示演示文档元数据，不加载私有文件正文或下载链接。</Notice><DataTable rows={documents.filter(item => item.kbId === kb.id)} searchLabel="搜索文档" columns={[{ key: "name", label: "文档", render: row => title(row.name, row.id) }, { key: "owner", label: "归口", render: row => row.owner }, { key: "status", label: "状态", render: row => badge(row.status) }, { key: "updated", label: "更新", render: row => row.updated }]}/></>}
      {tab === "处理任务" && <DataTable rows={processingTasks.filter(item => item.kbId === kb.id)} searchLabel="搜索任务" columns={[{ key: "name", label: "任务", render: row => title(row.name, row.id) }, { key: "status", label: "状态", render: row => badge(row.status) }, { key: "updated", label: "更新", render: row => row.updated }]}/>}
      {tab === "访问成员" && <DataTable rows={members.slice(0, 2)} searchLabel="搜索成员" onOpen={row => go(`${base}/members/${row.id}`)} columns={[{ key: "name", label: "成员", render: row => row.name }, { key: "role", label: "角色", render: row => row.role }]}/>}
      </> : <><PageHead eyebrow="KNOWLEDGE & CONTENT" title="知识与内容" description="按知识库查看文档、索引与处理状态；私有正文受 owner/grant 保护。"/>{list(knowledge, [{ key: "name", label: "知识库", render: row => title(row.name, row.owner) }, { key: "files", label: "文档", render: row => row.files }, { key: "index", label: "索引状态", render: row => badge(row.index) }, { key: "updated", label: "更新", render: row => row.updated }], row => `${base}/knowledge/${row.id}`, "搜索知识库")}</>;
  } else if (root === "usage") {
    const call = calls.find(item => item.id === segments[1]);
    content = call ? <><PageHead eyebrow="USAGE DETAIL" title={`调用 ${call.id}`} breadcrumbs={crumbs("用量与记录", `${base}/usage`, call.id)} description="仅查看当前学校获授权的实际消耗记录。"/><DetailGrid rows={[{ label: "时间", value: call.time }, { label: "成员", value: call.member }, { label: "应用", value: call.app }, { label: "服务", value: call.service }, { label: "实际用量", value: call.usage }, { label: "状态", value: badge(call.status) }, { label: "额度消耗", value: call.grant }, { label: "所属学校", value: tenant.name }, { label: "记录来源", value: "演示调用" }]}/>{call.status === "待核对" && <Notice tone="warn">真实用量尚未确认，不能将该调用记作零。</Notice>}</> : <><PageHead eyebrow="USAGE & RECORDS" title="用量与记录" description="从服务、应用或成员逐级查看单次调用；不展示其他学校。"/>{list(calls, [{ key: "id", label: "调用", render: row => title(row.id, row.time) }, { key: "member", label: "成员 / 应用", render: row => title(row.member, row.app) }, { key: "service", label: "服务", render: row => row.service }, { key: "usage", label: "实际用量", render: row => row.usage }, { key: "status", label: "状态", render: row => badge(row.status) }], row => `${base}/usage/${row.id}`, "搜索用量")}</>;
  } else if (root === "events") {
    const event = events.find(item => item.id === segments[1]);
    content = event ? <><PageHead eyebrow="EVENT DETAIL" title={event.action} breadcrumbs={crumbs("管理事件", `${base}/events`, event.id)}/><DetailGrid rows={[{ label: "事件编号", value: event.id }, { label: "时间", value: event.time }, { label: "操作者", value: event.actor }, { label: "目标", value: event.target }, { label: "状态", value: badge(event.status) }, { label: "所属学校", value: tenant.name }]}/></> : <><PageHead eyebrow="TENANT EVENTS" title="管理事件" description="当前学校的应用、授权与知识资源操作记录。"/>{list(events, [{ key: "action", label: "事件", render: row => title(row.action, row.id) }, { key: "target", label: "目标", render: row => row.target }, { key: "actor", label: "操作者", render: row => row.actor }, { key: "time", label: "时间", render: row => row.time }], row => `${base}/events/${row.id}`, "搜索事件")}</>;
  } else { content = <StatePanel state="empty" message="该原型页面不存在。"/>; }
  return content;
  };

  // 演示路由也不允许通过猜测 ID 或追加写入路径读取越界对象。
  const allowedIds: Record<string, string[]> = {
    members: members.map(item => item.id), apps: apps.map(item => item.id), services: services.map(item => item.id),
    quotas: grants.map(item => item.id), knowledge: knowledge.map(item => item.id), usage: calls.map(item => item.id), events: events.map(item => item.id),
  };
  const deniedTarget = root === "tenants" || segments.length > 2 || (segments[1] && root !== "skills" && !allowedIds[root]?.includes(segments[1]));
  const isDetail = segments.length > 1 && root !== "skills";
  const detailName = root === "members" ? members.find(row => row.id === segments[1])?.name
    : root === "apps" ? apps.find(row => row.id === segments[1])?.name
    : root === "services" ? services.find(row => row.id === segments[1])?.name
    : root === "quotas" ? `配额 ${segments[1]}`
    : root === "knowledge" ? knowledge.find(row => row.id === segments[1])?.name
    : root === "usage" ? `调用 ${segments[1]}`
    : root === "events" ? events.find(row => row.id === segments[1])?.action : undefined;
  const listContent = renderContent(isDetail ? [root] : segments);
  const detailContent = isDetail ? renderContent(segments) : null;

  return <AdminShell product="TMS" subtitle="学校智能体管理后台" scope={`${tenant.name} · ${schoolCode}`} groups={role === "member" ? nav.slice(0, 1) : nav} path={root === "home" ? base : `${base}/${root}`} onNavigate={path => { setTab("概览"); setFormOpen(false); setMessage(""); go(path); }}>
    <div className="scenario-bar" style={{ justifyContent: "flex-end", marginBottom: 12 }}><span>演示角色</span><select aria-label="演示角色" value={role} onChange={e => setRole(e.target.value)}><option value="admin">学校管理员</option><option value="member">普通成员</option></select></div>
    {viewState === "forbidden" || deniedTarget ? <StatePanel state="forbidden" message="当前主体不能访问该学校管理资源或写入路径。"/> : <>{listContent}{isDetail && <Drawer title={`详情 · ${detailName ?? "未找到"}`} onClose={() => { setFormOpen(false); setTab("概览"); go(`${base}/${root}`); }} suspended={formOpen}>{detailContent}</Drawer>}</>}
  </AdminShell>;
}
