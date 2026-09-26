import "@deeptutor/admin-ui/styles.css";
import type { CSSProperties } from "react";
import { brandThemeStyle, loadBrandTheme } from "@deeptutor/branding";

export const metadata = { title: "OMS · DeepTutor 平台运营原型", description: "仅供开发环境审计的独立 OMS 前端原型" };
export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const theme = await loadBrandTheme({ baseUrl: process.env.EDUPLUS2_BRANDING_BASE_URL, context: { scope: "platform" } });
  return <html lang="zh-CN" style={brandThemeStyle(theme.palette) as CSSProperties}><body>{children}</body></html>;
}
