import { test, expect, type Page } from "@playwright/test";
import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
const source = {
  source: "browser-fixture",
  source_identity: "synthetic-only",
  external_id: "session-one",
  title: "合成测试：数据库学习",
  messages: [
    { id: "u1", role: "user", content: "我偏好中文。" },
    {
      id: "a1",
      role: "assistant",
      content: "事务确保全部成功或全部回滚。",
      parent_id: "u1",
    },
  ],
};
async function navigate(page: Page, name: string) {
  if (await page.getByRole("button", { name: "打开导航" }).isVisible())
    await page.getByRole("button", { name: "打开导航" }).click();
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("button", { name, exact: true })
    .click();
}
async function configure(page: Page) {
  await page.getByRole("button", { name: "模型设置", exact: true }).click();
  await page.getByLabel("服务 Base URL").fill("http://provider.test/v1");
  await page.getByLabel("对话模型", { exact: true }).fill("synthetic-test");
  await page.getByLabel("向量模型（可选）").fill("synthetic-vector");
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByText("设置已保存。连接需重新测试。")).toBeVisible();
  await page.getByRole("button", { name: "测试已保存的连接" }).click();
  await expect(page.getByText("连接已验证", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "关闭模型设置" }).click();
}
async function screenshot(page: Page, name: string) {
  if (process.env.RECALLNEST_SCREENSHOTS) {
    mkdirSync(process.env.RECALLNEST_SCREENSHOTS, { recursive: true });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: resolve(process.env.RECALLNEST_SCREENSHOTS, name + ".png"),
      fullPage: true,
    });
  }
}
test.beforeEach(async ({ request }) => {
  await request.post("http://127.0.0.1:18787/_test/reset");
});

test("empty and unconfigured states retain basic features, save failed chat once, export real archive", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(
    page.getByText("模型尚未配置", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("还没有对话档案")).toBeVisible();
  await screenshot(page, "recallnest-empty");
  await navigate(page, "对话");
  await page.getByLabel("消息内容").fill("未配置时的合成消息");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.getByText(/消息已保存/)).toBeVisible();
  await page.getByText("查看请求详情", { exact: true }).click();
  await expect(
    page.getByText("configuration_required", { exact: true }),
  ).toBeVisible();
  const before = await (
    await request.get("http://127.0.0.1:18787/api/stats")
  ).json();
  await page.getByRole("button", { name: "重试此消息" }).click();
  await expect(page.getByRole("button", { name: "重试此消息" })).toBeEnabled();
  expect(
    (await (await request.get("http://127.0.0.1:18787/api/stats")).json())
      .messages,
  ).toBe(before.messages);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 JSON" }).click();
  const exported = await download;
  expect(exported.suggestedFilename()).toBe("recallnest-export.json");
  const archive = JSON.parse(readFileSync((await exported.path())!, "utf8"));
  expect(archive.schema_version).toBe(1);
  expect(archive.conversations).toHaveLength(1);
  expect(archive.conversations[0].messages).toHaveLength(1);
  expect(archive.conversations[0].messages[0].content).toBe(
    "未配置时的合成消息",
  );
  expect(archive).not.toHaveProperty("settings");
  const markdownDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 Markdown" }).click();
  const markdown = await markdownDownload;
  expect(markdown.suggestedFilename()).toBe("recallnest-export.md");
  expect(readFileSync((await markdown.path())!, "utf8")).toContain(
    "未配置时的合成消息",
  );
});

