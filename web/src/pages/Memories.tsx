import { useEffect, useState } from "react";
import { api, entityPath, query } from "../api";
import { useAction, useResource } from "../hooks";
import type { Filters as FilterValues, Memory } from "../types";
import { EvidenceRail } from "../components/Evidence";
import { EntityEditor } from "../components/EntityEditor";
import { Filters, names } from "../components/Filters";
import { Empty, History, Notice, Timestamp } from "../components/UI";
export function Memories({ initialId }: { initialId?: string } = {}) {
  const [filters, setFilters] = useState<FilterValues>({});
  const [selected, setSelected] = useState(initialId || "");
  const [editing, setEditing] = useState<"new" | "edit">();
  useEffect(() => {
    setEditing(undefined);
  }, [selected, initialId]);
  const action = useAction();
  const list = useResource<{ items: Memory[] }>(query("/memories", filters));
  const context = useResource<{ items: Memory[] }>("/memories/context");
  const detail = useResource<Memory>(
    selected ? entityPath("memories", selected) : null,
  );
  useEffect(() => {
    if (initialId) setSelected(initialId);
  }, [initialId]);
  const update = (status: string) =>
    action.run(async () => {
      await api.patch(entityPath("memories", selected), { status });
      detail.refresh();
      list.refresh();
      context.refresh();
    });
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>我的记忆</h1>
          <p>亲自确认后，记忆才会用于个性化对话。</p>
        </div>
        <button className="primary" onClick={() => setEditing("new")}>
          新建记忆
        </button>
      </div>
      <p className="context-summary">
        当前用于个性化的记忆：{context.data?.items.length ?? "…"} 条
      </p>
      <p className="meta">
        是否生效以服务返回的当前上下文为准。历史证据与状态变化始终保留。
      </p>
      <Notice
        busy={context.busy || list.busy}
        error={context.error || list.error}
      />
      <Filters
        value={filters}
        onChange={(v) => {
          setFilters(v);
          setSelected("");
        }}
        fields={["status", "category"]}
      />
      <div className="workbench">
        <section className="document-list" aria-label="记忆列表">
          {["preference", "background", "goal", "state", "constraint"].map(
            (category) => {
              const items = list.data?.items.filter(
                (m) => m.category === category,
              );
              return items?.length ? (
                <section key={category}>
                  <h2 className="group-heading">{names[category]}</h2>
                  {items.map((item) => (
                    <div
                      key={item.id}
                      className={`document-row ${selected === item.id ? "selected" : ""}`}
                    >
                      <button
                        className="row-title"
                        onClick={() => setSelected(item.id)}
                      >
                        {item.content}
                      </button>
                      <p className="meta">
                        {names[item.status]} · {item.subject}
                        {context.data?.items.some((m) => m.id === item.id) &&
                          " · 当前生效"}
                      </p>
                    </div>
                  ))}
                </section>
              ) : null;
            },
          )}
          {list.data && !list.data.items.length && (
            <Empty>暂无记忆。可手写候选，或导入对话后整理。</Empty>
          )}
        </section>
        <section className="reading-pane" aria-label="记忆详情">
          <Notice
            busy={detail.busy || action.busy}
            error={detail.error || action.error}
          />
          {detail.data ? (
            <>
              <div className="actions">
                <button onClick={() => setEditing("edit")}>编辑记忆</button>
                {detail.data.status === "candidate" && (
                  <>
                    <button
                      className="primary"
                      disabled={action.busy}
                      onClick={() => update("confirmed")}
                    >
                      确认记忆
                    </button>
                    <button
                      disabled={action.busy}
                      onClick={() => update("rejected")}
                    >
                      拒绝记忆
                    </button>
                  </>
                )}
                {["confirmed", "candidate"].includes(detail.data.status) && (
                  <button
                    disabled={action.busy}
                    onClick={() => update("expired")}
                  >
                    使记忆过期
                  </button>
                )}
              </div>
              <div className="detail-with-evidence">
                <article>
                  <h2>
                    {names[detail.data.category]}：
                    {detail.data.subject || "未指定主题"}
                  </h2>
                  <p className="memory-content">{detail.data.content}</p>
                  <p className="meta">
                    状态：{names[detail.data.status]} · 来源：
                    {detail.data.source}
                  </p>
                  <p>
                    生效：
                    <Timestamp value={detail.data.effective_at} />
                    <br />
                    过期：
                    {detail.data.expires_at ? (
                      <Timestamp value={detail.data.expires_at} />
                    ) : (
                      "未设置"
                    )}
                  </p>
                  {context.data && (
                    <p
                      className={
                        context.data.items.some((m) => m.id === selected)
                          ? "success"
                          : "meta"
                      }
                    >
                      {context.data.items.some((m) => m.id === selected)
                        ? "当前用于个性化"
                        : "当前不在个性化上下文中"}
                    </p>
                  )}
                  {detail.data.supersedes && (
                    <button
                      onClick={() => setSelected(detail.data!.supersedes!)}
                    >
                      查看被替代的记忆
                    </button>
                  )}
                  <History history={detail.data.history} />
                </article>
                <EvidenceRail evidence={detail.data.evidence} />
              </div>
            </>
          ) : (
            !detail.busy && <Empty>选择一条记忆，核对原文、时间和状态。</Empty>
          )}
        </section>
      </div>
      {editing && (
        <EntityEditor
          kind="memories"
          entity={editing === "edit" ? detail.data : undefined}
          onClose={() => setEditing(undefined)}
          onSaved={(id) => {
            setEditing(undefined);
            setSelected(id);
            detail.refresh();
            list.refresh();
            context.refresh();
          }}
        />
      )}
    </>
  );
}
