import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import TmsPrototype from "../apps/tms/src/TmsPrototype";
import TmsSchoolPage from "../apps/tms/app/tms/prototype/[schoolCode]/[[...slug]]/page";

let path = "/tms/prototype/demo-school/services";
vi.mock("next/navigation", () => ({ usePathname: () => path }));

beforeEach(() => {
  vi.unstubAllEnvs();
  path = "/tms/prototype/demo-school/services";
  window.history.replaceState({}, "", path);
  sessionStorage.clear();
});

describe("教育业务的学校路由与名称", () => {
  it("TMS 在学校 code 路由显示服务列表，详情深链保留 code", () => {
    render(<TmsPrototype/>);
    expect(screen.getByText("学校智能体管理后台")).toBeInTheDocument();
    expect(screen.getAllByText(/demo-school/).length).toBeGreaterThan(0);
    expect(document.querySelector(".workspace-switch .lucide-chevron-down")).toBeNull();
    expect(screen.getByRole("heading", { name: "可用服务" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看文档 OCR详情" }));
    expect(window.location.pathname).toBe("/tms/prototype/demo-school/services/ocr");
    expect(screen.getByRole("dialog", { name: /详情.*文档 OCR/ })).toBeInTheDocument();
  });

  it("OMS 以学校而不是租户展示学校目录", () => {
    path = "/oms/prototype";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    expect(screen.getByRole("button", { name: "学校列表" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "租户列表" })).not.toBeInTheDocument();
  });

  it("TMS 服务端页面只接受部署配置中的学校 code，生产原型不可达", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("TMS_DEMO_SCHOOL_CODE", "jygjzx");
    vi.stubEnv("TMS_DEMO_TENANT_ID", "92");
    await expect(TmsSchoolPage({ params: Promise.resolve({ schoolCode: "other" }) })).rejects.toThrow();
    const page = await TmsSchoolPage({ params: Promise.resolve({ schoolCode: "jygjzx" }) });
    expect(page.props.schoolCode).toBe("jygjzx");
    vi.stubEnv("NODE_ENV", "production");
    await expect(TmsSchoolPage({ params: Promise.resolve({ schoolCode: "jygjzx" }) })).rejects.toThrow();
  });
});