test("real import, provider-backed job citations, memory context exclusion and review history", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await configure(page);
  await page
    .getByRole("button", { name: "导入对话", exact: true })
    .first()
    .click();
  await page.getByLabel("对话文件").setInputFiles({
    name: "source.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(source)),
  });
  await page.getByLabel("来源标识").fill("synthetic-only");
  await expect(page.getByRole("button", { name: "确认导入" })).toBeDisabled();
  await page.getByRole("button", { name: "预览文件" }).click();
  await expect(page.getByText(source.title, { exact: true })).toBeVisible();
  await page.getByLabel("来源标识").fill("synthetic-only-changed");
  await expect(page.getByRole("button", { name: "确认导入" })).toBeDisabled();
  await page.getByLabel("来源标识").fill("synthetic-only");
  await page.getByRole("button", { name: "预览文件" }).click();
  await expect(page.getByRole("button", { name: "确认导入" })).toBeEnabled();
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page.getByText(/新增对话 1/)).toBeVisible();
  await page.getByRole("button", { name: "关闭导入对话" }).click();
  await page
    .getByRole("button", { name: "导入对话", exact: true })
    .first()
    .click();
  await page.getByLabel("对话文件").setInputFiles({
    name: "same-source.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(source)),
  });
  await page.getByLabel("来源标识").fill("synthetic-only");
  await page.getByRole("button", { name: "预览文件" }).click();
  await expect(page.getByRole("button", { name: "确认导入" })).toBeEnabled();
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page.getByText(/新增对话 0，更新 0，重复 1/)).toBeVisible();
  await page.getByRole("button", { name: "关闭导入对话" }).click();
  await page.getByRole("button", { name: "运行整理" }).click();
  await expect(page.getByText("整理完成", { exact: true })).toBeVisible();
  await navigate(page, "知识");
  await page.getByRole("button", { name: "事务与原子性", exact: true }).click();
  await page.getByRole("button", { name: "查看原始消息" }).click();
  await expect(
    page
      .getByRole("dialog")
      .getByText("事务确保全部成功或全部回滚。", { exact: true })
      .last(),
  ).toBeVisible();
  await page.getByRole("button", { name: "关闭原始对话与证据" }).click();
  await screenshot(page, "recallnest-knowledge");
  await navigate(page, "我的记忆");
  await page.getByRole("button", { name: "我偏好中文。", exact: true }).click();
  await page.getByRole("button", { name: "确认记忆" }).click();
  await expect(page.getByText("当前用于个性化的记忆：1 条")).toBeVisible();
  const memory = (
    await (
      await request.get("http://127.0.0.1:18787/api/memories/context")
    ).json()
  ).items[0];
  await navigate(page, "对话");
  await page.getByLabel("消息内容").fill("讲讲事务");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(
    page.getByText("这是本地测试服务的真实 HTTP 边界回复。"),
  ).toBeVisible();
  await page.getByText("查看使用的记忆标识", { exact: true }).click();
  await expect(page.getByText(memory.id, { exact: true })).toBeVisible();
  await navigate(page, "我的记忆");
  await page.getByRole("button", { name: "我偏好中文。", exact: true }).click();
  await page.getByRole("button", { name: "使记忆过期" }).click();
  await expect(page.getByText("当前用于个性化的记忆：0 条")).toBeVisible();
  await navigate(page, "对话");
  await page.getByLabel("消息内容").fill("现在讲讲事务");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.getByText("记忆：0 条", { exact: true })).toBeVisible();
  await navigate(page, "复习");
  await expect(
    page.getByRole("button", { name: "记得", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "显示答案" }).click();
  await expect(page.getByText("确保写入全部成功或全部回滚。")).toBeVisible();
  await page.getByRole("button", { name: "记得", exact: true }).click();
  await expect(page.getByText(/已更新下次复习时间/)).toBeVisible();
  await screenshot(page, "recallnest-review");
  await page.getByRole("button", { name: "模型设置", exact: true }).click();
  await page.getByRole("button", { name: "重新索引" }).click();
  await expect(page.getByText(/索引完成/)).toBeVisible();
  await page.getByRole("button", { name: "关闭模型设置" }).click();
  await page.getByLabel("全局搜索").fill("事务");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "事务与原子性", exact: true }),
  ).toBeVisible();
});

test("mobile drawer, editable manual entities, exact source versions and safe Markdown", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await navigate(page, "知识");
  await page.getByRole("button", { name: "新建知识" }).click();
  await page.getByLabel("知识标题").fill("手写中文笔记");
  await page
    .getByLabel("正文（支持 Markdown）")
    .fill(
      "**安全正文**\n\n<script>alert(1)</script>\n\n![追踪](https://outside.invalid/a.png)",
    );
  await page.getByRole("button", { name: "保存知识", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "手写中文笔记" }),
  ).toBeVisible();
  await expect(page.locator(".prose img")).toHaveCount(0);
  await expect(page.locator(".prose script")).toHaveCount(0);
  await page.getByRole("button", { name: "收藏知识" }).click();
  await expect(page.getByRole("button", { name: "取消收藏" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await screenshot(page, "recallnest-mobile");
  await navigate(page, "项目");
  await page.getByRole("button", { name: "新建项目" }).click();
  await page.getByLabel("项目名称").fill("合成练习");
  await page.getByLabel("目标（每行一项）").fill("理解事务\n完成复习");
  await page.getByRole("button", { name: "保存项目" }).click();
  await expect(page.getByRole("heading", { name: "合成练习" })).toBeVisible();
  await navigate(page, "知识");
  await page.getByRole("button", { name: "手写中文笔记", exact: true }).click();
  await page.getByRole("button", { name: "编辑知识" }).click();
  await page.getByLabel("关联项目").selectOption({ label: "合成练习" });
  await page.getByRole("button", { name: "保存知识" }).click();
  const projects = (
    await (await request.get("http://127.0.0.1:18787/api/projects")).json()
  ).items;
  expect(
    (
      await (
        await request.get(
          `http://127.0.0.1:18787/api/projects/${projects[0].id}/links`,
        )
      ).json()
    ).knowledge,
  ).toHaveLength(1);
  await page.getByRole("button", { name: "导入对话", exact: true }).click();
  await page.getByLabel("对话文件").setInputFiles({
    name: "invalid.json",
    mimeType: "application/json",
    buffer: Buffer.from("{"),
  });
  await page.getByRole("button", { name: "预览文件" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认导入" })).toBeDisabled();
  await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "关闭导入对话" }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
