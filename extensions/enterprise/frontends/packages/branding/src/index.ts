export type BrandPalette = {
  primary: string;
  primary_hover: string;
  primary_light: string;
  primary_bg: string;
  sidebar: string;
  sidebar_hover: string;
  text_on_primary: string;
};

export type BrandContext = { scope: "platform" } | { scope: "tenant"; schoolCode: string; tenantId: string };
export type BrandTheme = { origin: "remote" | "fallback"; palette: BrandPalette; brandSource?: string };
type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
const PALETTE_KEYS = ["primary", "primary_hover", "primary_light", "primary_bg", "sidebar", "sidebar_hover", "text_on_primary"] as const;

export const SKY_PALETTE: BrandPalette = {
  primary: "#0369A1", primary_hover: "#075985", primary_light: "#E0F2FE",
  primary_bg: "#F0F9FF", sidebar: "#082F49", sidebar_hover: "#0C4A6E", text_on_primary: "#FFFFFF",
};

export function brandThemeStyle(palette: BrandPalette): Record<string, string> {
  return {
    "--brand-primary": palette.primary,
    "--brand-primary-hover": palette.primary_hover,
    "--brand-primary-light": palette.primary_light,
    "--brand-primary-bg": palette.primary_bg,
    "--brand-sidebar": palette.sidebar,
    "--brand-sidebar-hover": palette.sidebar_hover,
    "--brand-on-primary": palette.text_on_primary,
    "--brand-on-sidebar": readableOn(palette.sidebar),
  };
}

function channel(value: string): number[] {
  const hex = value.slice(1);
  return [0, 2, 4].map(index => Number.parseInt(hex.slice(index, index + 2), 16) / 255);
}

function luminance(value: string): number {
  const [red, green, blue] = channel(value).map(part => part <= 0.04045 ? part / 12.92 : ((part + 0.055) / 1.055) ** 2.4);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrast(a: string, b: string): number {
  const first = luminance(a), second = luminance(b);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

function readableOn(background: string): string {
  return contrast(background, "#FFFFFF") >= contrast(background, "#000000") ? "#FFFFFF" : "#000000";
}

function readPalette(value: unknown): BrandPalette | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (!PALETTE_KEYS.every(key => typeof record[key] === "string" && /^#[0-9a-fA-F]{6}$/.test(record[key]))) return null;
  const palette = Object.fromEntries(PALETTE_KEYS.map(key => [key, record[key]])) as BrandPalette;
  if (contrast(palette.primary, palette.text_on_primary) < 4.5 || contrast(palette.primary_hover, palette.text_on_primary) < 4.5) return null;
  if (contrast(palette.primary, "#FFFFFF") < 4.5 || contrast(palette.primary, palette.primary_bg) < 4.5) return null;
  if (contrast("#1C2B43", palette.primary_bg) < 4.5 || contrast(palette.primary_hover, palette.primary_light) < 4.5) return null;
  if (contrast(palette.sidebar_hover, readableOn(palette.sidebar)) < 4.5) return null;
  return palette;
}

function endpoint(baseUrl: string): URL | null {
  try {
    const base = new URL(baseUrl);
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(base.hostname);
    if (base.protocol !== "https:" && !(base.protocol === "http:" && local)) return null;
    if (base.username || base.password || base.search || base.hash || base.pathname !== "/") return null;
    return new URL("/api/v1/public/branding", base.origin);
  } catch { return null; }
}

export async function loadBrandTheme(options: { baseUrl?: string; context: BrandContext; fetcher?: Fetcher }): Promise<BrandTheme> {
  const fallback: BrandTheme = { origin: "fallback", palette: SKY_PALETTE };
  const url = endpoint(options.baseUrl ?? "");
  if (!url) return fallback;
  if (options.context.scope === "tenant") {
    const schoolCode = options.context.schoolCode.trim(), tenantId = options.context.tenantId.trim();
    if (!schoolCode || !tenantId) return fallback;
    url.searchParams.set("school_code", schoolCode);
    url.searchParams.set("tenant_id", tenantId);
  }
  try {
    const response = await (options.fetcher ?? fetch)(url.toString(), {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(3000),
      next: { revalidate: 300 },
    } as RequestInit);
    if (!response.ok) return fallback;
    const payload: unknown = await response.json();
    if (!payload || typeof payload !== "object" || (payload as { code?: unknown }).code !== 0) return fallback;
    const data = (payload as { data?: unknown }).data;
    if (!data || typeof data !== "object") return fallback;
    const brand = data as { palette?: unknown; brand_source?: unknown };
    if (options.context.scope === "platform" && brand.brand_source !== "platform_default") return fallback;
    const palette = readPalette(brand.palette);
    return palette ? { origin: "remote", palette, brandSource: typeof brand.brand_source === "string" ? brand.brand_source : undefined } : fallback;
  } catch { return fallback; }
}
