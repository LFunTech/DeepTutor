import "@deeptutor/admin-ui/styles.css";
import type { CSSProperties } from "react";
import { brandThemeStyle, loadBrandTheme, type BrandContext } from "@deeptutor/branding";
import { demoSchoolContext } from "../src/demo-school";

export const metadata = { title: "TMS · 学校智能体管理后台原型", description: "仅供开发环境审计的学校智能体管理后台原型" };
export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const demo = demoSchoolContext(process.env);
  const context: BrandContext = demo.tenantId ? { scope: "tenant", schoolCode: demo.schoolCode, tenantId: demo.tenantId } : { scope: "platform" };
  const theme = await loadBrandTheme({ baseUrl: process.env.EDUPLUS2_BRANDING_BASE_URL, context });
  return <html lang="zh-CN" style={brandThemeStyle(theme.palette) as CSSProperties}><body>
    {context.scope === "tenant" && theme.origin === "remote" && theme.brandSource === "school_brand" && <div className="branding-preview-note" role="note">品牌主题预览：下方业务记录为合成演示数据。</div>}
    {children}
  </body></html>;
}
