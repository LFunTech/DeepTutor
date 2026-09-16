import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import KbDocumentList from "@/components/knowledge/KbDocumentList";

const api = vi.hoisted(() => ({
  listKnowledgeBaseFiles: vi.fn(),
  createKbFolder: vi.fn(),
  deleteKbFile: vi.fn(),
  moveKbFile: vi.fn(),
}));

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/features/knowledge/api/files", () => ({
  listKnowledgeBaseFiles: api.listKnowledgeBaseFiles,
  createKbFolder: api.createKbFolder,
  deleteKbFile: api.deleteKbFile,
  moveKbFile: api.moveKbFile,
}));

beforeEach(() => {
  api.listKnowledgeBaseFiles.mockResolvedValue([]);
  api.createKbFolder.mockResolvedValue(undefined);
  api.deleteKbFile.mockResolvedValue(undefined);
  api.moveKbFile.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("does not expose local file mutation controls for a read-only knowledge base", async () => {
  render(
    <KbDocumentList
      kbName="test"
      readOnly
      refreshKey={0}
      selectedFile={null}
      onSelect={() => undefined}
      collapsed={false}
      onToggleCollapsed={() => undefined}
    />,
  );

  await waitFor(() => expect(api.listKnowledgeBaseFiles).toHaveBeenCalledWith("test", { force: false }));

  expect(screen.queryByRole("button", { name: "New folder" })).toBeNull();
  expect(screen.getByText("This knowledge base is connected to an external resource. Files are managed in the external system."));
});
