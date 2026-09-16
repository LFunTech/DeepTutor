const STATUSES = ["managed", "locked", "draft", "active", "failed"] as const;

export default function TmsGovernancePage() {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <section className="rounded-3xl border border-slate-200 bg-white/80 p-6 shadow-sm dark:border-slate-800 dark:bg-slate-950/70">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-600">TMS</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-950 dark:text-slate-50">
          Tenant runtime governance
        </h1>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
          Tenant administrators manage models, tools, KB, workspace and object policies through the
          Settings/Policy provider. The write contract is <code>/api/v1/tms/settings</code>; local
          settings files are not treated as production authority.
        </p>
      </section>

      <section className="grid gap-3 sm:grid-cols-5" aria-label="Configuration states">
        {STATUSES.map((status) => (
          <div key={status} className="rounded-2xl border border-slate-200 p-4 dark:border-slate-800">
            <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{status}</div>
            <div className="mt-2 text-sm text-slate-700 dark:text-slate-200">
              Externalized provider state is shown explicitly instead of surfacing a generic 500.
            </div>
          </div>
        ))}
      </section>

      <section className="rounded-3xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
        <strong>Secret reference required.</strong> Model/ObjectStore credentials are displayed as a
        Secret reference and readiness summary only; secret plaintext is never shown in this UI.
      </section>
    </main>
  );
}
