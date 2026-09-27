import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import TmsPrototype from "../apps/tms/src/TmsPrototype";

let path = "/oms/prototype/skills";
vi.mock("next/navigation", () => ({ usePathname: () => path }));

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  window.history.replaceState({}, "", path);
});

describe("列表页面只保留一个标题", () => {
  it("OMS 与 TMS 的 Skills 清单不再重复显示清单标题和说明", () => {
    path = "/oms/prototype/skills";
    window.history.replaceState({}, "", path);
    const oms = render(<OmsPrototype/>);
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Skills" })).toBeInTheDocument();
    expect(screen.queryByText("选择 Skill 查看来源、版本与可用状态")).not.toBeInTheDocument();
    oms.unmount();

    path = "/tms/prototype/demo-school/skills";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Skills" })).toBeInTheDocument();
  });

  it("普通列表和服务目录的筛选表格直接跟在唯一页标题后", () => {
    path = "/oms/prototype/tenants";
    window.history.replaceState({}, "", path);
    const oms = render(<OmsPrototype/>);
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getByRole("searchbox", { name: "搜索学校" })).toBeInTheDocument();
    oms.unmount();

    path = "/tms/prototype/demo-school/services";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getByRole("searchbox", { name: "搜索服务" })).toBeInTheDocument();
  });

  it("供给标签页不再在标签页下重复显示标题", () => {
    path = "/oms/prototype/supply";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    fireEvent.click(screen.getByRole("tab", { name: "资源方案" }));
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getByRole("searchbox", { name: "搜索资源方案" })).toBeInTheDocument();
  });
});
