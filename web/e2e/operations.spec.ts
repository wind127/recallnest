import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
test.beforeEach(async ({ request }) => {
  await request.post("http://127.0.0.1:18787/_test/reset");
});
test("failed jobs batch retry sequentially against real job routes", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:18787/api/settings", {
    data: { base_url: "http://provider.test/v1", chat_model: "fail-model" },
  });
  for (let i = 0; i < 2; i++)
    await request.post("http://127.0.0.1:18787/api/conversations", {
      data: {
        title: `合成整理 ${i}`,
        messages: [{ id: "u1", role: "user", content: "我偏好中文。" }],
      },
    });
  await page.goto("/");
  await page
    .getByRole("button", { name: "运行整理", exact: true })
    .first()
    .click();
  await expect(page.getByText("整理失败", { exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "运行整理", exact: true }).click();
  await expect(page.getByText("整理失败", { exact: true })).toHaveCount(2);
  await page.getByRole("button", { name: "模型设置", exact: true }).click();
  await page.getByLabel("对话模型", { exact: true }).fill("synthetic-test");
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByText("设置已保存。连接需重新测试。")).toBeVisible();
  await page.getByRole("button", { name: "关闭模型设置" }).click();
  const requests: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/jobs/") && r.method() === "POST")
      requests.push(r.url().split("/").at(-1)!);
  });
  await page.getByRole("button", { name: "批量重试失败整理" }).click();
  await expect(page.getByText(/批量重试完成，共 2 项/)).toBeVisible();
  await expect(page.getByText("整理完成", { exact: true })).toHaveCount(2);
  expect(requests).toEqual(["retry", "run", "retry", "run"]);
});
test("manual memory replacement preserves predecessor history and review edits pause and filter by due date", async ({
  page,
  request,
}) => {
  const predecessor = await (
    await request.post("http://127.0.0.1:18787/api/memories", {
      data: {
        content: "我偏好中文。",
        category: "preference",
        subject: "语言",
        status: "confirmed",
      },
    })
  ).json();
  await page.goto("/#memories");
  await page.getByRole("button", { name: "新建记忆" }).click();
  await page.getByLabel("记忆内容").fill("我偏好英文。");
  await page.getByLabel("主题", { exact: true }).fill("语言");
  await page.getByLabel("替代的旧记忆").selectOption(predecessor.id);
  await page.getByRole("button", { name: "保存记忆" }).click();
  await expect(page.getByText("当前用于个性化的记忆：1 条")).toBeVisible();
  await page.getByRole("button", { name: "确认记忆" }).click();
  await expect(page.getByText("状态：已确认 · 来源：manual")).toBeVisible();
  await page.getByRole("button", { name: "查看被替代的记忆" }).click();
  await expect(page.getByText("状态：已替代 · 来源：manual")).toBeVisible();
  await expect(page.getByText(/查看历史/)).toBeVisible();
  await page.goto("/#review");
  await page.getByRole("button", { name: "新建复习卡" }).click();
  await page.getByLabel("问题", { exact: true }).fill("手写测试问题");
  await page.getByLabel("答案", { exact: true }).fill("可编辑答案");
  await page.getByRole("button", { name: "保存复习卡" }).click();
  await expect(
    page.getByRole("heading", { name: "手写测试问题" }),
  ).toBeVisible();
  // Keep paused cards in this queue while exercising pause/recovery. The
  // default due queue correctly excludes a card once it is paused.
  await page.getByRole("checkbox", { name: "仅到期卡片" }).uncheck();
  await page.getByRole("button", { name: "暂停复习", exact: true }).click();
  await expect(page.getByText("此卡已暂停，恢复后可以评分。")).toBeVisible();
  await page.getByRole("button", { name: "显示答案" }).click();
  await expect(
    page.getByRole("button", { name: "记得", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "恢复复习", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "记得", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "记得", exact: true }).click();
  await expect(page.getByText(/已更新下次复习时间/)).toBeVisible();
  await page.getByRole("checkbox", { name: "仅到期卡片" }).uncheck();
  const card = (
    await (await request.get("http://127.0.0.1:18787/api/reviews")).json()
  ).items[0];
  const due = card.due_at.slice(0, 10);
  await page.getByLabel("到期日期自（UTC）").fill(due);
  await page.getByLabel("到期日期至（UTC，含当天）").fill(due);
  await expect(
    page.getByRole("button", { name: "手写测试问题", exact: true }),
  ).toBeVisible();
});
test("semantic search warns on fallback and settings explicitly clear a saved key", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:18787/api/knowledge", {
    data: { title: "语义检索合成笔记", body: "事务与数据库", tags: ["数据库"] },
  });
  await request.post("http://127.0.0.1:18787/api/settings", {
    data: {
      base_url: "http://provider.test/v1",
      chat_model: "synthetic-test",
      api_key: "synthetic-browser-secret",
    },
  });
  await page.goto("/");
  await page.getByLabel("全局搜索").fill("事务");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await page.getByRole("checkbox", { name: "语义混合搜索" }).check();
  await expect(page.getByText(/已回退文字检索/)).toBeVisible();
  await page.getByRole("button", { name: "模型设置", exact: true }).click();
  await expect(page.getByLabel("API 密钥")).toHaveValue("");
  await page.getByLabel("向量模型（可选）").fill("synthetic-vector");
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByText("设置已保存。连接需重新测试。")).toBeVisible();
  expect(
    (await (await request.get("http://127.0.0.1:18787/api/settings")).json())
      .has_api_key,
  ).toBe(true);
  await page.getByRole("button", { name: "重新索引" }).click();
  await expect(page.getByText(/索引完成/)).toBeVisible();
  await page.getByRole("button", { name: "关闭模型设置" }).click();
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 JSON" }).click();
  const downloaded = await downloading;
  const archiveText = readFileSync((await downloaded.path())!, "utf8");
  expect(JSON.parse(archiveText).knowledge[0].title).toBe("语义检索合成笔记");
  expect(archiveText).not.toContain("synthetic-browser-secret");
  expect(archiveText).not.toContain("provider.test");
  expect(JSON.parse(archiveText)).not.toHaveProperty("settings");
  await page.getByRole("button", { name: "模型设置", exact: true }).click();
  await expect(page.getByLabel("对话模型", { exact: true })).toHaveValue(
    "synthetic-test",
  );
  await page.getByRole("checkbox", { name: "清除已保存的密钥" }).check();
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByText("设置已保存。连接需重新测试。")).toBeVisible();
  await expect
    .poll(
      async () =>
        (
          await (
            await request.get("http://127.0.0.1:18787/api/settings")
          ).json()
        ).has_api_key,
    )
    .toBe(false);
  await page.getByRole("button", { name: "关闭模型设置" }).click();
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByText(/文字 \+ 语义混合检索/)).toBeVisible();
  await expect(page.getByText(/已回退文字检索/)).toHaveCount(0);
});
