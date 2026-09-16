const CONTRACTS = [
  { label: "Usage", path: "/api/v1/oms/usage" },
  { label: "Audit", path: "/api/v1/oms/audit" },
  { label: "Secret references", path: "/api/v1/oms/secrets" },
] as const;

export default function OmsGovernancePage() {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <section className="rounded-3xl border border-slate-200 bg-white/80 p-6 shadow-sm dark:border-slate-800 dark:bg-slate-950/70">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600">OMS</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-950 dark:text-slate-50">
          Operations governance
        </h1>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
          Operators inspect ObjectStore usage, pending cleanup, configuration failures, Secret
          rotation state and redacted audit metadata. OMS must not expose private file body content
          or any long-lived download URL.
        </p>
      </section>

      <section className="grid gap-4 sm:grid-cols-3" aria-label="OMS API contracts">
        {CONTRACTS.map((item) => (
          <article key={item.path} className="rounded-2xl border border-slate-200 p-4 dark:border-slate-800">
            <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">{item.label}</div>
            <code className="mt-2 block rounded bg-slate-100 px-2 py-1 text-xs text-slate-700 dark:bg-slate-900 dark:text-slate-200">
              {item.path}
            </code>
          </article>
        ))}
      </section>

      <section className="rounded-3xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-100">
        Retry/cancel/compensation actions operate on authorized tenant resources and jobs only; they
        are idempotent governance operations, not direct bucket-prefix controls.
      </section>
    </main>
  );
}
