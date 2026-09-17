"use client";

import { FormEvent, useMemo, useState } from "react";

type AuditEvent = {
  id: string;
  created_at: string;
  event_kind: string;
  request_id: string;
  client_id: string;
  external_tenant_id: string;
  external_app_id: string;
  external_user_id: string;
  internal_user_id: string;
  result: string;
  reason: string;
  policy_version: string;
  summary: Record<string, unknown>;
};

type ExportJob = {
  id: string;
  status: string;
  format: "jsonl" | "csv";
  row_count: number;
  file_ref: string;
  expires_at: string;
  preview: string;
};

const FILTERS = [
  ["event_kind", "Event kind", "token.exchange"],
  ["client_id", "Client ID", "client-a"],
  ["external_user_id", "External user", "u-001"],
  ["result", "Result", "success"],
  ["request_id", "Request ID", "req-..."],
] as const;

function compactFilters(form: Record<string, string>) {
  return Object.fromEntries(Object.entries(form).filter(([, value]) => value.trim()));
}

export default function EduPlus2AuditPage() {
  const [filters, setFilters] = useState<Record<string, string>>({ limit: "50" });
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [job, setJob] = useState<ExportJob | null>(null);
  const [format, setFormat] = useState<"jsonl" | "csv">("jsonl");
  const [busy, setBusy] = useState<"query" | "export" | "">("");
  const [error, setError] = useState("");

  const queryString = useMemo(() => {
    const params = new URLSearchParams(compactFilters(filters));
    return params.toString();
  }, [filters]);

  async function query(event?: FormEvent) {
    event?.preventDefault();
    setBusy("query");
    setError("");
    try {
      const response = await fetch(`/api/v1/enterprise/audit/eduplus2/events?${queryString}`, {
        credentials: "include",
      });
      if (!response.ok) throw new Error(`Query failed: HTTP ${response.status}`);
      const payload = await response.json();
      setEvents(payload.items ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setBusy("");
    }
  }

  async function exportAudit() {
    setBusy("export");
    setError("");
    try {
      const response = await fetch("/api/v1/enterprise/audit/eduplus2/exports", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...compactFilters(filters), format }),
      });
      if (!response.ok) throw new Error(`Export failed: HTTP ${response.status}`);
      setJob(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setBusy("");
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,rgba(14,165,233,0.16),transparent_34rem),linear-gradient(135deg,#f8fafc,#eef2ff)] px-6 py-10 text-slate-950 dark:bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.15),transparent_34rem),linear-gradient(135deg,#020617,#0f172a)] dark:text-slate-50">
      <section className="mx-auto flex max-w-6xl flex-col gap-6">
        <div className="rounded-[2rem] border border-slate-200/80 bg-white/80 p-7 shadow-[0_24px_80px_rgba(15,23,42,0.10)] backdrop-blur dark:border-slate-700/80 dark:bg-slate-950/70">
          <p className="text-xs font-black uppercase tracking-[0.32em] text-sky-600 dark:text-sky-300">
            Enterprise audit · EduPlus2
          </p>
          <h1 className="mt-3 max-w-3xl text-4xl font-black tracking-tight text-slate-950 dark:text-white">
            联邦访问审计导出
          </h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            独立企业审计入口，不依赖 /tms 或 /oms。查询和导出均由后端按租户、角色、脱敏规则强制校验；页面不会展示 raw token、client secret 或完整 profile。
          </p>
        </div>

        <form onSubmit={query} className="grid gap-3 rounded-[1.75rem] border border-slate-200 bg-white/85 p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950/70 md:grid-cols-6">
          {FILTERS.map(([key, label, placeholder]) => (
            <label key={key} className="flex flex-col gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
              {label}
              <input
                className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm normal-case tracking-normal text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-50 dark:focus:ring-sky-950"
                placeholder={placeholder}
                value={filters[key] ?? ""}
                onChange={(event) => setFilters((prev) => ({ ...prev, [key]: event.target.value }))}
              />
            </label>
          ))}
          <label className="flex flex-col gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            Limit
            <input
              className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm normal-case tracking-normal text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-50"
              value={filters.limit ?? "50"}
              onChange={(event) => setFilters((prev) => ({ ...prev, limit: event.target.value }))}
            />
          </label>
          <div className="flex items-end gap-2 md:col-span-6">
            <button className="rounded-2xl bg-slate-950 px-5 py-3 text-sm font-bold text-white shadow-lg shadow-slate-950/15 transition hover:-translate-y-0.5 disabled:opacity-60 dark:bg-sky-300 dark:text-slate-950" disabled={busy !== ""}>
              {busy === "query" ? "查询中…" : "查询审计"}
            </button>
            <select className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-900" value={format} onChange={(event) => setFormat(event.target.value as "jsonl" | "csv") }>
              <option value="jsonl">JSONL</option>
              <option value="csv">CSV</option>
            </select>
            <button type="button" onClick={exportAudit} className="rounded-2xl border border-sky-300 bg-sky-50 px-5 py-3 text-sm font-bold text-sky-900 transition hover:-translate-y-0.5 disabled:opacity-60 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-100" disabled={busy !== ""}>
              {busy === "export" ? "导出中…" : "生成导出"}
            </button>
          </div>
        </form>

        {error ? (
          <div className="rounded-3xl border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-900 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-100">
            {error}
          </div>
        ) : null}

        {job ? (
          <section className="rounded-[1.75rem] border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100">
            <div className="font-black uppercase tracking-[0.2em]">Export {job.status}</div>
            <div className="mt-2 grid gap-2 md:grid-cols-3">
              <code className="rounded-xl bg-white/70 p-3 dark:bg-slate-950/60">{job.file_ref}</code>
              <div className="rounded-xl bg-white/70 p-3 dark:bg-slate-950/60">Rows: {job.row_count}</div>
              <div className="rounded-xl bg-white/70 p-3 dark:bg-slate-950/60">Expires: {job.expires_at}</div>
            </div>
            <pre className="mt-3 max-h-52 overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">{job.preview}</pre>
          </section>
        ) : null}

        <section className="overflow-hidden rounded-[1.75rem] border border-slate-200 bg-white/85 shadow-sm dark:border-slate-800 dark:bg-slate-950/70">
          <div className="border-b border-slate-200 px-5 py-4 text-sm font-black uppercase tracking-[0.2em] text-slate-500 dark:border-slate-800">
            Results · {events.length}
          </div>
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {events.map((item) => (
              <article key={item.id} className="grid gap-3 px-5 py-4 text-sm md:grid-cols-[12rem_1fr_8rem]">
                <div className="font-mono text-xs text-slate-500">{new Date(item.created_at).toLocaleString()}</div>
                <div>
                  <div className="font-bold text-slate-950 dark:text-white">{item.event_kind}</div>
                  <div className="mt-1 text-xs text-slate-500">
                    req={item.request_id || "—"} · client={item.client_id || "—"} · user={item.external_user_id || "—"}
                  </div>
                </div>
                <div className={`rounded-full px-3 py-1 text-center text-xs font-black ${item.result === "success" ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" : "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"}`}>
                  {item.result}
                </div>
              </article>
            ))}
            {events.length === 0 ? <div className="px-5 py-10 text-center text-sm text-slate-500">暂无结果。调整筛选条件后查询。</div> : null}
          </div>
        </section>
      </section>
    </main>
  );
}
