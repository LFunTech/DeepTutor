import "@deeptutor/admin-ui/styles.css";
import type { CSSProperties } from "react";
import { brandThemeStyle, loadBrandTheme } from "@deeptutor/branding";

export const metadata = { title: "智能体基座 · 平台智能体运营后台", description: "平台智能体运营后台正式受控入口" };
export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const theme = await loadBrandTheme({ baseUrl: process.env.EDUPLUS2_BRANDING_BASE_URL, context: { scope: "platform" } });
  return <html lang="zh-CN" style={brandThemeStyle(theme.palette) as CSSProperties}><body>{children}</body></html>;
}
