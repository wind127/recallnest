import Markdown from "react-markdown";
export function safeURL(value?: string) {
  if (!value || /[\u0000-\u0020\u007f]/.test(value)) return undefined;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
export function SafeMarkdown({ text }: { text: string }) {
  return (
    <div className="prose">
      <Markdown
        urlTransform={safeURL}
        components={{
          img: ({ alt }) => (
            <span className="media-placeholder">
              [图片：{alt || "未命名"}，未加载外部资源]
            </span>
          ),
          a: ({ href, children }) =>
            href ? (
              <a href={safeURL(href)} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
