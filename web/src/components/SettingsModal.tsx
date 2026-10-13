import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAction, useResource } from "../hooks";
import type { ProviderSettings } from "../types";
import { Field, Modal, Notice } from "./UI";
export function SettingsModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const resource = useResource<ProviderSettings>("/settings");
  const action = useAction();
  const alive = useRef(true);
  const [form, setForm] = useState({
    base_url: "",
    chat_model: "",
    embedding_model: "",
    api_key: "",
  });
  const [saved, setSaved] = useState<ProviderSettings>();
  const [clear, setClear] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );
  useEffect(() => {
    if (resource.data) {
      setSaved(resource.data);
      setForm({
        base_url: resource.data.base_url,
        chat_model: resource.data.chat_model,
        embedding_model: resource.data.embedding_model,
        api_key: "",
      });
    }
  }, [resource.data]);
  const change = (key: keyof typeof form, value: string) => {
    setForm({ ...form, [key]: value });
    setDirty(true);
    setNotice("");
  };
  const save = () =>
    action.run(async () => {
      const body: Record<string, string> = {
        base_url: form.base_url,
        chat_model: form.chat_model,
        embedding_model: form.embedding_model,
      };
      if (clear) body.api_key = "";
      else if (form.api_key) body.api_key = form.api_key;
      const data = await api.post<ProviderSettings>("/settings", body);
      if (alive.current) {
        setSaved(data);
        setForm({ ...form, api_key: "" });
        setClear(false);
        setDirty(false);
        setNotice("设置已保存。连接需重新测试。");
        onSaved();
      }
    });
  const test = () =>
    action.run(async () => {
      const data = await api.post<{ connection_verified: boolean }>(
        "/settings/test",
      );
      if (alive.current) {
        setSaved((s) =>
          s ? { ...s, connection_verified: data.connection_verified } : s,
        );
        setNotice("");
      }
    });
  const reindex = () =>
    action.run(async () => {
      setNotice("正在重新索引，保持窗口打开…");
      const data = await api.post<{
        indexed: number;
        skipped_changed: number;
        status: string;
      }>("/search/reindex");
      if (alive.current)
        setNotice(
          `索引${data.status === "completed" ? "完成" : data.status}：${data.indexed} 项，跳过已变化 ${data.skipped_changed} 项。`,
        );
    });
  return (
    <Modal title="模型设置" onClose={onClose}>
      <p>
        使用兼容 OpenAI 的本地或远程服务。基础导入、检索、编辑和复习无需模型。
      </p>
      <Notice error={resource.error || action.error} busy={resource.busy} />
      {saved && (
        <>
          <p className={saved.model_configured ? "meta" : "warning"}>
            {saved.model_configured ? "模型字段已配置" : "模型尚未配置"} ·{" "}
            <span>
              {saved.connection_verified && !dirty
                ? "连接已验证"
                : "连接未验证"}
            </span>
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
            aria-busy={action.busy}
          >
            <fieldset disabled={action.busy}>
              <Field label="服务 Base URL">
                <input
                  type="url"
                  value={form.base_url}
                  onChange={(e) => change("base_url", e.target.value)}
                  placeholder="http://127.0.0.1:1234/v1"
                  maxLength={2048}
                />
              </Field>
              <p className="meta">
                填入完整 API 路径（通常含 /v1），模型名采用服务实际提供的名称。
              </p>
              <Field label="对话模型">
                <input
                  value={form.chat_model}
                  onChange={(e) => change("chat_model", e.target.value)}
                  maxLength={200}
                />
              </Field>
              <Field label="向量模型（可选）">
                <input
                  value={form.embedding_model}
                  onChange={(e) => change("embedding_model", e.target.value)}
                  maxLength={200}
                />
              </Field>
              <Field label="API 密钥">
                <input
                  type="password"
                  autoComplete="new-password"
                  value={form.api_key}
                  onChange={(e) => change("api_key", e.target.value)}
                  placeholder={
                    saved.has_api_key
                      ? "已保存密钥；留空保留"
                      : "留空使用无密钥服务"
                  }
                  maxLength={4096}
                  disabled={clear}
                />
              </Field>
              <label className="check">
                <input
                  type="checkbox"
                  checked={clear}
                  onChange={(e) => {
                    setClear(e.target.checked);
                    setDirty(true);
                    setNotice("");
                  }}
                />
                清除已保存的密钥
              </label>
              <p className="meta">
                密钥保存在本地服务设置文件，界面只显示是否存在。留空保留已有密钥。
              </p>
              <div className="actions">
                <button className="primary" type="submit">
                  保存设置
                </button>
                <button
                  type="button"
                  onClick={test}
                  disabled={dirty || !saved.model_configured}
                >
                  测试已保存的连接
                </button>
              </div>
              {dirty && (
                <p className="meta">有未保存的更改，请先保存再测试。</p>
              )}
              <hr />
              <h3>语义检索索引</h3>
              <p>
                向量模型可选。修改源资料或模型后，手动重新索引；失败时文字检索仍可用。
              </p>
              <button
                type="button"
                onClick={reindex}
                disabled={dirty || !saved.embedding_model || !saved.base_url}
              >
                重新索引
              </button>
            </fieldset>
          </form>
          <Notice busy={action.busy} />
          {notice && <p role="status">{notice}</p>}
        </>
      )}
    </Modal>
  );
}
