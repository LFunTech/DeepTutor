import { headers } from "next/headers";
import { redirect } from "next/navigation";
import OmsFormalApp from "../src/OmsFormalApp";
import { hasOmsSessionCookieHeader, omsForwardedOrigin, omsLoginStartUrl, omsReturnPath, type OmsSearchParams } from "../src/omsServerGate";

async function requireOmsSession(returnPath: string) {
  const requestHeaders = await headers();
  const origin = omsForwardedOrigin(requestHeaders);
  if (!hasOmsSessionCookieHeader(requestHeaders.get("cookie") ?? "")) redirect(omsLoginStartUrl(origin, returnPath));
}

export default async function Page({ searchParams }: { searchParams?: Promise<OmsSearchParams> }) {
  await requireOmsSession(omsReturnPath([], await searchParams));
  return <OmsFormalApp/>;
}
