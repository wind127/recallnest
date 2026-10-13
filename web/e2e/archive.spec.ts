import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
async function configure(page: Page, model = "synthetic-test") {
  await page.getByRole("button", { name: "模型设置", exact: true }).click();
  await page.getByLabel("服务 Base URL").fill("http://provider.test/v1");
  await page.getByLabel("对话模型", { exact: true }).fill(model);
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByText("设置已保存。连接需重新测试。")).toBeVisible();
  await page.getByRole("button", { name: "关闭模型设置" }).click();
}
async function createSource(request: APIRequestContext, id = "branch-source") {
  const response = await request.post(
    "http://127.0.0.1:18787/api/conversations",
    {
      data: {
        title: "合成分支档案",
        source: "synthetic-test",
        external_id: id,
        messages: [
          { id: "u1", role: "user", content: "我偏好中文。" },
          { id: "a1", role: "assistant", content: "分支甲", parent_id: "u1" },
          { id: "a2", role: "assistant", content: "分支乙", parent_id: "u1" },
        ],
        current_node: "a1",
      },
    },
  );
  expect(response.status()).toBe(201);
  return response.json();
}
test.beforeEach(async ({ request }) => {
  await request.post("http://127.0.0.1:18787/_test/reset");
});
test("branch selection uses internal IDs and historical evidence selects its exact archived version", async ({
  page,
  request,
}) => {
  const conversation = await createSource(request);
  const user = conversation.messages.find(
    (m: { external_id: string }) => m.external_id === "u1",
  );
  const note = await (
    await request.post("http://127.0.0.1:18787/api/knowledge", {
      data: {
        title: "历史证据笔记",
        body: "可追溯引用",
        evidence: [
          { message_id: user.id, message_version: 1, quote: "我偏好中文。" },
        ],
      },
    })
  ).json();
  await request.post(
    `http://127.0.0.1:18787/api/conversations/${conversation.id}/messages`,
    {
      data: { messages: [{ id: "u1", role: "user", content: "我偏好英文。" }] },
    },
  );
  await request.patch(
    `http://127.0.0.1:18787/api/conversations/${conversation.id}`,
    {
      data: {
        current_node: conversation.messages.find(
          (m: { external_id: string }) => m.external_id === "a1",
        ).id,
      },
    },
  );
  await page.goto(`/#conversations/${conversation.id}`);
  await expect(page.getByText("分支甲", { exact: true }).first()).toBeVisible();
  const second = conversation.messages.find(
    (m: { external_id: string }) => m.external_id === "a2",
  );
  await page.getByLabel("对话分支").selectOption(second.id);
  await expect(page.getByText("分支乙", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "设为当前分支" }).click();
  await expect
    .poll(
      async () =>
        (
          await (
            await request.get(
              `http://127.0.0.1:18787/api/conversations/${conversation.id}`,
            )
          ).json()
        ).current_node,
    )
    .toBe(second.id);
  await page.goto(`/#knowledge/${note.id}`);
  await expect(page.getByText(/历史证据 · 源文已更新/)).toBeVisible();
  await page.getByRole("button", { name: "查看原始消息" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("消息版本")).toHaveValue("1");
  await expect(
    dialog.getByText("我偏好中文。", { exact: true }).last(),
  ).toBeVisible();
  await dialog.getByLabel("消息版本").selectOption("2");
  await expect(dialog.getByText("我偏好英文。", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "查看原始消息" }),
  ).toBeFocused();
});
test("renewed current proof keeps confirmed memory active even with an older stale proof", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await configure(page);
  const conversation = await createSource(request);
  let jobs = (
    await (await request.get("http://127.0.0.1:18787/api/jobs")).json()
  ).items;
  await request.post(`http://127.0.0.1:18787/api/jobs/${jobs[0].id}/run`);
  const memory = (
    await (await request.get("http://127.0.0.1:18787/api/memories")).json()
  ).items[0];
  await request.patch(`http://127.0.0.1:18787/api/memories/${memory.id}`, {
    data: { status: "confirmed" },
  });
  await request.post(
    `http://127.0.0.1:18787/api/conversations/${conversation.id}/messages`,
    {
      data: {
        messages: [
          {
            id: "u1",
            role: "user",
            content: "我偏好中文。\n新增合成学习内容。",
          },
        ],
      },
    },
  );
  jobs = (await (await request.get("http://127.0.0.1:18787/api/jobs")).json())
    .items;
  const queued = jobs.find((j: { status: string }) => j.status === "queued");
  await request.post(`http://127.0.0.1:18787/api/jobs/${queued.id}/run`);
  const full = await (
    await request.get(`http://127.0.0.1:18787/api/memories/${memory.id}`)
  ).json();
  expect(full.evidence.some((e: { stale: boolean }) => e.stale)).toBe(true);
  expect(full.evidence.some((e: { stale: boolean }) => !e.stale)).toBe(true);
  await page.goto(`/#memories/${memory.id}`);
  await expect(page.getByText("当前用于个性化的记忆：1 条")).toBeVisible();
  await expect(page.getByText("当前用于个性化", { exact: true })).toBeVisible();
  const context = (
    await (
      await request.get("http://127.0.0.1:18787/api/memories/context")
    ).json()
  ).items[0];
  expect(context.evidence.every((e: { stale: boolean }) => !e.stale)).toBe(
    true,
  );
});
test("oversized saved turn retries one UUID and a smaller resend creates one new turn", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await configure(page);
  await page.goto("/#conversations");
  const content = "\u0001".repeat(12000);
  await page.getByLabel("消息内容").fill(content);
  const sent = page.waitForResponse(
    (r) => r.url().endsWith("/api/chat") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  const result = await sent;
  expect(result.status()).toBe(413);
  const body = await result.json();
  await page.getByText("查看请求详情", { exact: true }).click();
  await expect(
    page.getByText("request_too_large", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("记忆：0 条", { exact: true })).toBeVisible();
  expect(
    (await (await request.get("http://127.0.0.1:18787/api/stats")).json())
      .messages,
  ).toBe(1);
  const retried = page.waitForResponse((r) => r.url().endsWith("/api/chat"));
  await page.getByRole("button", { name: "重试此消息" }).click();
  const retryResponse = await retried;
  expect(retryResponse.request().postDataJSON().client_turn_id).toBe(
    body.client_turn_id,
  );
  expect((await retryResponse.json()).user_message.id).toBe(
    body.user_message.id,
  );
  await page.getByLabel("消息内容").fill("缩短后的合成问题");
  const smaller = page.waitForResponse((r) => r.url().endsWith("/api/chat"));
  await page.getByRole("button", { name: "发送新消息" }).click();
  const success = await smaller;
  expect(success.status()).toBe(200);
  expect(success.request().postDataJSON().client_turn_id).not.toBe(
    body.client_turn_id,
  );
  await expect(
    page.getByText("这是本地测试服务的真实 HTTP 边界回复。"),
  ).toBeVisible();
  expect(
    (await (await request.get("http://127.0.0.1:18787/api/stats")).json())
      .messages,
  ).toBe(3);
});
test("provider failure keeps input, sanitized saved result and idempotent retries", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await configure(page);
  await page.goto("/#conversations");
  await page.getByLabel("消息内容").fill("失败请求");
  const sent = page.waitForResponse((r) => r.url().endsWith("/api/chat"));
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  expect((await sent).status()).toBe(502);
  await page.getByText("查看请求详情", { exact: true }).click();
  await expect(page.getByText("provider_http", { exact: true })).toBeVisible();
  await expect(page.getByLabel("消息内容")).toHaveValue("失败请求");
  await expect(page.getByText("synthetic private provider detail")).toHaveCount(
    0,
  );
  const retried = page.waitForResponse((r) => r.url().endsWith("/api/chat"));
  await page.getByRole("button", { name: "重试此消息" }).click();
  expect((await retried).status()).toBe(502);
  expect(
    (await (await request.get("http://127.0.0.1:18787/api/stats")).json())
      .messages,
  ).toBe(1);
});
