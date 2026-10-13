import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { useState } from "react";
import { useResource } from "./hooks";

test("resource data from an old request is never exposed under the next request key", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      path.endsWith("old")
        ? Promise.resolve(new Response(JSON.stringify({ name: "old-data" })))
        : new Promise<Response>(() => {}),
    ),
  );
  const renders: { path: string; data?: string; busy: boolean }[] = [];
  function Probe() {
    const [path, setPath] = useState("/old");
    const resource = useResource<{ name: string }>(path);
    renders.push({ path, data: resource.data?.name, busy: resource.busy });
    return (
      <>
        <p>{resource.data?.name || "等待新结果"}</p>
        <button onClick={() => setPath("/new")}>更换请求</button>
      </>
    );
  }
  render(<Probe />);
  await screen.findByText("old-data");
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "更换请求" }));
  expect(
    renders
      .filter((r) => r.path === "/new")
      .every((r) => r.data === undefined && r.busy),
  ).toBe(true);
  expect(screen.queryByText("old-data")).not.toBeInTheDocument();
});
