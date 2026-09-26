import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TmsPrototype from "../apps/tms/src/TmsPrototype";

let path = "/tms/prototype/demo-school/apps";
vi.mock("next/navigation", () => ({ usePathname: () => path, useRouter: () => ({ push: (target: string) => { path = target; } }) }));
beforeEach(() => { path = "/tms/prototype/demo-school/apps"; sessionStorage.clear(); });

describe("TMS 列表、详情和操作层级", () => {
  it("应用从列表打开详情抽屉，关闭后保留列表", () => {
    render(<TmsPrototype/>);
    fireEvent.click(screen.getAllByRole("button", { name: /查看详情/ })[0]);
    expect(screen.getByRole("dialog", { name: /详情/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(screen.getByRole("heading", { name: "应用与接入" })).toBeInTheDocument();
  });
  it("新增应用使用模态框，不撑开列表", () => {
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增应用（演示）" }));
    const modal = screen.getByRole("dialog", { name: "新增应用" });
    expect(within(modal).getByRole("textbox", { name: "应用名称" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "创建演示应用" })).not.toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog", { name: "新增应用" })).not.toBeInTheDocument();
  });
  it("新增应用回读所选归口部门，而不是固定部门", () => {
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增应用（演示）" }));
    const modal = screen.getByRole("dialog", { name: "新增应用" });
    fireEvent.change(within(modal).getByRole("textbox", { name: "应用名称" }), { target: { value: "演示备课应用" } });
    fireEvent.change(within(modal).getByRole("combobox", { name: "归口部门" }), { target: { value: "数学教研组" } });
    fireEvent.click(within(modal).getByRole("button", { name: "保存演示应用" }));
    const row = screen.getByText("演示备课应用").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row!).getByText("数学教研组")).toBeInTheDocument();
  });
  it("配额直达详情仍只读且显示在抽屉", () => {
    path = "/tms/prototype/demo-school/quotas/q-101";
    render(<TmsPrototype/>);
    expect(screen.getByRole("dialog", { name: /详情/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "配额清单" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /新增配额|调整额度|撤销额度/ })).not.toBeInTheDocument();
  });
  it("成员访问授权表单从详情抽屉打开独立模态框", () => {
    path = "/tms/prototype/demo-school/members/m-01";
    render(<TmsPrototype/>);
    expect(screen.getByRole("dialog", { name: /详情/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "授予应用访问（演示）" }));
    const modal = screen.getByRole("dialog", { name: "授予应用访问" });
    expect(within(modal).getByRole("combobox", { name: "应用" })).toBeInTheDocument();
    expect(within(modal).queryByRole("option", { name: "外部课程接入" })).not.toBeInTheDocument();
    expect(within(modal).queryByRole("option", { name: "资料归档助手" })).not.toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog", { name: "授予应用访问" })).not.toBeInTheDocument();
  });
});
