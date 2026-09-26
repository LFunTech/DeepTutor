import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ServiceList } from "@deeptutor/service-components";
import { projectService, type ServiceView } from "@deeptutor/api-contracts";
import { consumeGiftFirst } from "../apps/oms/src/ledger";

const services: ServiceView[] = [
  { id: "ocr", name: "文档 OCR", category: "知识处理", status: "available", unit: "页", description: "文档文字识别" },
  { id: "search", name: "联网搜索", category: "工具服务", status: "limited", unit: "次", description: "检索公开资料" },
];

describe("共享服务组件", () => {
  it("搜索、筛选并进入同一服务详情", () => {
    const open = vi.fn();
    render(<ServiceList services={services} onOpen={open} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索服务" }), { target: { value: "OCR" } });
    expect(screen.getByText("文档 OCR")).toBeInTheDocument();
    expect(screen.queryByText("联网搜索")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看文档 OCR详情" }));
    expect(open).toHaveBeenCalledWith("ocr");
  });

  it("平台专有字段不进入学校共用 DTO", () => {
    const safe = projectService({ ...services[0], secretRef: "secret", supplierCost: 120, tenantId: "other" });
    expect(safe).toEqual(services[0]);
  });

  it("共用列表分页可由键盘操作", async () => {
    const open = vi.fn();
    const many = Array.from({ length: 10 }, (_, index) => ({ ...services[0], id: `ocr-${index}`, name: `文档 OCR ${index}` }));
    render(<ServiceList services={many} onOpen={open}/>);
    expect(screen.getByText("共 10 条记录 · 第 1 / 2 页")).toBeInTheDocument();
    const next = screen.getByRole("button", { name: "下一页" });
    next.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByText("共 10 条记录 · 第 2 / 2 页")).toBeInTheDocument();
  });
});

describe("额度消耗", () => {
  it("赠送先于充值，单次消耗可拆分，余额不可为负", () => {
    const result = consumeGiftFirst([
      { id: "g", method: "gift", remaining: 30 },
      { id: "r", method: "recharge", remaining: 80 },
    ], 50);
    expect(result.allocations).toEqual([{ id: "g", amount: 30 }, { id: "r", amount: 20 }]);
    expect(result.remaining).toEqual([{ id: "g", method: "gift", remaining: 0 }, { id: "r", method: "recharge", remaining: 60 }]);
  });

  it("额度不足不会产生部分消耗", () => {
    expect(consumeGiftFirst([{ id: "g", method: "gift", remaining: 10 }], 20).status).toBe("insufficient");
  });
});
