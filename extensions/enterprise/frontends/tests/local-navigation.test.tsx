import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import TmsPrototype from "../apps/tms/src/TmsPrototype";

let initialPath = "/oms/prototype/services";
const push = vi.fn();
vi.mock("next/navigation", () => ({ usePathname: () => initialPath, useRouter: () => ({ push }) }));

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
});

describe("原型本地导航", () => {
  it("OMS 服务详情不触发 Next 服务端导航，并可通过历史记录返回列表", () => {
    initialPath = "/oms/prototype/services";
    window.history.replaceState({}, "", initialPath);
    render(<OmsPrototype/>);

    fireEvent.click(within(screen.getByText("对话模型").closest("tr")!).getByRole("button", { name: "服务概况" }));
    expect(screen.getByRole("dialog", { name: /详情.*对话模型/ })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/oms/prototype/services/llm/info");
    expect(push).not.toHaveBeenCalled();

    window.history.replaceState({}, "", initialPath);
    fireEvent.popState(window);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "模型与服务" })).toBeInTheDocument();
  });

  it("TMS 服务详情同样只更新本地历史记录", () => {
    initialPath = "/tms/prototype/demo-school/services";
    window.history.replaceState({}, "", initialPath);
    render(<TmsPrototype/>);

    fireEvent.click(within(screen.getByText("文档 OCR").closest("tr")!).getByRole("button", { name: "服务资料" }));
    expect(screen.getByRole("dialog", { name: /详情.*文档 OCR/ })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/tms/prototype/demo-school/services/ocr/info");
    expect(push).not.toHaveBeenCalled();
  });

  it("OMS 从工作台待办进入详情后，关闭抽屉返回工作台", () => {
    initialPath = "/oms/prototype";
    window.history.replaceState({}, "", initialPath);
    render(<OmsPrototype/>);

    const task = screen.getByText("文档 OCR 服务供给接近可授予上限").closest("tr")!;
    fireEvent.click(within(task).getByRole("button", { name: /查看详情/ }));
    expect(window.location.pathname).toBe("/oms/prototype/supply/s-ocr");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/oms/prototype");
    expect(screen.getByRole("heading", { name: "工作台" })).toBeInTheDocument();
  });

  it("TMS 从学校工作台待办进入详情后，关闭抽屉返回本校工作台", () => {
    initialPath = "/tms/prototype/demo-school";
    window.history.replaceState({}, "", initialPath);
    render(<TmsPrototype/>);

    const task = screen.getByText("文档 OCR 额度已用尽").closest("tr")!;
    fireEvent.click(within(task).getByRole("button", { name: /查看详情/ }));
    expect(window.location.pathname).toBe("/tms/prototype/demo-school/quotas/q-103");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/tms/prototype/demo-school");
    expect(screen.getByRole("heading", { name: "工作台" })).toBeInTheDocument();
  });
});
