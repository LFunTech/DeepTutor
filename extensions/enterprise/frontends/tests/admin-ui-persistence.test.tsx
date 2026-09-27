import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { DataTable, useSessionFilter } from "@deeptutor/admin-ui";

function Filter({ storageKey }: { storageKey: string }) {
  const [value] = useSessionFilter(storageKey, "all");
  return <output>{value}</output>;
}

const rows = [{ id: "a", name: "文档 OCR" }];
function Table({ storageKey }: { storageKey: string }) {
  return <DataTable rows={rows} columns={[{ key: "name", label: "名称", render: row => row.name }]} searchLabel="搜索服务" persistKey={storageKey}/>;
}

beforeEach(() => sessionStorage.clear());

describe("管理后台筛选上下文", () => {
  it("筛选值尚未恢复时不得覆盖原会话记录", () => {
    const key = "deeptutor-prototype:filter:tms:school-a:method";
    sessionStorage.setItem(key, "充值");
    const view = render(<Filter storageKey="tms:school-a:method"/>);
    expect(sessionStorage.getItem(key)).toBe("充值");
    view.unmount();
  });

  it("列表尚未恢复时不得覆盖搜索与页码记录", () => {
    const key = "deeptutor-prototype:tms:school-a:services";
    const saved = JSON.stringify({ query: "OCR", page: 2 });
    sessionStorage.setItem(key, saved);
    const view = render(<Table storageKey="tms:school-a:services"/>);
    expect(sessionStorage.getItem(key)).toBe(saved);
    view.unmount();
  });

  it("同一表格实例更换作用域时不显示上一作用域的搜索词", async () => {
    sessionStorage.setItem("deeptutor-prototype:tms:school-b:services", JSON.stringify({ query: "", page: 1 }));
    const view = render(<Table storageKey="tms:school-a:services"/>);
    const search = screen.getByRole("searchbox", { name: "搜索服务" });
    fireEvent.change(search, { target: { value: "不存在" } });
    view.rerender(<Table storageKey="tms:school-b:services"/>);
    expect(screen.getByRole("searchbox", { name: "搜索服务" })).toHaveValue("");
    await waitFor(() => expect(screen.getByText("文档 OCR")).toBeInTheDocument());
  });
});
