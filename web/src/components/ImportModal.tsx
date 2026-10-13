import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAction } from "../hooks";
import { Field, Modal, Notice } from "./UI";
type Preview = {
  conversations: number;
  messages: number;
  errors: number;
  non_text_blocks: number;
  warnings: string[];
  items: { title: string; source: string; messages: number }[];
};
type Imported = {
  imported: number;
  updated: number;
  duplicates: number;
  messages: number;
  edited_messages: number;
  duplicate_messages: number;
  errors: number;
  error_details?: unknown[];
};
export function ImportModal({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: () => void;
}) {
  const [file, setFile] = useState<File>();
  const [identity, setIdentity] = useState("");
  const [preview, setPreview] = useState<Preview>();
  const [result, setResult] = useState<Imported>();
  const revision = useRef(0);
  const alive = useRef(true);
  const action = useAction();
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );
  const invalidate = () => {
    revision.current++;
    setPreview(undefined);
    setResult(undefined);
  };
  const inspect = () =>
    action.run(async () => {
      if (!file) return;
      const captured = revision.current;
      const data = await api.upload<Preview>("/import/preview", file, identity);
      if (alive.current && captured === revision.current) setPreview(data);
    });
  const confirm = () =>
    action.run(async () => {
      if (!file || !preview) return;
      const captured = revision.current;
      const data = await api.upload<Imported>("/import", file, identity);
      if (alive.current) {
        if (captured === revision.current) setResult(data);
        onImported();
      }
    });
  return (
    <Modal title="导入对话" onClose={onClose}>
      <p>选择 ChatGPT、Codex 或 Markdown 导出。预览后确认写入本地档案。</p>
      <Field label="对话文件">
        <input
          type="file"
          accept=".json,.jsonl,.md,.markdown,.zip"
          onChange={(e) => {
            invalidate();
            setFile(e.target.files?.[0]);
          }}
          disabled={action.busy}
        />
      </Field>
      <Field label="来源标识">
        <input
          value={identity}
          onChange={(e) => {
            invalidate();
            setIdentity(e.target.value);
          }}
          placeholder="例如：个人账户、工作空间"
          disabled={action.busy}
        />
      </Field>
      <p className="meta">
        相同来源请使用稳定标识，避免与其他账户混淆。更换文件或标识后需重新预览。
      </p>
      <div className="actions">
        <button onClick={inspect} disabled={!file || action.busy}>
          预览文件
        </button>
        <button
          className="primary"
          onClick={confirm}
          disabled={!preview || action.busy || !!result}
        >
          确认导入
        </button>
      </div>
      <Notice error={action.error} busy={action.busy} />
      {preview && (
        <section aria-label="导入预览">
          <h3>预览结果</h3>
          <p>
            对话 {preview.conversations} · 消息 {preview.messages} · 错误{" "}
            {preview.errors} · 非文本内容 {preview.non_text_blocks}
          </p>
          {preview.items.map((item, i) => (
            <div className="document-row" key={i}>
              <strong>{item.title}</strong>
              <p className="meta">
                {item.source} · {item.messages} 条消息
              </p>
            </div>
          ))}
          {preview.warnings.map((warning, i) => (
            <p className="warning" key={i}>
              {warning}
            </p>
          ))}
        </section>
      )}
      {result && (
        <p role="status" className="success">
          新增对话 {result.imported}，更新 {result.updated}，重复{" "}
          {result.duplicates}；新增消息 {result.messages}，编辑{" "}
          {result.edited_messages}，重复消息 {result.duplicate_messages}，错误{" "}
          {result.errors}。
        </p>
      )}
    </Modal>
  );
}
