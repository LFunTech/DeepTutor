"use client";

import { useState } from "react";
import type { supply as supplyFixture } from "./fixtures";
import { Button, DataTable, DetailGrid, Drawer, FormModal, Notice, Section, StatusBadge, Tabs } from "@deeptutor/admin-ui";

type Supply = (typeof supplyFixture)[number];
type Plan = { id: string; name: string; serviceId: string; provider: string; unit: string; note: string; status: string };
type Batch = { id: string; planId: string; amount: number; source: string; status: string };

export default function OmsSupplyCatalog({ supply, canWrite, onOpen, onOpenService, selected, onSelectRecord, onCloseRecord }: { supply: Supply[]; canWrite: boolean; onOpen: (id: string, view: "info" | "acquisition" | "commitments" | "usage") => void; onOpenService: (id: string) => void; selected?: { type: "plan" | "batch"; id: string; view?: "batches" } | null; onSelectRecord: (type: "plan" | "batch", id: string, view?: "batches") => void; onCloseRecord: () => void }) {
  const [tab, setTab] = useState("供给概览");
  const activeTab = selected?.type === "plan" ? "资源方案" : selected?.type === "batch" ? "供给批次" : tab;
  const [plans, setPlans] = useState<Plan[]>(supply.map(row => ({ id: `plan-${row.id}`, name: `${row.name}方案`, serviceId: row.id, provider: row.provider, unit: row.unit, note: "演示初始方案", status: "演示基线" })));
  const [batches, setBatches] = useState<Batch[]>([]);
  const [form, setForm] = useState<"plan" | "batch" | null>(null);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [serviceId, setServiceId] = useState(supply[0]?.id ?? "");
  const [provider, setProvider] = useState("");
  const [note, setNote] = useState("");
  const [planId, setPlanId] = useState(plans[0]?.id ?? "");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const open = (next: "plan" | "batch") => { setForm(next); setId(""); setName(""); setProvider(""); setNote(""); setAmount(""); setError(""); };
  const save = () => {
    const cleanId = id.trim();
    if (!/^[a-z][a-z0-9-]{1,63}$/.test(cleanId)) { setError("标识须为 2–64 位小写字母、数字或连字符。"); return; }
    if (form === "plan") {
      if (plans.some(row => row.id === cleanId)) { setError("方案标识已存在。"); return; }
      if (name.trim().length < 2 || !provider.trim() || !note.trim()) { setError("请填写方案名称、供应商和资源说明。"); return; }
      const source = supply.find(row => row.id === serviceId);
      if (!source) { setError("请选择平台已有的可计量服务。"); return; }
      setPlans(current => [...current, { id: cleanId, name: name.trim(), serviceId, provider: provider.trim(), unit: source.unit, note: note.trim(), status: "草稿" }]);
      setTab("资源方案");
    } else {
      if (batches.some(row => row.id === cleanId)) { setError("批次标识已存在。"); return; }
      const count = Number(amount);
      if (!plans.some(row => row.id === planId) || !Number.isSafeInteger(count) || count <= 0 || !note.trim()) { setError("请选择资源方案、填写正整数数量和来源凭证。"); return; }
      setBatches(current => [...current, { id: cleanId, planId, amount: count, source: note.trim(), status: "待核对" }]);
      setTab("供给批次");
    }
    setForm(null); setMessage("仅登记本地供给草稿；未经来源核对，不增加平台可授予量。");
  };
  const plan = selected?.type === "plan" ? plans.find(row => row.id === selected.id) : undefined;
  const batch = selected?.type === "batch" ? batches.find(row => row.id === selected.id) : undefined;
  return <>
    <div className="section-head"><Tabs tabs={["供给概览", "资源方案", "供给批次"]} active={activeTab} onChange={setTab}/>{canWrite && activeTab === "资源方案" && <Button onClick={() => open("plan")}>新增供给方案</Button>}{canWrite && activeTab === "供给批次" && <Button variant="primary" onClick={() => open("batch")}>新增供给批次</Button>}</div>
    {activeTab === "供给概览" && <Section><DataTable rows={supply} searchLabel="搜索服务供给" rowActions={row => [{ label: "资源概况", onClick: () => onOpen(row.id, "info") }, { label: "取得记录", onClick: () => onOpen(row.id, "acquisition") }, { label: "已承诺额度", onClick: () => onOpen(row.id, "commitments") }, { label: "实际消耗", onClick: () => onOpen(row.id, "usage") }]} columns={[{ key: "name", label: "资源", render: row => <><span className="cell-title">{row.name}</span><span className="cell-sub">{row.provider}</span></> }, { key: "available", label: "可继续授予", render: row => `${row.available.toLocaleString()} ${row.unit}` }, { key: "committed", label: "已承诺", render: row => `${row.committed.toLocaleString()} ${row.unit}` }, { key: "status", label: "状态", render: row => <StatusBadge tone={row.status === "充足" ? "good" : "warn"}>{row.status}</StatusBadge> }]}/></Section>}
    {activeTab === "资源方案" && <Section><DataTable rows={plans} searchLabel="搜索资源方案" onOpen={row => onSelectRecord("plan", row.id)} columns={[{ key: "name", label: "方案", render: row => row.name }, { key: "provider", label: "供应商", render: row => row.provider }, { key: "unit", label: "计量单位", render: row => row.unit }, { key: "status", label: "状态", render: row => row.status }]}/></Section>}
    {activeTab === "供给批次" && <Section><DataTable rows={batches} searchLabel="搜索供给批次" onOpen={row => onSelectRecord("batch", row.id)} columns={[{ key: "id", label: "批次", render: row => row.id }, { key: "plan", label: "资源方案", render: row => plans.find(item => item.id === row.planId)?.name ?? row.planId }, { key: "amount", label: "取得数量", render: row => `${row.amount.toLocaleString()} ${plans.find(item => item.id === row.planId)?.unit ?? ""}` }, { key: "status", label: "核对状态", render: row => row.status }]}/></Section>}
    {message && <Notice>{message}</Notice>}
    {selected && <Drawer title={`详情 · ${plan?.name ?? batch?.id ?? "未找到"}`} onClose={() => { setTab(activeTab); onCloseRecord(); }} suspended={!!form}>{plan ? selected.view === "batches" ? <Section title="关联批次" action={canWrite ? <Button onClick={() => { setPlanId(plan.id); open("batch"); }}>登记该方案批次</Button> : undefined}><DataTable rows={batches.filter(row => row.planId === plan.id)} searchLabel="搜索关联批次" rowActions={row => [{ label: "批次资料", onClick: () => onSelectRecord("batch", row.id) }]} columns={[{ key: "id", label: "批次", render: row => row.id }, { key: "amount", label: "取得数量", render: row => `${row.amount.toLocaleString()} ${plan.unit}` }, { key: "status", label: "核对状态", render: row => row.status }]}/><Notice>待核对批次不增加平台可授予量。</Notice></Section> : <><DetailGrid rows={[{ label: "方案标识", value: plan.id }, { label: "供应商", value: plan.provider }, { label: "关联服务", value: supply.find(row => row.id === plan.serviceId)?.service ?? plan.serviceId }, { label: "计量单位", value: plan.unit }, { label: "资源说明", value: plan.note }, { label: "状态", value: plan.status }, { label: "生效", value: "待执行者确认" }]}/><div className="form-actions"><Button onClick={() => { const service = supply.find(row => row.id === plan.serviceId); if (service) onOpenService(service.serviceId); }}>查看关联服务</Button><Button onClick={() => onSelectRecord("plan", plan.id, "batches")}>关联批次</Button>{canWrite && <Button variant="primary" onClick={() => { setPlanId(plan.id); open("batch"); }}>登记该方案批次</Button>}</div></> : batch ? <><DetailGrid rows={[{ label: "批次标识", value: batch.id }, { label: "资源方案", value: plans.find(row => row.id === batch.planId)?.name ?? batch.planId }, { label: "数量", value: `${batch.amount.toLocaleString()} ${plans.find(row => row.id === batch.planId)?.unit ?? ""}` }, { label: "来源凭证", value: batch.source }, { label: "核对状态", value: batch.status }, { label: "可授予量", value: "未增加" }]}/><Notice tone="warn">真实采购与来源校验未接入，此批次不能用于额度授予。</Notice><Button onClick={() => onSelectRecord("plan", batch.planId)}>查看关联方案</Button></> : <Notice tone="bad">对象不存在。</Notice>}</Drawer>}
    {form && <FormModal title={form === "plan" ? "新增供给方案" : "新增供给批次"} onClose={() => setForm(null)}><div className="side-panel"><Notice tone="warn">仅登记本地草稿，不代表真实采购或平台可授予量增加。</Notice><div className="form-grid"><label className="form-field">{form === "plan" ? "方案标识" : "批次标识"}<input value={id} onChange={event => setId(event.target.value)}/></label>{form === "plan" ? <><label className="form-field">方案名称<input value={name} onChange={event => setName(event.target.value)}/></label><label className="form-field">关联服务<select value={serviceId} onChange={event => setServiceId(event.target.value)}>{supply.map(row => <option key={row.id} value={row.id}>{row.service} · {row.unit}</option>)}</select></label><label className="form-field">供应商<input value={provider} onChange={event => setProvider(event.target.value)}/></label><label className="form-field">资源说明<input value={note} onChange={event => setNote(event.target.value)}/></label></> : <><label className="form-field">资源方案<select value={planId} onChange={event => setPlanId(event.target.value)}>{plans.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label><label className="form-field">取得数量<input type="number" min="1" value={amount} onChange={event => setAmount(event.target.value)}/></label><label className="form-field">来源凭证<input value={note} onChange={event => setNote(event.target.value)}/></label></>}</div>{error && <Notice tone="bad">{error}</Notice>}<div className="form-actions"><Button variant="primary" onClick={save}>保存草稿</Button><Button onClick={() => setForm(null)}>取消</Button></div></div></FormModal>}
  </>;
}
