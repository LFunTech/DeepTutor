import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { AppShellProvider } from "@/context/AppShellContext";
import {
  LANGUAGE_STORAGE_KEY,
  RESPONSE_LANGUAGE_STORAGE_KEY,
} from "@/context/app-shell-storage";
import { TranscriptTurnContent } from "@/app/enterprise/eduplus2/conversation-test/TranscriptTurnContent";

function renderTranscriptTurn(ui: React.ReactElement) {
  return render(<AppShellProvider>{ui}</AppShellProvider>);
}

describe("enterprise conversation transcript rich content", () => {
  beforeEach(() => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "zh");
    localStorage.setItem(RESPONSE_LANGUAGE_STORAGE_KEY, "zh");
  });

  it("renders streamed assistant chunks as Markdown with LaTeX and fenced code", async () => {
    const { container, rerender } = renderTranscriptTurn(
      <TranscriptTurnContent role="assistant" content="" streaming />,
    );

    expect(screen.getByText("正在组织回答…")).toBeInTheDocument();

    rerender(
      <AppShellProvider>
        <TranscriptTurnContent
          role="assistant"
          content={
            "**重点**：用 $x^2$ 表示平方。\n\n```ts\nconst answer = 42;\n```"
          }
          streaming
        />
      </AppShellProvider>,
    );

    expect(screen.getByRole("status")).toHaveTextContent("正在输出");

    await waitFor(() => {
      expect(container.querySelector("strong")).toHaveTextContent("重点");
      expect(container.querySelectorAll(".katex").length).toBeGreaterThan(0);
      expect(container.textContent).toContain("const answer = 42;");
    });
    expect(container).not.toHaveTextContent("$x^2$");
  });

  it("keeps user turns as plain text instead of rendering Markdown syntax", () => {
    const { container } = renderTranscriptTurn(
      <TranscriptTurnContent
        role="user"
        content="**这只是用户原文**，不是页面渲染的答案。"
        streaming={false}
      />,
    );

    expect(container).toHaveTextContent("**这只是用户原文**");
    expect(container.querySelector("strong")).toBeNull();
  });

  it("shows a DeepSeek-like thinking process separately from the final answer", () => {
    const { container } = renderTranscriptTurn(
      <TranscriptTurnContent
        role="assistant"
        content="最终答案：$y=x^2$。"
        streaming={false}
        thinkingSteps={[
          { id: "think-1", kind: "thinking", title: "思考中", content: "先判断题意" },
          { id: "tool-1", kind: "tool_call", title: "正在查找知识库内容", content: "" },
        ]}
      />,
    );

    expect(screen.getByText("思考过程")).toBeInTheDocument();
    expect(screen.getByText("思考中")).toBeInTheDocument();
    expect(screen.getByText("先判断题意")).toBeInTheDocument();
    expect(screen.getByText("正在查找知识库内容")).toBeInTheDocument();
    expect(container.textContent).not.toContain("tool_call");
    expect(container.textContent).not.toContain("raw JSON");
  });

  it("removes raw think tags from the answer body and shows their text in the thinking panel", async () => {
    const { container } = renderTranscriptTurn(
      <TranscriptTurnContent
        role="assistant"
        content="<think>先判断题意，再选择知识库。</think>\n\n最终答案：$y=x^2$。"
        streaming={false}
      />,
    );

    expect(screen.getByText("思考过程")).toBeInTheDocument();
    expect(screen.getByText("先判断题意，再选择知识库。")).toBeInTheDocument();
    expect(container.textContent).not.toContain("<think>");
    expect(container.textContent).not.toContain("</think>");

    await waitFor(() => {
      expect(container).toHaveTextContent("最终答案");
      expect(container.querySelectorAll(".katex").length).toBeGreaterThan(0);
    });
  });

  it("collapses the thinking panel once answer text is streaming so the answer stays visible", () => {
    const { container } = renderTranscriptTurn(
      <TranscriptTurnContent
        role="assistant"
        content="最终答案正在流式输出。"
        streaming
        thinkingSteps={[
          {
            id: "think-long",
            kind: "thinking",
            title: "思考中",
            content: "较长的思考过程会持续增长，但不应把正文流式输出挤到视口外。",
          },
        ]}
      />,
    );

    expect(container).toHaveTextContent("最终答案正在流式输出。");
    expect(screen.getByText("正在输出")).toBeInTheDocument();
    expect(screen.getByText("思考过程").closest("details")).not.toHaveAttribute("open");
  });
});
