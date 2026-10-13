import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
const base = "http://127.0.0.1:18787/api";
async function readyDetail(
  page: import("@playwright/test").Page,
  kind: string,
  label: string,
) {
  if (kind === "memories")
    await expect(page.locator(".memory-content")).toHaveText(label);
  else
    await expect(
      page.getByRole("heading", { name: label, exact: true }),
    ).toBeVisible();
}
test.beforeEach(async ({ request }) => {
  await request.post("http://127.0.0.1:18787/_test/reset");
});
for (const [kind, route, field, edit, save, bodyA, bodyB] of [
  [
    "knowledge",
    "knowledge",
    "知识标题",
    "编辑知识",
    "保存知识",
    { title: "A", body: "Body A" },
    { title: "B", body: "Body B" },
  ],
  [
    "memories",
    "memories",
    "记忆内容",
    "编辑记忆",
    "保存记忆",
    { category: "preference", content: "A", subject: "A" },
    { category: "preference", content: "B", subject: "B" },
  ],
  [
    "projects",
    "projects",
    "项目名称",
    "编辑项目",
    "保存项目",
    { name: "A", description: "Body A" },
    { name: "B", description: "Body B" },
  ],
  [
    "reviews",
    "review",
    "问题",
    "编辑复习卡",
    "保存复习卡",
    { question: "A", answer: "Body A" },
    { question: "B", answer: "Body B" },
  ],
] as const) {
  test(`${kind} browser Back closes A draft without modifying B or creating a ghost entity`, async ({
    page,
    request,
  }) => {
    const a = await (
      await request.post(base + "/" + kind, { data: bodyA })
    ).json();
    const b = await (
      await request.post(base + "/" + kind, { data: bodyB })
    ).json();
    await page.goto("/#" + route + "/" + b.id);
    await readyDetail(page, kind, "B");
    await page.evaluate(
      (hash) => {
        location.hash = hash;
      },
      route + "/" + a.id,
    );
    await readyDetail(page, kind, "A");
    await page.getByRole("button", { name: edit }).click();
    await page.getByLabel(field).fill("Draft A");
    await page.goBack();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await readyDetail(page, kind, "B");
    expect(
      await (await request.get(base + "/" + kind + "/" + a.id)).json(),
    ).toMatchObject(bodyA);
    expect(
      await (await request.get(base + "/" + kind + "/" + b.id)).json(),
    ).toMatchObject(bodyB);
    expect(
      (await (await request.get(base + "/" + kind)).json()).items,
    ).toHaveLength(2);
    if (kind === "knowledge" && process.env.RECALLNEST_SCREENSHOTS) {
      mkdirSync(process.env.RECALLNEST_SCREENSHOTS, { recursive: true });
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: resolve(
          process.env.RECALLNEST_SCREENSHOTS,
          "recallnest-editor-back-safe.png",
        ),
        fullPage: true,
      });
    }
    await page.getByRole("button", { name: edit }).click();
    await expect(page.getByLabel(field)).toHaveValue("B");
  });
  test(`${kind} a real save finishing after Back updates only its original target and cannot select it again`, async ({
    page,
    request,
  }) => {
    const a = await (
      await request.post(base + "/" + kind, { data: bodyA })
    ).json();
    const b = await (
      await request.post(base + "/" + kind, { data: bodyB })
    ).json();
    await page.goto("/#" + route + "/" + b.id);
    await readyDetail(page, kind, "B");
    await page.evaluate(
      (hash) => {
        location.hash = hash;
      },
      route + "/" + a.id,
    );
    await readyDetail(page, kind, "A");
    await page.getByRole("button", { name: edit }).click();
    await page.getByLabel(field).fill("Saved draft A");
    let release!: () => void;
    let reached!: () => void;
    const stored = new Promise<void>((resolve) => {
      reached = resolve;
    });
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/" + kind + "/" + a.id, async (routeRequest) => {
      if (routeRequest.request().method() !== "PATCH")
        return routeRequest.continue();
      const response = await routeRequest.fetch();
      expect(response.status()).toBe(200);
      reached();
      await gate;
      await routeRequest.fulfill({ response });
    });
    await page.getByRole("button", { name: save }).click();
    await stored;
    await page.goBack();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    release();
    await readyDetail(page, kind, "B");
    expect(page.url()).toContain("/#" + route + "/" + b.id);
    const payloadField = {
      knowledge: "title",
      memories: "content",
      projects: "name",
      reviews: "question",
    }[kind];
    expect(
      (await (await request.get(base + "/" + kind + "/" + a.id)).json())[
        payloadField
      ],
    ).toBe("Saved draft A");
    expect(
      await (await request.get(base + "/" + kind + "/" + b.id)).json(),
    ).toMatchObject(bodyB);
    expect(
      (await (await request.get(base + "/" + kind)).json()).items,
    ).toHaveLength(2);
  });
}
for (const kind of ["memories", "reviews"] as const) {
  test(`${kind} microseconds survive an unrelated edit; explicit date changes and clearing remain deliberate`, async ({
    page,
    request,
  }) => {
    const dates =
      kind === "memories"
        ? {
            effective_at: "2026-10-20T04:35:42.123456+00:00",
            expires_at: "2026-10-21T04:35:59.654321+00:00",
          }
        : { due_at: "2026-10-20T04:35:42.123456+00:00" };
    const entity = await (
      await request.post(base + "/" + kind, {
        data: {
          ...(kind === "memories"
            ? { content: "精确时间", category: "preference", subject: "before" }
            : { question: "精确时间", answer: "before" }),
          ...dates,
        },
      })
    ).json();
    const route = kind === "memories" ? "memories" : "review";
    const edit = kind === "memories" ? "编辑记忆" : "编辑复习卡";
    const save = kind === "memories" ? "保存记忆" : "保存复习卡";
    await page.goto("/#" + route + "/" + entity.id);
    await page.getByRole("button", { name: edit }).click();
    await page
      .getByLabel(kind === "memories" ? "主题" : "答案")
      .fill("unrelated edit");
    const first = page.waitForResponse(
      (r) =>
        r.url().endsWith("/" + kind + "/" + entity.id) &&
        r.request().method() === "PATCH",
    );
    await page.getByRole("button", { name: save }).click();
    const saved = await (await first).json();
    for (const key of Object.keys(dates)) expect(saved[key]).toBe(entity[key]);
    await page.getByRole("button", { name: edit }).click();
    const field = page.getByLabel(
      kind === "memories" ? /^过期时间/ : /^下次复习时间/,
    );
    const local = "2026-10-22T13:40";
    await field.fill(local);
    const second = page.waitForResponse(
      (r) =>
        r.url().endsWith("/" + kind + "/" + entity.id) &&
        r.request().method() === "PATCH",
    );
    await page.getByRole("button", { name: save }).click();
    const changed = await (await second).json();
    const key = kind === "memories" ? "expires_at" : "due_at";
    expect(new Date(changed[key]).toISOString()).toBe(
      await page.evaluate((value) => new Date(value).toISOString(), local),
    );
    if (kind === "memories")
      expect(changed.effective_at).toBe(entity.effective_at);
    await page.getByRole("button", { name: edit }).click();
    await page
      .getByLabel(kind === "memories" ? /^过期时间/ : /^下次复习时间/)
      .fill("");
    const third = page.waitForResponse(
      (r) =>
        r.url().endsWith("/" + kind + "/" + entity.id) &&
        r.request().method() === "PATCH",
    );
    await page.getByRole("button", { name: save }).click();
    const clearedResponse = await third;
    expect(clearedResponse.request().postDataJSON()[key]).toBeNull();
    const cleared = await clearedResponse.json();
    if (kind === "memories") expect(cleared.expires_at).toBeNull();
    else expect(cleared.due_at).toBe(changed.due_at);
  });
}
