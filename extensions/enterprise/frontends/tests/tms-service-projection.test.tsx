import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectService } from "@deeptutor/api-contracts";
import TmsPrototype from "../apps/tms/src/TmsPrototype";
import { services } from "../apps/tms/src/fixtures";

let path = "/tms/prototype/demo-school/services";
vi.mock("next/navigation", () => ({ usePathname: () => path }));
beforeEach(() => { path = "/tms/prototype/demo-school/services"; window.history.replaceState({}, "", path); sessionStorage.clear(); });

describe("TMS 服务安全展示", () => {
  it("共享服务 DTO 白名单去除 OMS 配置与 Secret 字段", () => {
    const result = projectService({ ...services[0], provider: "dashscope", api_format: "openai_chat", api_key: "demo-secret", profile_id: "p1", model: "qwen-plus" });
    expect(Object.keys(result).sort()).toEqual(["category", "description", "id", "name", "status", "unit"]);
    expect(JSON.stringify(result)).not.toMatch(/dashscope|demo-secret|qwen-plus/);
  });

  it("学校服务页只提供资料、配额与使用范围，不出现平台配置入口", () => {
    render(<TmsPrototype schoolCode="demo-school"/>);
    const row = screen.getByText("对话模型").closest("tr")!;
    expect(within(row).getByRole("button", { name: "服务资料" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "关联配额" })).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /供应商|模型清单|Provider|凭据|编辑配置/ })).not.toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "服务资料" }));
    expect(screen.getByRole("dialog", { name: /对话模型/ })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "供应商" })).not.toBeInTheDocument();
  });
});
