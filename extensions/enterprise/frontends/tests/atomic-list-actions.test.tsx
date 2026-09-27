import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DataTable } from "@deeptutor/admin-ui";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import TmsPrototype from "../apps/tms/src/TmsPrototype";

let path = "/oms/prototype/tenants";
vi.mock("next/navigation", () => ({ usePathname: () => path }));
beforeEach(() => {
  sessionStorage.clear();
  path = "/oms/prototype/tenants";
  window.history.replaceState({}, "", path);
});

describe("共享列表具名操作", () => {
  it("可对同一行提供多个独立动作，不附带含混的查看详情", () => {
    const selected: string[] = [];
    render(<DataTable rows={[{ id: "school-1", name: "示范学校" }]} columns={[{ key: "name", label: "学校", render: row => row.name }]}
      rowActions={row => [
        { label: "学校资料", onClick: () => selected.push(`info:${row.id}`) },
        { label: "服务授权", onClick: () => selected.push(`access:${row.id}`) },
      ]}/>);
    const row = screen.getByText("示范学校").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "学校资料" }));
    fireEvent.click(within(row).getByRole("button", { name: "服务授权" }));
    expect(selected).toEqual(["info:school-1", "access:school-1"]);
    expect(within(row).queryByRole("button", { name: "查看详情" })).not.toBeInTheDocument();
  });
});

describe("OMS 学校专题", () => {
  it("学校列表三个动作分别打开单一主题抽屉", () => {
    render(<OmsPrototype/>);
    const row = screen.getByText("星河实验学校").closest("tr")!;
    for (const [action, segment, visible, hidden] of [
      ["学校资料", "info", "学校编号", "搜索额度"],
      ["服务授权", "access", "搜索授权服务", "学校编号"],
      ["额度清单", "grants", "搜索额度", "搜索授权服务"],
    ]) {
      fireEvent.click(within(row).getByRole("button", { name: action }));
      const drawer = screen.getByRole("dialog", { name: /星河实验学校/ });
      expect(window.location.pathname).toBe(`/oms/prototype/tenants/aurora/${segment}`);
      if (visible.startsWith("搜索")) expect(within(drawer).getByRole("searchbox", { name: visible })).toBeInTheDocument();
      else expect(within(drawer).getByText(visible)).toBeInTheDocument();
      if (hidden.startsWith("搜索")) expect(within(drawer).queryByRole("searchbox", { name: hidden })).not.toBeInTheDocument();
      else expect(within(drawer).queryByText(hidden)).not.toBeInTheDocument();
      expect(within(drawer).queryByRole("tablist")).not.toBeInTheDocument();
      fireEvent.click(within(drawer).getByRole("button", { name: "关闭抽屉" }));
    }
  });

  it("从学校授权进入服务资料，关闭后回到学校授权", () => {
    path = "/oms/prototype/tenants/aurora/access";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /星河实验学校/ });
    fireEvent.click(within(within(drawer).getByText("对话模型").closest("tr")!).getByRole("button", { name: "服务资料" }));
    expect(window.location.pathname).toBe("/oms/prototype/services/llm/info");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/oms/prototype/tenants/aurora/access");
  });
});

describe("TMS 成员专题", () => {
  it("成员资料与应用访问分开，不能把全校服务标作成员资格", () => {
    path = "/tms/prototype/demo-school/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const row = screen.getByText("林老师").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "成员资料" }));
    expect(window.location.pathname).toMatch(/\/members\/m-01\/info$/);
    let drawer = screen.getByRole("dialog", { name: /林老师/ });
    expect(within(drawer).getByText("身份来源")).toBeInTheDocument();
    expect(within(drawer).queryByText("服务资格")).not.toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "关闭抽屉" }));
    fireEvent.click(within(row).getByRole("button", { name: "应用访问" }));
    drawer = screen.getByRole("dialog", { name: /林老师/ });
    expect(window.location.pathname).toMatch(/\/members\/m-01\/access$/);
    expect(within(drawer).getByRole("searchbox", { name: "搜索应用" })).toBeInTheDocument();
    expect(within(drawer).queryByText("身份来源")).not.toBeInTheDocument();
  });

  it("撤销应用访问须确认，取消时成员访问清单不变化", () => {
    path = "/tms/prototype/demo-school/members/m-01/access";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /林老师/ });
    const row = within(drawer).getByText("校园学习助手").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "撤销访问" }));
    const confirmation = screen.getByRole("alertdialog", { name: "确认撤销应用访问" });
    expect(within(confirmation).getByText(/林老师.*校园学习助手/)).toBeInTheDocument();
    fireEvent.click(within(confirmation).getByRole("button", { name: "取消" }));
    expect(within(drawer).getByText("校园学习助手")).toBeInTheDocument();
  });

  it("授予新的应用访问经确认后才出现在该成员清单", () => {
    path = "/tms/prototype/demo-school/members/m-01/access";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /林老师/ });
    expect(within(drawer).queryByText("数学教研工作台")).not.toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "授予应用访问（演示）" }));
    const form = screen.getByRole("dialog", { name: "授予应用访问" });
    expect(within(form).getByRole("option", { name: "数学教研工作台" })).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "确认演示授权" }));
    expect(within(drawer).queryByText("数学教研工作台")).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "确认授予应用访问" })).getByRole("button", { name: "确认" }));
    expect(within(drawer).getByText("数学教研工作台")).toBeInTheDocument();
  });
});

