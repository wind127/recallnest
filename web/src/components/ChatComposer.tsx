import { useEffect, useRef, useState } from "react";
import { APIError, api } from "../api";
import { useAction } from "../hooks";
import { useNavigation } from "../navigation";
import type { ChatRequest, ChatResult, Context } from "../types";
import { EvidenceRail } from "./Evidence";
import { SafeMarkdown } from "./SafeMarkdown";
import { Field, Notice } from "./UI";
export function UsedContext({ value }: { value: Context }) {
  const { go, showEvidence } = useNavigation();
  return (
    <section className="used-context" aria-label="实际发送的上下文">
      <h3>实际发送的上下文</h3>
      <p className="meta">
        只列出本次请求实际使用的条目；未配置或请求超限时为空。
      </p>
      <p>记忆：{value.memory_ids.length} 条</p>
      <details>
        <summary>查看使用的记忆标识</summary>
        <div className="id-links">
          {value.memory_ids.map((id) => (
            <button key={id} onClick={() => go({ page: "memories", id })}>
              {id}
            </button>
          ))}
        </div>
      </details>
      <p>知识：{value.knowledge_ids.length} 条</p>
      <details>
        <summary>查看使用的知识标识</summary>
        <div className="id-links">
          {value.knowledge_ids.map((id) => (
            <button key={id} onClick={() => go({ page: "knowledge", id })}>
              {id}
            </button>
          ))}
        </div>
      </details>
      <details>
        <summary>消息标识（{value.message_ids.length}）</summary>
        {value.message_ids.map((id) => {
          const evidence = value.evidence.find((e) => e.message_id === id);
          return evidence ? (
            <button key={id} onClick={() => showEvidence(evidence)}>
              {id}
            </button>
          ) : (
            <p className="identifier" key={id}>
              {id}
            </p>
          );
        })}
      </details>
      {value.evidence.length > 0 && <EvidenceRail evidence={value.evidence} />}
    </section>
  );
}
const chatGuidance: Record<string, string> = {
  configuration_required:
    "请在模型设置中填写服务地址和模型名，保存并测试后重试此消息。",
  request_too_large:
    "输入超出模型请求容量。请缩短输入后发送新消息；原始消息已完整归档，重试不会重复保存。",
  stale_turn: "来源或分支已更新，请核对当前资料后重试此消息。",
  turn_running: "此消息仍在生成中，请稍后重试查看结果。",
  turn_interrupted: "上次生成已中断，可以重试此消息。",
  provider_http: "模型服务未能完成请求，请检查服务权限和配置后重试。",
  provider_timeout: "模型服务响应超时，请稍后重试。",
  provider_network: "无法连接模型服务，请检查地址和网络后重试。",
  invalid_output: "模型服务返回的内容无法读取，请检查服务兼容性后重试。",
};
export function ChatComposer({
  conversationId,
  branch,
  onSaved,
}: {
  conversationId: string | null;
  branch: string | null;
  onSaved: (result: ChatResult) => void;
}) {
  const [input, setInput] = useState("");
  const [retry, setRetry] = useState<ChatRequest>();
  const [result, setResult] = useState<ChatResult>();
  const [turns, setTurns] = useState<ChatResult[]>([]);
  const action = useAction();
  const alive = useRef(true);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );
  const send = (request: ChatRequest) =>
    action.run(async () => {
      let response: ChatResult;
      try {
        response = await api.post<ChatResult>("/chat", request);
      } catch (error) {
        if (!(error instanceof APIError) || !error.data.conversation_id) {
          setRetry(request);
          throw error;
        }
        response = error.data as unknown as ChatResult;
      }
      if (!alive.current) return;
      setResult(response);
      setRetry(response.assistant_message ? undefined : request);
      setTurns((existing) => [
        ...existing.filter(
          (turn) => turn.client_turn_id !== response.client_turn_id,
        ),
        response,
      ]);
      if (response.assistant_message)
        setInput((previous) => (previous === request.content ? "" : previous));
      onSaved(response);
    });
  const submit = () =>
    send(
      retry && input === retry.content
        ? retry
        : {
            conversation_id: conversationId || result?.conversation_id || null,
            branch,
            content: input,
            client_turn_id: crypto.randomUUID(),
          },
    );
  return (
    <section className="chat-composer" aria-label="个性化对话">
      <h2>{conversationId ? "继续对话" : "新对话"}</h2>
      {!conversationId &&
        turns.map((turn) => (
          <div key={turn.client_turn_id}>
            <div className="message">
              <strong>用户</strong>
              <SafeMarkdown text={turn.user_message?.content || ""} />
            </div>
            {turn.assistant_message && (
              <div className="message">
                <strong>助手</strong>
                <SafeMarkdown text={turn.assistant_message.content} />
              </div>
            )}
          </div>
        ))}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        aria-busy={action.busy}
      >
        <Field label="消息内容">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={4}
            maxLength={16000}
            disabled={action.busy}
            placeholder="写下问题或补充新的信息…"
          />
        </Field>
        <div className="actions">
          <button
            className="primary"
            type="submit"
            disabled={!input.trim() || action.busy}
          >
            {retry && input !== retry.content ? "发送新消息" : "发送消息"}
          </button>
          {retry && (
            <button
              type="button"
              disabled={action.busy}
              onClick={() => send(retry)}
            >
              重试此消息
            </button>
          )}
        </div>
        {retry && input !== retry.content && (
          <p className="meta">
            输入已修改，发送将创建新消息。重试按钮始终使用原始消息。
          </p>
        )}
      </form>
      <Notice busy={action.busy} error={action.error} />
      {result && (
        <>
          {result.error_kind && (
            <div className="warning" role="alert">
              <p>消息已保存；尚未生成助手回复。</p>
              <p>
                {chatGuidance[result.error_kind] ||
                  "服务暂时无法回复，请检查设置后重试。"}
              </p>
              <details>
                <summary>查看请求详情</summary>
                <p>
                  <code>{result.error_kind}</code>：{result.detail}
                </p>
                <p className="identifier">
                  消息：{result.user_message?.id}
                  <br />
                  请求：{result.client_turn_id}
                </p>
              </details>
            </div>
          )}
          <UsedContext value={result.used_context} />
        </>
      )}
    </section>
  );
}
