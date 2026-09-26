import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectSkill, resolveSkillForTenant } from "@deeptutor/api-contracts";
import { SkillList } from "@deeptutor/service-components";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import TmsPrototype from "../apps/tms/src/TmsPrototype";
import { skillZip, zipEntries } from "./skill-zip-fixture";

let path = "/oms/prototype/skills";
vi.mock("next/navigation", () => ({ usePathname: () => path, useRouter: () => ({ push: (target: string) => { path = target; } }) }));
beforeEach(() => { path = "/oms/prototype/skills"; sessionStorage.clear(); });

describe("共享 Skill 安全契约", () => {
  it("仅投影安全字段，不把跨学校授权、审核材料和正文交给共享列表", () => {
    const view = projectSkill({ id: "global:pdf", name: "pdf", description: "PDF", owner: "global", source: "builtin", version: "1.0", tags: ["文档"], status: "已发布", grants: ["north"], content: "secret", reviewNotes: "internal" });
    expect(Object.keys(view).sort()).toEqual(["description", "id", "name", "owner", "source", "status", "tags", "version"].sort());
    expect(JSON.stringify(view)).not.toContain("north");
    render(<SkillList skills={[view]} onOpen={() => {}}/>);
    expect(screen.getByText("pdf")).toBeInTheDocument();
  });
  it("本学校已发布 Skill 优先；不可用时也不回退 global", () => {
    const rows = [
      { id: "global:pdf", name: "pdf", owner: "global" as const, published: true, authorized: true, ready: true },
      { id: "tenant:aurora:pdf", name: "pdf", owner: "tenant" as const, tenantId: "aurora", published: true, authorized: true, ready: false },
    ];
    expect(resolveSkillForTenant(rows, "pdf", "aurora")?.id).toBe("tenant:aurora:pdf");
    expect(resolveSkillForTenant(rows, "pdf", "harbor")?.id).toBe("global:pdf");
    expect(resolveSkillForTenant(rows.filter(row => row.owner === "global" && !row.authorized), "pdf", "aurora")).toBeUndefined();
  });
});

