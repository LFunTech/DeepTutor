import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import OmsPage from "../apps/oms/app/oms/prototype/[[...slug]]/page";
import TmsPrototype from "../apps/tms/src/TmsPrototype";
import TmsRootPage from "../apps/tms/app/tms/prototype/page";
import TmsSchoolPage from "../apps/tms/app/tms/prototype/[schoolCode]/[[...slug]]/page";

let path = "/tms/prototype/demo-school/services";
vi.mock("next/navigation", () => ({
  usePathname: () => path,
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  redirect: (target: string) => { throw new Error(`NEXT_REDIRECT:${target}`); },
}));

beforeEach(() => {
  vi.unstubAllEnvs();
  path = "/tms/prototype/demo-school/services";
  window.history.replaceState({}, "", path);
  sessionStorage.clear();
});

describe("教育业务的学校路由与名称", () => {
  it("OMS 旧学校后台开通深链由服务端返回 404", async () => {
    vi.stubEnv("NODE_ENV", "development");
    await expect(OmsPage({ params: Promise.resolve({ slug: ["tms-bootstrap"] }) })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(OmsPage({ params: Promise.resolve({ slug: ["tms-bootstrap", "demo-school"] }) })).rejects.toThrow("NEXT_NOT_FOUND");
    const page = await OmsPage({ params: Promise.resolve({ slug: ["platform-people"] }) });
    expect(page.type).toBe(OmsPrototype);
  });

  it("TMS 在学校 code 路由显示服务列表，详情深链保留 code", () => {
    render(<TmsPrototype/>);
    expect(within(screen.getByRole("banner")).getByText("学校智能体管理后台")).toBeInTheDocument();
    expect(screen.getAllByText(/demo-school/).length).toBeGreaterThan(0);
    expect(document.querySelector(".workspace-switch .lucide-chevron-down")).toBeNull();
    expect(screen.getByRole("heading", { name: "可用服务" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "学校概览" })).not.toHaveClass("active");
    expect(screen.getByRole("button", { name: "可用服务" })).toHaveClass("active");
    fireEvent.click(within(screen.getByText("文档 OCR").closest("tr")!).getByRole("button", { name: "服务资料" }));
    expect(window.location.pathname).toBe("/tms/prototype/demo-school/services/ocr/info");
    expect(screen.getByRole("dialog", { name: /详情.*文档 OCR/ })).toBeInTheDocument();
  });

  it("自定义演示学校 code 的抽屉直达和关闭始终保留学校前缀", () => {
    path = "/tms/prototype/jygjzx/services";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype schoolCode="jygjzx"/>);
    fireEvent.click(within(screen.getByText("文档 OCR").closest("tr")!).getByRole("button", { name: "服务资料" }));
    expect(window.location.pathname).toBe("/tms/prototype/jygjzx/services/ocr/info");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/tms/prototype/jygjzx/services");
    expect(screen.getByRole("heading", { name: "可用服务" })).toBeInTheDocument();
  });

  it("一所学校的配额筛选不带入另一学校的原型会话", async () => {
    path = "/tms/prototype/demo-school/quotas";
    window.history.replaceState({}, "", path);
    const first = render(<TmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "获取方式" }), { target: { value: "充值" } });
    first.unmount();

    path = "/tms/prototype/jygjzx/quotas";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype schoolCode="jygjzx"/>);
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
    expect(screen.getByRole("combobox", { name: "获取方式" })).toHaveValue("all");
  });

  it("同一前端实例切换学校时，路由、筛选与搜索均切换到新学校作用域", async () => {
    path = "/tms/prototype/demo-school/quotas";
    window.history.replaceState({}, "", path);
    const view = render(<TmsPrototype schoolCode="demo-school"/>);
    fireEvent.change(screen.getByRole("combobox", { name: "获取方式" }), { target: { value: "充值" } });
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索配额" }), { target: { value: "不存在" } });

    path = "/tms/prototype/jygjzx/quotas";
    window.history.replaceState({}, "", path);
    view.rerender(<TmsPrototype schoolCode="jygjzx"/>);

    await waitFor(() => expect(screen.getByRole("heading", { name: "配额清单" })).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("combobox", { name: "获取方式" })).toHaveValue("all"));
    expect(screen.getByRole("searchbox", { name: "搜索配额" })).toHaveValue("");
    expect(screen.getByText("q-101")).toBeInTheDocument();
  });

  it("OMS 以学校而不是租户展示学校目录", () => {
    path = "/oms/prototype/tenants";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    expect(screen.getByRole("button", { name: "学校列表" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "租户列表" })).not.toBeInTheDocument();
    expect(within(screen.getByRole("banner")).getByText("平台智能体运营后台")).toBeInTheDocument();
    expect(screen.queryByText("北辰研究院")).not.toBeInTheDocument();
    expect(screen.queryByText("企业")).not.toBeInTheDocument();
  });

  it("TMS 服务端页面只接受部署配置中的学校 code，生产原型不可达", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("TMS_DEMO_SCHOOL_CODE", "jygjzx");
    vi.stubEnv("TMS_DEMO_TENANT_ID", "92");
    await expect(TmsSchoolPage({ params: Promise.resolve({ schoolCode: "other" }) })).rejects.toThrow("NEXT_NOT_FOUND");
    const page = await TmsSchoolPage({ params: Promise.resolve({ schoolCode: "jygjzx" }) });
    expect(page.props.schoolCode).toBe("jygjzx");
    vi.stubEnv("NODE_ENV", "production");
    await expect(TmsSchoolPage({ params: Promise.resolve({ schoolCode: "jygjzx" }) })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("开发旧入口仅跳转配对演示学校，生产旧入口也拒绝", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("TMS_DEMO_SCHOOL_CODE", "jygjzx");
    vi.stubEnv("TMS_DEMO_TENANT_ID", "92");
    expect(() => TmsRootPage()).toThrow("NEXT_REDIRECT:/tms/prototype/jygjzx");
    vi.stubEnv("NODE_ENV", "production");
    expect(() => TmsRootPage()).toThrow("NEXT_NOT_FOUND");
  });

  it("学校 code 不匹配时客户端不显示其他学校的演示详情", () => {
    path = "/tms/prototype/other/quotas/q-101";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype schoolCode="demo-school"/>);
    expect(screen.getByText("没有访问权限")).toBeInTheDocument();
    expect(screen.queryByText("300,000 Token")).not.toBeInTheDocument();
  });

  it("格式错误的 Skill 深链应显示无权限状态，而不是渲染异常", () => {
    path = "/tms/prototype/demo-school/skills/%E0%A4%A";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    expect(screen.getByText("没有访问权限")).toBeInTheDocument();
  });
});
