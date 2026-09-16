"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

/** The workspace root has one destination; sessions live under `/chat`.
 *
 * Keep this as a client-side replacement instead of a Server Component
 * `redirect("/chat")`: in Next dev/Turbopack, an RSC tree that only throws a
 * root redirect can make React's User Timing flush try to measure
 * `WorkspaceRootPage` with a negative end timestamp, which crashes the dev
 * overlay before the user reaches chat.
 */
export default function WorkspaceRootPage() {
  const { t } = useTranslation();

  useEffect(() => {
    window.location.replace("/chat");
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--background)] p-6 text-sm text-[var(--muted-foreground)]">
      <Link
        className="rounded-full border border-[var(--border)] px-4 py-2 transition hover:bg-[var(--secondary)] hover:text-[var(--foreground)]"
        href="/chat"
      >
        {t("Redirecting...")}
      </Link>
    </main>
  );
}
