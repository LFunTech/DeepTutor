"use client";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import {
  splitAssistantThinkingFromAnswer,
  type ConversationThinkingStep,
} from "@/lib/enterprise-conversation-test";

const ASSISTANT_PENDING_TEXT = "正在组织回答…";
const ASSISTANT_STREAMING_TEXT = "正在输出";

export function TranscriptTurnContent({
  role,
  content,
  streaming = false,
  statusMessage,
  thinkingSteps = [],
}: {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  statusMessage?: string | undefined;
  thinkingSteps?: ConversationThinkingStep[];
}) {
  if (role === "user") {
    return <div className="whitespace-pre-wrap break-words leading-7">{content}</div>;
  }

  const splitContent = splitAssistantThinkingFromAnswer(content);
  const displayThinkingSteps = mergeEmbeddedThinkingStep(thinkingSteps, splitContent.thinking);
  const hasVisibleAnswer = splitContent.answer.trim().length > 0;
  const thinkingPanel =
    displayThinkingSteps.length > 0 ? (
      <ThinkingProcessPanel
        defaultOpen={!hasVisibleAnswer}
        steps={displayThinkingSteps}
        streaming={streaming}
      />
    ) : null;

  if (!hasVisibleAnswer) {
    return (
      <>
        {thinkingPanel}
        <div className="whitespace-pre-wrap break-words leading-7 text-[#62665d]">
          {streaming ? statusMessage || ASSISTANT_PENDING_TEXT : ""}
        </div>
      </>
    );
  }

  return (
    <div className="break-words leading-7">
      {thinkingPanel}
      <MarkdownRenderer
        content={splitContent.answer}
        variant="prose"
        enableMath
        enableCode
        enableImages={false}
        className="dt-enterprise-conversation-markdown max-w-none text-[#252a24] [&_.md-code-block]:my-3 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0"
      />
      {streaming ? (
        <div
          aria-live="polite"
          className="mt-3 inline-flex items-center gap-2 rounded-full bg-[#e5f4ee] px-3 py-1 text-xs font-semibold text-[#0d5f53]"
          role="status"
        >
          <span className="size-2 animate-pulse rounded-full bg-[#0d5f53]" />
          {statusMessage || ASSISTANT_STREAMING_TEXT}
        </div>
      ) : null}
    </div>
  );
}

function mergeEmbeddedThinkingStep(
  steps: ConversationThinkingStep[],
  embeddedThinking: string,
): ConversationThinkingStep[] {
  const text = embeddedThinking.trim();
  if (!text) return steps;
  const alreadyShown = steps.some((step) => {
    const existing = step.content.trim();
    return existing && (existing.includes(text) || text.includes(existing));
  });
  if (alreadyShown) return steps;
  return [
    ...steps,
    {
      id: "embedded-thinking",
      kind: "thinking",
      title: "思考中",
      content: text,
    },
  ];
}

function ThinkingProcessPanel({
  defaultOpen,
  steps,
  streaming,
}: {
  defaultOpen: boolean;
  steps: ConversationThinkingStep[];
  streaming: boolean;
}) {
  return (
    <details
      className="mb-4 rounded-2xl border border-[#dbe7df] bg-[#f3faf6] p-3 text-sm text-[#38463e]"
      open={defaultOpen}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold text-[#0d5f53]">
        <span className="inline-flex size-2 rounded-full bg-[#0d5f53]" />
        思考过程
        {streaming ? <span className="text-xs font-medium text-[#6a766e]">正在更新</span> : null}
      </summary>
      <ol className="mt-3 max-h-56 space-y-3 overflow-y-auto border-l border-[#c9ddd2] pl-4 pr-2">
        {steps.map((step) => (
          <li className="relative" key={step.id}>
            <span className="absolute -left-[1.35rem] top-2 size-2 rounded-full bg-[#0d5f53]" />
            <div className="font-semibold text-[#26352d]">{step.title}</div>
            {step.content ? (
              <div className="mt-1 whitespace-pre-wrap break-words text-[#5a635d]">{step.content}</div>
            ) : null}
          </li>
        ))}
      </ol>
    </details>
  );
}
