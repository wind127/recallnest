import { useEffect, useId, useRef, type ReactNode } from "react";
import { dateLabel, localZone } from "../dates";
export function Notice({ error, busy }: { error?: string; busy?: boolean }) {
  return (
    <>
      {busy && <p role="status">正在加载…</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const element = ref.current!;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const items = () =>
      Array.from(
        element.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex="0"]',
        ),
      ).filter(
        (el) =>
          !el.hidden &&
          (!el.closest("details:not([open])") || el.tagName === "SUMMARY"),
      );
    (items()[0] || element).focus();
    const trap = (e: KeyboardEvent) => {
      if (Array.from(document.querySelectorAll(".modal")).at(-1) !== element)
        return;
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close.current();
      }
      if (e.key === "Tab") {
        const choices = items();
        const first = choices[0];
        const last = choices.at(-1);
        if (!first) {
          e.preventDefault();
          element.focus();
        } else if (
          e.shiftKey &&
          (document.activeElement === first ||
            !element.contains(document.activeElement))
        ) {
          e.preventDefault();
          last?.focus();
        } else if (
          !e.shiftKey &&
          (document.activeElement === last ||
            !element.contains(document.activeElement))
        ) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", trap, true);
    return () => {
      document.removeEventListener("keydown", trap, true);
      document.body.style.overflow = oldOverflow;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <div className="modal-backdrop">
      <div
        className="modal"
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="modal-heading">
          <h2 id={titleId}>{title}</h2>
          <button onClick={onClose} aria-label={`关闭${title}`}>
            关闭
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
export function History({ history }: { history?: unknown[] }) {
  return history?.length ? (
    <details className="history">
      <summary>查看历史（{history.length}）</summary>
      {history.map((entry, i) => (
        <pre key={i}>{JSON.stringify(entry, null, 2)}</pre>
      ))}
    </details>
  ) : (
    <p className="meta">暂无修改历史</p>
  );
}
export function Timestamp({ value }: { value?: string | null }) {
  return (
    <time dateTime={value || undefined} title={localZone}>
      {dateLabel(value)}
    </time>
  );
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
