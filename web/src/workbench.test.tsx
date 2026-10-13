import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, test, expect } from "vitest";
import { ImportModal } from "./components/ImportModal";
import { Memories } from "./pages/Memories";
import { Review } from "./pages/Review";

function server(handler: (path: string, init?: RequestInit) => unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (url: string, init?: RequestInit) =>
        new Response(JSON.stringify(handler(String(url), init)), {
          headers: { "Content-Type": "application/json" },
        }),
    ),
  );
}
const memory = {
  id: "m1",
  content: "我偏好中文。",
  category: "preference",
  subject: "语言",
  status: "candidate",
  source: "extracted",
  evidence: [],
  created_at: "2026-10-14T00:00:00Z",
};
const card = {
  id: "r1",
  question: "事务有什么作用？",
  answer: "保证原子性。",
  evidence: [],
  paused: false,
  due_at: "2026-10-14T00:00:00Z",
  grade_history: [],
  history: [],
};

test("preview is required and changing the source identity invalidates confirmation", async () => {
  const calls: { path: string; data: FormData }[] = [];
  server((path, init) => {
    calls.push({ path, data: init?.body as FormData });
    return path.endsWith("/preview")
      ? {
          conversations: 1,
          messages: 2,
          errors: 0,
          non_text_blocks: 0,
          warnings: [],
          items: [{ title: "测试", source: "manual", messages: 2 }],
        }
      : {
          imported: 1,
          updated: 0,
          duplicates: 0,
          messages: 2,
          edited_messages: 0,
          duplicate_messages: 0,
          errors: 0,
        };
  });
  render(<ImportModal onClose={() => {}} onImported={() => {}} />);
  const user = userEvent.setup();
  expect(screen.getByRole("button", { name: "确认导入" })).toBeDisabled();
  await user.upload(
    screen.getByLabelText("对话文件"),
    new File(["{}"], "source.json", { type: "application/json" }),
  );
  await user.type(screen.getByLabelText("来源标识"), "account-a");
  await user.click(screen.getByRole("button", { name: "预览文件" }));
  await screen.findByText("测试");
  expect(screen.getByRole("button", { name: "确认导入" })).toBeEnabled();
  await user.type(screen.getByLabelText("来源标识"), "-changed");
  expect(screen.getByRole("button", { name: "确认导入" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "预览文件" }));
  await user.click(await screen.findByRole("button", { name: "确认导入" }));
  await screen.findByText(/新增对话 1/);
  expect(calls[1].data.get("file")).toBe(calls[2].data.get("file"));
  expect(calls[1].data.get("source_identity")).toBe(
    calls[2].data.get("source_identity"),
  );
});

test("confirm and expire a candidate refresh the authoritative active context", async () => {
  let status = "candidate";
  server((path, init) => {
    if (init?.method === "PATCH") {
      status = JSON.parse(init.body as string).status;
      return { ...memory, status };
    }
    if (path.endsWith("/context"))
      return { items: status === "confirmed" ? [{ ...memory, status }] : [] };
    if (path.includes("/memories/m1"))
      return { ...memory, status, history: [] };
    return { items: path.includes("/memories") ? [{ ...memory, status }] : [] };
  });
  render(<Memories />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "我偏好中文。" }));
  await user.click(screen.getByRole("button", { name: "确认记忆" }));
  await screen.findByText("当前用于个性化的记忆：1 条");
  await user.click(screen.getByRole("button", { name: "使记忆过期" }));
  await screen.findByText("当前用于个性化的记忆：0 条");
});

test("review only offers named grades after answer reveal and displays updated due history", async () => {
  let updated = false;
  server((path) => {
    if (path.endsWith("/grade")) {
      updated = true;
      return {
        ...card,
        due_at: "2026-10-17T00:00:00Z",
        grade_history: [
          {
            id: "g1",
            grade: "good",
            next_due_at: "2026-10-17T00:00:00Z",
            reviewed_at: "2026-10-14T00:00:00Z",
          },
        ],
      };
    }
    if (path.includes("/reviews/r1")) return card;
    return { items: path.includes("/reviews") && !updated ? [card] : [] };
  });
  render(<Review />);
  const user = userEvent.setup();
  await screen.findByText(card.question);
  expect(
    screen.queryByRole("button", { name: "记得" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(card.answer)).not.toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "显示答案" }));
  expect(screen.getByText(card.answer)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "记得" }));
  await waitFor(() =>
    expect(screen.getAllByText(/2026\/10\/17/).length).toBeGreaterThan(0),
  );
});
