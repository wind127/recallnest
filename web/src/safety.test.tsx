import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { SafeMarkdown } from "./components/SafeMarkdown";
import { SettingsModal } from "./components/SettingsModal";
import { toUTC, toLocalInput } from "./dates";

test("untrusted Markdown formats prose without fetching images or enabling script links", () => {
  const { container } = render(
    <SafeMarkdown
      text={
        "**可读文本**\n\n<script>alert(1)</script>\n\n[攻击](javascript:alert%281%29)\n\n![外部图片](https://remote.invalid/tracker.png)"
      }
    />,
  );
  expect(container.querySelector("strong")).toHaveTextContent("可读文本");
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector('a[href^="javascript"]')).toBeNull();
  expect(screen.getByText(/外部图片/)).toBeInTheDocument();
});

test("local date inputs round trip to UTC without assuming the local date is UTC", () => {
  const input = "2026-10-14T09:30";
  expect(toUTC(input)).toBe(new Date(2026, 9, 14, 9, 30).toISOString());
  expect(toLocalInput(new Date(2026, 9, 14, 9, 30).toISOString())).toBe(input);
});

test("blank key is omitted, explicit clear sends empty key, and testing uses saved settings", async () => {
  const writes: { path: string; body?: Record<string, string> }[] = [];
  const config = {
    base_url: "http://127.0.0.1:18888/v1",
    chat_model: "local",
    embedding_model: "",
    has_api_key: true,
    model_configured: true,
    connection_verified: false,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST")
        writes.push({
          path,
          body: init.body ? JSON.parse(init.body as string) : undefined,
        });
      return new Response(
        JSON.stringify(
          path.endsWith("/test")
            ? { connection_verified: true, model_configured: true }
            : config,
        ),
      );
    }),
  );
  render(<SettingsModal onClose={() => {}} onSaved={() => {}} />);
  const user = userEvent.setup();
  await screen.findByDisplayValue("local");
  expect(screen.getByLabelText("API 密钥")).toHaveAttribute("type", "password");
  expect(screen.getByLabelText("API 密钥")).toHaveValue("");
  await user.click(screen.getByRole("button", { name: "保存设置" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body).not.toHaveProperty("api_key");
  await user.click(screen.getByRole("button", { name: "测试已保存的连接" }));
  await screen.findByText("连接已验证");
  expect(writes[1]).toEqual({ path: "/api/settings/test", body: undefined });
  await user.click(screen.getByRole("checkbox", { name: "清除已保存的密钥" }));
  await user.click(screen.getByRole("button", { name: "保存设置" }));
  await waitFor(() => expect(writes[2].body).toHaveProperty("api_key", ""));
});
