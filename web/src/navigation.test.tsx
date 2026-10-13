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
              ? { model_configured: false }
              : path.includes("/stats")
                ? {
                    conversations: 0,
                    messages: 0,
                    knowledge: 0,
                    confirmed_memories: 0,
                    due_reviews: 0,
                  }
                : { items: [], mode: "text", warning: null },
          ),
        ),
    ),
  );
});
test("malformed escaped route falls back to a usable overview", () => {
  window.location.hash = "#knowledge/%E0";
  expect(() => render(<App />)).not.toThrow();
  expect(screen.getByRole("heading", { name: "概览" })).toBeInTheDocument();
});
test("explicit resubmission refreshes the same query and a search survives reloading its route", async () => {
  const user = userEvent.setup();
  const view = render(<App />);
  await user.type(screen.getByLabelText("全局搜索"), "中文");
  await user.click(screen.getByRole("button", { name: "搜索" }));
  await screen.findByRole("heading", { name: "搜索" });
  const fetchMock = vi.mocked(fetch);
  const searchCalls = () =>
    fetchMock.mock.calls.filter(([path]) => String(path).includes("/search?"))
      .length;
  await waitFor(() => expect(searchCalls()).toBeGreaterThan(0));
  const before = searchCalls();
  await user.click(screen.getByRole("button", { name: "搜索" }));
  await waitFor(() => expect(searchCalls()).toBeGreaterThan(before));
  expect(window.location.hash).toBe("#search/" + encodeURIComponent("中文"));
  view.unmount();
  render(<App />);
  expect(screen.getByRole("heading", { name: "搜索" })).toBeInTheDocument();
});
