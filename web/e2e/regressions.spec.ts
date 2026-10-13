import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

async function capture(page: Page, name: string) {
  if (!process.env.RECALLNEST_SCREENSHOTS) return;
  mkdirSync(process.env.RECALLNEST_SCREENSHOTS, { recursive: true });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: resolve(process.env.RECALLNEST_SCREENSHOTS, name + ".png"),
    fullPage: true,
  });
}

const base = "http://127.0.0.1:18787";
test.beforeEach(async ({ request }) => {
  await request.post(base + "/_test/reset");
});

for (const [kind, route, fields, edit, save] of [
  [
    "knowledge",
    "knowledge",
    { title: "引用知识", body: "测试正文" },
    "编辑知识",
    "保存知识",
  ],
  [
    "memories",
    "memories",
    { category: "preference", content: "我偏好中文。" },
    "编辑记忆",
    "保存记忆",
  ],
  [
    "reviews",
    "review",
    { question: "引用卡片", answer: "测试答案" },
    "编辑复习卡",
    "保存复习卡",
  ],
] as const) {
  for (const stale of [false, true]) {
    test(`${kind} saves ${stale ? "historical stale" : "current"} evidence without output-only fields`, async ({
      page,
      request,
    }) => {
      const conversation = await (
        await request.post(base + "/api/conversations", {
          data: {
            title: "引用来源",
            messages: [{ id: "u1", role: "user", content: "我偏好中文。" }],
          },
        })
      ).json();
      const evidence = {
        message_id: conversation.messages[0].id,
        conversation_id: conversation.id,
        message_version: 1,
        quote: "我偏好中文。",
      };
      const entity = await (
        await request.post(base + "/api/" + kind, {
          data: { ...fields, evidence: [evidence] },
        })
      ).json();
      if (stale)
        await request.post(
          base + "/api/conversations/" + conversation.id + "/messages",
          {
            data: {
              messages: [{ id: "u1", role: "user", content: "我偏好英文。" }],
            },
          },
        );
      await page.goto("/#" + route + "/" + entity.id);
      if (stale)
        await expect(page.getByText(/历史证据 · 源文已更新/)).toBeVisible();
      await page.getByRole("button", { name: edit, exact: true }).click();
      const pending = page.waitForResponse(
        (r) =>
          r.url().endsWith("/api/" + kind + "/" + entity.id) &&
          r.request().method() === "PATCH",
      );
      await page.getByRole("button", { name: save, exact: true }).click();
      const response = await pending;
      expect(response.status()).toBe(200);
      expect(response.request().postDataJSON().evidence).toEqual([evidence]);
      const saved = await response.json();
      expect(saved.evidence[0]).toMatchObject({ ...evidence, stale });
      if (stale) {
        await expect(page.getByText(/历史证据 · 源文已更新/)).toBeVisible();
        await page.getByRole("button", { name: "查看原始消息" }).click();
        await expect(
          page.getByRole("dialog").getByLabel("消息版本"),
        ).toHaveValue("1");
        await expect(
          page
            .getByRole("dialog")
            .getByText("我偏好中文。", { exact: true })
            .last(),
        ).toBeVisible();
        if (kind === "knowledge")
          await capture(page, "recallnest-stale-evidence");
      }
    });
  }
}

test("review filters reconcile detail with current text/date/project result and empty queue has no interactive card", async ({
  page,
  request,
}) => {
  const firstProject = await (
    await request.post(base + "/api/projects", { data: { name: "甲项目" } })
  ).json();
  const secondProject = await (
    await request.post(base + "/api/projects", { data: { name: "乙项目" } })
  ).json();
  await request.post(base + "/api/reviews", {
    data: {
      question: "SPEC alpha",
      answer: "alpha answer",
      due_at: "2026-10-01T00:00:00Z",
      project_id: firstProject.id,
    },
  });
  await request.post(base + "/api/reviews", {
    data: {
      question: "SPEC beta",
      answer: "beta answer",
      due_at: "2026-10-02T00:00:00Z",
      project_id: secondProject.id,
    },
  });
  await page.goto("/#review");
  await expect(page.getByRole("heading", { name: "SPEC alpha" })).toBeVisible();
  await page.getByLabel("筛选文字").fill("SPEC beta");
  await expect(
    page
      .getByRole("region", { name: "复习队列" })
      .getByRole("button", { name: "SPEC beta" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "SPEC beta" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "SPEC alpha" })).toHaveCount(
    0,
  );
  await page.getByLabel("筛选文字").fill("NO RESULT");
  await expect(page.getByText(/当前筛选下没有复习卡/)).toBeVisible();
  await expect(page.getByRole("button", { name: "显示答案" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "编辑复习卡" })).toHaveCount(0);
  await page.getByRole("button", { name: "清除筛选" }).click();
  await page.getByLabel("到期日期自（UTC）").fill("2026-10-02");
  await page.getByLabel("到期日期至（UTC，含当天）").fill("2026-10-02");
  await expect(page.getByRole("heading", { name: "SPEC beta" })).toBeVisible();
  await page.getByRole("button", { name: "清除筛选" }).click();
  await page.getByLabel("项目").selectOption(firstProject.id);
  await expect(page.getByRole("heading", { name: "SPEC alpha" })).toBeVisible();
  await page.getByLabel("项目").selectOption(secondProject.id);
  await expect(page.getByRole("heading", { name: "SPEC beta" })).toBeVisible();
  await page.getByRole("checkbox", { name: "仅到期卡片" }).check();
  await page.getByRole("button", { name: "显示答案" }).click();
  await page.getByRole("button", { name: "记得", exact: true }).click();
  await expect(page.getByText(/已更新下次复习时间/)).toBeVisible();
  await expect(page.getByText(/当前筛选下没有复习卡/)).toBeVisible();
  await expect(page.getByRole("button", { name: "显示答案" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "编辑复习卡" })).toHaveCount(0);
});