describe("OMS Skills", () => {
  it("builtin 只读、默认零授权，并显示运行条件", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "查看xlsx详情" }));
    expect(screen.getByText(/尚无学校授权/)).toBeInTheDocument();
    expect(screen.getAllByText(/运行条件/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "编辑 Skill" })).not.toBeInTheDocument();
  });
  it("管理员只能用 ZIP 新增 global 草稿，内容元数据从 SKILL.md 读取", async () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增平台 Skill" }));
    const modal = screen.getByRole("dialog", { name: "新增平台 Skill" });
    expect(within(modal).queryByRole("textbox", { name: "Skill 内容" })).not.toBeInTheDocument();
    expect(within(modal).queryByRole("textbox", { name: "Skill 名称" })).not.toBeInTheDocument();
    fireEvent.change(within(modal).getByLabelText("Skill ZIP 包"), { target: { files: [skillZip("course-helper", "课程资料整理", "帮助整理课程资料")] } });
    expect(await within(modal).findByText("课程资料整理")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(screen.getByText("course-helper")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看course-helper详情" }));
    expect(screen.getByText("帮助整理课程资料")).toBeInTheDocument();
  });
  it("审计角色不可新增或授权 builtin", () => {
    render(<OmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "auditor" } });
    expect(screen.queryByRole("button", { name: "新增平台 Skill" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看pdf详情" }));
    expect(screen.queryByRole("button", { name: "管理学校授权" })).not.toBeInTheDocument();
  });
  it("Hub 不能只凭地址登记，且新版本必须保持同名", async () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "从 Hub 导入" }));
    const hub = screen.getByRole("dialog", { name: "从 Hub 导入" });
    fireEvent.change(within(hub).getByRole("textbox", { name: "Hub HTTPS 地址" }), { target: { value: "https://example.com/demo" } });
    fireEvent.click(within(hub).getByRole("button", { name: "保存草稿" }));
    expect(within(hub).getByText(/先选择并通过预检/)).toBeInTheDocument();
    fireEvent.click(within(hub).getByRole("button", { name: "取消" }));
    fireEvent.click(screen.getByRole("button", { name: "新增平台 Skill" }));
    const create = screen.getByRole("dialog", { name: "新增平台 Skill" });
    fireEvent.change(within(create).getByLabelText("Skill ZIP 包"), { target: { files: [skillZip("course-helper", "课程助手", "内容")] } });
    expect(await within(create).findByText("课程助手")).toBeInTheDocument();
    fireEvent.click(within(create).getByRole("button", { name: "保存草稿" }));
    fireEvent.click(screen.getByRole("button", { name: "查看course-helper详情" }));
    fireEvent.click(screen.getByRole("button", { name: "编辑 Skill" }));
    const edit = screen.getByRole("dialog", { name: "编辑 Skill" });
    fireEvent.change(within(edit).getByLabelText("Skill ZIP 包"), { target: { files: [skillZip("other-skill", "另一个技能", "内容")] } });
    expect(await within(edit).findByText("另一个技能")).toBeInTheDocument();
    fireEvent.click(within(edit).getByRole("button", { name: "保存草稿" }));
    expect(within(edit).getByText(/名称必须与当前 Skill 相同/)).toBeInTheDocument();
    fireEvent.change(within(edit).getByLabelText("Skill ZIP 包"), { target: { files: [skillZip("course-helper", "课程助手新版本", "新版内容")] } });
    expect(await within(edit).findByText("课程助手新版本")).toBeInTheDocument();
    fireEvent.click(within(edit).getByRole("button", { name: "保存草稿" }));
    expect(screen.getByText("历史包版本")).toBeInTheDocument();
    expect(screen.getByText(/第 1 版 · course-helper.zip/)).toBeInTheDocument();
    expect(screen.getByText("第 2 版")).toBeInTheDocument();
  });
  it("OMS 上传错误展示具体文件和修复建议，不把辅助文件称为安全威胁", async () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "新增平台 Skill" }));
    const modal = screen.getByRole("dialog", { name: "新增平台 Skill" });
    fireEvent.change(within(modal).getByLabelText("Skill ZIP 包"), { target: { files: [skillZip("demo", "说明", "正文", [{ name: "demo/.DS_Store", content: "meta" }])] } });
    const error = await within(modal).findByText(/包内容问题.*\.DS_Store.*移除/);
    expect(error).not.toHaveTextContent(/安全|危险/);
    expect(error).toHaveClass("notice-warn");
    fireEvent.click(within(modal).getByRole("button", { name: "保存草稿" }));
    expect(within(modal).getByText(/包内容问题.*\.DS_Store.*移除/)).toBeInTheDocument();
  });
  it("OMS 后授权同名平台 Skill 时告知学校版本仍优先", () => {
    render(<OmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "查看pdf详情" }));
    fireEvent.click(screen.getByRole("button", { name: /星河实验学校 · 撤销/ }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "撤销 Skill 授权" })).getByRole("button", { name: "确认" }));
    fireEvent.click(screen.getByRole("button", { name: "管理学校授权" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "管理学校授权" })).getByRole("button", { name: "提交授权" }));
    expect(within(screen.getByRole("alertdialog", { name: "确认学校 Skill 授权" })).getByText(/本学校版本在运行时仍优先/)).toBeInTheDocument();
  });
});

