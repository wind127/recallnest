import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ChatComposer } from "./components/ChatComposer";
import { EntityEditor } from "./components/EntityEditor";
import { Review } from "./pages/Review";
test("a late chat result cannot refresh a different conversation after unmount", async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  const saved = vi.fn();
  const user = userEvent.setup();
  const { unmount } = render(
    <ChatComposer conversationId="c1" branch="b1" onSaved={saved} />,
  );
  await user.type(screen.getByLabelText("消息内容"), "合成问题");
  await user.click(screen.getByRole("button", { name: "发送消息" }));
  unmount();
  await act(async () => {
    finish(
      new Response(
        JSON.stringify({
          conversation_id: "c1",
          assistant_message: { id: "a1" },
          used_context: {
            memory_ids: [],
            knowledge_ids: [],
            message_ids: [],
            evidence: [],
          },
        }),
      ),
    );
  });
  expect(saved).not.toHaveBeenCalled();
});
test("a closed editor cannot select its old entity when a pending save finishes", async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn((_: string, init?: RequestInit) =>
      init?.method === "POST"
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(new Response(JSON.stringify({ items: [] }))),
    ),
  );
  const saved = vi.fn();
  const user = userEvent.setup();
  const { unmount } = render(
    <EntityEditor kind="knowledge" onClose={() => {}} onSaved={saved} />,
  );
  await user.type(screen.getByLabelText("知识标题"), "旧选择");
  await user.click(screen.getByRole("button", { name: "保存知识" }));
  unmount();
  await act(async () => {
    finish(new Response(JSON.stringify({ id: "old" })));
  });
  expect(saved).not.toHaveBeenCalled();
});

test("a late grade cannot replace the selected card or display the old card's due date", async () => {
  let finish!: (response: Response) => void;
  const first = {
    id: "r1",
    question: "第一个问题",
    answer: "第一个答案",
    evidence: [],
    due_at: "2026-10-14T00:00:00Z",
    grade_history: [],
    paused: false,
  };
  const second = {
    ...first,
    id: "r2",
    question: "第二个问题",
    answer: "第二个答案",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      path.endsWith("/grade")
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(
            new Response(
              JSON.stringify(
                path.includes("/reviews/r1")
                  ? first
                  : path.includes("/reviews/r2")
                    ? second
                    : {
                        items: path.includes("/reviews") ? [first, second] : [],
                      },
              ),
            ),
          ),
    ),
  );
  render(<Review initialId="r1" />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "显示答案" }));
  await user.click(screen.getByRole("button", { name: "记得" }));
  await user.click(screen.getByRole("button", { name: "第二个问题" }));
  await screen.findByRole("heading", { name: "第二个问题" });
  await act(async () => {
    finish(
      new Response(
        JSON.stringify({ ...first, due_at: "2026-10-17T00:00:00Z" }),
      ),
    );
  });
  expect(screen.queryByText(/已更新下次复习时间/)).not.toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "第二个问题" }),
  ).toBeInTheDocument();
});