test("selected alternate branch continues a visible parent chain and failed retry keeps its frozen request", async ({
  page,
  request,
}) => {
  await request.post(base + "/api/settings", {
    data: { base_url: "http://provider.test/v1", chat_model: "synthetic-test" },
  });
  const conversation = await (
    await request.post(base + "/api/conversations", {
      data: {
        title: "连续分支对话",
        current_node: "a",
        messages: [
          { id: "u", role: "user", content: "分支根" },
          { id: "a", role: "assistant", content: "默认分支", parent_id: "u" },
          { id: "b", role: "assistant", content: "另一个分支", parent_id: "u" },
        ],
      },
    })
  ).json();
  const branch = conversation.messages.find(
    (m: { external_id: string }) => m.external_id === "b",
  );
  await page.goto("/#conversations/" + conversation.id);
  await page.getByLabel("对话分支").selectOption(branch.id);
  let previous = branch.id;
  for (const content of ["分支第一个问题", "分支第二个问题"]) {
    await page.getByLabel("消息内容").fill(content);
    const pending = page.waitForResponse((r) => r.url().endsWith("/api/chat"));
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    const response = await pending;
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.user_message.parent_id).toBe(previous);
    expect(result.used_context.message_ids).toContain(previous);
    expect(result.used_context.message_ids).toContain(result.user_message.id);
    expect(result.used_context.message_ids).not.toContain(
      conversation.messages.find(
        (m: { external_id: string }) => m.external_id === "a",
      ).id,
    );
    previous = result.assistant_message.id;
    await expect(
      page
        .getByRole("region", { name: "对话详情" })
        .getByText(content, { exact: true }),
    ).toBeVisible();
    await expect(
      page
        .locator(".reading-pane > .message")
        .getByText(result.assistant_message.content, { exact: true })
        .last(),
    ).toBeVisible();
    await expect(page.getByLabel("对话分支")).toHaveValue(previous);
    await expect(
      page.getByRole("region", { name: "实际发送的上下文" }),
    ).toBeVisible();
  }
  await request.post(base + "/api/settings", {
    data: { chat_model: "fail-model" },
  });
  await page.getByLabel("消息内容").fill("失败后重试的分支问题");
  const failed = page.waitForResponse((r) => r.url().endsWith("/api/chat"));
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  const failure = await failed;
  expect(failure.status()).toBe(502);
  const original = failure.request().postDataJSON();
  const saved = await failure.json();
  expect(saved.user_message.parent_id).toBe(previous);
  await expect(
    page
      .locator(".reading-pane > .message")
      .getByText("失败后重试的分支问题", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("消息内容")).toHaveValue(original.content);
  await request.post(base + "/api/settings", {
    data: { chat_model: "synthetic-test" },
  });
  const retried = page.waitForResponse((r) => r.url().endsWith("/api/chat"));
  await page.getByRole("button", { name: "重试此消息" }).click();
  const retryResponse = await retried;
  expect(retryResponse.status()).toBe(200);
  expect(retryResponse.request().postDataJSON()).toEqual(original);
  const reply = await retryResponse.json();
  expect(reply.user_message.id).toBe(saved.user_message.id);
  expect(reply.assistant_message.parent_id).toBe(saved.user_message.id);
  await expect(page.getByLabel("对话分支")).toHaveValue(
    reply.assistant_message.id,
  );
  await expect(
    page
      .locator(".reading-pane > .message")
      .getByText(reply.assistant_message.content, { exact: true })
      .last(),
  ).toBeVisible();
  const archived = await (
    await request.get(base + "/api/conversations/" + conversation.id)
  ).json();
  expect(archived.messages).toHaveLength(9);
  await capture(page, "recallnest-branch-chat");
});

