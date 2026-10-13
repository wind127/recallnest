import { useEffect, useState } from "react";
import { api, entityPath, query } from "../api";
import { useAction, useResource } from "../hooks";
import { useNavigation } from "../navigation";
import type { Conversation, Knowledge, Project, ReviewCard } from "../types";
import { EntityEditor } from "../components/EntityEditor";
import { names } from "../components/Filters";
import { SafeMarkdown, safeURL } from "../components/SafeMarkdown";
import { Empty, Field, History, Notice } from "../components/UI";
export function Projects({ initialId }: { initialId?: string }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState(initialId || "");
  const [editing, setEditing] = useState<"new" | "edit">();
  const [link, setLink] = useState("");
  useEffect(() => {
    setEditing(undefined);
  }, [selected, initialId]);
  const action = useAction();
  const { go } = useNavigation();
  const list = useResource<{ items: Project[] }>(
    query("/projects", { q, status }),
  );
  const detail = useResource<Project>(
    selected ? entityPath("projects", selected) : null,
  );
  const links = useResource<{
    conversations: Conversation[];
    knowledge: Knowledge[];
    reviews: ReviewCard[];
  }>(selected ? entityPath("projects", selected) + "/links" : null);
  const conversations = useResource<{ items: Conversation[] }>(
    "/conversations",
  );
  useEffect(() => {
    if (initialId) setSelected(initialId);
  }, [initialId]);
  const associate = (id: string, project_id: string | null) =>
    action.run(async () => {
      await api.patch(entityPath("conversations", id), { project_id });
      links.refresh();
      conversations.refresh();
    });
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>项目</h1>
          <p>围绕目标组织对话、知识、复习与成果。</p>
        </div>
        <button className="primary" onClick={() => setEditing("new")}>
          新建项目
        </button>
      </div>
      <div className="filters">
        <Field label="搜索项目">
          <input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setSelected("");
            }}
          />
        </Field>
        <Field label="项目状态筛选">
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setSelected("");
            }}
          >
            <option value="">全部</option>
            {["active", "paused", "completed", "archived"].map((v) => (
              <option key={v} value={v}>
                {names[v]}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Notice busy={list.busy} error={list.error} />
      <div className="workbench">
        <section className="document-list" aria-label="项目列表">
          {list.data?.items.map((item) => (
            <div
              key={item.id}
              className={`document-row ${item.id === selected ? "selected" : ""}`}
            >
              <button
                className="row-title"
                onClick={() => setSelected(item.id)}
              >
                {item.name}
              </button>
              <p className="meta">
                {names[item.status]} · {item.goals.length} 项目标
              </p>
            </div>
          ))}
          {list.data && !list.data.items.length && (
            <Empty>暂无项目。新建一个项目，把相关资料放在一起。</Empty>
          )}
        </section>
        <section className="reading-pane" aria-label="项目详情">
          <Notice
            busy={detail.busy || links.busy || action.busy}
            error={detail.error || links.error || action.error}
          />
          {detail.data ? (
            <>
              <div className="actions">
                <button onClick={() => setEditing("edit")}>编辑项目</button>
                <span className="meta">{names[detail.data.status]}</span>
              </div>
              <h2>{detail.data.name}</h2>
              <SafeMarkdown text={detail.data.description} />
              <h3>目标</h3>
              {detail.data.goals.length ? (
                <ul>
                  {detail.data.goals.map((goal, i) => (
                    <li key={i}>{goal}</li>
                  ))}
                </ul>
              ) : (
                <p className="meta">尚未填写目标</p>
              )}
              <h3>成果链接</h3>
              {detail.data.artifact_links.length ? (
                <ul>
                  {detail.data.artifact_links.map((artifact, i) => (
                    <li key={i}>
                      {safeURL(artifact.url) ? (
                        <a
                          href={safeURL(artifact.url)}
                          target="_blank"
                          rel="noreferrer noopener"
                        >
                          {artifact.title || artifact.url}
                        </a>
                      ) : (
                        "无效链接"
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="meta">暂无成果链接</p>
              )}
              <h3>关联对话</h3>
              <Field label="选择要关联的对话">
                <select value={link} onChange={(e) => setLink(e.target.value)}>
                  <option value="">选择对话</option>
                  {conversations.data?.items
                    .filter((c) => c.project_id !== selected)
                    .map((c) => (
                      <option value={c.id} key={c.id}>
                        {c.title}
                      </option>
                    ))}
                </select>
              </Field>
              <button
                disabled={!link || action.busy}
                onClick={() => {
                  associate(link, selected);
                  setLink("");
                }}
              >
                关联对话
              </button>
              {links.data?.conversations.map((c) => (
                <div key={c.id} className="linked-row">
                  <button
                    className="text-button"
                    onClick={() => go({ page: "conversations", id: c.id })}
                  >
                    {c.title}
                  </button>
                  <button
                    disabled={action.busy}
                    onClick={() => associate(c.id, null)}
                  >
                    取消关联
                  </button>
                </div>
              ))}
              <h3>关联知识</h3>
              {links.data?.knowledge.map((k) => (
                <p key={k.id}>
                  <button
                    className="text-button"
                    onClick={() => go({ page: "knowledge", id: k.id })}
                  >
                    {k.title}
                  </button>
                </p>
              ))}
              <h3>关联复习卡</h3>
              {links.data?.reviews.map((r) => (
                <p key={r.id}>
                  <button
                    className="text-button"
                    onClick={() => go({ page: "review", id: r.id })}
                  >
                    {r.question}
                  </button>
                </p>
              ))}
              <p className="meta">
                在知识或复习卡的编辑窗口中选择此项目即可关联。
              </p>
              <History history={detail.data.history} />
            </>
          ) : (
            !detail.busy && <Empty>选择一个项目，查看目标和关联资料。</Empty>
          )}
        </section>
      </div>
      {editing && (
        <EntityEditor
          kind="projects"
          entity={editing === "edit" ? detail.data : undefined}
          onClose={() => setEditing(undefined)}
          onSaved={(id) => {
            setEditing(undefined);
            setSelected(id);
            list.refresh();
            detail.refresh();
            links.refresh();
          }}
        />
      )}
    </>
  );
}