describe("OMS 资源专题", () => {
  it("服务列表直接区分概况、配置、Provider 和发布记录", () => {
    path = "/oms/prototype/services";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const row = screen.getByText("对话模型").closest("tr")!;
    for (const action of ["服务概况", "服务配置", "Provider 配置", "模型清单", "发布记录"]) {
      expect(within(row).getByRole("button", { name: action })).toBeInTheDocument();
    }
    fireEvent.click(within(row).getByRole("button", { name: "发布记录" }));
    const drawer = screen.getByRole("dialog", { name: /对话模型/ });
    expect(within(drawer).queryByRole("tablist")).not.toBeInTheDocument();
    expect(within(drawer).queryByText("配置概况")).not.toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "关闭抽屉" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "搜索服务" }), { target: { value: "OCR" } });
    const ocr = screen.getByText("文档 OCR").closest("tr")!;
    expect(within(ocr).queryByRole("button", { name: "Provider 配置" })).not.toBeInTheDocument();
    expect(within(ocr).queryByRole("button", { name: "模型清单" })).not.toBeInTheDocument();
  });

  it("Profile 和模型只读详情替换当前抽屉，不作为表单模态框", () => {
    path = "/oms/prototype/services/llm/provider";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /对话模型/ });
    expect(within(drawer).getByRole("searchbox", { name: "搜索 Profile" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("tablist")).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "新增模型" })).not.toBeInTheDocument();
  });

  it("供给三类列表只显示当前对象的新增入口", () => {
    path = "/oms/prototype/supply";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    expect(screen.queryByRole("button", { name: "新增供给方案" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "资源方案" }));
    expect(screen.getByRole("button", { name: "新增供给方案" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新增供给批次" })).not.toBeInTheDocument();
  });
});

describe("TMS 对象专题", () => {
  it("应用资料和成员访问各自独立，不在一个详情里切标签", () => {
    path = "/tms/prototype/demo-school/apps";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const row = screen.getByText("校园学习助手").closest("tr")!;
    for (const action of ["应用资料", "服务范围", "成员访问", "接入状态"]) {
      expect(within(row).getByRole("button", { name: action })).toBeInTheDocument();
    }
    fireEvent.click(within(row).getByRole("button", { name: "成员访问" }));
    const drawer = screen.getByRole("dialog", { name: /校园学习助手/ });
    expect(within(drawer).getByRole("searchbox", { name: "搜索成员" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("tablist")).not.toBeInTheDocument();
    expect(within(drawer).queryByText("应用归口")).not.toBeInTheDocument();
  });

  it("从应用成员钻入成员资料，关闭后返回来源专题", () => {
    path = "/tms/prototype/demo-school/apps/app-01/members";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    fireEvent.click(within(within(screen.getByRole("dialog", { name: /校园学习助手/ })).getByText("林老师").closest("tr")!).getByRole("button", { name: "成员资料" }));
    expect(window.location.pathname).toBe("/tms/prototype/demo-school/members/m-01/info");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/tms/prototype/demo-school/apps/app-01/members");
    expect(within(screen.getByRole("dialog", { name: /校园学习助手/ })).getByRole("searchbox", { name: "搜索成员" })).toBeInTheDocument();
  });

  it("配额详情只读，消耗明细从用量清单筛选", () => {
    path = "/tms/prototype/demo-school/quotas/q-101";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const drawer = screen.getByRole("dialog", { name: /配额 q-101/ });
    expect(within(drawer).getByText("剩余额度")).toBeInTheDocument();
    expect(within(drawer).queryByRole("searchbox", { name: "搜索调用" })).not.toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "查看消耗明细" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /调整|撤销/ })).not.toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "查看消耗明细" }));
    expect(window.location.search).toBe("?grant=q-101");
    expect(screen.getByText("use-7429")).toBeInTheDocument();
    expect(screen.queryByText("use-7426")).not.toBeInTheDocument();
  });

  it("知识库访问范围没有可信关系时不伪造成员授权", () => {
    path = "/tms/prototype/demo-school/knowledge";
    window.history.replaceState({}, "", path);
    render(<TmsPrototype/>);
    const row = screen.getByText("高二数学课程资料").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "访问范围" }));
    const drawer = screen.getByRole("dialog", { name: /高二数学课程资料/ });
    expect(within(drawer).getByText(/待接入|待核对/)).toBeInTheDocument();
    expect(within(drawer).queryByText("林老师")).not.toBeInTheDocument();
  });
});