test("alternate branch oversized turn retains retry identity and smaller resend follows the saved user", async ({
  page,
  request,
}) => {
  await request.post(base + "/api/settings", {
    data: { base_url: "http://provider.test/v1", chat_model: "synthetic-test" },
  });
  const conversation = await (
    await request.post(base + "/api/conversations", {
      data: {
        title: "分支超限测试",
        current_node: "a",
        messages: [
          { id: "u", role: "user", content: "根" },
          { id: "a", role: "assistant", content: "默认叶", parent_id: "u" },
          { id: "b", role: "assistant", content: "备选叶", parent_id: "u" },
        ],
      },
    })
  ).json();
  const branch = conversation.messages.find(
    (m: { external_id: string }) => m.external_id === "b",
  );
  await page.goto("/#conversations/" + conversation.id);
  await page.getByLabel("对话分支").selectOption(branch.id);
  await page.getByLabel("消息内容").fill("\u0001".repeat(12000));
  const failed = page.waitForResponse((r) => r.url().endsWith("/api/chat"));
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  const failure = await failed;
  expect(failure.status()).toBe(413);
  const original = failure.request().postDataJSON();
  const saved = await failure.json();
  expect(saved.user_message.parent_id).toBe(branch.id);
  await expect(page.getByLabel("对话分支")).toHaveValue(saved.user_message.id);
  await expect(page.getByLabel("消息内容")).toHaveValue(original.content);
  const retried = page.waitForResponse((r) => r.url().endsWith("/api/chat"));
  await page.getByRole("button", { name: "重试此消息" }).click();
  const response = await retried;
  expect(response.status()).toBe(413);
  expect(response.request().postDataJSON()).toEqual(original);
  expect((await response.json()).user_message.id).toBe(saved.user_message.id);
  await page.getByLabel("消息内容").fill("短消息");
  const smaller = page.waitForResponse((r) => r.url().endsWith("/api/chat"));
  await page.getByRole("button", { name: "发送新消息" }).click();
  const success = await smaller;
  expect(success.status()).toBe(200);
  expect(success.request().postDataJSON().client_turn_id).not.toBe(
    original.client_turn_id,
  );
  const reply = await success.json();
  expect(reply.user_message.parent_id).toBe(saved.user_message.id);
  await expect(page.getByLabel("对话分支")).toHaveValue(
    reply.assistant_message.id,
  );
  await expect(
    page
      .locator(".reading-pane > .message")
      .getByText("短消息", { exact: true }),
  ).toBeVisible();
  expect(
    (
      await (
        await request.get(base + "/api/conversations/" + conversation.id)
      ).json()
    ).messages,
  ).toHaveLength(6);
});

test("late selected-branch response cannot replace a subsequent manual branch selection or its context", async ({
  page,
  request,
}) => {
  await request.post(base + "/api/settings", {
    data: { base_url: "http://provider.test/v1", chat_model: "synthetic-test" },
  });
  const conversation = await (
    await request.post(base + "/api/conversations", {
      data: {
        title: "延迟选择测试",
        current_node: "a",
        messages: [
          { id: "u", role: "user", content: "根" },
          {
            id: "a",
            role: "assistant",
            content: "保留当前选择",
            parent_id: "u",
          },
          {
            id: "b",
            role: "assistant",
            content: "发起请求的叶",
            parent_id: "u",
          },
        ],
      },
    })
  ).json();
  const initial = conversation.messages.find(
    (m: { external_id: string }) => m.external_id === "a",
  );
  const branch = conversation.messages.find(
    (m: { external_id: string }) => m.external_id === "b",
  );
  await page.goto("/#conversations/" + conversation.id);
  await page.getByLabel("对话分支").selectOption(branch.id);
  await page.getByLabel("消息内容").fill("延迟分支问题");
  const started = page.waitForRequest((r) => r.url().endsWith("/api/chat"));
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  const outgoing = await started;
  await page.getByLabel("对话分支").selectOption(initial.id);
  await expect(page.getByLabel("对话分支")).toHaveValue(initial.id);
  await expect
    .poll(async () =>
      (
        await (
          await request.get(base + "/api/conversations/" + conversation.id)
        ).json()
      ).messages.some(
        (m: { external_id: string; role: string }) =>
          m.role === "assistant" &&
          m.external_id ===
            "chat-assistant:" + outgoing.postDataJSON().client_turn_id,
      ),
    )
    .toBe(true);
  await expect(page.getByLabel("对话分支")).toHaveValue(initial.id);
  await expect(
    page
      .locator(".reading-pane > .message")
      .getByText("延迟分支问题", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "实际发送的上下文" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("消息内容")).toHaveValue("");
});
