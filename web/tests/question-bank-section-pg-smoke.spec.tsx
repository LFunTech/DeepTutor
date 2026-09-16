import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QuestionBankSection from "@/components/space/question-bank/QuestionBankSection";

const fixture = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  fetch: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: fixture.push, replace: fixture.replace }),
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options
        ? key.replace(/{{(\w+)}}/g, (_, name: string) => String(options[name] ?? ""))
        : key,
    i18n: { language: "en" },
  }),
}));

vi.stubGlobal("fetch", fixture.fetch);

const jsonResponse = (body: unknown, init: ResponseInit = {}) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });

const pgEntry = {
  id: 42,
  session_id: "pg-session-1",
  turn_id: "turn-1",
  question_id: "q-1",
  question: "What is PostgreSQL authority?",
  question_type: "short_answer",
  options: {},
  correct_answer: "The PG provider is authoritative.",
  explanation: "Stored by the shared PG session provider.",
  difficulty: "medium",
  user_answer: "SQLite fallback",
  is_correct: false,
  resolved: false,
  bookmarked: true,
  source: "deep_question",
  material_id: "material-1",
  material_title: "Algebra notes",
  score_history: [],
  answer_images: [],
  categories: [{ id: 7, name: "Migrations", entry_count: 1 }],
  created_at: 1,
  updated_at: 2,
};

function installQuestionBankApi({ failEntries = false } = {}) {
  fixture.fetch.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/question-notebook/entries")) {
      if (failEntries) {
        return jsonResponse({ detail: "PG provider unavailable" }, { status: 503, statusText: "Service Unavailable" });
      }
      return jsonResponse({ items: [pgEntry], total: 1, limit: 60, offset: 0 });
    }
    if (url.startsWith("/api/question-notebook/categories")) {
      return jsonResponse([{ id: 7, name: "Migrations", entry_count: 1 }]);
    }
    if (url.startsWith("/api/question-notebook/stats")) {
      return jsonResponse({
        total: 1,
        bookmarked: 1,
        unresolved: 1,
        correct: 0,
        incorrect: 1,
        uncategorized: 0,
        by_category: [{ id: 7, name: "Migrations", count: 1 }],
      });
    }
    if (url.startsWith("/api/question-notebook/materials")) {
      return jsonResponse([{ material_id: "material-1", title: "Algebra notes", count: 1 }]);
    }
    return jsonResponse({ detail: `Unexpected request: ${url}` }, { status: 500, statusText: "Unexpected" });
  });
}

describe("QuestionBankSection PG smoke", () => {
  beforeEach(() => {
    fixture.fetch.mockReset();
    fixture.push.mockReset();
    fixture.replace.mockReset();
  });

  it("renders committed question-bank rows from the original notebook API endpoints", async () => {
    installQuestionBankApi();

    render(<QuestionBankSection />);

    expect(await screen.findByText("What is PostgreSQL authority?")).toBeInTheDocument();
    expect(screen.getAllByText("Migrations").length).toBeGreaterThan(0);
    expect(screen.getByText("1 questions.count.suffix")).toBeInTheDocument();

    const requested = fixture.fetch.mock.calls.map(([input]) => String(input));
    expect(requested).toContain("/api/question-notebook/categories");
    expect(requested).toContain("/api/question-notebook/stats");
    expect(requested).toContain("/api/question-notebook/materials");
    expect(requested.some((url) => url.startsWith("/api/question-notebook/entries?"))).toBe(true);
  });

  it("shows the PG/provider error instead of replacing failures with an empty bank", async () => {
    installQuestionBankApi({ failEntries: true });

    render(<QuestionBankSection />);

    expect(await screen.findByText("Failed to load entries")).toBeInTheDocument();
    expect(screen.getByText("PG provider unavailable")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("No entries yet")).not.toBeInTheDocument(),
    );
  });
});
