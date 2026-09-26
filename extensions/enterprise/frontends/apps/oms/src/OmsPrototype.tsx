"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, Blocks, CloudCog, LayoutDashboard, Layers3, LibraryBig, Link2, Network, PackageCheck, ScrollText, UsersRound, Sparkles } from "lucide-react";
import type { DisplayState, ServiceView } from "@deeptutor/api-contracts";
import { AdminShell, Button, ConfirmModal, FormModal, DataTable, DetailGrid, Drawer, MetricStrip, Notice, PageHead, Section, StatePanel, StatusBadge, Tabs, useSessionFilter } from "@deeptutor/admin-ui";
import { OcrServiceList, ServiceDetail, ServiceList } from "@deeptutor/service-components";
import { consumeGiftFirst } from "./ledger";
import ServiceConfigForm from "./ServiceConfigForm";
import OmsSkills from "./OmsSkills";
import OmsSupplyCatalog from "./OmsSupplyCatalog";
import OmsResourceCreate from "./OmsResourceCreate";
import type { ResourceDraft, ResourceKind } from "./OmsResourceCreate";
import OmsModelCreate from "./OmsModelCreate";
import type { ModelDraft, ProfileDraft } from "./OmsModelCreate";
import { audits, calls, grants as initialGrants, providerAttributes, resourceGroups, services, supply as initialSupply, tenants } from "./fixtures";
import type { GrantRecord } from "./fixtures";

const base = "/oms/prototype";
const nav = [
  { label: "工作台", items: [{ label: "运营概览", href: base, icon: <LayoutDashboard/> }] },
  { label: "学校与权益", items: [{ label: "学校列表", href: `${base}/tenants`, icon: <UsersRound/> }] },
  { label: "资源目录", items: [
    { label: "模型与服务", href: `${base}/services`, icon: <Blocks/> },
    { label: "供应商连接", href: `${base}/connections`, icon: <Link2/> },
    { label: "Agent 与能力", href: `${base}/agents`, icon: <Layers3/> },
    { label: "工具与集成", href: `${base}/tools`, icon: <Network/> },
    { label: "Skills", href: `${base}/skills`, icon: <Sparkles/> },
    { label: "知识基础能力", href: `${base}/knowledge`, icon: <LibraryBig/> },
    { label: "运行资源", href: `${base}/runtime`, icon: <CloudCog/> },
  ] },
  { label: "资源供给", items: [
    { label: "服务供给", href: `${base}/supply`, icon: <PackageCheck/> },
  ] },
  { label: "用量与运行", items: [
    { label: "用量与运行", href: `${base}/usage`, icon: <Activity/> },
  ] },
  { label: "审计与治理", items: [
    { label: "审计与治理", href: `${base}/audit`, icon: <ScrollText/> },
  ] },
];

const initialConnections = [
  { id: "c-model", name: "演示模型连接", scope: "llm / task / embedding", status: "已配置", provider: "演示供应商 A", note: "凭据引用已关联（示意）", baseUrl: "" },
  { id: "c-voice", name: "演示语音连接", scope: "tts / stt", status: "草稿", provider: "演示供应商 B", note: "尚未发布", baseUrl: "" },
  { id: "c-media", name: "演示图像连接", scope: "imagegen / videogen", status: "已配置", provider: "演示供应商 C", note: "凭据引用已关联（示意）", baseUrl: "" },
];
const connectionTargets = [{ id: "llm", name: "对话模型" }, { id: "task", name: "任务模型" }, { id: "embedding", name: "向量服务" }, { id: "tts", name: "语音合成" }, { id: "stt", name: "语音识别" }, { id: "imagegen", name: "图片生成" }, { id: "videogen", name: "视频生成" }];

function badge(value: string) {
  const tone = value.includes("不足") || value.includes("失败") || value.includes("用尽") ? "bad" : value.includes("待") || value.includes("受限") || value.includes("需") || value.includes("同步") || value.includes("草稿") ? "warn" : "good";
  return <StatusBadge tone={tone}>{value}</StatusBadge>;
}
function title(value: string, sub?: string) { return <><span className="cell-title">{value}</span>{sub && <span className="cell-sub">{sub}</span>}</>; }
function localToday() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`; }
function defaultExpiry() { const date = new Date(); date.setMonth(date.getMonth() + 3); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`; }

