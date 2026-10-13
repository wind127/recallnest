import { useEffect, useState } from "react";
import { api, entityPath, query } from "../api";
import { useAction, useResource } from "../hooks";
import { useNavigation } from "../navigation";
import type { Conversation, Evidence, Message } from "../types";
import { Field, History, Modal, Notice, Timestamp } from "./UI";
import { SafeMarkdown } from "./SafeMarkdown";
export function EvidenceRail({ evidence }: { evidence: Evidence[] }) {
  const { showEvidence } = useNavigation();
  const [copied, setCopied] = useState("");
  return (
    <aside className="evidence-rail" aria-label="来源证据">
      <h3>来源证据</h3>
      {!evidence.length && (
        <p className="meta">手写条目暂无引用，可在编辑时添加真实原文。</p>
      )}
      {evidence.map((item, i) => (
        <div className="citation" key={i}>
          <p className={item.stale ? "warning" : "meta"}>
            {item.stale ? "历史证据 · 源文已更新" : "原文引用"} · 版本{" "}
            {item.message_version ?? "当前"}
          </p>
          <blockquote>{item.quote}</blockquote>
          <button onClick={() => showEvidence(item)}>查看原始消息</button>
          <details>
            <summary>引用标识</summary>
            <p className="identifier">
              对话：{item.conversation_id || "未知"}
              <br />
              消息：{item.message_id}
            </p>
            <button
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(JSON.stringify(item));
                  setCopied(item.message_id);
                } catch {
                  setCopied("复制不可用，可选中标识手动复制。");
                }
              }}
            >
              复制证据标识
            </button>
          </details>
        </div>
      ))}
      {copied && (
        <p role="status" className="meta">
          {copied.startsWith("复制") ? copied : "证据标识已复制"}
        </p>
      )}
    </aside>
  );
}
export function EvidenceEditor({
  value,
  onChange,
}: {
  value: Evidence[];
  onChange: (value: Evidence[]) => void;
}) {
  const conversations = useResource<{ items: Conversation[] }>(
    "/conversations",
  );
  const [conversation, setConversation] = useState("");
  const detail = useResource<Conversation>(
    conversation ? entityPath("conversations", conversation) : null,
  );
  const [message, setMessage] = useState("");
  const [version, setVersion] = useState("");
  const [quote, setQuote] = useState("");
  const selected = detail.data?.messages.find((m) => m.id === message);
  const source =
    selected?.versions.find((v) => v.version === Number(version)) || selected;
  const valid = !!source && !!quote.trim() && source.content.includes(quote);
  return (
    <details className="evidence-editor">
      <summary>编辑原文引用（{value.length}）</summary>
      {value.map((item, i) => (
        <div className="citation" key={i}>
          <blockquote>{item.quote}</blockquote>
          <p className="identifier">
            {item.message_id} · v{item.message_version}
          </p>
          <button
            type="button"
            onClick={() => onChange(value.filter((_, j) => i !== j))}
          >
            移除此引用
          </button>
        </div>
      ))}
      <Field label="引用来源对话">
        <select
          value={conversation}
          onChange={(e) => {
            setConversation(e.target.value);
            setMessage("");
            setVersion("");
            setQuote("");
          }}
        >
          <option value="">选择真实来源</option>
          {conversations.data?.items.map((c) => (
            <option value={c.id} key={c.id}>
              {c.title}
            </option>
          ))}
        </select>
      </Field>
      <Notice error={conversations.error || detail.error} busy={detail.busy} />
      <Field label="引用消息">
        <select
          value={message}
          onChange={(e) => {
            setMessage(e.target.value);
            setVersion("");
            setQuote("");
          }}
        >
          <option value="">选择消息</option>
          {detail.data?.messages.map((m) => (
            <option key={m.id} value={m.id}>
              {m.role}：{m.content.slice(0, 70)}
            </option>
          ))}
        </select>
      </Field>
      {selected && (
        <>
          <Field label="引用版本">
            <select
              value={version || String(selected.version)}
              onChange={(e) => {
                setVersion(e.target.value);
                setQuote("");
              }}
            >
              {selected.versions.map((v) => (
                <option key={v.version} value={v.version}>
                  版本 {v.version}
                  {v.version === selected.version ? "（当前）" : "（历史）"}
                </option>
              ))}
            </select>
          </Field>
          <pre className="source-text">{source?.content}</pre>
          <Field label="引用原文（必须与所选版本逐字一致）">
            <textarea
              value={quote}
              onChange={(e) => setQuote(e.target.value)}
            />
          </Field>
          {quote && !valid && (
            <p className="warning">引用必须是所选原文的精确片段。</p>
          )}
          <button
            type="button"
            disabled={!valid}
            onClick={() => {
              if (source)
                onChange([
                  ...value,
                  {
                    conversation_id: conversation,
                    message_id: message,
                    message_version: source.version,
                    quote,
                  },
                ]);
              setQuote("");
            }}
          >
            添加引用
          </button>
        </>
      )}
    </details>
  );
}
export function MessageView({
  message,
  initialVersion,
}: {
  message: Message;
  initialVersion?: number | null;
}) {
  const [version, setVersion] = useState(initialVersion || message.version);
  const selected =
    message.versions.find((v) => v.version === version) || message;
  return (
    <article className="message" id={`message-${message.id}`}>
      <div className="message-meta">
        <strong>
          {(
            {
              user: "用户",
              assistant: "助手",
              tool: "工具",
              system: "系统来源",
              developer: "开发者来源",
            } as Record<string, string>
          )[selected.role] || selected.role}
        </strong>
        <span>
          <Timestamp value={selected.timestamp} />
        </span>
        <Field label="消息版本">
          <select
            value={version}
            onChange={(e) => setVersion(Number(e.target.value))}
          >
            {message.versions.map((v) => (
              <option key={v.version} value={v.version}>
                版本 {v.version}
                {v.version === message.version ? "（最新）" : "（历史）"}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {version !== message.version && (
        <p className="warning">
          正在查看历史版本；最新版本仍保留在版本选择器中。
        </p>
      )}
      <SafeMarkdown text={selected.content} />
      <details>
        <summary>消息标识与原始记录</summary>
        <p className="identifier">
          内部消息 ID：{message.id}
          <br />
          外部 ID：{message.external_id}
        </p>
        <pre>
          {JSON.stringify(
            { raw: selected.raw, metadata: selected.metadata },
            null,
            2,
          )}
        </pre>
      </details>
    </article>
  );
}
export function SourceViewer({
  evidence,
  onClose,
}: {
  evidence: Evidence;
  onClose: () => void;
}) {
  const [branch, setBranch] = useState("");
  const resource = useResource<Conversation>(
    evidence.conversation_id
      ? query(entityPath("conversations", evidence.conversation_id), { branch })
      : null,
  );
  const action = useAction();
  const message = resource.data?.messages.find(
    (m) => m.id === evidence.message_id,
  );
  const [all, setAll] = useState(false);
  useEffect(() => {
    setBranch("");
    setAll(false);
  }, [evidence]);
  return (
    <Modal title="原始对话与证据" onClose={onClose}>
      <p className={evidence.stale ? "warning" : "meta"}>
        {evidence.stale
          ? "源消息已变化，引用指向保留的历史版本。"
          : "精确引用版本"}{" "}
        v{evidence.message_version}
      </p>
      <blockquote>{evidence.quote}</blockquote>
      <Notice
        busy={resource.busy || action.busy}
        error={resource.error || action.error}
      />
      {resource.data && (
        <>
          <h3>{resource.data.title}</h3>
          <p className="meta">
            {resource.data.source} · 修订 {resource.data.revision}
          </p>
          {message ? (
            <MessageView
              key={`${message.id}-${evidence.message_version}`}
              message={message}
              initialVersion={evidence.message_version}
            />
          ) : (
            <p role="alert">未找到引用消息。</p>
          )}
          <Field label="查看对话分支">
            <select
              value={branch || resource.data.current_node || ""}
              onChange={(e) => setBranch(e.target.value)}
            >
              {resource.data.branches.map((b) => (
                <option key={b.leaf_id} value={b.leaf_id}>
                  {b.external_id}
                </option>
              ))}
            </select>
          </Field>
          <button
            disabled={action.busy || !branch}
            onClick={() =>
              action.run(async () => {
                await api.patch(
                  entityPath("conversations", resource.data!.id),
                  { current_node: branch },
                );
                resource.refresh();
              })
            }
          >
            设为当前分支
          </button>
          <button onClick={() => setAll((v) => !v)}>
            {all ? "收起完整对话" : "查看完整对话"}
          </button>
          {all &&
            resource.data.active_message_ids.map((id) => {
              const item = resource.data!.messages.find((m) => m.id === id);
              return item ? <MessageView key={item.id} message={item} /> : null;
            })}
          <History history={resource.data.raw_versions} />
        </>
      )}
    </Modal>
  );
}
