import { useEffect, useRef, useState } from "react";
import { query } from "../api";
import { useResource } from "../hooks";
import { useNavigation } from "../navigation";
import type { Filters as FilterValues, Page, SearchHit } from "../types";
import { EvidenceRail } from "../components/Evidence";
import { Filters, names } from "../components/Filters";
import { Empty, Notice, Timestamp } from "../components/UI";
export function Search({
  text,
  refreshToken = 0,
}: {
  text: string;
  refreshToken?: number;
}) {
  const [filters, setFilters] = useState<FilterValues>({ q: text });
  const { go, showEvidence } = useNavigation();
  const result = useResource<{
    items: SearchHit[];
    mode: string;
    warning: { error_kind: string; detail: string } | null;
  }>(filters.q ? query("/search", filters) : null);
  const lastRefresh = useRef(refreshToken);
  useEffect(() => {
    if (lastRefresh.current !== refreshToken) {
      lastRefresh.current = refreshToken;
      result.refresh();
    }
  }, [refreshToken]);
  const open = (hit: SearchHit) => {
    if (hit.entity_type === "message" && hit.evidence[0])
      showEvidence(hit.evidence[0]);
    else {
      const page = (
        {
          conversation: "conversations",
          knowledge: "knowledge",
          memory: "memories",
        } as Record<string, Page>
      )[hit.entity_type];
      if (page) go({ page, id: hit.id });
    }
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>搜索</h1>
          <p>检索原始消息、知识和当前生效的记忆。</p>
        </div>
      </div>
      <Filters
        value={filters}
        onChange={setFilters}
        fields={[
          "semantic",
          "entity_type",
          "type",
          "source",
          "tag",
          "project_id",
          "dates",
        ]}
      />
      <Notice error={result.error} busy={result.busy} />
      {result.data && (
        <>
          <p className="meta">
            {result.data.mode === "hybrid" ? "文字 + 语义混合检索" : "文字检索"}{" "}
            · {result.data.items.length} 项结果
          </p>
          {result.data.warning && (
            <p className="warning" role="status">
              语义检索不可用，已回退文字检索：{result.data.warning.error_kind} ·{" "}
              {result.data.warning.detail}
            </p>
          )}
          {result.data.items.map((hit) => (
            <article
              key={`${hit.entity_type}-${hit.id}`}
              className="search-result"
            >
              <div>
                <button className="row-title" onClick={() => open(hit)}>
                  {hit.title}
                </button>
                <p className="meta">
                  {names[hit.entity_type]} · {hit.source} ·{" "}
                  <Timestamp value={hit.created_at} />
                </p>
                <p className="excerpt">{hit.excerpt}</p>
              </div>
              {hit.evidence.length > 0 && (
                <EvidenceRail evidence={hit.evidence} />
              )}
            </article>
          ))}
          {!result.data.items.length && (
            <Empty>没有匹配资料。可以缩短关键词或清除筛选。</Empty>
          )}
        </>
      )}
      {!filters.q && <Empty>输入文字开始搜索。</Empty>}
    </>
  );
}