describe("TMS Skills", () => {
  it("只展示配对 fixture 中已授权 global 与本学校 Skill，不暴露未授权 builtin", () => {
    path = "/tms/prototype/demo-school/skills";
    render(<TmsPrototype/>);
    const main = screen.getByRole("main");
    expect(within(main).getByText("pdf")).toBeInTheDocument();
    expect(within(main).queryByText("xlsx")).not.toBeInTheDocument();
    expect(within(main).queryByRole("button", { name: /授权学校|修改平台 Skill/ })).not.toBeInTheDocument();
    expect(within(main).getByText("已授权 · 暂不可用")).toHaveClass("status-warn");
    fireEvent.click(within(main).getByRole("button", { name: "查看pdf详情" }));
    expect(screen.queryByRole("button", { name: "编辑 Skill" })).not.toBeInTheDocument();
  });
  it("未授权 builtin 深链与普通成员均被拒绝；运行条件不足不可读取正文", () => {
    path = "/tms/prototype/demo-school/skills/global%3Axlsx";
    const view = render(<TmsPrototype/>);
    expect(screen.getByText("没有访问权限")).toBeInTheDocument();
    view.unmount();
    path = "/tms/prototype/demo-school/skills/global%3Adocx";
    render(<TmsPrototype/>);
    expect(screen.getByText(/当前候选运行条件不足/)).toBeInTheDocument();
    expect(screen.queryByText("已授权 PDF 参考文件（演示）")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "member" } });
    expect(screen.getByText("没有访问权限")).toBeInTheDocument();
  });
  it("跨学校 Skill 深链与普通成员的 Skills 入口均拒绝", () => {
    path = "/tms/prototype/demo-school/skills/tenant%3Aharbor%3Alesson-notes";
    const view = render(<TmsPrototype/>);
    expect(screen.getByText(/当前学校不能访问此 Skill/)).toBeInTheDocument();
    view.unmount();
    path = "/tms/prototype/demo-school/skills";
    render(<TmsPrototype/>);
    fireEvent.change(screen.getByRole("combobox", { name: "演示角色" }), { target: { value: "member" } });
    expect(screen.getByText("没有访问权限")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "上传 Skill" })).not.toBeInTheDocument();
  });
  it("同名上传须独立确认；取消保留表单且不保存", async () => {
    path = "/tms/prototype/demo-school/skills";
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "上传 Skill" }));
    const modal = screen.getByRole("dialog", { name: "上传 Skill" });
    expect(within(modal).queryByRole("textbox", { name: "Skill 名称" })).not.toBeInTheDocument();
    fireEvent.change(within(modal).getByLabelText("Skill ZIP 包"), { target: { files: [skillZip("pdf", "校内 PDF 规范", "校内 PDF 说明")] } });
    expect(await within(modal).findByText("校内 PDF 规范")).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByRole("alertdialog", { name: /同名 Skill/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.getByRole("dialog", { name: "上传 Skill" })).toBeInTheDocument();
    expect(within(screen.getByRole("dialog", { name: "上传 Skill" })).getByText(/已选文件：pdf\.zip/)).toBeInTheDocument();
  });

  it("TMS Hub 不能只凭地址创建 tenant Skill", () => {
    path = "/tms/prototype/demo-school/skills";
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "从 Hub 导入" }));
    const modal = screen.getByRole("dialog", { name: "从 Hub 导入" });
    fireEvent.change(within(modal).getByRole("textbox", { name: "Hub HTTPS 地址" }), { target: { value: "https://example.com/demo" } });
    fireEvent.click(within(modal).getByRole("button", { name: "保存草稿" }));
    expect(within(modal).getByText(/先选择并通过预检/)).toBeInTheDocument();
  });
  it("TMS 缺 SKILL.md 时展示包结构错误且不保存", async () => {
    path = "/tms/prototype/demo-school/skills";
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "上传 Skill" }));
    const modal = screen.getByRole("dialog", { name: "上传 Skill" });
    fireEvent.change(within(modal).getByLabelText("Skill ZIP 包"), { target: { files: [zipEntries([{ name: "demo/references/readme.md", content: "说明" }])] } });
    expect(await within(modal).findByText(/包结构问题.*未找到.*SKILL\.md/)).toHaveClass("notice-warn");
    fireEvent.click(within(modal).getByRole("button", { name: "保存草稿" }));
    expect(within(modal).getByText(/包结构问题.*未找到.*SKILL\.md/)).toBeInTheDocument();
  });
  it("含文本脚本、缺 requires 的包仍只生成待审查草稿，不执行也不调用用户级 API", async () => {
    path = "/tms/prototype/demo-school/skills";
    const network = vi.fn();
    vi.stubGlobal("fetch", network);
    try {
      render(<TmsPrototype/>);
      fireEvent.click(screen.getByRole("button", { name: "上传 Skill" }));
      const modal = screen.getByRole("dialog", { name: "上传 Skill" });
      fireEvent.change(within(modal).getByLabelText("Skill ZIP 包"), { target: { files: [skillZip("course-script", "脚本说明", "正文", [{ name: "course-script/scripts/run.js", content: "globalThis.__skillExecuted = true" }])] } });
      expect(await within(modal).findByText("脚本说明")).toBeInTheDocument();
      expect(within(modal).getByText("运行条件").parentElement).toHaveTextContent("未声明");
      fireEvent.click(within(modal).getByRole("button", { name: "保存草稿" }));
      expect(screen.getByText("course-script")).toBeInTheDocument();
      expect(screen.getByText("待安全审查")).toBeInTheDocument();
      expect(Reflect.get(globalThis, "__skillExecuted")).toBeUndefined();
      expect(network).not.toHaveBeenCalled();
    } finally { vi.unstubAllGlobals(); }
  });

  it("tenant Skill 更新只能提交同名新 ZIP，并保留旧包修订", async () => {
    path = "/tms/prototype/demo-school/skills";
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "上传 Skill" }));
    const create = screen.getByRole("dialog", { name: "上传 Skill" });
    fireEvent.change(within(create).getByLabelText("Skill ZIP 包"), { target: { files: [skillZip("course-helper", "初始说明", "初始正文")] } });
    expect(await within(create).findByText("初始说明")).toBeInTheDocument();
    fireEvent.click(within(create).getByRole("button", { name: "保存草稿" }));
    fireEvent.click(screen.getByRole("button", { name: "查看course-helper详情" }));
    fireEvent.click(screen.getByRole("button", { name: "编辑 Skill" }));
    const edit = screen.getByRole("dialog", { name: "编辑 Skill" });
    fireEvent.change(within(edit).getByLabelText("Skill ZIP 包"), { target: { files: [skillZip("course-helper", "更新说明", "更新正文")] } });
    expect(await within(edit).findByText("更新说明")).toBeInTheDocument();
    fireEvent.click(within(edit).getByRole("button", { name: "保存草稿" }));
    expect(screen.getByText(/第 1 版 · course-helper.zip/)).toBeInTheDocument();
    expect(screen.getByText("第 2 版")).toBeInTheDocument();
    expect(screen.queryByText("更新正文")).not.toBeInTheDocument();
  });

  it("同名上传确认后经审查、发布才优先；撤销前提示平台版本恢复", async () => {
    path = "/tms/prototype/demo-school/skills";
    render(<TmsPrototype/>);
    fireEvent.click(screen.getByRole("button", { name: "上传 Skill" }));
    const modal = screen.getByRole("dialog", { name: "上传 Skill" });
    fireEvent.change(within(modal).getByLabelText("Skill ZIP 包"), { target: { files: [skillZip("pdf", "校内 PDF 规范", "校内 PDF 说明")] } });
    expect(await within(modal).findByText("校内 PDF 规范")).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "保存草稿" }));
    const collision = await screen.findByRole("alertdialog", { name: "同名 Skill 上传确认" });
    expect(within(collision).getByText(/本学校版本发布后将优先/)).toBeInTheDocument();
    fireEvent.click(within(collision).getByRole("button", { name: "确认" }));
    expect(screen.getByText("校内 PDF 规范")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "查看pdf详情" })[1]);
    expect(screen.getByText(/当前候选：pdf · 平台/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "提交审查" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "提交 Skill 审查" })).getByRole("button", { name: "确认" }));
    fireEvent.click(screen.getByRole("button", { name: "记录演示审查通过" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "记录演示审查通过" })).getByRole("button", { name: "确认" }));
    fireEvent.click(screen.getByRole("button", { name: "发布（演示）" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "发布本学校 Skill" })).getByRole("button", { name: "确认" }));
    expect(screen.getByText(/当前候选：pdf · 本学校/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "撤销发布" }));
    expect(within(screen.getByRole("alertdialog", { name: "撤销本学校 Skill" })).getByText(/同名已授权平台 Skill 将重新成为运行候选/)).toBeInTheDocument();
  });
});
