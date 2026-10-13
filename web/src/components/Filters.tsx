import { useResource } from "../hooks";
import type { Filters as FilterValues, Project } from "../types";
import { Field } from "./UI";
export function ProjectSelect({
  value,
  onChange,
  label = "项目",
  all = false,
}: {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  all?: boolean;
}) {
  const { data } = useResource<{ items: Project[] }>("/projects");
  return (
    <Field label={label}>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{all ? "全部项目" : "未关联"}</option>
        {data?.items.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
    </Field>
  );
}
export function Filters({
  value,
  onChange,
  fields = [],
  dateKind = "创建日期",
}: {
  value: FilterValues;
  onChange: (value: FilterValues) => void;
  fields?: string[];
  dateKind?: string;
}) {
  const set = (key: string, v: string | boolean) =>
    onChange({ ...value, [key]: v });
  const options: Record<string, [string, string[]]> = {
    entity_type: ["对象", ["conversation", "message", "knowledge", "memory"]],
    category: [
      "类别",
      ["preference", "background", "goal", "state", "constraint"],
    ],
    status: [
      "状态",
      ["candidate", "confirmed", "rejected", "expired", "superseded"],
    ],
    paused: ["暂停状态", ["true", "false"]],
  };
  return (
    <div className="filters">
      <Field label="筛选文字">
        <input
          value={String(value.q || "")}
          onChange={(e) => set("q", e.target.value)}
          placeholder="标题、正文或关键词"
        />
      </Field>
      {fields
        .filter((key) => key !== "dates")
        .map((key) =>
          key === "project_id" ? (
            <ProjectSelect
              all
              key={key}
              value={String(value[key] || "")}
              onChange={(v) => set(key, v)}
            />
          ) : options[key] ? (
            <Field key={key} label={options[key][0]}>
              <select
                value={String(value[key] ?? "")}
                onChange={(e) => set(key, e.target.value)}
              >
                <option value="">全部</option>
                {options[key][1].map((v) => (
                  <option key={v} value={v}>
                    {names[v] || v}
                  </option>
                ))}
              </select>
            </Field>
          ) : key === "favorite" ||
            key === "unresolved" ||
            key === "semantic" ||
            key === "due" ? (
            <label className="check" key={key}>
              <input
                type="checkbox"
                checked={value[key] === true}
                onChange={(e) => set(key, e.target.checked ? true : "")}
              />
              {
                {
                  favorite: "仅收藏",
                  unresolved: "仅待解决",
                  semantic: "语义混合搜索",
                  due: "仅到期卡片",
                }[key]
              }
            </label>
          ) : (
            <Field
              key={key}
              label={
                key === "source" ? "来源" : key === "type" ? "类型" : "标签"
              }
            >
              <input
                value={String(value[key] || "")}
                onChange={(e) => set(key, e.target.value)}
              />
            </Field>
          ),
        )}
      {fields.includes("dates") && (
        <>
          <Field label={`${dateKind}自（UTC）`}>
            <input
              type="date"
              value={String(value.date_from || "")}
              onChange={(e) => set("date_from", e.target.value)}
            />
          </Field>
          <Field label={`${dateKind}至（UTC，含当天）`}>
            <input
              type="date"
              value={String(value.date_to || "")}
              onChange={(e) => set("date_to", e.target.value)}
            />
          </Field>
        </>
      )}
      <button onClick={() => onChange({})}>清除筛选</button>
    </div>
  );
}
export const names: Record<string, string> = {
  note: "笔记",
  summary: "摘要",
  topic: "主题",
  qa: "问答",
  decision: "决策",
  unresolved: "待解决",
  candidate: "待确认",
  confirmed: "已确认",
  rejected: "已拒绝",
  expired: "已过期",
  superseded: "已替代",
  preference: "偏好",
  background: "背景",
  goal: "目标",
  state: "当前状态",
  constraint: "约束",
  active: "进行中",
  paused: "暂停",
  completed: "已完成",
  archived: "归档",
  again: "忘记了",
  hard: "吃力",
  good: "记得",
  easy: "很轻松",
  conversation: "对话",
  message: "消息",
  knowledge: "知识",
  memory: "记忆",
  true: "已暂停",
  false: "未暂停",
};
