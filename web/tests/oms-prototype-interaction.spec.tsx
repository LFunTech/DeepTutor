import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import OmsPrototype from "@/features/oms-prototype/OmsPrototype";

describe("OMS 开发态交互预览", () => {
  it("可从运营导航进入只读服务属性清单，并切换非 LLM 服务", async () => {
    const user = userEvent.setup();
    render(<OmsPrototype />);

    await user.click(
      within(screen.getByRole("navigation", { name: "OMS 原型导航" })).getByRole("button", {
        name: /服务可用性/,
      }),
    );
    expect(
      screen.getByRole("heading", { name: "按 DeepTutor 模型目录逐项看" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "知识检索向量服务" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("是否发送维度参数");
    expect(screen.getByRole("tabpanel")).not.toHaveTextContent("API Key");

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("tab", { name: "联网搜索" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "联网搜索" })).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("没有模型选择");
  });

  it("价格预览只改变演示金额，待核算明细始终不收费", async () => {
    const user = userEvent.setup();
    render(<OmsPrototype />);
    await user.click(
      within(screen.getByRole("navigation", { name: "OMS 原型导航" })).getByRole("button", {
        name: /Token 与费用/,
      }),
    );

    expect(screen.getAllByText("待核算").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("region", { name: "演示用户汇总" })).toHaveTextContent("示例用户 01");
    expect(screen.getByRole("region", { name: "演示用户汇总" })).not.toHaveTextContent("¥0.00");
    const price = screen.getByRole("textbox", { name: /演示单价/ });
    await user.clear(price);
    await user.type(price, "20");
    expect(screen.getByText("¥30.20")).toBeInTheDocument();
    expect(screen.getAllByText("待核算").length).toBeGreaterThanOrEqual(2);

    await user.click(screen.getByRole("button", { name: "查看DEMO-001详情" }));
    expect(screen.getByText("1,000,000 / 250,000 / 1,250,000")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /欠费处理路径/ }));
    expect(screen.getByRole("dialog", { name: "欠费只影响模型使用" })).toHaveTextContent(
      "等待 EduPlus2 独立 webhook",
    );
    await user.click(screen.getByRole("button", { name: "关闭欠费流程" }));
    await user.click(screen.getByRole("button", { name: /供应商成本拆分/ }));
    expect(screen.getByText("供应商成本 · 虚构示例")).toBeInTheDocument();
    expect(screen.getByText("¥12.08")).toBeInTheDocument();
    expect(screen.getByText("成本待核算")).toBeInTheDocument();
  });

  it("合计按未舍入调用费用计算，并向运营解释分位显示差异", async () => {
    const user = userEvent.setup();
    render(<OmsPrototype />);
    await user.click(
      within(screen.getByRole("navigation", { name: "OMS 原型导航" })).getByRole("button", {
        name: /Token 与费用/,
      }),
    );
    const price = screen.getByRole("textbox", { name: /演示单价/ });
    await user.clear(price);
    await user.type(price, "0.01");
    expect(screen.getByText("¥0.02")).toBeInTheDocument();
    expect(screen.getByText(/合计按未舍入金额汇总/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看DEMO-001详情" }));
    expect(screen.getByText(/未舍入示例：¥0\.0125/)).toBeInTheDocument();
  });

  it("欠费流程弹窗支持 Escape 与焦点返回", async () => {
    const user = userEvent.setup();
    render(<OmsPrototype />);
    await user.click(
      within(screen.getByRole("navigation", { name: "OMS 原型导航" })).getByRole("button", {
        name: /Token 与费用/,
      }),
    );
    const trigger = screen.getByRole("button", { name: /欠费处理路径/ });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "欠费只影响模型使用" });
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
