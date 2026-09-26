"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  BookOpen,
  Check,
  ChevronDown,
  CircleAlert,
  Clock3,
  FileClock,
  Layers3,
  LockKeyhole,
  PanelLeftClose,
  ReceiptText,
  Search,
  ShieldCheck,
  UsersRound,
  X,
  type LucideIcon,
} from "lucide-react";

import Modal from "@/components/common/Modal";

import {
  formatDemoFee,
  formatDemoFeeExact,
  INVENTORY_FIELD_LABELS,
  OMS_SERVICE_INVENTORY,
} from "./service-inventory";

type View = "overview" | "tenants" | "services" | "billing" | "activity";
type TenantId = "sample-a" | "sample-b";

const NAV: readonly { view: View; label: string; hint: string; icon: LucideIcon }[] = [
  { view: "overview", label: "运营总览", hint: "先看需要跟进的事", icon: Layers3 },
  { view: "tenants", label: "租户与接入", hint: "资格和模型使用分开", icon: UsersRound },
  { view: "services", label: "服务可用性", hint: "模型目录逐项核对", icon: Activity },
  { view: "billing", label: "Token 与费用", hint: "用量明细和计价", icon: ReceiptText },
  { view: "activity", label: "审计与任务", hint: "只读跟进记录", icon: FileClock },
];

const TENANTS: readonly {
  id: TenantId;
  name: string;
  contact: string;
  modelStatus: string;
  modelTone: "amber" | "rose";
  note: string;
}[] = [
  {
    id: "sample-a",
    name: "示例租户 A",
    contact: "华东片区 · 体验环境",
    modelStatus: "模型限制待外部确认",
    modelTone: "amber",
    note: "计费处理已提出；尚未收到 EduPlus2 模型资格确认。不能显示为已限制。",
  },
  {
    id: "sample-b",
    name: "示例租户 B",
    contact: "华南片区 · 体验环境",
    modelStatus: "模型使用受限",
    modelTone: "rose",
    note: "仅新的模型调用受限；登录、管理、历史查询与非模型操作仍可用。",
  },
];

const CALLS = [
  {
    id: "DEMO-001",
    tenant: "sample-a" as TenantId,
    user: "示例用户 01",
    service: "对话模型",
    provider: "示例供应商甲",
    model: "示例模型 α",
    time: "09:42",
    inputTokens: 1_000_000,
    outputTokens: 250_000,
    tokens: 1_250_000,
    usage: "供应商返回",
    state: "已核算",
  },
  {
    id: "DEMO-002",
    tenant: "sample-a" as TenantId,
    user: "示例用户 02",
    service: "后台任务模型",
    provider: "示例供应商甲",
    model: "示例模型 β",
    time: "10:18",
    inputTokens: 200_000,
    outputTokens: 60_000,
    tokens: 260_000,
    usage: "供应商返回",
    state: "已核算",
  },
  {
    id: "DEMO-003",
    tenant: "sample-b" as TenantId,
    user: "示例用户 03",
    service: "对话模型",
    provider: "示例供应商乙",
    model: "示例模型 γ",
    time: "11:07",
    inputTokens: null,
    outputTokens: null,
    tokens: null,
    usage: "流中断，缺少最终 usage",
    state: "待核算",
  },
] as const;

const viewTitle: Record<View, string> = {
  overview: "把需要处理的事放在前面",
  tenants: "租户状态，分清两道门",
  services: "每项服务都要真正可用",
  billing: "用量可追溯，费用算得清",
  activity: "过程留痕，异常可跟进",
};

