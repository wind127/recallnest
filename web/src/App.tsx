import { useEffect, useRef, useState } from "react";
import { download } from "./api";
import { localZone } from "./dates";
import { useAction, useResource } from "./hooks";
import { Navigation, type Target } from "./navigation";
import type { Evidence, Page, ServiceStatus } from "./types";
import { ImportModal } from "./components/ImportModal";
import { SettingsModal } from "./components/SettingsModal";
import { SourceViewer } from "./components/Evidence";
import { Modal, Notice } from "./components/UI";
import { Overview } from "./pages/Overview";
import { Knowledge } from "./pages/Knowledge";
import { Conversations } from "./pages/Conversations";
import { Projects } from "./pages/Projects";
import { Review } from "./pages/Review";
import { Memories } from "./pages/Memories";
import { Search } from "./pages/Search";
const pages: [Page, string, string][] = [
  ["overview", "概览", "⌂"],
  ["knowledge", "知识", "▤"],
  ["conversations", "对话", "◷"],
  ["projects", "项目", "▱"],
  ["review", "复习", "↺"],
  ["memories", "我的记忆", "♧"],
];
function readRoute(): Target & { search?: string } {
  const [page, id] = location.hash.slice(1).split("/");
  try {
    const decoded = id ? decodeURIComponent(id) : undefined;
    if (page === "search" && decoded)
      return { page: "overview", search: decoded };
    return {
      page: pages.some(([key]) => key === page) ? (page as Page) : "overview",
      id: decoded,
    };
  } catch {
    return { page: "overview" };
  }
}
function Nest() {
  return (
    <svg viewBox="0 0 40 40" width="38" height="38" aria-hidden="true">
      <path
        d="M6 17c5 15 24 17 29 0M4 23c10 11 24 11 32-2M9 28c7 7 15 7 23 0M9 16l22 12M5 20l25 12M31 14L10 28M35 19L13 32"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <ellipse
        cx="20"
        cy="18"
        rx="7"
        ry="4.5"
        fill="#ffffff"
        stroke="currentColor"
        strokeWidth="1.4"
      />
    </svg>
  );
}
export default function App() {
  const [target, setTarget] = useState<Target>(readRoute);
  const [search, setSearch] = useState(() => readRoute().search || "");
  const [queryText, setQueryText] = useState(() => readRoute().search || "");
  const [searchRevision, setSearchRevision] = useState(0);
  const [modal, setModal] = useState<"import" | "settings">();
  const [drawer, setDrawer] = useState(false);
  const [evidence, setEvidence] = useState<Evidence>();
  const [revision, setRevision] = useState(0);
  const main = useRef<HTMLElement>(null);
  const status = useResource<ServiceStatus>("/status");
  const codexMode = status.data?.consolidation_mode === "codex";
  const action = useAction();
  useEffect(() => {
    const update = () => {
      const route = readRoute();
      setTarget(route);
      setQueryText(route.search || "");
      if (route.search) setSearch(route.search);
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  const go = (next: Target) => {
    setTarget(next);
    setQueryText("");
    setDrawer(false);
    location.hash = `${next.page}${next.id ? "/" + encodeURIComponent(next.id) : ""}`;
    requestAnimationFrame(() => main.current?.focus());
  };
  const showEvidence = (value: Evidence) => setEvidence(value);
  const nav = (
    <nav aria-label="主导航">
      {pages.map(([page, label, icon]) => (
        <button
          key={page}
          aria-current={target.page === page && !queryText ? "page" : undefined}
          onClick={() => go({ page })}
        >
          <span aria-hidden="true">{icon}</span>
          {label}
        </button>
      ))}
    </nav>
  );
  const content = queryText ? (
    <Search key={queryText} refreshToken={searchRevision} text={queryText} />
  ) : (
    {
      overview: (
        <Overview onImport={() => setModal("import")} codexMode={codexMode} />
      ),
      knowledge: <Knowledge initialId={target.id} />,
      conversations: (
        <Conversations initialId={target.id} codexMode={codexMode} />
      ),
      projects: <Projects initialId={target.id} />,
      review: <Review initialId={target.id} />,
      memories: <Memories initialId={target.id} />,
    }[target.page]
  );
  return (
    <Navigation value={{ go, showEvidence }}>
      <a
        className="skip-link"
        href="#main-content"
        onClick={(e) => {
          e.preventDefault();
          main.current?.focus();
        }}
      >
        跳到主要内容
      </a>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            <Nest />
            <div>
              <strong>RecallNest</strong>
              <span>对话里的知识，归巢。</span>
            </div>
          </div>
          {nav}
          <div className="sidebar-note">
            <span className="nest-line" />
            <p>
              从问题到知识
              <br />
              从知识回到原文
            </p>
            <p className="meta">本地 SQLite 档案</p>
          </div>
        </aside>
        <div className="app-column">
          <header className="topbar">
            <button
              className="mobile-menu"
              aria-label="打开导航"
              onClick={() => setDrawer(true)}
            >
              ☰
            </button>
            <form
              className="global-search"
              onSubmit={(e) => {
                e.preventDefault();
                if (search.trim()) {
                  setQueryText(search.trim());
                  setSearchRevision((v) => v + 1);
                  location.hash = "search/" + encodeURIComponent(search.trim());
                }
              }}
            >
              <label className="sr-only" htmlFor="global-search">
                全局搜索
              </label>
              <input
                id="global-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索对话与知识…"
                maxLength={2000}
              />
              <button type="submit" disabled={!search.trim()}>
                搜索
              </button>
            </form>
            <div className="topbar-actions">
              <button onClick={() => setModal("import")}>导入对话</button>
              {!codexMode && (
                <button onClick={() => setModal("settings")}>模型设置</button>
              )}
            </div>
          </header>
          <div className="service-state">
            <span
              className={
                codexMode || status.data?.model_configured
                  ? "status-dot configured"
                  : "status-dot"
              }
              aria-hidden="true"
            />
            <span>
              {status.busy
                ? "正在连接本地服务"
                : status.error
                  ? "本地服务不可用"
                  : codexMode
                    ? "Codex 负责整理 · 本地保存与复习 · 无需额外 API Key"
                    : status.data?.model_configured
                      ? "模型字段已配置（连接验证请查看设置）"
                      : "模型尚未配置"}
            </span>
            {status.data && !codexMode && !status.data.model_configured && (
              <button
                className="text-button"
                onClick={() => setModal("settings")}
              >
                设置模型
              </button>
            )}
            <span className="timezone">
              时间显示：{localZone} · 日期筛选：UTC
            </span>
          </div>
          <Notice error={status.error} />
          <main
            id="main-content"
            ref={main}
            tabIndex={-1}
            key={`${target.page}-${target.id || ""}-${revision}`}
            className="workspace"
          >
            {content}
          </main>
          <footer>
            <span>RecallNest · 本地知识工作台</span>
            <div className="actions">
              <button
                disabled={action.busy}
                onClick={() => action.run(() => download("json"))}
              >
                导出 JSON
              </button>
              <button
                disabled={action.busy}
                onClick={() => action.run(() => download("markdown"))}
              >
                导出 Markdown
              </button>
            </div>
            <Notice error={action.error} />
          </footer>
        </div>
      </div>
      {drawer && (
        <Modal title="导航" onClose={() => setDrawer(false)}>
          {nav}
        </Modal>
      )}
      {modal === "import" && (
        <ImportModal
          onClose={() => setModal(undefined)}
          onImported={() => setRevision((v) => v + 1)}
        />
      )}
      {modal === "settings" && (
        <SettingsModal
          onClose={() => setModal(undefined)}
          onSaved={() => status.refresh()}
        />
      )}
      {evidence && (
        <SourceViewer
          evidence={evidence}
          onClose={() => setEvidence(undefined)}
        />
      )}
    </Navigation>
  );
}