export default function OmsPrototype() {
  const pathname = usePathname();
  const [route, setRoute] = useState(pathname);
  useEffect(() => { const onPopState = () => setRoute(window.location.pathname); window.addEventListener("popstate", onPopState); return () => window.removeEventListener("popstate", onPopState); }, []);
  const segments = route.replace(base, "").split("/").filter(Boolean);
  const root = segments[0] || "home";
  const go = (path: string) => { setFormOpen(""); setMessage(""); setTab("概览"); setRoute(path); if (window.location.pathname !== path) window.history.pushState(null, "", path); };
  const [role, setRole] = useState("admin");
  const [scenario, setScenario] = useState("normal");
  const [tab, setTab] = useState("概览");
  const [grants, setGrants] = useState<GrantRecord[]>(initialGrants);
  const [supply, setSupply] = useState(initialSupply);
  const [supplyHistory, setSupplyHistory] = useState(initialSupply.map(row => ({ id: `origin-${row.id}`, supplyId: row.id, amount: row.acquired, source: "初始演示供给", time: "演示初始数据" })));
  const [supplySource, setSupplySource] = useState("");
  const [connections, setConnections] = useState(initialConnections);
  const [serviceRows, setServiceRows] = useState(services);
  const [serviceDrafts, setServiceDrafts] = useState<Record<string, ResourceDraft>>({});
  const [profiles, setProfiles] = useState<ProfileDraft[]>([]);
  const [models, setModels] = useState<ModelDraft[]>([]);
  const [resourceRows, setResourceRows] = useState(resourceGroups);
  const [resourcePolicies, setResourcePolicies] = useState<Record<string, { note: string; scope: string }>>({});
  const [configDrafts, setConfigDrafts] = useState<Record<string, Record<string, string>>>({});
  const [releaseRequests, setReleaseRequests] = useState<{ id: string; serviceId: string; name: string; status: string }[]>([]);
  const [formOpen, setFormOpen] = useState("");
  const [confirm, setConfirm] = useState<{ title: string; description: string; action: () => void } | null>(null);
  const [method, setMethod] = useState("赠送");
  const [quantity, setQuantity] = useState("1000");
  const [validDate, setValidDate] = useState(defaultExpiry);
  const [policyNote, setPolicyNote] = useState("");
  const [policyScope, setPolicyScope] = useState("获授权学校");
  const [connectionName, setConnectionName] = useState("");
  const [connectionProvider, setConnectionProvider] = useState("");
  const [connectionScope, setConnectionScope] = useState("llm");
  const [connectionUrl, setConnectionUrl] = useState("");
  const [message, setMessage] = useState("");
  const [catalogTab, setCatalogTab] = useState("全部服务");
  const [providerTab, setProviderTab] = useState("连接");
  const [quotaFilter, setQuotaFilter] = useSessionFilter("oms:tenant-quota-method", "all");
  const [authorized, setAuthorized] = useState<Record<string, string[]>>({});
  const [revokedAuth, setRevokedAuth] = useState<Record<string, string[]>>({});
  const [authService, setAuthService] = useState("ocr");
  const [grantService, setGrantService] = useState("llm");
  const canWrite = role === "operator" || role === "admin";
  const canConfigure = role === "admin";
  const viewState: DisplayState = scenario === "loading" ? "loading" : scenario === "empty" ? "empty" : scenario === "error" ? "error" : scenario === "forbidden" || role === "limited" ? "forbidden" : "ready";

  const list = <T extends { id: string }>(rows: T[], columns: { key: string; label: string; render: (row: T) => React.ReactNode }[], route: (row: T) => string, searchLabel: string, extra?: React.ReactNode) => <><Section title="记录列表" action={extra}><DataTable rows={viewState === "empty" ? [] : rows} columns={columns} searchLabel={searchLabel} persistKey={`oms:${root}`} onOpen={row => go(route(row))} state={viewState}/></Section></>;
  const crumbs = (section: string, parent: string, detail?: string) => [{ label: "工作台", onClick: () => go(base) }, { label: section, onClick: () => go(parent) }, ...(detail ? [{ label: detail }] : [])];
  const notice = message && <Notice>{message}</Notice>;
  const authorizedFor = (tenant: (typeof tenants)[number]) => services.filter((service, index) => (
    index < tenant.services ||
    (authorized[tenant.id] ?? []).includes(service.id) ||
    grants.some(grant => grant.tenantId === tenant.id && grant.serviceId === service.id)
  ) && !(revokedAuth[tenant.id] ?? []).includes(service.id));
  const openConnectionEditor = (id?: string) => {
    const existing = connections.find(row => row.id === id);
    setConnectionName(existing?.name ?? "");
    setConnectionProvider(existing?.provider ?? "");
    setConnectionScope(existing?.scope ?? "llm");
    setConnectionUrl(existing?.baseUrl ?? "");
    setMessage("");
    setFormOpen(id ? "connection" : "new-connection");
  };
  const connectionForm = (id?: string) => <div className="side-panel"><h3>{id ? "编辑连接草稿" : "新增连接"} · 本地演示</h3><div className="form-grid"><label className="form-field">名称<input value={connectionName} onChange={event => setConnectionName(event.target.value)}/></label><label className="form-field">供应商<input value={connectionProvider} onChange={event => setConnectionProvider(event.target.value)} placeholder="以服务端 descriptor 候选为准"/></label><fieldset className="connection-targets"><legend>适用服务</legend><div>{connectionTargets.map(target => <label key={target.id}><input type="checkbox" checked={connectionScope.split(" / ").includes(target.id)} onChange={event => { const current = connectionScope.split(" / ").filter(Boolean); setConnectionScope(event.target.checked ? [...current, target.id].join(" / ") : current.filter(id => id !== target.id).join(" / ")); }}/>{target.name}</label>)}</div></fieldset><label className="form-field">Base URL<input value={connectionUrl} onChange={event => setConnectionUrl(event.target.value)} placeholder="留空使用供应商默认端点"/></label><label className="form-field">凭据引用<input value="受控 Secret 管理，不在原型录入" readOnly/></label></div><Notice tone="warn">联网搜索使用独立 profile，不在 connections 中创建；API Key 明文不进入普通运营界面。</Notice>{notice}<div className="form-actions"><Button variant="primary" onClick={() => { if (!connectionName.trim() || !connectionProvider.trim()) { setMessage("请填写连接名称与供应商。"); return; } if (!connectionScope) { setMessage("请至少选择一项适用服务。"); return; } const row = { id: id ?? `c-demo-${Date.now()}`, name: connectionName.trim(), provider: connectionProvider.trim(), scope: connectionScope, baseUrl: connectionUrl.trim(), status: "草稿", note: "本地配置草稿，尚未发布" }; setConnections(id ? connections.map(item => item.id === id ? row : item) : [...connections, row]); setFormOpen(""); setMessage("连接草稿已保存至本地演示列表；真实配置未变更。"); }}>保存演示草稿</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div>;

  const providerSection = (service: ServiceView) => {
    const supportsProfile = ["llm", "task", "embedding", "tts", "stt", "imagegen", "videogen", "search"].includes(service.id);
    const supportsModel = supportsProfile && service.id !== "search";
    const scopedProfiles = profiles.filter(row => row.serviceId === service.id);
    const scopedModels = models.filter(row => row.serviceId === service.id);
    const selectedProfile = profiles.find(row => formOpen === `profile-detail:${row.id}` && row.serviceId === service.id);
    const selectedModel = models.find(row => formOpen === `model-detail:${row.id}` && row.serviceId === service.id);
    return <>
      <Section title="供应商配置" subtitle="连接、Profile 与模型分层维护；草稿不代表真实配置生效" action={canConfigure && supportsProfile ? <div className="inline-list"><Button onClick={() => { setProviderTab("Profile"); setFormOpen("new-profile"); }}>新增 Provider profile</Button>{supportsModel && <Button variant="primary" onClick={() => { setProviderTab("模型"); setFormOpen("new-model"); }}>新增模型</Button>}</div> : undefined}>
        <Tabs tabs={["连接", "Profile", ...(supportsModel ? ["模型"] : [])]} active={providerTab} onChange={setProviderTab}/>
        {providerTab === "连接" && <><DataTable rows={service.id === "search" ? [] : connections.filter(c => c.scope.includes(service.id))} searchLabel="搜索连接" onOpen={service.id === "search" ? undefined : row => go(`${base}/connections/${row.id}`)} columns={[{ key: "name", label: "连接", render: row => title(row.name, row.provider) }, { key: "scope", label: "适用服务", render: row => row.scope }, { key: "status", label: "状态", render: row => badge(row.status) }]}/>{service.id === "search" && <Notice>联网搜索使用独立 Profile，不进入 connections，也没有模型列表。</Notice>}</>}
        {providerTab === "Profile" && <DataTable rows={scopedProfiles} searchLabel="搜索 Profile" onOpen={row => setFormOpen(`profile-detail:${row.id}`)} columns={[{ key: "name", label: "Profile", render: row => title(row.name, row.provider) }, { key: "status", label: "状态", render: row => badge(row.status) }]}/>}
        {providerTab === "模型" && supportsModel && <DataTable rows={scopedModels} searchLabel="搜索模型" onOpen={row => setFormOpen(`model-detail:${row.id}`)} columns={[{ key: "name", label: "模型", render: row => title(row.name, row.model) }, { key: "profile", label: "所属 Profile", render: row => profiles.find(item => item.id === row.profileId)?.name ?? "待核对" }, { key: "status", label: "状态", render: row => badge(row.status) }]}/>}
      </Section>
      {formOpen === "new-profile" && supportsProfile && canConfigure && <FormModal title="新增 Provider profile" onClose={() => setFormOpen("")} suspended={!!confirm}><ServiceConfigForm serviceId={service.id} requireProvider existingNames={scopedProfiles.map(row => row.name)} onSave={values => { setProfiles(current => [{ id: `profile-${Date.now()}`, serviceId: service.id, name: values.name, provider: values.provider, fields: values, status: "草稿" }, ...current]); setFormOpen(""); setMessage("Provider profile 已保存为本地草稿；尚未发布或连接真实 Secret。"); }} onCancel={() => setFormOpen("")}/></FormModal>}
      {formOpen === "new-model" && supportsModel && canConfigure && <FormModal title="新增模型" onClose={() => setFormOpen("")} suspended={!!confirm}><OmsModelCreate serviceId={service.id} profiles={scopedProfiles} models={scopedModels} onSave={row => { setModels(current => [row, ...current]); setFormOpen(""); setMessage("模型草稿已加入本服务；未发布且不可调用。"); }} onCancel={() => setFormOpen("")}/></FormModal>}
      {selectedProfile && <FormModal title="Profile 详情" onClose={() => setFormOpen("")}><DetailGrid rows={[{ label: "名称", value: selectedProfile.name }, { label: "供应商", value: selectedProfile.provider }, { label: "服务", value: service.name }, { label: "状态", value: selectedProfile.status }, { label: "模型标识", value: selectedProfile.fields.model || "未指定" }, { label: "真实生效", value: "待执行者确认" }]}/></FormModal>}
      {selectedModel && <FormModal title="模型详情" onClose={() => setFormOpen("")}><DetailGrid rows={[{ label: "名称", value: selectedModel.name }, { label: "模型标识", value: selectedModel.model }, { label: "所属 Profile", value: profiles.find(row => row.id === selectedModel.profileId)?.name ?? "待核对" }, { label: "服务", value: service.name }, { label: "扩展参数", value: selectedModel.detail || "使用供应商默认" }, { label: "状态", value: selectedModel.status }]}/></FormModal>}
    </>;
  };

  const renderContent = (segments: string[]): React.ReactNode => {
  let content: React.ReactNode;
  if (root === "home") {
    const alerts = [
      { id: "a-1", issue: "文档 OCR 服务供给接近可授予上限", object: "文档 OCR · 演示解析引擎", status: "需补充", to: `${base}/supply/s-ocr` },
      { id: "a-2", issue: "星河实验学校 OCR 额度已用尽", object: "星河实验学校 · 文档 OCR", status: "额度不足", to: `${base}/tenants/aurora` },
      { id: "a-3", issue: "一条模型调用用量尚未确认", object: "北辰研究院 · 对话模型", status: "待核对", to: `${base}/usage/use-7427` },
    ];
    content = <><PageHead eyebrow="PLATFORM OVERVIEW" title="工作台" description="关注需要处理的供给、额度与用量事项。" actions={<div className="scenario-bar"><label htmlFor="scenario">审计场景</label><select id="scenario" value={scenario} onChange={e => setScenario(e.target.value)}><option value="normal">正常</option><option value="loading">加载中</option><option value="empty">空记录</option><option value="error">读取失败</option><option value="forbidden">无权限</option></select></div>}/>
      <MetricStrip items={[{ label: "服务目录", value: "11", note: "含模型、OCR、工具" }, { label: "运营学校", value: "4", note: "状态来自 EduPlus2" }, { label: "待处理事项", value: "3", note: "供给与用量" }, { label: "待核对调用", value: "1", note: "不能记作零消耗", tone: "warning" }]}/>
      <Section title="待处理事项" subtitle="按影响优先处理；查看详情后再做决定"><DataTable rows={viewState === "empty" ? [] : alerts} state={viewState} searchLabel="搜索待办" onOpen={row => go(row.to)} columns={[{ key: "issue", label: "事项", render: row => title(row.issue, row.object) }, { key: "status", label: "状态", render: row => badge(row.status) }]}/></Section>
      <div className="audit-note">演示数据仅用于界面审计，不代表平台服务已经部署或配置生效。</div></>;
  } else if (root === "tenants") {
    const selected = tenants.find(item => item.id === segments[1]);
    if (!selected) {
      content = <><PageHead eyebrow="TENANT OPERATIONS" title="学校与权益" description="学校生命周期由 EduPlus2 同步；在详情中管理服务授权与额度。"/>
        {list(tenants, [{ key: "name", label: "学校", render: row => title(row.name, row.code) }, { key: "kind", label: "类型", render: row => row.kind }, { key: "services", label: "授权服务", render: row => `${authorizedFor(row).length} 项` }, { key: "status", label: "同步状态", render: row => badge(row.status) }], row => `${base}/tenants/${row.id}`, "搜索学校")}</>;
    } else if (segments[2] === "grants" && segments[3]) {
      const grant = grants.find(item => item.id === segments[3]);
      content = grant ? <><PageHead eyebrow="ENTITLEMENT DETAIL" title={`额度 ${grant.id}`} breadcrumbs={[{ label: "工作台", onClick: () => go(base) }, { label: "学校与权益", onClick: () => go(`${base}/tenants`) }, { label: selected.name, onClick: () => go(`${base}/tenants/${selected.id}`) }, { label: grant.id }]} description="授予记录与实际消耗分别呈现；赠送额度优先使用。" actions={canWrite && grant.remaining !== null ? <div className="inline-list"><Button onClick={() => { setQuantity("1000"); setFormOpen("adjust-grant"); }}>调整额度</Button><Button onClick={() => { if (!grant.remaining) { setMessage("该额度没有可撤销的未使用部分。"); return; } const unused = grant.remaining; setConfirm({ title: "确认撤销额度", description: `${selected.name} · ${grant.service}\n撤销未使用的 ${unused.toLocaleString()} ${grant.unit}，历史已消耗 ${grant.used?.toLocaleString()} ${grant.unit} 保留。仅更新本地演示。`, action: () => { setGrants(current => current.map(row => row.id === grant.id ? { ...row, remaining: 0, revoked: (row.revoked ?? 0) + unused, status: "已结束" } : row)); setSupply(current => current.map(row => row.id === `s-${grant.serviceId}` ? { ...row, committed: row.committed - unused, available: row.available + unused } : row)); setMessage("未使用额度已在本地演示中撤销；历史消耗保留。"); } }); }}>撤销未使用额度</Button></div> : undefined}/>
        <DetailGrid rows={[{ label: "服务", value: grant.service }, { label: "获取方式", value: grant.method }, { label: "状态", value: badge(grant.status) }, { label: "授予总量", value: `${grant.total.toLocaleString()} ${grant.unit}` }, { label: "已消耗", value: grant.used === null ? "待核对" : `${grant.used.toLocaleString()} ${grant.unit}` }, { label: "剩余额度", value: grant.remaining === null ? "待核对" : `${grant.remaining.toLocaleString()} ${grant.unit}` }, { label: "已撤销未用", value: grant.revoked ? `${grant.revoked.toLocaleString()} ${grant.unit}` : "未发生" }, { label: "有效期", value: grant.valid }, { label: "授予来源", value: "OMS 演示记录" }, { label: "所属学校", value: selected.name }]}/>
        {formOpen === "adjust-grant" && canWrite && <FormModal title="调整额度" onClose={() => setFormOpen("")} suspended={!!confirm}><div className="side-panel"><h3>增加未使用额度 · 本地演示</h3><label className="form-field">增加额度（{grant.unit}）<input type="number" min="1" value={quantity} onChange={event => setQuantity(event.target.value)}/></label><div className="form-actions"><Button variant="primary" onClick={() => { const amount = Number(quantity); const source = supply.find(row => row.id === `s-${grant.serviceId}`); if (!Number.isSafeInteger(amount) || amount <= 0) { setMessage("请输入有效的正整数额度。"); return; } if (!source || source.available < amount) { setMessage("平台可授予额度不足，请先补充服务供给。"); return; } setConfirm({ title: "确认调整额度", description: `${selected.name} · ${grant.service}\n增加 ${amount.toLocaleString()} ${grant.unit} 未使用额度。仅更新本地演示。`, action: () => { setGrants(current => current.map(row => row.id === grant.id ? { ...row, total: row.total + amount, remaining: (row.remaining ?? 0) + amount, status: "生效中" } : row)); setSupply(current => current.map(row => row.id === source.id ? { ...row, committed: row.committed + amount, available: row.available - amount } : row)); setFormOpen(""); setMessage("本地演示额度调整已保存；历史消耗未改变。"); } }); }}>提交调整</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div>{notice}</FormModal>}{!formOpen && notice}
        <Section title="关联消耗" subtitle="只有真实调用才形成消耗，授予动作不计为用量"><DataTable rows={calls.filter(call => call.tenant === selected.name && call.service === grant.service)} searchLabel="搜索调用" onOpen={row => go(`${base}/usage/${row.id}`)} columns={[{ key: "id", label: "调用", render: row => title(row.id, row.time) }, { key: "usage", label: "用量", render: row => row.usage }, { key: "status", label: "状态", render: row => badge(row.status) }]}/></Section></> : <StatePanel state="empty"/>;
    } else {
      const tenantGrants = grants.filter(item => item.tenantId === selected.id);
      const tenantAuthorized = authorizedFor(selected);
      content = <><PageHead eyebrow="TENANT DETAIL" title={selected.name} description="先核对学校信息，再管理授权与额度。" breadcrumbs={crumbs("学校与权益", `${base}/tenants`, selected.name)} actions={canWrite ? <Button onClick={() => { setFormOpen(formOpen === "grant" ? "" : "grant"); setMessage(""); }} variant="primary">授予额度（演示）</Button> : undefined}/>
        <DetailGrid rows={[{ label: "学校编号", value: selected.code }, { label: "机构类型", value: selected.kind }, { label: "生命周期来源", value: selected.source }, { label: "同步状态", value: badge(selected.status) }, { label: "授权服务", value: `${tenantAuthorized.length} 项` }, { label: "额度记录", value: `${tenantGrants.length} 条` }]}/>
        <Notice>学校开通、暂停与恢复只能由 EduPlus2 生命周期事件触发；OMS 不提供直接开停操作。</Notice>
        {formOpen === "grant" && canWrite && <FormModal title="授予额度" onClose={() => setFormOpen("")} suspended={!!confirm}><div className="side-panel"><h3>新增授予 · 本地演示</h3><div className="form-grid"><label className="form-field">服务<select value={grantService} onChange={e => setGrantService(e.target.value)}>{supply.map(item => <option key={item.id} value={item.id.slice(2)}>{item.service} · {item.unit}</option>)}</select></label><label className="form-field">获取方式<select value={method} onChange={e => setMethod(e.target.value)}><option>赠送</option><option>充值</option></select></label><label className="form-field">授予数量<input type="number" min="1" value={quantity} onChange={e => setQuantity(e.target.value)}/></label><label className="form-field">有效期<input type="date" value={validDate} onChange={event => setValidDate(event.target.value)}/></label></div><div className="form-actions"><Button variant="primary" onClick={() => { const amount = Number(quantity); const source = supply.find(row => row.id === `s-${grantService}`); if (!Number.isSafeInteger(amount) || amount <= 0 || !source) { setMessage("请输入有效的服务与正整数额度。"); return; } if (!tenantAuthorized.some(row => row.id === grantService)) { setMessage("请先授权该服务，再授予额度。"); return; } if (!validDate || validDate < localToday()) { setMessage("请选择今天或之后的有效期。"); return; } if (amount > source.available) { setMessage("平台可授予额度不足，请先补充服务供给。"); return; } const next = { id: `q-demo-${Date.now()}`, tenant: selected.name, tenantId: selected.id, service: source.service, serviceId: grantService, method, total: amount, used: 0, remaining: amount, unit: source.unit, valid: validDate, status: "生效中" }; setConfirm({ title: "确认授予额度", description: `${selected.name} · ${source.service}\n${method} ${amount.toLocaleString()} ${source.unit}，有效期至 ${validDate}。此操作仅更新本地演示状态。`, action: () => { setGrants(current => [...current, next]); setSupply(current => current.map(row => row.id === source.id ? { ...row, committed: row.committed + amount, available: row.available - amount } : row)); setMessage("演示授予已加入本地列表；没有写入真实 OMS。"); setFormOpen(""); } }); }}>确认演示授予</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div>{notice}</FormModal>}
        {!formOpen && notice}<Tabs tabs={["额度清单", "服务授权", "使用概况"]} active={tab === "概览" ? "额度清单" : tab} onChange={setTab}/>
        {(tab === "概览" || tab === "额度清单") && <DataTable rows={tenantGrants.filter(g => quotaFilter === "all" || g.method === quotaFilter)} searchLabel="搜索额度" persistKey={`oms:tenant:${selected.id}:grants`} filters={[{ label: "获取方式", value: quotaFilter, options: [{ value: "all", label: "全部方式" }, { value: "赠送", label: "赠送" }, { value: "充值", label: "充值" }], onChange: setQuotaFilter }]} onOpen={row => go(`${base}/tenants/${selected.id}/grants/${row.id}`)} columns={[{ key: "service", label: "服务", render: row => title(row.service, row.id) }, { key: "method", label: "获取方式", render: row => row.method }, { key: "remaining", label: "剩余额度", render: row => row.remaining === null ? "待核对" : `${row.remaining.toLocaleString()} ${row.unit}` }, { key: "status", label: "状态", render: row => badge(row.status) }]}/>}
        {tab === "服务授权" && <><div className="section-head"><h2>已授权服务</h2>{canWrite && <div className="inline-list"><Button onClick={() => setFormOpen("authorize")}>授权服务（演示）</Button><Button onClick={() => { setAuthService(tenantAuthorized[0]?.id ?? "llm"); setFormOpen("revoke-auth"); }}>撤销服务授权</Button></div>}</div>{formOpen === "authorize" && <FormModal title="授权服务" onClose={() => setFormOpen("")} suspended={!!confirm}><div className="side-panel"><h3>添加学校服务资格 · 本地演示</h3><div className="form-grid"><label className="form-field">服务<select value={authService} onChange={e => setAuthService(e.target.value)}>{services.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label></div><div className="form-actions"><Button variant="primary" onClick={() => { const target = services.find(s => s.id === authService); if (!target) return; if (tenantAuthorized.some(s => s.id === authService)) { setMessage("该服务已在学校授权清单中。"); return; } setConfirm({ title: "确认服务授权", description: `${selected.name} · ${target.name}；此操作仅更新本地演示状态。`, action: () => { setAuthorized(current => ({ ...current, [selected.id]: [...(current[selected.id] ?? []), authService] })); setRevokedAuth(current => ({ ...current, [selected.id]: (current[selected.id] ?? []).filter(id => id !== authService) })); setMessage("演示服务资格已更新；实际授权未写入。"); setFormOpen(""); } }); }}>确认演示授权</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div>{notice}</FormModal>}{formOpen === "revoke-auth" && <FormModal title="撤销服务授权" onClose={() => setFormOpen("")} suspended={!!confirm}><div className="side-panel"><h3>撤销服务资格 · 本地演示</h3><label className="form-field">服务<select value={authService} onChange={e => setAuthService(e.target.value)}>{tenantAuthorized.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label><div className="form-actions"><Button variant="primary" onClick={() => { const target = tenantAuthorized.find(s => s.id === authService); if (!target) return; if (tenantGrants.some(g => g.serviceId === authService && (g.remaining === null || g.remaining > 0))) { setMessage("该服务仍有关联有效或待核对额度，请先处理额度后再撤销授权。"); return; } setConfirm({ title: "确认撤销服务授权", description: `${selected.name} · ${target.name}；不会变更历史消耗。此操作仅更新本地演示状态。`, action: () => { setRevokedAuth(current => ({ ...current, [selected.id]: [...(current[selected.id] ?? []), authService] })); setMessage("演示服务资格已撤销；历史记录保留。"); setFormOpen(""); } }); }}>继续撤销</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div>{notice}</FormModal>}<DataTable rows={tenantAuthorized} searchLabel="搜索授权服务" onOpen={row => go(`${base}/services/${row.id}`)} columns={[{ key: "name", label: "服务", render: row => row.name }, { key: "category", label: "类别", render: row => row.category }, { key: "status", label: "状态", render: row => badge(row.status === "available" ? "已授权" : "需关注") }]}/></>}
        {tab === "使用概况" && <DataTable rows={calls.filter(call => call.tenant === selected.name)} searchLabel="搜索消耗" onOpen={row => go(`${base}/usage/${row.id}`)} columns={[{ key: "time", label: "时间", render: row => row.time }, { key: "service", label: "服务", render: row => row.service }, { key: "usage", label: "用量", render: row => row.usage }, { key: "status", label: "状态", render: row => badge(row.status) }]}/>}
      </>;
    }
  } else if (root === "services") {
    const service = serviceRows.find(item => item.id === segments[1]);
    if (!service) {
      content = <><PageHead eyebrow="RESOURCE CATALOG" title="模型与服务" description="按 DeepTutor 服务语义管理平台目录；配置与实际生效分离。" actions={canConfigure ? <Button variant="primary" onClick={() => setFormOpen("create-resource")}>新增服务接入</Button> : undefined}/><Tabs tabs={["全部服务", "文档识别与解析"]} active={catalogTab} onChange={setCatalogTab}/>{catalogTab === "全部服务" ? <ServiceList services={viewState === "empty" ? [] : serviceRows} state={viewState} onOpen={id => { setTab("概览"); go(`${base}/services/${id}`); }}/> : <OcrServiceList services={serviceRows.filter(item => item.id === "ocr" || item.id === "rag")} state={viewState} onOpen={id => { setTab("概览"); go(`${base}/services/${id}`); }}/>}</>;
    } else {
      const attr = providerAttributes[service.id] ?? { fields: ["适配器方案", "原生计量单位", "服务端 descriptor 待接入"], note: "外部服务草稿未接入 DeepTutor 执行者，不能发起真实调用。" };
      const tabs = ["概览", "供应商配置", "参数与能力", "发布记录"];
      content = <><PageHead eyebrow="SERVICE DETAIL" title={service.name} description={service.description} breadcrumbs={crumbs("模型与服务", `${base}/services`, service.name)} actions={canConfigure && !serviceDrafts[service.id] ? <div className="inline-list"><Button variant="primary" onClick={() => { setFormOpen("config"); setMessage(""); }}>编辑配置草稿</Button>{configDrafts[service.id] && <Button onClick={() => setConfirm({ title: "确认提交发布申请", description: `${service.name} · ${configDrafts[service.id].name}\n仅登记本地演示申请，真实配置仍须由执行者测试与确认。`, action: () => { setReleaseRequests(current => [...current, { id: `release-${Date.now()}`, serviceId: service.id, name: configDrafts[service.id].name, status: "待执行者确认" }]); setMessage("本地演示发布申请已登记；运行态未改变。"); } })}>提交发布申请（演示）</Button>}</div> : undefined}/><ServiceDetail service={service}/>{serviceDrafts[service.id] && <Notice tone="warn">适配器方案：{serviceDrafts[service.id].detail}。此目录条目尚未接入执行者，不可调用或授予额度。</Notice>}{formOpen === "config" && canConfigure && <FormModal title={`编辑${service.name}配置`} onClose={() => setFormOpen("")} suspended={!!confirm}><ServiceConfigForm serviceId={service.id} initialValues={configDrafts[service.id]} onSave={values => { setConfigDrafts({ ...configDrafts, [service.id]: values }); setMessage(`“${values.name}”演示草稿已保存；真实配置未变更。`); setFormOpen(""); }} onCancel={() => setFormOpen("")}/></FormModal>}
        {notice}<Tabs tabs={tabs} active={tabs.includes(tab) ? tab : "概览"} onChange={setTab}/>
        {(tab === "概览" || !tabs.includes(tab)) && <div className="two-column"><Section title="配置概况"><DetailGrid rows={[{ label: "本地配置草稿", value: configDrafts[service.id]?.name ?? "尚无草稿" }, { label: "配置生效", value: badge(configDrafts[service.id] ? "未发布 · 待确认" : "待确认") }, { label: "关联额度", value: `${grants.filter(g => g.serviceId === service.id).length} 条` }]}/></Section><div className="side-panel"><h3>关联对象</h3><p>查看此服务的学校授权、供给与调用用量。</p><div className="inline-list"><Button onClick={() => go(`${base}/supply`)}>服务供给</Button><Button onClick={() => go(`${base}/usage`)}>用量明细</Button></div></div></div>}
        {tab === "供应商配置" && providerSection(service)}
        {tab === "参数与能力" && <div className="two-column"><Section title="DeepTutor 现有设置属性" subtitle="字段名以现有设置逻辑为准；条件值由后端提供"><div className="side-panel"><div className="inline-list">{attr.fields.map(field => <span className="mini-pill" key={field}>{field}</span>)}</div><p>{attr.note}</p></div></Section><div className="side-panel"><h3>配置边界</h3><p>个人偏好、私有知识内容与原始凭据不在这里维护。平台配置发布需要独立权限、测试和生效确认。</p></div></div>}
        {tab === "发布记录" && <Section title="发布与生效记录" subtitle="演示申请不是已生效配置；需执行者测试并确认">{releaseRequests.some(row => row.serviceId === service.id) ? <DataTable rows={releaseRequests.filter(row => row.serviceId === service.id)} searchLabel="搜索发布申请" columns={[{ key: "name", label: "配置草稿", render: row => row.name }, { key: "status", label: "确认状态", render: row => badge(row.status) }]}/> : <StatePanel state="empty" message="尚无真实发布记录；演示草稿不会成为运行态配置。"/>}</Section>}
      </>;
    }
  } else if (root === "skills") {
    content = <OmsSkills selectedId={segments[1] ? decodeURIComponent(segments[1]) : undefined} onOpen={id => go(`${base}/skills/${encodeURIComponent(id)}`)} onClose={() => go(`${base}/skills`)} canConfigure={canConfigure} state={viewState}/>;
  } else if (root === "connections") {
    const connection = connections.find(item => item.id === segments[1]);
    content = connection ? <><PageHead eyebrow="PROVIDER CONNECTION" title={connection.name} breadcrumbs={crumbs("供应商连接", `${base}/connections`, connection.name)} description="维护连接绑定与受控凭据引用；平台凭据不在普通详情明文展示。" actions={canConfigure ? <Button variant="primary" onClick={() => openConnectionEditor(connection.id)}>编辑连接草稿</Button> : undefined}/><DetailGrid rows={[{ label: "供应商", value: connection.provider }, { label: "适用服务", value: connection.scope }, { label: "状态", value: badge(connection.status) }, { label: "凭据", value: "受控引用（演示）" }, { label: "Base URL", value: connection.baseUrl || "供应商默认端点" }, { label: "备注", value: connection.note }]}/><Notice>DeepTutor connections 目前支持 llm/task/embedding/tts/stt/imagegen/videogen；search 使用独立 profile。</Notice>{!formOpen && notice}{formOpen === "connection" && canConfigure && <FormModal title={`编辑${connection.name}`} onClose={() => setFormOpen("")} suspended={!!confirm}>{connectionForm(connection.id)}</FormModal>}</> : <><PageHead eyebrow="PROVIDER CONNECTIONS" title="供应商连接" description="连接与服务配置分层维护；凭据由高权限角色处理。" actions={canConfigure ? <Button variant="primary" onClick={() => openConnectionEditor()}>新增连接</Button> : undefined}/>{list(connections, [{ key: "name", label: "连接", render: row => title(row.name, row.provider) }, { key: "scope", label: "适用服务", render: row => row.scope }, { key: "status", label: "状态", render: row => badge(row.status) }], row => `${base}/connections/${row.id}`, "搜索连接")}</>;
  } else if (["agents", "tools", "knowledge", "runtime"].includes(root)) {
    const data = resourceRows[root as keyof typeof resourceRows];
    const heading = ({ agents: "Agent 与能力", tools: "工具与集成", knowledge: "知识基础能力", runtime: "运行资源" } as Record<string, string>)[root] ?? "平台资源";
    const item = data.find(row => row.id === segments[1]);
    const policy = item ? resourcePolicies[`${root}:${item.id}`] : undefined;
    content = item ? <><PageHead eyebrow="RESOURCE DETAIL" title={item.name} breadcrumbs={crumbs(heading, `${base}/${root}`, item.name)} description="内置能力身份来自 DeepTutor；OMS 维护平台使用策略，不在线改写注册表。" actions={canConfigure ? <Button variant="primary" onClick={() => { setPolicyNote(policy?.note ?? ""); setPolicyScope(policy?.scope ?? "获授权学校"); setFormOpen("policy"); }}>管理平台策略</Button> : undefined}/><DetailGrid rows={[{ label: "资源类别", value: item.type }, { label: "运行状态", value: badge(item.status) }, { label: "依赖", value: item.dependency }, { label: "配置来源", value: item.status === "草稿" ? "OMS 本地平台草稿" : "DeepTutor 现有能力 / 企业扩展演示" }, { label: "平台策略草稿", value: policy?.note ?? "尚无草稿" }, { label: "适用范围草稿", value: policy?.scope ?? "尚无草稿" }, { label: "真实生效", value: "待执行者确认" }]}/>{!formOpen && notice}{formOpen === "policy" && canConfigure && <FormModal title={`管理${item.name}策略`} onClose={() => setFormOpen("")} suspended={!!confirm}><div className="side-panel"><h3>{heading} · 平台策略草稿</h3><Notice>这里不修改内置代码、学校私有资源或运行态。</Notice><div className="form-grid"><label className="form-field">适用范围<select value={policyScope} onChange={event => setPolicyScope(event.target.value)}><option>获授权学校</option><option>仅平台测试</option><option>暂不开放新调用</option></select></label><label className="form-field">策略说明<input value={policyNote} onChange={event => setPolicyNote(event.target.value)} placeholder="例如：仅供已授权学校使用"/></label></div>{notice}<div className="form-actions"><Button variant="primary" onClick={() => { if (!policyNote.trim()) { setMessage("请填写策略说明。"); return; } setResourcePolicies({ ...resourcePolicies, [`${root}:${item.id}`]: { note: policyNote.trim(), scope: policyScope } }); setFormOpen(""); setMessage("本地演示策略草稿已保存；真实运行状态未变更。"); }}>保存策略草稿</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div></FormModal>}<Section title="关联对象"><div className="callout-grid"><button className="callout" onClick={() => go(`${base}/services`)}><strong>关联服务</strong><span>查看所依赖的模型与服务</span></button><button className="callout" onClick={() => go(`${base}/tenants`)}><strong>学校可用范围</strong><span>从学校详情查看实际授权</span></button></div></Section></> : <><PageHead eyebrow="RESOURCE CATALOG" title={heading} description="以对象列表进入详情；获授权人员可维护平台策略。" actions={canConfigure ? <Button variant="primary" onClick={() => setFormOpen("create-resource")}>新增 {heading}</Button> : undefined}/>{list(data, [{ key: "name", label: "资源", render: row => title(row.name, row.id) }, { key: "type", label: "类别", render: row => row.type }, { key: "dependency", label: "依赖或配置", render: row => row.dependency }, { key: "status", label: "状态", render: row => badge(row.status) }], row => `${base}/${root}/${row.id}`, "搜索资源")}</>;
  } else if (root === "supply") {
    const selected = supply.find(item => item.id === segments[1]);
    content = selected ? <><PageHead eyebrow="SERVICE CAPACITY" title={selected.name} breadcrumbs={crumbs("服务供给", `${base}/supply`, selected.name)} description="外部资源取得、学校承诺与实际消耗分开记录。" actions={canWrite ? <Button variant="primary" onClick={() => setFormOpen(formOpen === "purchase" ? "" : "purchase")}>补充供给（演示）</Button> : undefined}/>
      <DetailGrid rows={[{ label: "供应来源", value: selected.provider }, { label: "服务", value: selected.service }, { label: "计量单位", value: selected.unit }, { label: "累计取得", value: selected.acquired.toLocaleString() }, { label: "已承诺", value: selected.committed.toLocaleString() }, { label: "实际消耗", value: selected.used.toLocaleString() }, { label: "可继续授予", value: selected.available.toLocaleString() }, { label: "状态", value: badge(selected.status) }, { label: "记录类型", value: "供给批次（演示）" }]}/>
      {formOpen === "purchase" && canWrite && <FormModal title="补充服务供给" onClose={() => setFormOpen("")} suspended={!!confirm}><div className="side-panel"><h3>补充服务供给 · 本地演示</h3><div className="form-grid"><label className="form-field">补充数量（{selected.unit}）<input type="number" min="1" value={quantity} onChange={e => setQuantity(e.target.value)}/></label><label className="form-field">来源说明<input value={supplySource} onChange={event => setSupplySource(event.target.value)} placeholder="外部供应商采购/补充记录"/></label></div><div className="form-actions"><Button variant="primary" onClick={() => { const amount = Number(quantity); if (!Number.isSafeInteger(amount) || amount <= 0) { setMessage("请输入有效的正整数。"); return; } if (!supplySource.trim()) { setMessage("请填写供给来源说明。"); return; } const source = supplySource.trim(); setConfirm({ title: "确认补充供给", description: `${selected.name}\n补充 ${amount.toLocaleString()} ${selected.unit}，来源：${source}。此操作仅更新本地演示状态。`, action: () => { setSupply(current => current.map(row => row.id === selected.id ? { ...row, acquired: row.acquired + amount, available: row.available + amount, status: "充足" } : row)); setSupplyHistory(current => [...current, { id: `acq-demo-${Date.now()}`, supplyId: selected.id, amount, source, time: "本次演示" }]); setMessage("演示补充已更新本地供给；不代表真实采购。"); setFormOpen(""); setSupplySource(""); } }); }}>确认演示补充</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div>{notice}</FormModal>}{!formOpen && notice}
      <Tabs tabs={["采购与补充", "已承诺额度", "实际消耗"]} active={tab === "概览" ? "采购与补充" : tab} onChange={setTab}/>
      {(tab === "概览" || tab === "采购与补充") && <><Notice>供应商成本仅限 OMS 高权限查看；此原型不伪造金额。</Notice><DataTable rows={supplyHistory.filter(row => row.supplyId === selected.id)} searchLabel="搜索取得记录" columns={[{ key: "source", label: "来源说明", render: row => row.source }, { key: "amount", label: "取得额度", render: row => `${row.amount.toLocaleString()} ${selected.unit}` }, { key: "time", label: "记录时间", render: row => row.time }]}/></>}
      {tab === "已承诺额度" && <DataTable rows={grants.filter(g => g.service === selected.service)} searchLabel="搜索额度" onOpen={row => go(`${base}/tenants/${row.tenantId}/grants/${row.id}`)} columns={[{ key: "tenant", label: "学校", render: row => row.tenant }, { key: "method", label: "获取方式", render: row => row.method }, { key: "remaining", label: "剩余", render: row => row.remaining === null ? "待核对" : `${row.remaining.toLocaleString()} ${row.unit}` }]}/>}
      {tab === "实际消耗" && <DataTable rows={calls.filter(c => c.service === selected.service)} searchLabel="搜索调用" onOpen={row => go(`${base}/usage/${row.id}`)} columns={[{ key: "id", label: "调用", render: row => row.id }, { key: "tenant", label: "学校", render: row => row.tenant }, { key: "usage", label: "用量", render: row => row.usage }]}/>}
      </> : <><PageHead eyebrow="RESOURCE SUPPLY" title="服务供给" description="采购/补充形成供给；授予形成承诺，只有实际调用才产生消耗。"/><MetricStrip items={[{ label: "供给项目", value: `${supply.length}` }, { label: "需补充", value: `${supply.filter(item => item.status === "需补充").length}`, tone: "warning" }, { label: "待核对", value: "1", note: "不可记为零" }, { label: "计量单位", value: "多种", note: "不可混算 Token" }]}/><OmsSupplyCatalog supply={supply} canWrite={canWrite} onOpen={id => go(`${base}/supply/${id}`)}/></>;
  } else if (root === "usage") {
    const call = calls.find(item => item.id === segments[1]);
    content = call ? <><PageHead eyebrow="USAGE DETAIL" title={`调用 ${call.id}`} breadcrumbs={crumbs("用量与运行", `${base}/usage`, call.id)} description="逐次记录原生用量与额度分摊，未知结果需核对。"/><DetailGrid rows={[{ label: "发生时间", value: call.time }, { label: "学校", value: call.tenant }, { label: "用户", value: call.user }, { label: "服务", value: call.service }, { label: "实际用量", value: call.usage }, { label: "核对状态", value: badge(call.status) }, { label: "额度消耗", value: call.grant }, { label: "供应商供给", value: call.status === "待核对" ? "待确认" : "演示供给批次" }, { label: "幂等键", value: "演示调用编号" }]}/>{call.status === "待核对" && <Notice tone="warn">此调用结果尚未核实，不能按零消耗扣减或结算。</Notice>}
      {canWrite && call.id === "use-7429" && <Section title="演示一次额度扣减" subtitle="用量 50 Token：先赠送，再充值；不写入真实用量总账"><Button onClick={() => { const result = consumeGiftFirst([{ id: "q-101", method: "gift", remaining: 30 }, { id: "q-102", method: "recharge", remaining: 350000 }], 50); setMessage(`演示分摊：${result.allocations.map(a => `${a.id} ${a.amount}`).join("、")} Token；只在本页展示，不重复计入总账。`); }}>查看分摊结果</Button>{notice}</Section>}</> : <><PageHead eyebrow="USAGE & OPERATIONS" title="用量与运行" description="按学校、服务和用户核对调用；复合 Agent 的底层用量不可重复计算。"/>{list(calls, [{ key: "id", label: "调用", render: row => title(row.id, row.time) }, { key: "tenant", label: "学校 / 用户", render: row => title(row.tenant, row.user) }, { key: "service", label: "服务", render: row => row.service }, { key: "usage", label: "实际用量", render: row => row.usage }, { key: "status", label: "状态", render: row => badge(row.status) }], row => `${base}/usage/${row.id}`, "搜索用量")}</>;
  } else if (root === "audit") {
    const event = audits.find(item => item.id === segments[1]);
    content = event ? <><PageHead eyebrow="AUDIT DETAIL" title={event.action} breadcrumbs={crumbs("审计与治理", `${base}/audit`, event.id)}/><DetailGrid rows={[{ label: "事件编号", value: event.id }, { label: "时间", value: event.time }, { label: "操作者", value: event.actor }, { label: "目标", value: event.target }, { label: "状态", value: badge(event.status) }, { label: "记录来源", value: "OMS 演示记录" }]}/></> : <><PageHead eyebrow="GOVERNANCE" title="审计与治理" description="授权、配置与供给变更均应形成可追溯记录。"/>{list(audits, [{ key: "action", label: "事件", render: row => title(row.action, row.id) }, { key: "target", label: "目标", render: row => row.target }, { key: "actor", label: "操作者", render: row => row.actor }, { key: "time", label: "时间", render: row => row.time }, { key: "status", label: "状态", render: row => badge(row.status) }], row => `${base}/audit/${row.id}`, "搜索审计事件")}</>;
  } else { content = <StatePanel state="empty" message="该原型页面不存在。"/>; }
  return content;
  };

  const isDetail = segments.length > 1 && root !== "skills";
  const closeDetail = () => go(root === "tenants" && segments[2] === "grants" && segments[1]
    ? `${base}/tenants/${segments[1]}`
    : `${base}/${root}`);
  let detailName: string | undefined;
  if (root === "services") detailName = serviceRows.find(row => row.id === segments[1])?.name;
  else if (root === "connections") detailName = connections.find(row => row.id === segments[1])?.name;
  else if (root === "tenants") {
    const tenant = tenants.find(row => row.id === segments[1]);
    detailName = segments[2] === "grants" ? (tenant && grants.some(row => row.tenantId === tenant.id && row.id === segments[3]) ? `额度 ${segments[3]}` : undefined) : tenant?.name;
  } else if (root === "supply") detailName = supply.find(row => row.id === segments[1])?.name;
  else if (["agents", "tools", "knowledge", "runtime"].includes(root)) detailName = resourceRows[root as keyof typeof resourceRows].find(row => row.id === segments[1])?.name;
  else if (root === "usage") detailName = calls.some(row => row.id === segments[1]) ? `调用 ${segments[1]}` : undefined;
  else if (root === "audit") detailName = audits.some(row => row.id === segments[1]) ? `事件 ${segments[1]}` : undefined;
  const listContent = renderContent(isDetail ? [root] : segments);
  const detailContent = isDetail ? (detailName ? renderContent(segments) : <StatePanel state="empty" message="对象不存在或不可访问"/>) : null;

  return <AdminShell product="OMS" subtitle="PLATFORM OPERATIONS" scope="平台运营空间" groups={role === "limited" ? nav.slice(0, 1) : nav} path={root === "home" ? base : `${base}/${root}`} onNavigate={go}>
    <div className="scenario-bar" style={{ justifyContent: "flex-end", marginBottom: 12 }}><span>演示角色</span><select aria-label="演示角色" value={role} onChange={event => { setRole(event.target.value); setFormOpen(""); setConfirm(null); }}><option value="admin">平台管理员</option><option value="operator">平台运营</option><option value="auditor">只读审计</option><option value="limited">无权限</option></select></div>
    {viewState === "forbidden" ? <StatePanel state="forbidden"/> : <>{listContent}{!isDetail && message && <Notice>{message}</Notice>}{isDetail && <Drawer title={`详情 · ${detailName ?? "未找到"}`} onClose={closeDetail} suspended={!!formOpen || !!confirm}>{detailContent}</Drawer>}{formOpen === "new-connection" && canConfigure && !isDetail && <FormModal title="新增连接" onClose={() => setFormOpen("")} suspended={!!confirm}>{connectionForm()}</FormModal>}{formOpen === "create-resource" && canConfigure && !isDetail && ["services", "agents", "tools", "knowledge", "runtime"].includes(root) && <FormModal title={root === "services" ? "新增服务接入" : `新增 ${({ agents: "Agent 与能力", tools: "工具与集成", knowledge: "知识基础能力", runtime: "运行资源" } as Record<string, string>)[root]}`} onClose={() => setFormOpen("")}><OmsResourceCreate kind={root as ResourceKind} existingIds={root === "services" ? serviceRows.map(row => row.id) : resourceRows[root as keyof typeof resourceRows].map(row => row.id)} onSave={row => { if (root === "services") { setServiceRows(current => [{ id: row.id, name: row.name, category: "外部接入草稿", status: "unavailable", unit: row.unit ?? "", description: "适配器待接入，不可调用" }, ...current]); setServiceDrafts(current => ({ ...current, [row.id]: row })); } else { const key = root as keyof typeof resourceRows; setResourceRows(current => ({ ...current, [key]: [row, ...current[key]] })); } setFormOpen(""); setMessage("平台资源草稿已保存至本地目录；执行者未接入，尚未生效。"); }} onCancel={() => setFormOpen("")}/></FormModal>}</>}
    {confirm && <ConfirmModal title={confirm.title} description={confirm.description} onCancel={() => setConfirm(null)} onConfirm={() => { confirm.action(); setConfirm(null); }}/ >}
  </AdminShell>;
}
