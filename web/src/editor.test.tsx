import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { EntityEditor } from "./components/EntityEditor";
import type { Knowledge, Memory, Project, ReviewCard } from "./types";
import { Knowledge as KnowledgePage } from "./pages/Knowledge";
import { Memories } from "./pages/Memories";
import { Projects } from "./pages/Projects";
import { Review } from "./pages/Review";

const common = {
  id: "a",
  created_at: "2026-10-14T00:00:00Z",
  evidence: [],
  history: [],
};
const note = {
  ...common,
  title: "A",
  body: "Body A",
  summary: "",
  type: "note",
  tags: [],
  favorite: false,
  unresolved: false,
} as Knowledge;
const memory = {
  ...common,
  content: "A",
  category: "preference",
  subject: "语言",
  status: "candidate",
  effective_at: "2026-10-20T04:35:42.123456+00:00",
  expires_at: "2026-10-21T04:35:59.654321+00:00",
  supersedes: null,
} as Memory;
const project = {
  id: "a",
  name: "A",
  description: "Body A",
  status: "active",
  goals: [],
  artifact_links: [],
} as Project;
const card = {
  ...common,
  question: "A",
  answer: "Body A",
  due_at: "2026-10-20T04:35:42.123456+00:00",
  paused: false,
  grade_history: [],
} as ReviewCard;
const cases = [
  ["knowledge", note, "知识标题", "保存知识", "编辑知识", KnowledgePage],
  ["memories", memory, "记忆内容", "保存记忆", "编辑记忆", Memories],
  ["projects", project, "项目名称", "保存项目", "编辑项目", Projects],
  ["reviews", card, "问题", "保存复习卡", "编辑复习卡", Review],
] as const;
for (const [kind, original, label, save, edit, Page] of cases) {
  test(`${kind} draft remains bound to the original target when props change or become loading`, async () => {
    const writes: {
      path: string;
      method: string;
      body: Record<string, unknown>;
    }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method)
          writes.push({
            path,
            method: init.method,
            body: JSON.parse(init.body as string),
          });
        return new Response(
          JSON.stringify(init?.method ? { id: "a" } : { items: [] }),
        );
      }),
    );
    const oldSaved = vi.fn();
    const newSaved = vi.fn();
    const user = userEvent.setup();
    const view = render(
      <EntityEditor
        kind={kind}
        entity={original}
        onClose={() => {}}
        onSaved={oldSaved}
      />,
    );
    await user.clear(screen.getByLabelText(label, { exact: true }));
    await user.type(screen.getByLabelText(label, { exact: true }), "Draft A");
    view.rerender(
      <EntityEditor
        kind={kind}
        entity={{ ...original, id: "b" }}
        onClose={() => {}}
        onSaved={newSaved}
      />,
    );
    await user.click(screen.getByRole("button", { name: save }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].path).toBe("/api/" + kind + "/a");
    expect(writes[0].method).toBe("PATCH");
    expect(newSaved).not.toHaveBeenCalled();
    view.rerender(
      <EntityEditor
        kind={kind}
        entity={undefined}
        onClose={() => {}}
        onSaved={newSaved}
      />,
    );
    await user.click(screen.getByRole("button", { name: save }));
    await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1].path).toBe("/api/" + kind + "/a");
    expect(writes[1].method).toBe("PATCH");
  });
  test(`${kind} changing selection closes an old draft before a loading target can create anything`, async () => {
    const second = { ...original, id: "b" };
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async (path: string) =>
          new Response(
            JSON.stringify(
              path.endsWith("/links")
                ? { conversations: [], knowledge: [], reviews: [] }
                : path === "/api/" + kind + "/a"
                  ? original
                  : path === "/api/" + kind + "/b"
                    ? second
                    : {
                        items: path.startsWith("/api/" + kind)
                          ? [original, second]
                          : [],
                      },
            ),
          ),
      ),
    );
    const view = render(<Page initialId="a" />);
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: edit }));
    view.rerender(<Page initialId="b" />);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => !init?.method)).toBe(
      true,
    );
  });
}
test("a pending save for A cannot notify B after editor props change", async () => {
  let finish!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn((_: string, init?: RequestInit) =>
      init?.method
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(new Response(JSON.stringify({ items: [] }))),
    ),
  );
  const saved = vi.fn();
  const view = render(
    <EntityEditor
      kind="knowledge"
      entity={note}
      onClose={() => {}}
      onSaved={saved}
    />,
  );
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "保存知识" }));
  view.rerender(
    <EntityEditor
      kind="knowledge"
      entity={{ ...note, id: "b" }}
      onClose={() => {}}
      onSaved={saved}
    />,
  );
  await act(async () => {
    finish(new Response(JSON.stringify({ id: "a" })));
  });
  expect(saved).not.toHaveBeenCalled();
});
for (const [kind, original, label, save] of [
  ["memories", memory, "主题", "保存记忆"],
  ["reviews", card, "答案", "保存复习卡"],
] as const) {
  test(`${kind} unrelated edits preserve raw microsecond timestamps and only changed dates are converted`, async () => {
    const writes: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_: string, init?: RequestInit) => {
        if (init?.method) writes.push(JSON.parse(init.body as string));
        return new Response(
          JSON.stringify(init?.method ? { id: "a" } : { items: [] }),
        );
      }),
    );
    const user = userEvent.setup();
    render(
      <EntityEditor
        kind={kind}
        entity={original}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    await user.clear(screen.getByLabelText(label, { exact: true }));
    await user.type(
      screen.getByLabelText(label, { exact: true }),
      "unrelated edit",
    );
    await user.click(screen.getByRole("button", { name: save }));
    await waitFor(() => expect(writes).toHaveLength(1));
    const keys =
      kind === "memories" ? ["effective_at", "expires_at"] : ["due_at"];
    for (const key of keys)
      expect(
        key in writes[0]
          ? writes[0][key]
          : (original as unknown as Record<string, unknown>)[key],
      ).toBe((original as unknown as Record<string, unknown>)[key]);
    const date = screen.getByLabelText(
      kind === "memories" ? /^过期时间/ : /^下次复习时间/,
    );
    await user.clear(date);
    await user.click(screen.getByRole("button", { name: save }));
    await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1][keys.at(-1)!]).toBeNull();
  });
}

test("untouched null memory expiry is omitted rather than changed during an unrelated edit", async () => {
  let body: Record<string, unknown> = {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_: string, init?: RequestInit) => {
      if (init?.method) body = JSON.parse(init.body as string);
      return new Response(
        JSON.stringify(init?.method ? { id: "a" } : { items: [] }),
      );
    }),
  );
  render(
    <EntityEditor
      kind="memories"
      entity={{ ...memory, expires_at: null }}
      onClose={() => {}}
      onSaved={() => {}}
    />,
  );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("主题"), "变化");
  await user.click(screen.getByRole("button", { name: "保存记忆" }));
  await waitFor(() => expect(body).toHaveProperty("subject", "语言变化"));
  expect(body).not.toHaveProperty("expires_at");
  expect(body).not.toHaveProperty("effective_at");
});
