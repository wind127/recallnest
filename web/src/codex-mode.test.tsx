import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import App from "./App";

beforeEach(() => {
  window.location.hash = "";
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (path: string) =>
        new Response(
          JSON.stringify(
            path.includes("/status")
              ? {
                  consolidation_mode: "codex",
                  model_configured: false,
                  worker_running: false,
                }
              : path.includes("/stats")
                ? {
                    conversations: 0,
                    messages: 0,
                    knowledge: 0,
                    confirmed_memories: 0,
                    due_reviews: 0,
                  }
                : path.includes("/jobs")
                  ? {
                      items: [
                        {
                          id: "job",
                          conversation_id: "c",
                          status: "queued",
                          attempts: 0,
                        },
                      ],
                    }
                  : { items: [], mode: "text", warning: null },
          ),
        ),
    ),
  );
});

test("Codex mode guides saving and review without provider controls or chat calls", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText("Codex 负责整理 · 本地保存与复习 · 无需额外 API Key");
  expect(
    screen.queryByRole("button", { name: "模型设置" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "设置模型" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "运行整理" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "批量重试失败整理" }),
  ).toBeDisabled();
  expect(
    screen.getByText(/用 \$recallnest 整理待处理会话/),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "对话" }));
  await screen.findByText(/请在 Codex 中继续对话/);
  expect(
    screen.queryByRole("region", { name: "个性化对话" }),
  ).not.toBeInTheDocument();
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(([path]) => String(path).includes("/conversations")),
    ).toBe(true),
  );
  expect(
    vi
      .mocked(fetch)
      .mock.calls.every(
        ([, options]) => !options?.method || options.method === "GET",
      ),
  ).toBe(true);
});
