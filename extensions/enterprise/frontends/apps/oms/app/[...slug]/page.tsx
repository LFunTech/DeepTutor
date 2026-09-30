import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import OmsFormalApp from "../../src/OmsFormalApp";
import { hasOmsSessionCookieHeader, isReservedOmsSlug, omsForwardedOrigin, omsLoginStartUrl, omsReturnPath, type OmsSearchParams } from "../../src/omsServerGate";

const RETIRED_SCHOOL_BOOTSTRAP_ROUTES = new Set([
  "tms-bootstrap",
  "tms-bootstrap-requests",
]);

async function requireOmsSession(returnPath: string) {
  const requestHeaders = await headers();
  const origin = omsForwardedOrigin(requestHeaders);
  if (!hasOmsSessionCookieHeader(requestHeaders.get("cookie") ?? "")) redirect(omsLoginStartUrl(origin, returnPath));
}

export default async function Page({ params, searchParams }: { params: Promise<{ slug?: string[] }>; searchParams?: Promise<OmsSearchParams> }) {
  const { slug } = await params;
  if (isReservedOmsSlug(slug)) notFound();
  if (slug?.[0] && RETIRED_SCHOOL_BOOTSTRAP_ROUTES.has(slug[0])) notFound();
  await requireOmsSession(omsReturnPath(slug ?? [], await searchParams));
  return <OmsFormalApp/>;
}
