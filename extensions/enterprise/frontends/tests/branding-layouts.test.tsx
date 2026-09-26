import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import OmsLayout from "../apps/oms/app/layout";
import TmsLayout from "../apps/tms/app/layout";

const platform = {
  primary: "#1A56DB", primary_hover: "#1441A4", primary_light: "#D5DCEC",
  primary_bg: "#EAEEF6", sidebar: "#0C2969", sidebar_hover: "#103689", text_on_primary: "#FFFFFF",
};
const tenant = {
  primary: "#7C3AED", primary_hover: "#5B14D6", primary_light: "#F1EDF8",
  primary_bg: "#F6F4FB", sidebar: "#410E99", sidebar_hover: "#4F11BA", text_on_primary: "#FFFFFF",
};

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("独立应用首屏品牌", () => {
  it("OMS 服务端首次渲染使用无参平台蓝色，独立环境域名可更换", async () => {
    vi.stubEnv("EDUPLUS2_BRANDING_BASE_URL", "https://auth.prod.example");
    const requested: string[] = [];
    vi.stubGlobal("fetch", async (input: string) => {
      requested.push(input);
      return Response.json({ code: 0, data: { brand_source: "platform_default", fallback_reason: "context_missing", palette: platform } });
    });
    const html = await OmsLayout({ children: <main/> });
    expect(requested).toEqual(["https://auth.prod.example/api/v1/public/branding"]);
    expect(html.props.style["--brand-primary"]).toBe("#1A56DB");
    expect(html.props.style["--brand-sidebar"]).toBe("#0C2969");
  });

  it("TMS 用配对演示学校参数首屏取得紫色，不读取页面伪造学校参数", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("EDUPLUS2_BRANDING_BASE_URL", "https://auth.test.example");
    vi.stubEnv("TMS_DEMO_SCHOOL_CODE", "jygjzx");
    vi.stubEnv("TMS_DEMO_TENANT_ID", "92");
    window.history.replaceState(null, "", "/tms/prototype/jygjzx?school_code=other&tenant_id=999");
    const requested: string[] = [];
    vi.stubGlobal("fetch", async (input: string) => {
      requested.push(input);
      return Response.json({ code: 0, data: { brand_source: "school_brand", fallback_reason: "school_brand_missing", palette: tenant } });
    });
    const html = await TmsLayout({ children: <main/> });
    expect(requested).toEqual(["https://auth.test.example/api/v1/public/branding?school_code=jygjzx&tenant_id=92"]);
    expect(html.props.style["--brand-primary"]).toBe("#7C3AED");
    expect(renderToStaticMarkup(html)).toContain("品牌主题预览：下方业务记录为合成演示数据");
  });

  it("TMS 演示标识只配置一半时不拼出混合学校请求，使用平台主题", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("EDUPLUS2_BRANDING_BASE_URL", "https://auth.test.example");
    vi.stubEnv("TMS_DEMO_SCHOOL_CODE", "jygjzx");
    vi.stubEnv("TMS_DEMO_TENANT_ID", "");
    const requested: string[] = [];
    vi.stubGlobal("fetch", async (input: string) => {
      requested.push(input);
      return Response.json({ code: 0, data: { brand_source: "platform_default", palette: platform } });
    });
    const html = await TmsLayout({ children: <main/> });
    expect(requested).toEqual(["https://auth.test.example/api/v1/public/branding"]);
    expect(html.props.style["--brand-primary"]).toBe("#1A56DB");
  });

  it("正式构建不消费原型演示学校标识", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("EDUPLUS2_BRANDING_BASE_URL", "https://auth.prod.example");
    vi.stubEnv("TMS_DEMO_SCHOOL_CODE", "jygjzx");
    vi.stubEnv("TMS_DEMO_TENANT_ID", "92");
    const requested: string[] = [];
    vi.stubGlobal("fetch", async (input: string) => {
      requested.push(input);
      return Response.json({ code: 0, data: { brand_source: "platform_default", palette: platform } });
    });
    const html = await TmsLayout({ children: <main/> });
    expect(requested).toEqual(["https://auth.prod.example/api/v1/public/branding"]);
    expect(renderToStaticMarkup(html)).not.toContain("品牌主题预览");
  });

  it("学校品牌请求失败或回退平台主题时，不误称已预览学校品牌", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("EDUPLUS2_BRANDING_BASE_URL", "https://auth.test.example");
    vi.stubEnv("TMS_DEMO_SCHOOL_CODE", "jygjzx");
    vi.stubEnv("TMS_DEMO_TENANT_ID", "92");
    vi.stubGlobal("fetch", async () => { throw new Error("offline"); });
    const unavailable = await TmsLayout({ children: <main/> });
    expect(unavailable.props.style["--brand-primary"]).toBe("#0369A1");
    expect(renderToStaticMarkup(unavailable)).not.toContain("品牌主题预览");

    vi.stubGlobal("fetch", async () => Response.json({ code: 0, data: { brand_source: "platform_default", palette: platform } }));
    const defaulted = await TmsLayout({ children: <main/> });
    expect(defaulted.props.style["--brand-primary"]).toBe("#1A56DB");
    expect(renderToStaticMarkup(defaulted)).not.toContain("品牌主题预览");
  });
});
