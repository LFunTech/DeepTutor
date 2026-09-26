import { describe, expect, it, vi } from "vitest";
import { brandThemeStyle, loadBrandTheme } from "../packages/branding/src/index";

const platformPalette = {
  primary: "#1A56DB", primary_hover: "#1441A4", primary_light: "#D5DCEC",
  primary_bg: "#EAEEF6", sidebar: "#0C2969", sidebar_hover: "#103689", text_on_primary: "#FFFFFF",
};
const tenantPalette = {
  primary: "#7C3AED", primary_hover: "#5B14D6", primary_light: "#F1EDF8",
  primary_bg: "#F6F4FB", sidebar: "#410E99", sidebar_hover: "#4F11BA", text_on_primary: "#FFFFFF",
};

function response(palette: unknown, source = "platform_default", code = 0) {
  return Response.json({ code, message: "success", data: {
    logo_url: null, school_name_display: "EduPlus", primary_color: "#000000",
    palette, brand_source: source, fallback_reason: "context_missing",
  } });
}

describe("EduPlus2 品牌主题适配", () => {
  it("OMS 不带学校参数读取平台 palette，忽略非错误的 fallback_reason", async () => {
    const requested: string[] = [];
    const result = await loadBrandTheme({
      baseUrl: "https://auth.example.test",
      context: { scope: "platform" },
      fetcher: async input => { requested.push(input); return response(platformPalette); },
    });
    expect(requested).toEqual(["https://auth.example.test/api/v1/public/branding"]);
    expect(result.origin).toBe("remote");
    expect(brandThemeStyle(result.palette)).toMatchObject({
      "--brand-primary": "#1A56DB", "--brand-primary-hover": "#1441A4",
      "--brand-primary-bg": "#EAEEF6", "--brand-sidebar": "#0C2969",
      "--brand-on-primary": "#FFFFFF",
    });
  });

  it("TMS 只把配对的可信学校 code/ID 发往当前环境域名", async () => {
    const requested: string[] = [];
    const result = await loadBrandTheme({
      baseUrl: "https://auth.prod.example",
      context: { scope: "tenant", schoolCode: "jygjzx", tenantId: "92" },
      fetcher: async input => { requested.push(input); return response(tenantPalette, "school_brand"); },
    });
    expect(requested).toEqual(["https://auth.prod.example/api/v1/public/branding?school_code=jygjzx&tenant_id=92"]);
    expect(result.origin).toBe("remote");
    expect(brandThemeStyle(result.palette)["--brand-primary"]).toBe("#7C3AED");
  });

  it("拒绝不完整、注入式及低对比度调色板，不混用部分远端颜色", async () => {
    for (const palette of [
      { ...platformPalette, sidebar: "red;background:url(https://bad.example)" },
      { ...platformPalette, primary_hover: undefined },
      { ...platformPalette, text_on_primary: "#FFFFFF", primary: "#FFFFFF" },
      { ...platformPalette, primary_hover: "#FFFFFF" },
      { ...platformPalette, sidebar_hover: "#FFFFFF" },
      { ...platformPalette, primary: "#FFFFFF", text_on_primary: "#000000" },
      { ...platformPalette, primary_bg: "#071225" },
      { ...platformPalette, primary_light: "#071225" },
    ]) {
      const result = await loadBrandTheme({ baseUrl: "https://auth.example.test", context: { scope: "platform" }, fetcher: async () => response(palette) });
      expect(result.origin).toBe("fallback");
      expect(brandThemeStyle(result.palette)["--brand-primary"]).toBe("#0369A1");
      expect(brandThemeStyle(result.palette)["--brand-sidebar"]).toBe("#082F49");
    }
  });

  it("侧栏文字按侧栏背景选择可读颜色", async () => {
    const result = await loadBrandTheme({ baseUrl: "https://auth.example.test", context: { scope: "platform" }, fetcher: async () => response({ ...platformPalette, sidebar: "#FFFFFF", sidebar_hover: "#EAF0F7" }) });
    expect(result.origin).toBe("remote");
    expect(brandThemeStyle(result.palette)["--brand-on-sidebar"]).toBe("#000000");
  });

  it("接口失败、缺少域名或平台返回学校品牌时使用天蓝色，不阻断渲染", async () => {
    const failed = await loadBrandTheme({ baseUrl: "https://auth.example.test", context: { scope: "platform" }, fetcher: async () => { throw new Error("offline"); } });
    const absent = await loadBrandTheme({ baseUrl: "", context: { scope: "platform" }, fetcher: vi.fn() });
    const wrongScope = await loadBrandTheme({ baseUrl: "https://auth.example.test", context: { scope: "platform" }, fetcher: async () => response(tenantPalette, "school_brand") });
    expect([failed.origin, absent.origin, wrongScope.origin]).toEqual(["fallback", "fallback", "fallback"]);
    expect(failed.palette).toEqual(absent.palette);
    expect(wrongScope.palette).toEqual(absent.palette);
  });

  it("只从固定路径请求品牌，不允许环境域名携带用户信息或查询串", async () => {
    for (const baseUrl of ["https://auth.example.test/?school_code=other", "https://user:pass@auth.example.test", "javascript:alert(1)"]) {
      const fetcher = vi.fn();
      const result = await loadBrandTheme({ baseUrl, context: { scope: "platform" }, fetcher });
      expect(result.origin).toBe("fallback");
      expect(fetcher).not.toHaveBeenCalled();
    }
  });
});
