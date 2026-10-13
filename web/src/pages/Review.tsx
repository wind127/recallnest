import { useEffect, useRef, useState } from "react";
import { api, entityPath, query } from "../api";
import { useAction, useResource } from "../hooks";
import type { Filters as FilterValues, Grade, ReviewCard } from "../types";
import { EvidenceRail } from "../components/Evidence";
import { EntityEditor } from "../components/EntityEditor";
import { Filters, names } from "../components/Filters";
import { SafeMarkdown } from "../components/SafeMarkdown";
import { Empty, History, Notice, Timestamp } from "../components/UI";

function GradeHistory({ card }: { card: ReviewCard }) {
  return (
    <>
      <h3>评分记录</h3>
      {card.grade_history?.length ? (
        <ul>
          {card.grade_history.map((event) => (
            <li key={event.id}>
              {names[event.grade]} · <Timestamp value={event.reviewed_at} />
              <br />
              下次：
              <Timestamp value={event.next_due_at} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="meta">尚未评分</p>
      )}
      <History history={card.history} />
    </>
  );
}
function GradeNotice({ card }: { card: ReviewCard }) {
  return (
    <p role="status" className="success">
      已更新下次复习时间：
      <Timestamp value={card.due_at} />
    </p>
  );
}
export function Review({ initialId }: { initialId?: string } = {}) {
  const [filters, setFilters] = useState<FilterValues>({ due: !initialId });
  const [selected, setSelected] = useState(initialId || "");
  const [revealed, setRevealed] = useState(false);
  const [updated, setUpdated] = useState<ReviewCard>();
  const [feedback, setFeedback] = useState<ReviewCard>();
  const [editing, setEditing] = useState<"new" | "edit">();
  useEffect(() => {
    setEditing(undefined);
  }, [selected, initialId]);
  const action = useAction();
  const queuePath = query("/reviews", filters);
  const selection = useRef({ id: selected, queuePath });
  selection.current = { id: selected, queuePath };
  const list = useResource<{ items: ReviewCard[] }>(queuePath);
  const eligible = !!list.data?.items.some((item) => item.id === selected);
  const detail = useResource<ReviewCard>(
    eligible ? entityPath("reviews", selected) : null,
  );
  const card = eligible
    ? updated?.id === selected
      ? updated
      : detail.data
    : undefined;
  const select = (id: string) => {
    setSelected(id);
    setRevealed(false);
    setUpdated(undefined);
    setFeedback(undefined);
  };
  useEffect(() => {
    if (initialId) {
      select(initialId);
      setFilters({ due: false });
    }
  }, [initialId]);
  useEffect(() => {
    if (!list.data) return;
    const next = list.data.items.some((item) => item.id === selected)
      ? selected
      : list.data.items[0]?.id || "";
    if (next !== selected) {
      setSelected(next);
      setRevealed(false);
      setUpdated(undefined);
    }
  }, [list.data, selected]);
  const grade = (value: Grade) =>
    action.run(async () => {
      const captured = { id: selected, queuePath };
      const result = await api.post<ReviewCard>(
        entityPath("reviews", selected) + "/grade",
        { grade: value },
      );
      if (
        selection.current.id === captured.id &&
        selection.current.queuePath === captured.queuePath
      ) {
        setUpdated(result);
        setFeedback(result);
        setRevealed(false);
      }
      list.refresh();
    });
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>复习</h1>
          <p>先回想，再显示答案，最后记录掌握程度。</p>
        </div>
        <button className="primary" onClick={() => setEditing("new")}>
          新建复习卡
        </button>
      </div>
      <Filters
        value={filters}
        onChange={(value) => {
          setFilters(value);
          select("");
          setEditing(undefined);
        }}
        dateKind="到期日期"
        fields={["project_id", "source", "due", "paused", "dates"]}
      />
      <Notice busy={list.busy} error={list.error} />
      <div className="workbench review-workbench">
        <section className="document-list" aria-label="复习队列">
          {list.data?.items.map((item) => (
            <div
              className={
                "document-row " + (item.id === selected ? "selected" : "")
              }
              key={item.id}
            >
              <button className="row-title" onClick={() => select(item.id)}>
                {item.question}
              </button>
              <p className="meta">
                {item.paused ? "暂停 · " : ""}到期：
                <Timestamp value={item.due_at} />
              </p>
            </div>
          ))}
          {list.data && !list.data.items.length && (
            <Empty>
              当前筛选下没有复习卡。取消「仅到期卡片」查看全部，或新建卡片。
            </Empty>
          )}
        </section>
        <section className="reading-pane" aria-label="复习卡详情">
          <Notice
            busy={detail.busy || action.busy}
            error={detail.error || action.error}
          />
          {card ? (
            <>
              <div className="actions">
                <button onClick={() => setEditing("edit")}>编辑复习卡</button>
                <button
                  disabled={action.busy}
                  onClick={() =>
                    action.run(async () => {
                      const captured = { id: selected, queuePath };
                      const result = await api.patch<ReviewCard>(
                        entityPath("reviews", selected),
                        { paused: !card.paused },
                      );
                      if (
                        selection.current.id === captured.id &&
                        selection.current.queuePath === captured.queuePath
                      )
                        setUpdated(result);
                      list.refresh();
                    })
                  }
                >
                  {card.paused ? "恢复复习" : "暂停复习"}
                </button>
              </div>
              <div className="detail-with-evidence">
                <article className="review-card">
                  <p className="meta">
                    下次复习：
                    <Timestamp value={card.due_at} /> · 已评分{" "}
                    {card.repetitions || 0} 次
                  </p>
                  <h2>{card.question}</h2>
                  {card.paused && (
                    <p className="warning">此卡已暂停，恢复后可以评分。</p>
                  )}
                  {revealed ? (
                    <>
                      <div className="answer">
                        <SafeMarkdown
                          text={card.answer || "此卡尚未填写答案。"}
                        />
                      </div>
                      <div className="grade-actions">
                        {(["again", "hard", "good", "easy"] as Grade[]).map(
                          (value) => (
                            <button
                              key={value}
                              disabled={action.busy || card.paused}
                              onClick={() => grade(value)}
                            >
                              {names[value]}
                            </button>
                          ),
                        )}
                      </div>
                    </>
                  ) : (
                    <button
                      className="primary"
                      onClick={() => setRevealed(true)}
                    >
                      显示答案
                    </button>
                  )}
                  {feedback?.id === card.id && <GradeNotice card={feedback} />}
                  <GradeHistory card={card} />
                </article>
                <EvidenceRail evidence={card.evidence} />
              </div>
            </>
          ) : (
            !list.busy &&
            !detail.busy && (
              <Empty>
                当前没有可复习的卡片。调整筛选或从队列选择一张卡片。
              </Empty>
            )
          )}
          {feedback && feedback.id !== card?.id && (
            <section aria-label="上次评分结果" className="review-feedback">
              <div className="detail-with-evidence">
                <article>
                  <h2>已完成本次复习</h2>
                  <p>{feedback.question}</p>
                  <GradeNotice card={feedback} />
                  <p className="meta">
                    {list.busy
                      ? "评分结果已保存，正在更新复习队列。"
                      : "评分结果仅供查看。此卡当前已离开队列；调整筛选后可再次选择。"}
                  </p>
                  <GradeHistory card={feedback} />
                </article>
                <EvidenceRail evidence={feedback.evidence} />
              </div>
            </section>
          )}
        </section>
      </div>
      {editing && (
        <EntityEditor
          kind="reviews"
          entity={editing === "edit" ? card : undefined}
          onClose={() => setEditing(undefined)}
          onSaved={(id) => {
            setEditing(undefined);
            select(id);
            detail.refresh();
            list.refresh();
          }}
        />
      )}
    </>
  );
}
