import { useEffect, useRef, useState } from "react";
import { api, entityPath, query } from "../api";
import { useAction, useResource } from "../hooks";
import type { Conversation, Filters as FilterValues } from "../types";
import { ChatComposer } from "../components/ChatComposer";
import { MessageView } from "../components/Evidence";
import { Filters, ProjectSelect } from "../components/Filters";
import { Empty, Field, History, Notice, Timestamp } from "../components/UI";
export function Conversations({
  initialId,
  codexMode = false,
}: {
  initialId?: string;
  codexMode?: boolean;
}) {
  const [filters, setFilters] = useState<FilterValues>({});
  const [selected, setSelected] = useState(initialId || "");
  const [branch, setBranch] = useState("");
  const [composerSession, setComposerSession] = useState(0);
  const selectionEpoch = useRef(0);
  const resetComposer = () => {
    selectionEpoch.current += 1;
    setComposerSession(selectionEpoch.current);
  };
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [project, setProject] = useState("");
  const action = useAction();
  const list = useResource<{ items: Conversation[] }>(
    query("/conversations", filters),
  );
  const detail = useResource<Conversation>(
    selected ? query(entityPath("conversations", selected), { branch }) : null,
  );
  useEffect(() => {
    if (initialId) {
      setSelected(initialId);
      setBranch("");
      resetComposer();
    }
  }, [initialId]);
  const select = (id: string) => {
    setSelected(id);
    setBranch("");
    resetComposer();
    setEditing(false);
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>对话</h1>
          <p>保留所有分支与版本，继续积累新的对话。</p>
        </div>
        <button className="primary" onClick={() => select("")}>
          新建对话
        </button>
      </div>
      <Filters
        value={filters}
        onChange={(v) => {
          setFilters(v);
          select("");
        }}
        fields={["source", "project_id", "dates"]}
      />
      <Notice busy={list.busy} error={list.error} />
      <div className="workbench">
        <section className="document-list" aria-label="对话列表">
          {list.data?.items.map((item) => (
            <div
              key={item.id}
              className={`document-row ${selected === item.id ? "selected" : ""}`}
            >
              <button className="row-title" onClick={() => select(item.id)}>
                {item.title}
              </button>
              <p className="meta">
                {item.source} · {item.message_count} 条消息 ·{" "}
                <Timestamp value={item.created_at} />
              </p>
            </div>
          ))}
          {list.data && !list.data.items.length && (
            <Empty>
              {codexMode
                ? "暂无对话。可以导入历史，或在 Codex 中用 $recallnest 保存会话。"
                : "暂无对话。可以导入历史，也可以直接发送新消息。"}
            </Empty>
          )}
        </section>
        <section className="reading-pane" aria-label="对话详情">
          <Notice
            busy={detail.busy || action.busy}
            error={detail.error || action.error}
          />
          {detail.data && (
            <>
              <h2>{detail.data.title}</h2>
              <p className="meta">
                {detail.data.source} · 修订 {detail.data.revision} · 来源标识{" "}
                {detail.data.source_identity}
              </p>
              <div className="actions">
                <Field label="对话分支">
                  <select
                    value={branch || detail.data.current_node || ""}
                    onChange={(e) => {
                      setBranch(e.target.value);
                      resetComposer();
                    }}
                  >
                    {detail.data.branches.map((item) => (
                      <option key={item.leaf_id} value={item.leaf_id}>
                        {item.external_id}
                      </option>
                    ))}
                  </select>
                </Field>
                <button
                  disabled={!branch || action.busy}
                  onClick={() =>
                    action.run(async () => {
                      await api.patch(entityPath("conversations", selected), {
                        current_node: branch,
                      });
                      detail.refresh();
                      list.refresh();
                    })
                  }
                >
                  设为当前分支
                </button>
                <button
                  onClick={() => {
                    setTitle(detail.data!.title);
                    setProject(detail.data!.project_id || "");
                    setEditing((v) => !v);
                  }}
                >
                  编辑对话信息
                </button>
              </div>
              {editing && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    action.run(async () => {
                      await api.patch(entityPath("conversations", selected), {
                        title,
                        project_id: project || null,
                      });
                      setEditing(false);
                      detail.refresh();
                      list.refresh();
                    });
                  }}
                >
                  <Field label="对话标题">
                    <input
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      disabled={action.busy}
                    />
                  </Field>
                  <ProjectSelect
                    value={project}
                    onChange={setProject}
                    label="对话关联项目"
                  />
                  <button disabled={action.busy}>保存对话信息</button>
                </form>
              )}
              {detail.data.active_message_ids.map((id) => {
                const message = detail.data!.messages.find((m) => m.id === id);
                return message ? (
                  <MessageView
                    key={`${message.id}-${message.version}`}
                    message={message}
                  />
                ) : null;
              })}
              <details>
                <summary>所有消息与源版本</summary>
                <p className="meta">
                  所有分支共 {detail.data.messages.length} 条消息。
                </p>
                {detail.data.messages
                  .filter(
                    (m) => !detail.data!.active_message_ids.includes(m.id),
                  )
                  .map((message) => (
                    <MessageView key={message.id} message={message} />
                  ))}
                <History history={detail.data.raw_versions} />
              </details>
            </>
          )}
          {codexMode ? (
            <p className="meta">
              请在 Codex 中继续对话，并用 $recallnest
              保存和整理。这里查看原文与分支。
            </p>
          ) : (
            <ChatComposer
              key={`${selected}/${composerSession}`}
              conversationId={selected || null}
              branch={branch || null}
              onSaved={(result) => {
                if (selectionEpoch.current !== composerSession) return;
                // Manual selection resets the composer; response advancement
                // retains its input, context and original idempotent retry body.
                const node =
                  result.assistant_message?.id || result.user_message?.id;
                if (selected && result.conversation_id === selected && node)
                  setBranch(node);
                list.refresh();
                detail.refresh();
              }}
            />
          )}
        </section>
      </div>
    </>
  );
}
