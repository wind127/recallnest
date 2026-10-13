import { useEffect, useState } from "react";
import { api, entityPath, query } from "../api";
import { useAction, useResource } from "../hooks";
import type { Filters as FilterValues, Knowledge as Note } from "../types";
import { EvidenceRail } from "../components/Evidence";
import { EntityEditor } from "../components/EntityEditor";
import { Filters, names } from "../components/Filters";
import { SafeMarkdown } from "../components/SafeMarkdown";
import { Empty, History, Notice, Timestamp } from "../components/UI";
export function Knowledge({ initialId }: { initialId?: string }) {
  const [filters, setFilters] = useState<FilterValues>({});
  const [selected, setSelected] = useState(initialId || "");
  const [editing, setEditing] = useState<"new" | "edit">();
  useEffect(() => {
    setEditing(undefined);
  }, [selected, initialId]);
  const action = useAction();
  const list = useResource<{ items: Note[] }>(query("/knowledge", filters));
  const detail = useResource<Note>(
    selected ? entityPath("knowledge", selected) : null,
  );
  useEffect(() => {
    if (initialId) setSelected(initialId);
  }, [initialId]);
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>知识</h1>
          <p>将对话沉淀为可查阅、可追溯的笔记。</p>
        </div>
        <button className="primary" onClick={() => setEditing("new")}>
          新建知识
        </button>
      </div>
      <Filters
        value={filters}
        onChange={(v) => {
          setFilters(v);
          setSelected("");
        }}
        fields={[
          "type",
          "source",
          "tag",
          "project_id",
          "favorite",
          "unresolved",
          "dates",
        ]}
      />
      <Notice busy={list.busy} error={list.error} />
      <div className="workbench">
        <section className="document-list" aria-label="知识列表">
          {list.data?.items.map((item) => (
            <div
              className={`document-row ${selected === item.id ? "selected" : ""}`}
              key={item.id}
            >
              <button
                className="row-title"
                onClick={() => setSelected(item.id)}
              >
                {item.title}
              </button>
              <p>{item.summary}</p>
              <p className="meta">
                {item.favorite && "★ 收藏 · "}
                {names[item.type] || item.type} · {item.tags.join("、")} ·{" "}
                <Timestamp value={item.created_at} />
              </p>
            </div>
          ))}
          {list.data && !list.data.items.length && (
            <Empty>暂无知识。导入后运行整理，或手动新建一条笔记。</Empty>
          )}
        </section>
        <section className="reading-pane" aria-label="知识详情">
          <Notice
            busy={detail.busy || action.busy}
            error={detail.error || action.error}
          />
          {detail.data ? (
            <>
              <div className="actions">
                <button onClick={() => setEditing("edit")}>编辑知识</button>
                <button
                  disabled={action.busy}
                  onClick={() =>
                    action.run(async () => {
                      await api.post(
                        entityPath("knowledge", selected) + "/favorite",
                        { favorite: !detail.data!.favorite },
                      );
                      detail.refresh();
                      list.refresh();
                    })
                  }
                >
                  {detail.data.favorite ? "取消收藏" : "收藏知识"}
                </button>
              </div>
              <div className="detail-with-evidence">
                <article>
                  <h2>{detail.data.title}</h2>
                  <p className="meta">
                    {names[detail.data.type] || detail.data.type} ·{" "}
                    {detail.data.source} ·{" "}
                    <Timestamp value={detail.data.created_at} />
                  </p>
                  <p className="summary">{detail.data.summary}</p>
                  <SafeMarkdown text={detail.data.body} />
                  <History history={detail.data.history} />
                </article>
                <EvidenceRail evidence={detail.data.evidence} />
              </div>
            </>
          ) : (
            !detail.busy && <Empty>选择一篇知识，查看正文和来源证据。</Empty>
          )}
        </section>
      </div>
      {editing && (
        <EntityEditor
          kind="knowledge"
          entity={editing === "edit" ? detail.data : undefined}
          onClose={() => setEditing(undefined)}
          onSaved={(id) => {
            setEditing(undefined);
            setSelected(id);
            list.refresh();
            detail.refresh();
          }}
        />
      )}
    </>
  );
}
