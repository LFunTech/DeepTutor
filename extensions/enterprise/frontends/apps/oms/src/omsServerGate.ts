export type OmsSearchParams = Record<string, string | string[] | undefined>;
export type CookieReader = { get(name: string): unknown };
export type HeaderReader = { get(name: string): string | null };

// `dt_oms_token` 与 `dt_oms_refresh` 的 Path 被限制在 `/api/v1/oms`，
// Next `/oms` 服务端入口通常看不到；`dt_oms_csrf` 是同一次 OMS 会话
// 设置在 `/` 的非敏感提示 Cookie，可用于避免已登录回跳登录页。
const OMS_SESSION_HINT_COOKIES = ["dt_oms_token", "dt_oms_refresh", "dt_oms_csrf"] as const;
const OMS_RESERVED_SLUG_FIRST_PARTS = new Set([
  "_next",
  "apple-icon.png",
  "favicon.ico",
  "icon.svg",
  "manifest.webmanifest",
  "robots.txt",
  "sitemap.xml",
]);

function safeHeader(value: string | null | undefined) {
  return value && !/[\r\n]/.test(value) ? value : "";
}

export function hasOmsSessionCookie(cookies: CookieReader) {
  return OMS_SESSION_HINT_COOKIES.some(name => Boolean(cookies.get(name)));
}

export function hasOmsSessionCookieHeader(cookieHeader: string) {
  const names = new Set(
    cookieHeader
      .split(";")
      .map(item => item.trim().split("=")[0])
      .filter(Boolean),
  );
  return OMS_SESSION_HINT_COOKIES.some(name => names.has(name));
}

export function omsForwardedOrigin(headers: HeaderReader) {
  const proto = safeHeader(headers.get("x-forwarded-proto")) || "https";
  const host = safeHeader(headers.get("x-forwarded-host")) || safeHeader(headers.get("host")) || "deeptutor.lfun.pub";
  return `${proto}://${host}`;
}

export function isReservedOmsSlug(slug: string[] = []) {
  const firstPart = slug[0] ?? "";
  return OMS_RESERVED_SLUG_FIRST_PARTS.has(firstPart);
}

export function omsReturnPath(slug: string[] = [], searchParams: OmsSearchParams = {}) {
  const path = slug.length
    ? `/oms/${slug.map(part => encodeURIComponent(part)).join("/")}`
    : "/oms";
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    if (typeof value === "undefined") continue;
    if (Array.isArray(value)) {
      for (const item of value) query.append(key, item);
    } else {
      query.append(key, value);
    }
  }
  const queryString = query.toString();
  return queryString ? `${path}?${queryString}` : path;
}

export function omsLoginStartUrl(origin: string, returnPath: string) {
  return `${origin}/api/v1/oms/auth/start?return_to=${encodeURIComponent(`${origin}${returnPath}`)}`;
}