describe("其余资源列表", () => {
  it("OMS Agent 将资料与策略分成两个抽屉", () => {
    path = "/oms/prototype/agents";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const row = screen.getByText("深度解题").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "平台策略" }));
    expect(window.location.pathname).toMatch(/\/policy$/);
    const drawer = screen.getByRole("dialog", { name: /深度解题/ });
    expect(within(drawer).getByRole("button", { name: "管理平台策略" })).toBeInTheDocument();
    expect(within(drawer).queryByText("资源类别")).not.toBeInTheDocument();
  });

  it("OMS 非法专题与额外写入路径不回退到其他详情", () => {
    for (const invalid of [
      "/oms/prototype/tenants/aurora/grants/q-101/edit",
      "/oms/prototype/services/llm/unknown",
      "/oms/prototype/agents/deep-solve/delete",
    ]) {
      path = invalid;
      window.history.replaceState({}, "", path);
      const view = render(<OmsPrototype/>);
      const drawer = screen.getByRole("dialog", { name: "详情 · 未找到" });
      expect(within(drawer).getByText("对象不存在或不可访问")).toBeInTheDocument();
      view.unmount();
    }
  });

  it("OMS 供给概览分别查看资源、取得记录与已承诺额度", () => {
    path = "/oms/prototype/supply";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const row = screen.getByText("对话模型资源").closest("tr")!;
    for (const action of ["资源概况", "取得记录", "已承诺额度", "实际消耗"]) {
      expect(within(row).getByRole("button", { name: action })).toBeInTheDocument();
    }
    fireEvent.click(within(row).getByRole("button", { name: "取得记录" }));
    const drawer = screen.getByRole("dialog", { name: /对话模型资源/ });
    expect(within(drawer).getByRole("searchbox", { name: "搜索取得记录" })).toBeInTheDocument();
    expect(within(drawer).queryByText("累计取得")).not.toBeInTheDocument();
  });

  it("供给方案有可直达的专属详情路径，关闭返回方案列表", () => {
    path = "/oms/prototype/supply/plans/plan-s-llm";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    expect(screen.getByRole("dialog", { name: /对话模型资源方案/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "资源方案" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/oms/prototype/supply");
    expect(screen.getByText("对话模型资源方案")).toBeInTheDocument();
  });

  it("供给方案的额外写入深链不展示方案详情", () => {
    path = "/oms/prototype/supply/plans/plan-s-llm/edit";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    expect(screen.queryByRole("dialog", { name: /对话模型资源方案/ })).not.toBeInTheDocument();
    expect(screen.getByText("对象不存在或不可访问")).toBeInTheDocument();
  });

  it("供给承诺钻入单条额度时先返回额度清单，再返回供给专题", () => {
    path = "/oms/prototype/supply/s-llm/commitments";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const commitments = screen.getByRole("dialog", { name: /对话模型资源/ });
    fireEvent.click(within(within(commitments).getAllByText("星河实验学校")[0].closest("tr")!).getByRole("button", { name: "额度详情" }));
    expect(window.location.pathname).toBe("/oms/prototype/tenants/aurora/grants/q-101");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/oms/prototype/tenants/aurora/grants");
    fireEvent.click(screen.getByRole("button", { name: "关闭抽屉" }));
    expect(window.location.pathname).toBe("/oms/prototype/supply/s-llm/commitments");
  });

  it("Skills 的资料、包内容、发布与授权分别呈现", () => {
    path = "/oms/prototype/skills";
    window.history.replaceState({}, "", path);
    render(<OmsPrototype/>);
    const row = screen.getByText("lesson-planner").closest("tr")!;
    for (const action of ["Skill 资料", "包与版本", "审查与发布", "学校授权"]) {
      expect(within(row).getByRole("button", { name: action })).toBeInTheDocument();
    }
    fireEvent.click(within(row).getByRole("button", { name: "包与版本" }));
    const drawer = screen.getByRole("dialog", { name: /lesson-planner/ });
    expect(within(drawer).getByText(/SKILL.md 与资源/)).toBeInTheDocument();
    expect(within(drawer).queryByText("学校授权")).not.toBeInTheDocument();
  });
});
