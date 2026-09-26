import { fireEvent, render, screen } from "@testing-library/react";
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

    fireEvent.click(screen.getByRole("button", { name: "查看对话模型详情" }));
    expect(screen.getByRole("dialog", { name: /详情.*对话模型/ })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/oms/prototype/services/llm");
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

    fireEvent.click(screen.getByRole("button", { name: "查看文档 OCR详情" }));
    expect(screen.getByRole("dialog", { name: /详情.*文档 OCR/ })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/tms/prototype/demo-school/services/ocr");
    expect(push).not.toHaveBeenCalled();
  });
});
