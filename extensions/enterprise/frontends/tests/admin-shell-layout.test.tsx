import { readFileSync } from "node:fs";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { AdminShell } from "@deeptutor/admin-ui";

const groups = [{ label: "资源目录", items: [
  { label: "工作台", href: "/oms/prototype" },
  { label: "模型与服务", href: "/oms/prototype/services" },
] }];

function shell(product = "OMS") {
  return <AdminShell product={product} subtitle={product === "OMS" ? "平台智能体运营后台" : "学校智能体管理后台"} scope="演示学校" groups={groups} path="/oms/prototype/services" onNavigate={() => {}}><p>列表内容</p></AdminShell>;
}

beforeEach(() => localStorage.clear());

describe("共享管理后台侧栏", () => {
  it("OMS 与 TMS 均展示智能体基座品牌，保留各自后台名称", () => {
    for (const product of ["OMS", "TMS"]) {
      const view = render(shell(product));
      const sidebar = screen.getByRole("complementary");
      expect(within(sidebar).getByText("智能体基座")).toBeInTheDocument();
      expect(within(sidebar).getByText(product === "OMS" ? "平台智能体运营后台" : "学校智能体管理后台")).toBeInTheDocument();
      expect(within(sidebar).queryByText("DeepTutor")).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("桌面侧栏默认展开，可收起为图标导航并重新展开", () => {
    render(shell());
    const layout = document.querySelector(".admin-shell");
    expect(layout).not.toHaveClass("sidebar-collapsed");

    const sidebar = screen.getByRole("complementary");
    expect(within(screen.getByRole("banner")).queryByRole("button", { name: "收起侧栏" })).toBeNull();
    fireEvent.click(within(sidebar).getByRole("button", { name: "收起侧栏" }));
    expect(layout).toHaveClass("sidebar-collapsed");
    expect(within(sidebar).getByRole("button", { name: "展开侧栏" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "模型与服务" })).toHaveAttribute("title", "模型与服务");
    expect(screen.getByRole("button", { name: "模型与服务" })).toHaveClass("active");

    fireEvent.click(within(sidebar).getByRole("button", { name: "展开侧栏" }));
    expect(layout).not.toHaveClass("sidebar-collapsed");
    expect(within(sidebar).getByRole("button", { name: "收起侧栏" })).toHaveAttribute("aria-expanded", "true");
  });

  it("侧栏偏好在刷新后保留，OMS 与 TMS 互不串用", async () => {
    const first = render(shell("OMS"));
    fireEvent.click(screen.getByRole("button", { name: "收起侧栏" }));
    first.unmount();

    const reopened = render(shell("OMS"));
    await waitFor(() => expect(document.querySelector(".admin-shell")).toHaveClass("sidebar-collapsed"));
    reopened.unmount();

    render(shell("TMS"));
    expect(document.querySelector(".admin-shell")).not.toHaveClass("sidebar-collapsed");
  });

  it("窄屏弹出导航仍由独立按钮控制，不被桌面收缩状态替代", () => {
    render(shell());
    fireEvent.click(screen.getByRole("button", { name: "收起侧栏" }));
    const mobileMenu = document.querySelector<HTMLButtonElement>(".mobile-menu");
    expect(mobileMenu).toHaveAttribute("aria-label", "切换导航");
    fireEvent.click(mobileMenu!);
    expect(document.querySelector(".sidebar")).toHaveClass("sidebar-open");
    expect(mobileMenu).toHaveAttribute("aria-expanded", "true");
  });
});

describe("列表页信息密度", () => {
  const css = readFileSync(`${process.cwd()}/packages/admin-ui/src/styles.css`, "utf8");
  const style = document.createElement("style");
  style.textContent = css;
  document.head.append(style);
  const rules = [...(style.sheet?.cssRules ?? [])];
  const declaration = (selector: string, property: string) => {
    const rule = rules.find(item => item instanceof CSSStyleRule && item.selectorText === selector) as CSSStyleRule | undefined;
    return rule?.style.getPropertyValue(property).trim() ?? "";
  };

  it("收缩后把横向空间交还列表，移动端仍使用完整宽度侧栏", () => {
    expect(declaration(".admin-shell.sidebar-collapsed", "grid-template-columns")).toBe("72px minmax(0,1fr)");
    const mobile = rules.find(item => item instanceof CSSMediaRule && item.conditionText === "(max-width:700px)") as CSSMediaRule | undefined;
    const mobileSidebar = [...(mobile?.cssRules ?? [])].find(item => item instanceof CSSStyleRule && item.selectorText === ".sidebar") as CSSStyleRule | undefined;
    expect(mobileSidebar?.style.getPropertyValue("width").trim()).toBe("246px");
  });

  it("缩小列表主标题和页头留白，同时放大实际操作文字", () => {
    expect(declaration(".page-head h1", "font-size")).toBe("21px");
    expect(declaration(".content", "padding")).toBe("20px 32px 56px");
    expect(declaration(".page-head", "margin-bottom")).toBe("14px");
    expect(declaration("table", "font-size")).toBe("13px");
    expect(declaration(".nav-item", "font-size")).toBe("14px");
    expect(declaration(".button", "font-size")).toBe("13px");
    expect(declaration(".search-field input", "font-size")).toBe("13px");
  });
});