function StatusPill({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "amber" | "rose" | "green";
}) {
  const colors = {
    neutral:
      "bg-stone-100 text-stone-600 border-stone-200 dark:bg-stone-800 dark:text-stone-300 dark:border-stone-700",
    amber:
      "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-900",
    rose: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:border-rose-900",
    green:
      "bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:border-emerald-900",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${colors[tone]}`}
    >
      {children}
    </span>
  );
}

function SectionTitle({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="mb-5">
      <p className="text-[11px] font-bold tracking-[0.22em] text-emerald-700 uppercase dark:text-emerald-300">
        {eyebrow}
      </p>
      <h2 className="mt-2 font-serif text-2xl font-semibold tracking-tight text-stone-950 dark:text-stone-50">
        {title}
      </h2>
      <p className="mt-1.5 max-w-3xl text-sm leading-6 text-stone-500 dark:text-stone-400">
        {description}
      </p>
    </div>
  );
}

function CallTable({ tenant, price }: { tenant: TenantId | "all"; price: string }) {
  const [opened, setOpened] = useState<string | null>(null);
  const rows = CALLS.filter(call => tenant === "all" || call.tenant === tenant);
  return (
    <div className="overflow-hidden rounded-2xl border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-950">
      <div className="overflow-x-auto">
        <table className="min-w-[760px] w-full text-left text-sm">
          <thead className="bg-stone-50 text-[11px] font-semibold tracking-wide text-stone-500 dark:bg-stone-900 dark:text-stone-400">
            <tr>
              <th className="px-5 py-3.5">调用 / 用户</th>
              <th className="px-4 py-3.5">服务</th>
              <th className="px-4 py-3.5">用量</th>
              <th className="px-4 py-3.5">示例费用（到分）</th>
              <th className="px-4 py-3.5">状态</th>
              <th className="px-4 py-3.5">
                <span className="sr-only">详情</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(call => (
              <tr
                key={call.id}
                className="border-t border-stone-100 align-top dark:border-stone-800"
              >
                <td className="px-5 py-4">
                  <strong className="block font-medium text-stone-900 dark:text-stone-100">
                    {call.user}
                  </strong>
                  <span className="mt-0.5 block text-xs text-stone-400">
                    {call.time} · {call.id}
                  </span>
                </td>
                <td className="px-4 py-4 text-stone-600 dark:text-stone-300">{call.service}</td>
                <td className="px-4 py-4 font-medium tabular-nums">
                  {call.tokens === null ? "—" : `${call.tokens.toLocaleString("zh-CN")} Token`}
                </td>
                <td className="px-4 py-4 font-semibold tabular-nums">
                  {formatDemoFee(call.tokens, price)}
                </td>
                <td className="px-4 py-4">
                  <StatusPill tone={call.tokens === null ? "amber" : "green"}>
                    {call.state}
                  </StatusPill>
                </td>
                <td className="px-4 py-4 text-right">
                  <button
                    type="button"
                    aria-label={`${opened === call.id ? "收起" : "查看"}${call.id}详情`}
                    aria-expanded={opened === call.id}
                    onClick={() => setOpened(opened === call.id ? null : call.id)}
                    className="rounded-lg p-1 text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800"
                  >
                    <ChevronDown
                      className={`h-4 w-4 transition-transform ${opened === call.id ? "rotate-180" : ""}`}
                    />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {opened &&
        rows.some(row => row.id === opened) &&
        (() => {
          const call = rows.find(row => row.id === opened)!;
          return (
            <div className="grid gap-4 border-t border-stone-200 bg-stone-50 px-5 py-4 text-xs sm:grid-cols-4 dark:border-stone-800 dark:bg-stone-900/50">
              <div>
                <span className="text-stone-400">供应商 / 模型</span>
                <p className="mt-1 font-medium">
                  {call.provider} · {call.model}
                </p>
              </div>
              <div>
                <span className="text-stone-400">用量来源</span>
                <p className="mt-1 font-medium">{call.usage}</p>
              </div>
              <div>
                <span className="text-stone-400">输入 / 输出 / 总计</span>
                <p className="mt-1 font-medium tabular-nums">
                  {call.tokens === null
                    ? "待供应商用量确认"
                    : `${call.inputTokens.toLocaleString("zh-CN")} / ${call.outputTokens.toLocaleString("zh-CN")} / ${call.tokens.toLocaleString("zh-CN")}`}
                </p>
              </div>
              <div>
                <span className="text-stone-400">核算规则</span>
                <p className="mt-1 font-medium">
                  {call.tokens === null
                    ? "缺失真实 usage，不能按 0 收费"
                    : "真实 usage × 调用时有效价格版本"}
                </p>
                {call.tokens !== null && (
                  <p className="mt-1 font-medium tabular-nums">
                    未舍入示例：{formatDemoFeeExact(call.tokens, price)}
                  </p>
                )}
              </div>
            </div>
          );
        })()}
    </div>
  );
}

function UserSummary({ tenant, price }: { tenant: TenantId | "all"; price: string }) {
  const groups = new Map<string, { tokens: number; pending: number }>();
  for (const call of CALLS) {
    if (tenant !== "all" && call.tenant !== tenant) continue;
    const current = groups.get(call.user) ?? { tokens: 0, pending: 0 };
    if (call.tokens === null) current.pending += 1;
    else current.tokens += call.tokens;
    groups.set(call.user, current);
  }

  return (
    <section aria-label="演示用户汇总">
      <div className="mb-3 flex items-end justify-between gap-3">
        <h3 className="font-serif text-lg font-semibold">按用户汇总</h3>
        <span className="text-xs text-stone-500">已核算与待核算分列</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {[...groups].map(([user, usage]) => (
          <div
            key={user}
            className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-950"
          >
            <p className="text-xs font-semibold text-stone-500">{user}</p>
            <p className="mt-2 font-serif text-xl font-semibold tabular-nums">
              {usage.pending && usage.tokens === 0
                ? "待核算"
                : usage.tokens.toLocaleString("zh-CN")}{" "}
              <span className="font-sans text-xs font-normal">
                {usage.pending && usage.tokens === 0 ? "" : "Token"}
              </span>
            </p>
            <div className="mt-3 flex items-center justify-between gap-2 border-t border-stone-100 pt-3 text-xs dark:border-stone-800">
              <span className="font-semibold text-emerald-800 dark:text-emerald-300">
                {usage.pending && usage.tokens === 0
                  ? "待核算"
                  : formatDemoFee(usage.tokens, price)}
              </span>
              <span className="text-stone-500">
                {usage.pending ? `${usage.pending} 条待核算` : "均已核算"}
              </span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function OmsPrototype() {
  const [view, setView] = useState<View>("overview");
  const [search, setSearch] = useState("");
  const [tenant, setTenant] = useState<TenantId | "all">("all");
  const [selectedService, setSelectedService] = useState(OMS_SERVICE_INVENTORY[0].service);
  const [price, setPrice] = useState("12.345678");
  const [showArrears, setShowArrears] = useState(false);
  const [showCost, setShowCost] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const visibleTenants = useMemo(
    () => TENANTS.filter(item => `${item.name} ${item.contact}`.includes(search.trim())),
    [search],
  );
  const service = OMS_SERVICE_INVENTORY.find(item => item.service === selectedService)!;
  const feeFormatValid = /^\d{1,12}(?:\.\d{1,6})?$/.test(price);
  const totalTokens = CALLS.filter(
    call => (tenant === "all" || call.tenant === tenant) && call.tokens !== null,
  ).reduce((sum, call) => sum + (call.tokens ?? 0), 0);

  const go = (next: View) => {
    setView(next);
    setSidebarOpen(false);
  };

  const moveServiceTab = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    const count = OMS_SERVICE_INVENTORY.length;
    let nextIndex: number;
    switch (event.key) {
      case "ArrowDown":
      case "ArrowRight":
        nextIndex = (index + 1) % count;
        break;
      case "ArrowUp":
      case "ArrowLeft":
        nextIndex = (index - 1 + count) % count;
        break;
      case "Home":
        nextIndex = 0;
        break;
      case "End":
        nextIndex = count - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    const nextService = OMS_SERVICE_INVENTORY[nextIndex].service;
    setSelectedService(nextService);
    document.getElementById(`oms-service-tab-${nextService}`)?.focus();
  };

  return (
    <main className="min-h-screen bg-[#f5f4ef] text-stone-900 dark:bg-[#171d1b] dark:text-stone-100">
      <div className="mx-auto flex min-h-screen max-w-[1600px]">
        {sidebarOpen && (
          <button
            type="button"
            aria-label="关闭导航"
            className="fixed inset-0 z-20 bg-black/40 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
        <aside
          className={`${sidebarOpen ? "translate-x-0" : "-translate-x-full"} fixed inset-y-0 left-0 z-30 flex w-[260px] shrink-0 flex-col border-r border-[#dfe3db] bg-[#e9eee6] px-4 py-6 transition-transform lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 dark:border-stone-800 dark:bg-[#202b27]`}
        >
          <div className="flex items-start justify-between px-3">
            <div>
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#194a3b] text-white">
                  <Layers3 className="h-4 w-4" />
                </div>
                <span className="font-serif text-2xl font-bold tracking-tight">OMS</span>
              </div>
              <p className="mt-2 text-xs tracking-[0.15em] text-stone-500 dark:text-stone-400">
                平台运营 · 交互预览
              </p>
            </div>
            <button
              type="button"
              aria-label="关闭侧边栏"
              className="lg:hidden"
              onClick={() => setSidebarOpen(false)}
            >
              <PanelLeftClose className="h-5 w-5" />
            </button>
          </div>
          <div className="mt-8 border-t border-[#ced9cc] pt-5 dark:border-stone-700">
            <p className="px-3 text-[10px] font-bold tracking-[0.2em] text-stone-500 uppercase">
              工作区
            </p>
            <nav className="mt-3 space-y-1" aria-label="OMS 原型导航">
              {NAV.map(({ view: item, label, hint, icon: Icon }) => (
                <button
                  key={item}
                  type="button"
                  aria-current={view === item ? "page" : undefined}
                  onClick={() => go(item)}
                  className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors ${view === item ? "bg-[#194a3b] text-white shadow-sm" : "text-stone-700 hover:bg-white/70 dark:text-stone-200 dark:hover:bg-white/10"}`}
                >
                  <Icon className="h-[18px] w-[18px] shrink-0" />
                  <span>
                    <span className="block text-sm font-semibold">{label}</span>
                    <span
                      className={`mt-0.5 block text-[11px] ${view === item ? "text-emerald-100/80" : "text-stone-500 dark:text-stone-400"}`}
                    >
                      {hint}
                    </span>
                  </span>
                </button>
              ))}
            </nav>
          </div>
          <div className="mt-auto rounded-xl border border-[#cbd8cc] bg-white/60 p-3 text-xs leading-5 text-stone-600 dark:border-stone-700 dark:bg-white/5 dark:text-stone-300">
            <span className="font-semibold text-emerald-800 dark:text-emerald-200">演示环境</span>
            <p className="mt-1">不连接 OMS 数据，不保存任何操作。正式能力由后续提案交付。</p>
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <div className="border-b border-[#e3e4dc] bg-[#fbfaf6] px-5 py-3.5 dark:border-stone-800 dark:bg-[#1b211e] sm:px-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  aria-label="打开导航"
                  className="rounded-lg border border-stone-200 p-2 lg:hidden dark:border-stone-700"
                  onClick={() => setSidebarOpen(true)}
                >
                  <Layers3 className="h-4 w-4" />
                </button>
                <span className="text-xs font-medium text-stone-500">平台运营</span>
                <ArrowRight className="h-3.5 w-3.5 text-stone-400" />
                <span className="text-xs font-semibold">
                  {NAV.find(item => item.view === view)?.label}
                </span>
              </div>
              <StatusPill tone="amber">
                <CircleAlert className="h-3.5 w-3.5" /> 仅供评审 · 非真实数据
              </StatusPill>
            </div>
          </div>
          <div className="mx-auto max-w-[1180px] px-5 pb-16 pt-8 sm:px-8 lg:px-10">
            <header className="mb-8 border-b border-[#dedfd7] pb-7 dark:border-stone-800">
              <p className="text-[11px] font-bold tracking-[0.24em] text-emerald-700 uppercase dark:text-emerald-300">
                DeepTutor / Operations Preview
              </p>
              <h1 className="mt-3 max-w-4xl font-serif text-3xl font-semibold tracking-tight sm:text-[38px]">
                {viewTitle[view]}
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-stone-500 dark:text-stone-400">
                这是开发环境中的 OMS
                交互演示。所有租户、调用和金额均为虚构样例；不代表已开通的治理、供应商或计费能力。
              </p>
            </header>

            {view === "overview" && (
              <div className="space-y-9">
                <section>
                  <SectionTitle
                    eyebrow="Today / 演示场景"
                    title="先处理，再浏览"
                    description="普通运营先看到影响范围和下一步，不必理解底层接口或数据库。"
                  />
                  <div className="grid gap-4 md:grid-cols-3">
                    <button
                      type="button"
                      onClick={() => go("tenants")}
                      className="group rounded-2xl border border-amber-200 bg-[#fff9ed] p-5 text-left transition-transform hover:-translate-y-0.5 dark:border-amber-900 dark:bg-amber-950/20"
                    >
                      <Clock3 className="h-5 w-5 text-amber-700" />
                      <p className="mt-5 text-xs font-semibold text-amber-800 dark:text-amber-200">
                        待外部确认
                      </p>
                      <h3 className="mt-1 font-serif text-xl font-semibold">模型限制尚未生效</h3>
                      <p className="mt-2 text-sm leading-6 text-stone-600 dark:text-stone-300">
                        示例租户 A 的处理请求仍在等待 EduPlus2 确认。
                      </p>
                      <span className="mt-5 inline-flex items-center gap-1 text-xs font-semibold text-amber-800">
                        查看租户{" "}
                        <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => go("billing")}
                      className="group rounded-2xl border border-stone-200 bg-white p-5 text-left transition-transform hover:-translate-y-0.5 dark:border-stone-800 dark:bg-stone-950"
                    >
                      <ReceiptText className="h-5 w-5 text-emerald-700" />
                      <p className="mt-5 text-xs font-semibold text-emerald-700">待核算明细</p>
                      <h3 className="mt-1 font-serif text-xl font-semibold">一条调用缺用量</h3>
                      <p className="mt-2 text-sm leading-6 text-stone-500">
                        流中断没有最终 usage；不能按零 Token 计费。
                      </p>
                      <span className="mt-5 inline-flex items-center gap-1 text-xs font-semibold text-emerald-700">
                        查看明细{" "}
                        <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => go("services")}
                      className="group rounded-2xl border border-stone-200 bg-white p-5 text-left transition-transform hover:-translate-y-0.5 dark:border-stone-800 dark:bg-stone-950"
                    >
                      <Activity className="h-5 w-5 text-emerald-700" />
                      <p className="mt-5 text-xs font-semibold text-emerald-700">服务覆盖</p>
                      <h3 className="mt-1 font-serif text-xl font-semibold">不止对话模型</h3>
                      <p className="mt-2 text-sm leading-6 text-stone-500">
                        逐项查看搜索、向量、语音、图片和视频服务的设置语义。
                      </p>
                      <span className="mt-5 inline-flex items-center gap-1 text-xs font-semibold text-emerald-700">
                        查看服务{" "}
                        <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                      </span>
                    </button>
                  </div>
                </section>
                <section className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
                  <div className="rounded-2xl bg-[#194a3b] p-6 text-white">
                    <p className="text-xs font-bold tracking-[0.15em] text-emerald-200">运营边界</p>
                    <h2 className="mt-4 font-serif text-2xl">OMS 管查询和计费，不管租户开停</h2>
                    <p className="mt-3 text-sm leading-7 text-emerald-50/80">
                      租户资格由 EduPlus2 权威 webhook 更新；Provider 和凭据由 DeepTutor
                      平台设置维护。欠费只限制新的模型调用，登录与管理继续可用。
                    </p>
                  </div>
                  <div className="rounded-2xl border border-stone-200 bg-white p-6 dark:border-stone-800 dark:bg-stone-950">
                    <ShieldCheck className="h-5 w-5 text-emerald-700" />
                    <h2 className="mt-4 font-serif text-xl font-semibold">正式上线的条件</h2>
                    <p className="mt-3 text-sm leading-7 text-stone-500">
                      平台权限、真实服务状态、逐调用 Token
                      总账、价格版本与外部资格确认均完成后，才会连接真实 API。
                    </p>
                  </div>
                </section>
              </div>
            )}

            {view === "tenants" && (
              <div className="space-y-6">
                <SectionTitle
                  eyebrow="Tenant / 只读治理"
                  title="两种状态，不能混为一谈"
                  description="租户资格决定整体入口；模型资格仅决定能否发起新的模型调用。OMS 不提供开停租户按钮。"
                />
                <div className="relative max-w-sm">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
                  <input
                    value={search}
                    onChange={event => setSearch(event.target.value)}
                    placeholder="搜索演示租户"
                    aria-label="搜索演示租户"
                    className="w-full rounded-xl border border-stone-200 bg-white py-2.5 pl-10 pr-3 text-sm outline-none focus:border-emerald-700 dark:border-stone-700 dark:bg-stone-950"
                  />
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  {visibleTenants.map(item => (
                    <article
                      key={item.id}
                      className="rounded-2xl border border-stone-200 bg-white p-6 dark:border-stone-800 dark:bg-stone-950"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-xs text-stone-400">{item.contact}</p>
                          <h3 className="mt-1 font-serif text-xl font-semibold">{item.name}</h3>
                        </div>
                        <StatusPill tone={item.modelTone}>{item.modelStatus}</StatusPill>
                      </div>
                      <div className="mt-6 grid gap-3 border-t border-stone-100 pt-5 text-sm sm:grid-cols-2 dark:border-stone-800">
                        <div>
                          <p className="text-xs text-stone-400">租户资格 · EduPlus2</p>
                          <p className="mt-1 font-medium">演示：可登录与管理</p>
                        </div>
                        <div>
                          <p className="text-xs text-stone-400">模型使用资格 · 独立事件</p>
                          <p className="mt-1 font-medium">{item.modelStatus}</p>
                        </div>
                      </div>
                      <p className="mt-5 rounded-xl bg-stone-50 p-3 text-xs leading-5 text-stone-600 dark:bg-stone-900 dark:text-stone-300">
                        {item.note}
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          setTenant(item.id);
                          go("billing");
                        }}
                        className="mt-5 inline-flex items-center gap-1 text-xs font-semibold text-emerald-800 hover:underline dark:text-emerald-300"
                      >
                        查看演示用量 <ArrowRight className="h-3.5 w-3.5" />
                      </button>
                    </article>
                  ))}
                </div>
                {visibleTenants.length === 0 && (
                  <p className="rounded-xl border border-dashed border-stone-300 p-8 text-center text-sm text-stone-500">
                    未找到匹配的演示租户。
                  </p>
                )}
                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-7 text-amber-950 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-100">
                  <strong>处理原则：</strong>欠费请求未收到 EduPlus2 webhook
                  前只能显示“待外部确认”；已确认受限时仍允许登录、TMS/OMS
                  管理、历史查询及非模型操作。
                </div>
              </div>
            )}

            {view === "services" && (
              <div>
                <SectionTitle
                  eyebrow="Services / 设置来源"
                  title="按 DeepTutor 模型目录逐项看"
                  description="八类模型目录服务逐项只读盘点；文档解析、外部 Agent 与视频学习在下方单列范围提示。供应商候选和字段条件来自现有设置逻辑，真实就绪状态尚待企业治理 API。"
                />
                <div className="grid gap-5 lg:grid-cols-[285px_minmax(0,1fr)]">
                  <div className="space-y-2" role="tablist" aria-label="服务类型">
                    {OMS_SERVICE_INVENTORY.map((item, index) => (
                      <button
                        key={item.service}
                        id={`oms-service-tab-${item.service}`}
                        type="button"
                        role="tab"
                        aria-selected={selectedService === item.service}
                        aria-controls="oms-service-panel"
                        tabIndex={selectedService === item.service ? 0 : -1}
                        onKeyDown={event => moveServiceTab(event, index)}
                        onClick={() => setSelectedService(item.service)}
                        className={`flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left text-sm transition-colors ${selectedService === item.service ? "border-[#194a3b] bg-[#194a3b] font-semibold text-white" : "border-stone-200 bg-white hover:border-emerald-600 dark:border-stone-800 dark:bg-stone-950"}`}
                      >
                        <span>{item.title}</span>
                        <ArrowRight className="h-4 w-4" />
                      </button>
                    ))}
                  </div>
                  <section
                    id="oms-service-panel"
                    role="tabpanel"
                    aria-labelledby={`oms-service-tab-${selectedService}`}
                    tabIndex={0}
                    className="rounded-2xl border border-stone-200 bg-white p-6 dark:border-stone-800 dark:bg-stone-950"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-xs font-bold tracking-[0.2em] text-emerald-700 uppercase dark:text-emerald-300">
                          DeepTutor · {service.service}
                        </p>
                        <h3 className="mt-2 font-serif text-2xl font-semibold">{service.title}</h3>
                        <p className="mt-1 text-sm text-stone-500">{service.purpose}</p>
                      </div>
                      <StatusPill tone="neutral">真实状态待接入</StatusPill>
                    </div>
                    <div className="mt-6 border-t border-stone-100 pt-5 dark:border-stone-800">
                      <h4 className="text-xs font-bold tracking-wide text-stone-500">
                        现有设置属性类别 · 只读清单
                      </h4>
                      <p className="mt-3 text-[11px] font-semibold text-stone-400">服务档案</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {service.profileFields.map(field => (
                          <span
                            key={`profile-${field}`}
                            title={field}
                            className="rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-700 dark:border-stone-800 dark:bg-stone-900 dark:text-stone-300"
                          >
                            {INVENTORY_FIELD_LABELS[field] ?? field}
                          </span>
                        ))}
                      </div>
                      <p className="mt-4 text-[11px] font-semibold text-stone-400">模型属性</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {service.modelFields.length ? (
                          service.modelFields.map(field => (
                            <span
                              key={`model-${field}`}
                              title={field}
                              className="rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-700 dark:border-stone-800 dark:bg-stone-900 dark:text-stone-300"
                            >
                              {INVENTORY_FIELD_LABELS[field] ?? field}
                            </span>
                          ))
                        ) : (
                          <span className="text-xs text-stone-500">
                            不适用；此服务没有模型选择。
                          </span>
                        )}
                      </div>
                      <p className="mt-4 text-xs leading-6 text-stone-500">{service.note}</p>
                    </div>
                    <div className="mt-6 rounded-xl bg-[#eef3ec] p-4 text-xs leading-6 text-[#315343] dark:bg-emerald-950/30 dark:text-emerald-200">
                      <strong>维护归口：DeepTutor 平台设置。</strong> OMS
                      只读服务可用性，不显示凭据、原始地址或配置写入口；服务 active
                      需执行者真实确认。
                    </div>
                  </section>
                </div>
                <div className="mt-6 grid gap-3 md:grid-cols-3">
                  <div className="rounded-xl border border-stone-200 bg-white p-4 text-xs leading-6 dark:border-stone-800 dark:bg-stone-950">
                    <BookOpen className="mb-2 h-4 w-4 text-emerald-700" />
                    <strong>共享连接</strong>
                    <p className="mt-1 text-stone-500">
                      覆盖除搜索外的七项模型服务；OMS 不显示密钥。
                    </p>
                  </div>
                  <div className="rounded-xl border border-stone-200 bg-white p-4 text-xs leading-6 dark:border-stone-800 dark:bg-stone-950">
                    <BookOpen className="mb-2 h-4 w-4 text-emerald-700" />
                    <strong>文档解析与外部 Agent</strong>
                    <p className="mt-1 text-stone-500">另有独立设置语义，不套用模型目录字段。</p>
                  </div>
                  <div className="rounded-xl border border-stone-200 bg-white p-4 text-xs leading-6 dark:border-stone-800 dark:bg-stone-950">
                    <BookOpen className="mb-2 h-4 w-4 text-emerald-700" />
                    <strong>视频学习</strong>
                    <p className="mt-1 text-stone-500">
                      YouTube / Invidious 播放来源，不等于文生视频。
                    </p>
                  </div>
                </div>
              </div>
            )}

            {view === "billing" && (
              <div className="space-y-7">
                <SectionTitle
                  eyebrow="Usage & Billing / 虚构明细"
                  title="从租户，到用户，再到每次调用"
                  description="只有目标供应商返回的真实 usage 才能正式入账；以下数据与费用仅展示交互结构，不是账单。"
                />
                <div className="flex flex-wrap items-end gap-4 rounded-2xl border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-950">
                  <label className="min-w-44 flex-1 text-xs font-semibold text-stone-500">
                    演示租户
                    <select
                      value={tenant}
                      onChange={event => setTenant(event.target.value as TenantId | "all")}
                      className="mt-2 block w-full rounded-lg border border-stone-200 bg-transparent px-3 py-2.5 text-sm text-stone-900 dark:border-stone-700 dark:text-stone-100"
                    >
                      <option value="all">全部演示租户</option>
                      {TENANTS.map(item => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="min-w-44 flex-1 text-xs font-semibold text-stone-500">
                    演示单价 · 元 / 百万 Token
                    <input
                      value={price}
                      onChange={event => setPrice(event.target.value)}
                      inputMode="decimal"
                      aria-invalid={!feeFormatValid}
                      className="mt-2 block w-full rounded-lg border border-stone-200 bg-transparent px-3 py-2.5 text-sm tabular-nums text-stone-900 outline-none focus:border-emerald-700 dark:border-stone-700 dark:text-stone-100"
                    />
                    <span className="mt-1 block font-normal">
                      只预览统一情景价，不保存，也不改动真实历史价格版本
                    </span>
                  </label>
                  <div className="min-w-36 pb-2">
                    <p className="text-xs font-semibold text-stone-500">已核算示例用量</p>
                    <p className="mt-1 font-serif text-xl font-semibold tabular-nums">
                      {totalTokens.toLocaleString("zh-CN")}
                    </p>
                  </div>
                  <div className="min-w-28 pb-2">
                    <p className="text-xs font-semibold text-stone-500">示例合计</p>
                    <p className="mt-1 font-serif text-xl font-semibold tabular-nums text-emerald-800 dark:text-emerald-300">
                      {formatDemoFee(totalTokens, price)}
                    </p>
                  </div>
                </div>
                <UserSummary tenant={tenant} price={price} />
                <CallTable tenant={tenant} price={price} />
                <p className="text-xs leading-5 text-stone-500">
                  示例合计排除待核算调用；合计按未舍入金额汇总，逐行显示到分，因此可能存在显示舍入差异。
                  正式价格由 OMS 授权管理并按调用时有效版本保存，费用在后端用 Decimal
                  计算；前端不得自行重算真实账单。
                </p>
                <div className="grid gap-4 md:grid-cols-2">
                  <button
                    type="button"
                    onClick={() => setShowArrears(true)}
                    className="group rounded-2xl border border-amber-200 bg-amber-50 p-5 text-left dark:border-amber-900 dark:bg-amber-950/20"
                  >
                    <Clock3 className="h-5 w-5 text-amber-700" />
                    <h3 className="mt-3 font-serif text-xl font-semibold">欠费处理路径</h3>
                    <p className="mt-2 text-sm leading-6 text-stone-600 dark:text-stone-300">
                      查看从计费处理到外部确认、再到模型调用限制的步骤。
                    </p>
                    <span className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-amber-800">
                      查看流程 <ArrowRight className="h-3.5 w-3.5 group-hover:translate-x-1" />
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowCost(!showCost)}
                    aria-expanded={showCost}
                    className="group rounded-2xl border border-stone-200 bg-white p-5 text-left dark:border-stone-800 dark:bg-stone-950"
                  >
                    <LockKeyhole className="h-5 w-5 text-emerald-700" />
                    <h3 className="mt-3 font-serif text-xl font-semibold">供应商成本拆分</h3>
                    <p className="mt-2 text-sm leading-6 text-stone-500">
                      仅 OMS 授权人员可读，租户和用户账单不包含。
                    </p>
                    <span className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-emerald-800 dark:text-emerald-300">
                      {showCost ? "收起演示拆分" : "查看演示拆分"}{" "}
                      <ArrowDownRight className="h-3.5 w-3.5" />
                    </span>
                  </button>
                </div>
                {showCost && (
                  <div className="overflow-hidden rounded-2xl border border-stone-200 bg-white text-sm dark:border-stone-800 dark:bg-stone-950">
                    <div className="border-b border-stone-100 px-5 py-4 dark:border-stone-800">
                      <strong>供应商成本 · 虚构示例</strong>
                      <p className="mt-1 text-xs leading-5 text-stone-500">
                        正式视图需要
                        `ops.billing.cost.read`。这里不是实际授权判断，也不展示真实成本。
                      </p>
                    </div>
                    <div className="grid grid-cols-[1fr_auto_auto] gap-3 px-5 py-4 text-xs sm:gap-6">
                      <div>
                        <strong>示例供应商甲 / 示例模型 α、β</strong>
                        <p className="mt-1 text-stone-500">
                          已核算 1,510,000 Token · 演示成本价 ¥8 / 百万
                        </p>
                      </div>
                      <span className="self-center text-stone-500">示例成本</span>
                      <strong className="self-center tabular-nums">
                        {formatDemoFee(1_510_000, "8")}
                      </strong>
                    </div>
                    <div className="grid grid-cols-[1fr_auto_auto] gap-3 border-t border-stone-100 px-5 py-4 text-xs sm:gap-6 dark:border-stone-800">
                      <div>
                        <strong>示例供应商乙 / 示例模型 γ</strong>
                        <p className="mt-1 text-stone-500">缺少真实 usage，不能按零成本计入</p>
                      </div>
                      <span className="self-center text-stone-500">示例成本</span>
                      <strong className="self-center text-amber-700">成本待核算</strong>
                    </div>
                    <p className="border-t border-stone-100 px-5 py-3 text-xs leading-5 text-stone-500 dark:border-stone-800">
                      正式页面按 provider/model、价格版本与调用分别核算；成本字段必须由服务端在
                      TMS、用户和租户导出中排除。
                    </p>
                  </div>
                )}
              </div>
            )}

            {view === "activity" && (
              <div>
                <SectionTitle
                  eyebrow="Audit / 只读记录"
                  title="查得到过程，但不在这里控制系统"
                  description="审计与任务面向运营追踪，不提供重试、取消、底层存储或基础设施按钮。"
                />
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-2xl border border-stone-200 bg-white p-6 dark:border-stone-800 dark:bg-stone-950">
                    <FileClock className="h-6 w-6 text-emerald-700" />
                    <h3 className="mt-4 font-serif text-xl font-semibold">审计记录</h3>
                    <p className="mt-2 text-sm leading-7 text-stone-500">
                      正式接入后可按租户、时间、动作和结果查询脱敏记录。当前不连接审计
                      API，不展示虚构“真实日志”。
                    </p>
                    <StatusPill>待接入只读查询</StatusPill>
                  </div>
                  <div className="rounded-2xl border border-stone-200 bg-white p-6 dark:border-stone-800 dark:bg-stone-950">
                    <Activity className="h-6 w-6 text-emerald-700" />
                    <h3 className="mt-4 font-serif text-xl font-semibold">任务状态</h3>
                    <p className="mt-2 text-sm leading-7 text-stone-500">
                      正式接入后显示影响对象、当前状态、建议动作与关联审计编号；技术错误只在脱敏详情中显示。
                    </p>
                    <StatusPill>待接入只读查询</StatusPill>
                  </div>
                </div>
                <p className="mt-6 text-xs text-stone-500">
                  状态文案将由后端 display descriptor 提供；缺失时显示“状态说明缺失，请联系支持”。
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
      <Modal
        isOpen={showArrears}
        onClose={() => setShowArrears(false)}
        title="欠费只影响模型使用"
        width="lg"
        showCloseButton={false}
      >
        <div className="p-6">
          <div className="flex items-start justify-between gap-4">
            <p className="text-xs font-bold tracking-[0.2em] text-amber-700 uppercase">
              演示流程 · 不执行处理
            </p>
            <button
              type="button"
              aria-label="关闭欠费流程"
              onClick={() => setShowArrears(false)}
              className="rounded-lg p-1.5 hover:bg-stone-100 dark:hover:bg-stone-800"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          <ol className="mt-6 space-y-4 border-l-2 border-amber-200 pl-5 text-sm">
            <li>
              <strong className="flex items-center gap-2">
                <Check className="h-4 w-4 text-emerald-700" /> OMS 记录计费处理
              </strong>
              <p className="mt-1 text-stone-500">
                需授权、原因、价格/欠费版本与审计；不直接改租户状态。
              </p>
            </li>
            <li>
              <strong className="flex items-center gap-2">
                <Clock3 className="h-4 w-4 text-amber-700" /> 等待 EduPlus2 独立 webhook
              </strong>
              <p className="mt-1 text-stone-500">待确认期间不能宣称模型使用已受限。</p>
            </li>
            <li>
              <strong className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-emerald-700" /> DeepTutor 在模型调用前执行
              </strong>
              <p className="mt-1 text-stone-500">登录、管理、历史查询及非模型操作继续可用。</p>
            </li>
          </ol>
          <button
            type="button"
            onClick={() => setShowArrears(false)}
            className="mt-7 w-full rounded-xl bg-[#194a3b] px-4 py-3 text-sm font-semibold text-white"
          >
            了解，仅关闭演示
          </button>
        </div>
      </Modal>
    </main>
  );
}
