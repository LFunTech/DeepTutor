"use client";

import { useState } from "react";
import { Button, Notice } from "@deeptutor/admin-ui";

/** 开发态交互样例：演示值仅存在于本模态框内，不交给页面状态或任何 API。 */
export default function DemoCredentialForm({ label, onSave, onCancel }: {
  label: "API Key" | "API Token";
  onSave: () => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState("");

  const save = () => {
    if (!/^demo-[A-Za-z0-9_-]{4,}$/.test(value)) {
      setError("仅接受 demo- 开头的演示值，请勿输入真实密钥。");
      return;
    }
    setValue("");
    onSave();
  };

  return <div className="side-panel">
    <Notice tone="warn">仅演示凭据配置交互，禁止输入真实密钥。演示值不会发送、保存或用于连接测试；正式 OMS 将由受控后端托管 Secret。</Notice>
    <label className="form-field">{label}
      <input type={visible ? "text" : "password"} value={value} autoComplete="new-password" spellCheck={false} onChange={event => { setValue(event.target.value); setError(""); }} placeholder="demo-..."/>
    </label>
    <div className="inline-list"><Button onClick={() => setVisible(current => !current)}>{visible ? "隐藏演示输入" : "显示演示输入"}</Button></div>
    {error && <Notice tone="bad">{error}</Notice>}
    <div className="form-actions"><Button variant="primary" onClick={save}>保存演示凭据</Button><Button onClick={() => { setValue(""); onCancel(); }}>取消</Button></div>
  </div>;
}
