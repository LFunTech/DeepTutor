import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(`${process.cwd()}/packages/admin-ui/src/styles.css`, "utf8");
const node = document.createElement("style");
node.textContent = css;
document.head.append(node);
const rules = [...(node.sheet?.cssRules ?? [])];

function declaration(selector: string, property: string): string {
  const rule = rules.find(item => item instanceof CSSStyleRule && item.selectorText === selector) as CSSStyleRule | undefined;
  return rule?.style.getPropertyValue(property).trim() ?? "";
}

describe("共用管理 UI 品牌色", () => {
  it("默认主题是完整的天蓝色，并允许服务端首屏覆盖", () => {
    expect(declaration(":root", "--brand-primary")).toBe("#0369A1");
    expect(declaration(":root", "--brand-primary-bg")).toBe("#F0F9FF");
    expect(declaration(":root", "--brand-sidebar")).toBe("#082F49");
  });

  it("关键导航、按钮、链接和焦点态消费品牌变量而非固定松绿色", () => {
    expect(declaration(".sidebar", "background")).toBe("var(--brand-sidebar)");
    expect(declaration(".nav-item.active", "background")).toBe("var(--brand-sidebar-hover)");
    expect(declaration(".nav-item.active", "box-shadow")).toBe("inset 3px 0 0 var(--brand-primary-light)");
    expect(declaration(".brand-mark", "background")).toBe("var(--brand-primary)");
    expect(declaration(".button-primary", "background")).toBe("var(--brand-primary)");
    expect(declaration(".button-primary:hover:not(:disabled)", "background")).toBe("var(--brand-primary-hover)");
    expect(declaration(".table-link", "color")).toBe("var(--brand-primary)");
    expect(declaration(".tabs button.selected", "color")).toBe("var(--brand-primary)");
    expect(declaration(".search-field:focus-within", "outline")).toBe("2px solid var(--brand-primary)");
    expect(declaration(".nav-item:focus-visible", "outline")).toBe("2px solid var(--brand-primary-light)");
  });

  it("业务成功、警告、错误状态不被品牌色覆盖", () => {
    expect(declaration(".status-good", "color")).toBe("rgb(45, 140, 104)");
    expect(declaration(".status-warn", "color")).toBe("rgb(172, 125, 40)");
    expect(declaration(".status-bad", "color")).toBe("rgb(178, 94, 89)");
  });
});
