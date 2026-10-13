import { useEffect, useRef, useState } from "react";
import { api, entityPath } from "../api";
import { localZone, toLocalInput, toUTC } from "../dates";
import { useAction, useResource } from "../hooks";
import { evidenceInput } from "../evidence";
import type {
  Evidence,
  EvidenceInput,
  Knowledge,
  Memory,
  Project,
  ReviewCard,
} from "../types";
import { EvidenceEditor } from "./Evidence";
import { names, ProjectSelect } from "./Filters";
import { Field, Modal, Notice } from "./UI";
import { safeURL } from "./SafeMarkdown";
type Editable = Knowledge | Memory | ReviewCard | Project;
type Values = Record<string, string | boolean>;
const stringList = (value: unknown) =>
  Array.isArray(value) ? value.join("\n") : "";
export function EntityEditor({
  kind: requestedKind,
  entity: requestedEntity,
  onClose,
  onSaved,
}: {
  kind: "knowledge" | "memories" | "reviews" | "projects";
  entity?: Editable;
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  // The draft and mutation target are one immutable editing session. Loading
  // or replacing the surrounding detail must never retarget or create it.
  const [snapshot] = useState(() => ({
    kind: requestedKind,
    entity: requestedEntity ? structuredClone(requestedEntity) : undefined,
  }));
  const { kind, entity } = snapshot;
  const currentTarget = useRef({
    kind: requestedKind,
    id: requestedEntity?.id,
  });
  currentTarget.current = { kind: requestedKind, id: requestedEntity?.id };
  const dirtyDates = useRef(new Set<string>());
  const alive = useRef(true);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );
  const initial = entity as unknown as Record<string, unknown> | undefined;
  const keys = [
    "title",
    "summary",
    "body",
    "type",
    "content",
    "category",
    "subject",
    "status",
    "question",
    "answer",
    "name",
    "description",
    "project_id",
    "knowledge_id",
    "supersedes",
  ];
  const [values, setValues] = useState<Values>(() =>
    Object.fromEntries([
      ...keys.map((key) => [
        key,
        String(
          initial?.[key] ??
            (
              {
                type: "note",
                category: "preference",
                status: kind === "projects" ? "active" : "candidate",
              } as Record<string, string>
            )[key] ??
            "",
        ),
      ]),
      ["tags", Array.isArray(initial?.tags) ? initial.tags.join(", ") : ""],
      ["goals", stringList(initial?.goals)],
      [
        "artifact_links",
        Array.isArray(initial?.artifact_links)
          ? initial.artifact_links
              .map((link) => `${link.title} | ${link.url}`)
              .join("\n")
          : "",
      ],
      ["effective_at", toLocalInput(initial?.effective_at as string)],
      ["expires_at", toLocalInput(initial?.expires_at as string)],
      ["due_at", toLocalInput(initial?.due_at as string)],
      ["favorite", !!initial?.favorite],
      ["unresolved", !!initial?.unresolved],
      ["paused", !!initial?.paused],
    ]),
  );
  const [evidence, setEvidence] = useState<EvidenceInput[]>(
    ((initial?.evidence as Evidence[]) || []).map(evidenceInput),
  );
  const action = useAction();
  const knowledge = useResource<{ items: Knowledge[] }>(
    kind === "reviews" ? "/knowledge" : null,
  );
  const memories = useResource<{ items: Memory[] }>(
    kind === "memories" ? "/memories" : null,
  );
  const set = (key: string, value: string | boolean) =>
    setValues((v) => ({ ...v, [key]: value }));
  const text = (
    key: string,
    label: string,
    required = false,
    multiline = false,
    maxLength?: number,
  ) => (
    <Field label={label}>
      {multiline ? (
        <textarea
          value={String(values[key])}
          onChange={(e) => set(key, e.target.value)}
          required={required}
          rows={key === "body" ? 9 : 4}
          maxLength={maxLength}
        />
      ) : (
        <input
          value={String(values[key])}
          onChange={(e) => set(key, e.target.value)}
          required={required}
          maxLength={maxLength}
        />
      )}
    </Field>
  );
  const select = (key: string, label: string, choices: string[]) => (
    <Field label={label}>
      <select
        value={String(values[key])}
        onChange={(e) => set(key, e.target.value)}
      >
        {choices.map((choice) => (
          <option key={choice} value={choice}>
            {names[choice] || choice}
          </option>
        ))}
      </select>
    </Field>
  );
  const check = (key: string, label: string) => (
    <label className="check">
      <input
        type="checkbox"
        checked={!!values[key]}
        onChange={(e) => set(key, e.target.checked)}
      />
      {label}
    </label>
  );
  const date = (key: string, label: string) => (
    <Field label={`${label}（${localZone}）`}>
      <input
        type="datetime-local"
        value={String(values[key])}
        onChange={(e) => {
          dirtyDates.current.add(key);
          set(key, e.target.value);
        }}
      />
    </Field>
  );
  // PATCH omits untouched dates, retaining the server's exact raw timestamp
  // (including microseconds) or null. Only deliberate edits/clears convert.
  const dateFields = (keys: string[]) =>
    Object.fromEntries(
      keys
        .filter((key) => !entity || dirtyDates.current.has(key))
        .map((key) => [key, toUTC(String(values[key]))]),
    );
  const save = () =>
    action.run(async () => {
      const proof = evidence.map(evidenceInput);
      let body: Record<string, unknown>;
      if (kind === "projects") {
        const links = String(values.artifact_links)
          .split("\n")
          .filter((line) => line.trim())
          .map((line) => {
            const separator = line.indexOf("|");
            const title = separator >= 0 ? line.slice(0, separator).trim() : "";
            const url = (
              separator >= 0 ? line.slice(separator + 1) : line
            ).trim();
            if (!safeURL(url))
              throw new Error("项目链接需使用完整 HTTP 或 HTTPS URL。");
            return { title, url };
          });
        body = {
          name: values.name,
          description: values.description,
          status: values.status,
          goals: String(values.goals)
            .split("\n")
            .filter((v) => v.trim()),
          artifact_links: links,
        };
      } else if (kind === "knowledge")
        body = {
          title: values.title,
          summary: values.summary,
          body: values.body,
          type: values.type,
          tags: String(values.tags)
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean),
          favorite: values.favorite,
          unresolved: values.unresolved,
          project_id: values.project_id || null,
          evidence: proof,
        };
      else if (kind === "memories")
        body = {
          content: values.content,
          category: values.category,
          subject: values.subject,
          status: values.status,
          supersedes: values.supersedes || null,
          ...dateFields(["effective_at", "expires_at"]),
          evidence: proof,
        };
      else {
        body = {
          question: values.question,
          answer: values.answer,
          knowledge_id: values.knowledge_id || null,
          project_id: values.project_id || null,
          paused: values.paused,
          ...dateFields(["due_at"]),
        };
        if (entity || proof.length) body.evidence = proof;
        if (!entity && !values.project_id && values.knowledge_id)
          delete body.project_id;
      }
      const result = entity
        ? await api.patch<{ id: string }>(entityPath(kind, entity.id), body)
        : await api.post<{ id: string }>(`/${kind}`, body);
      if (
        alive.current &&
        currentTarget.current.kind === kind &&
        currentTarget.current.id === entity?.id
      )
        onSaved(result.id);
    });
  const label = {
    knowledge: "知识",
    memories: "记忆",
    reviews: "复习卡",
    projects: "项目",
  }[kind];
  return (
    <Modal title={`${entity ? "编辑" : "新建"}${label}`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
        aria-busy={action.busy}
      >
        <fieldset disabled={action.busy}>
          {kind === "knowledge" && (
            <>
              {text("title", "知识标题", true)}
              {text("summary", "摘要", false, true)}
              {text("body", "正文（支持 Markdown）", false, true)}
              {text("type", "知识类型", true)}
              {text("tags", "标签（英文逗号分隔）")}
              {check("favorite", "收藏")}
              {check("unresolved", "待解决")}
            </>
          )}
          {kind === "memories" && (
            <>
              {text("content", "记忆内容", true, true)}
              {select("category", "记忆类别", [
                "preference",
                "background",
                "goal",
                "state",
                "constraint",
              ])}
              {text("subject", "主题")}
              {select("status", "记忆状态", [
                "candidate",
                "confirmed",
                "rejected",
                "expired",
                "superseded",
              ])}
              {date("effective_at", "生效时间")}
              {date("expires_at", "过期时间")}
              <Field label="替代的旧记忆">
                <select
                  value={String(values.supersedes)}
                  onChange={(e) => set("supersedes", e.target.value)}
                >
                  <option value="">不替代</option>
                  {memories.data?.items
                    .filter(
                      (m) =>
                        m.id !== entity?.id &&
                        m.category === values.category &&
                        m.subject === values.subject,
                    )
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.content}（{names[m.status]}）
                      </option>
                    ))}
                </select>
              </Field>
              <p className="meta">
                替代候选确认后旧记忆才会转为已替代。未来生效的替代请保持待确认。
              </p>
            </>
          )}
          {kind === "reviews" && (
            <>
              {text("question", "问题", true, true)}
              {text("answer", "答案", false, true)}
              <Field label="关联知识">
                <select
                  value={String(values.knowledge_id)}
                  onChange={(e) => set("knowledge_id", e.target.value)}
                >
                  <option value="">独立卡片</option>
                  {knowledge.data?.items.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.title}
                    </option>
                  ))}
                </select>
              </Field>
              {date("due_at", "下次复习时间")}
              {entity && (
                <p className="meta">
                  编辑时留空保留原复习时间；如需提前，请选择新时间。
                </p>
              )}
              {check("paused", "暂停复习")}
            </>
          )}
          {kind === "projects" && (
            <>
              {text("name", "项目名称", true)}
              {text("description", "项目描述", false, true)}
              {select("status", "项目状态", [
                "active",
                "paused",
                "completed",
                "archived",
              ])}
              {text("goals", "目标（每行一项）", false, true)}
              {text(
                "artifact_links",
                "成果链接（每行：标题 | https://…）",
                false,
                true,
              )}
            </>
          )}
          {["knowledge", "reviews"].includes(kind) && (
            <ProjectSelect
              label="关联项目"
              value={String(values.project_id)}
              onChange={(v) => set("project_id", v)}
            />
          )}
          {kind !== "projects" && (
            <EvidenceEditor
              value={evidence}
              onChange={(proofs) => setEvidence(proofs.map(evidenceInput))}
            />
          )}
          <div className="actions">
            <button className="primary" type="submit">
              保存{label}
            </button>
            <button type="button" onClick={onClose}>
              取消
            </button>
          </div>
        </fieldset>
        <Notice error={action.error} busy={action.busy} />
      </form>
    </Modal>
  );
}
