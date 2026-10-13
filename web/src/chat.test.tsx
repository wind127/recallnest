import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { test, expect, vi } from "vitest";
import { ChatComposer } from "./components/ChatComposer";
import type { ChatRequest } from "./types";
test("saved oversized turn retries the identical UUID and edited smaller message gets a new UUID", async () => {
  const bodies: ChatRequest[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      bodies.push(body);
      return new Response(
        JSON.stringify({
          conversation_id: "c1",
          client_turn_id: body.client_turn_id,
          user_message: {
            id: "u1",
            content: body.content,
            role: "user",
            versions: [],
          },
          assistant_message: null,
          used_context: {
            memory_ids: [],
            knowledge_ids: [],
            message_ids: [],
            evidence: [],
          },
          error_kind: "request_too_large",
          detail: "Request too large",
        }),
        { status: 413 },
      );
    }),
  );
  render(
    <ChatComposer conversationId={null} branch={null} onSaved={() => {}} />,
  );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("消息内容"), "较长原文");
  await user.click(screen.getByRole("button", { name: "发送消息" }));
  await screen.findByText("request_too_large");
  expect(
    screen.getByText("消息已保存；尚未生成助手回复。"),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("消息内容")).toHaveValue("较长原文");
  await user.click(screen.getByRole("button", { name: "重试此消息" }));
  await waitFor(() => expect(bodies).toHaveLength(2));
  expect(bodies[1]).toEqual(bodies[0]);
  await user.clear(screen.getByLabelText("消息内容"));
  await user.type(screen.getByLabelText("消息内容"), "短");
  await user.click(screen.getByRole("button", { name: "发送新消息" }));
  await waitFor(() => expect(bodies).toHaveLength(3));
  expect(bodies[2].client_turn_id).not.toBe(bodies[0].client_turn_id);
  expect(bodies[2].conversation_id).toBe("c1");
});
