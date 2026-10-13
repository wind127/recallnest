import { useEffect, useState } from "react";
import { api, entityPath } from "../api";
import { useAction, useResource } from "../hooks";
import { useNavigation } from "../navigation";
import type { Job, Knowledge, ReviewCard } from "../types";
import { Empty, Notice, Timestamp } from "../components/UI";
const jobNames: Record<string, string> = {
  queued: "等待整理",
  running: "正在整理",
  completed: "整理完成",
  failed: "整理失败",
};
export function Overview({ onImport }: { onImport: () => void }) {
  const stats = useResource<Record<string, number>>("/stats");
  const knowledge = useResource<{ items: Knowledge[] }>("/knowledge");
  const reviews = useResource<{ items: ReviewCard[] }>("/reviews?due=true");
  const jobs = useResource<{ items: Job[] }>("/jobs");
  const action = useAction();
  const { go } = useNavigation();
  const [progress, setProgress] = useState("");
  const refresh = () => {
    stats.refresh();
    knowledge.refresh();
    reviews.refresh();
    jobs.refresh();
  };
  const pending = jobs.data?.items.some((job) =>
    ["queued", "running"].includes(job.status),
  );
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => {
      jobs.refresh();
      stats.refresh();
      knowledge.refresh();
      reviews.refresh();
    }, 5000);
    return () => clearInterval(timer);
  }, [pending]);
  const operate = (job: Job, retry = false) =>
    action.run(async () => {
      if (retry) await api.post(entityPath("jobs", job.id) + "/retry");
      await api.post(entityPath("jobs", job.id) + "/run");
      refresh();
    });
  const batch = () =>
    action.run(async () => {
      const failed =
        jobs.data?.items.filter((job) => job.status === "failed") || [];
      const errors: string[] = [];
      for (let i = 0; i < failed.length; i++) {
        setProgress(`重试整理 ${i + 1} / ${failed.length}`);
        try {
          await api.post(entityPath("jobs", failed[i].id) + "/retry");
          await api.post(entityPath("jobs", failed[i].id) + "/run");
        } catch {
          errors.push(failed[i].id);
        }
      }
      setProgress(
        `批量重试完成，共 ${failed.length} 项${errors.length ? `，请求失败 ${errors.length} 项` : ""}。请检查各任务最终状态。`,
      );
      refresh();
    });
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>概览</h1>
          <p>让每次对话留下可查阅的知识，也留下下一次复习。</p>
        </div>
        <button className="primary" onClick={onImport}>
          导入对话
        </button>
      </div>
      <Notice busy={stats.busy} error={stats.error} />
      {stats.data && (
        <>
          <dl className="stats-strip">
            {(
              [
                ["conversations", "对话"],
                ["messages", "消息"],
                ["knowledge", "知识"],
                ["confirmed_memories", "已确认记忆"],
                ["due_reviews", "到期复习"],
              ] as const
            ).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{stats.data![key]}</dd>
              </div>
            ))}
          </dl>
          {stats.data.conversations === 0 && (
            <Empty>
              <h2>还没有对话档案</h2>
              <p>导入历史对话，或开始一次新的对话。</p>
              <div className="actions">
                <button onClick={onImport}>选择导入文件</button>
                <button onClick={() => go({ page: "conversations" })}>
                  开始新对话
                </button>
                <button
                  disabled={action.busy}
                  onClick={() =>
                    action.run(async () => {
                      await api.post("/demo");
                      refresh();
                    })
                  }
                >
                  载入明确标记的合成示例
                </button>
              </div>
              <p className="meta">
                合成示例不调用模型，用于体验资料、证据与复习流程。
              </p>
            </Empty>
          )}
        </>
      )}
      <div className="overview-reading">
        <section>
          <h2>最近的知识</h2>
          <Notice busy={knowledge.busy} error={knowledge.error} />
          {knowledge.data?.items.slice(0, 5).map((note) => (
            <div className="document-row" key={note.id}>
              <button
                className="row-title"
                onClick={() => go({ page: "knowledge", id: note.id })}
              >
                {note.title}
              </button>
              <p>{note.summary}</p>
              <p className="meta">
                <Timestamp value={note.created_at} />
              </p>
            </div>
          ))}
          {knowledge.data && !knowledge.data.items.length && (
            <p className="meta">暂无知识。导入对话后运行整理，或手动新建。</p>
          )}
        </section>
        <section className="next-review">
          <h2>下一次复习</h2>
          <Notice busy={reviews.busy} error={reviews.error} />
          {reviews.data?.items[0] ? (
            <>
              <h3>{reviews.data.items[0].question}</h3>
              <p className="meta">
                到期：
                <Timestamp value={reviews.data.items[0].due_at} />
              </p>
              <button
                onClick={() =>
                  go({ page: "review", id: reviews.data!.items[0].id })
                }
              >
                开始复习
              </button>
            </>
          ) : (
            <p className="meta">当前没有到期卡片。</p>
          )}
        </section>
      </div>
      <section className="jobs">
        <div className="section-heading">
          <h2>整理任务</h2>
          <div className="actions">
            <button disabled={action.busy} onClick={() => jobs.refresh()}>
              刷新任务
            </button>
            <button
              disabled={
                action.busy ||
                !jobs.data?.items.some((job) => job.status === "failed")
              }
              onClick={batch}
            >
              批量重试失败整理
            </button>
          </div>
        </div>
        <Notice error={jobs.error || action.error} busy={action.busy} />
        {progress && <p role="status">{progress}</p>}
        {jobs.data?.items.map((job) => (
          <div className="job-row" key={job.id}>
            <div>
              <strong>{jobNames[job.status] || job.status}</strong>
              <p className="meta">
                尝试 {job.attempts} 次 ·{" "}
                <button
                  className="text-button"
                  onClick={() =>
                    go({ page: "conversations", id: job.conversation_id })
                  }
                >
                  来源对话
                </button>
              </p>
              {job.error_kind && (
                <p className="warning">
                  {job.error_kind}：{job.error}
                </p>
              )}
              {job.next_attempt_at && (
                <p className="meta">
                  下次自动尝试：
                  <Timestamp value={job.next_attempt_at} />
                </p>
              )}
              {job.disposition && (
                <p className="meta">
                  {(
                    {
                      extracted: "已由模型整理",
                      synthetic_skipped: "合成示例：未调用模型",
                      superseded: "源资料已更新，结果已舍弃",
                      no_new_text: "没有新的非空文本",
                    } as Record<string, string>
                  )[job.disposition] || job.disposition}
                </p>
              )}
              {job.result && (
                <p className="meta">
                  知识 {job.result.knowledge} · 记忆 {job.result.memories} ·
                  复习 {job.result.reviews} · 处理消息{" "}
                  {job.result.processed_messages}
                </p>
              )}
            </div>
            <div className="actions">
              {job.status === "queued" && (
                <button disabled={action.busy} onClick={() => operate(job)}>
                  运行整理
                </button>
              )}
              {job.status === "failed" && (
                <button
                  disabled={action.busy}
                  onClick={() => operate(job, true)}
                >
                  重试整理
                </button>
              )}
            </div>
          </div>
        ))}
        {jobs.data && !jobs.data.items.length && (
          <p className="meta">暂无整理任务。</p>
        )}
      </section>
    </>
  );
}
