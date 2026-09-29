"use client";

import { useState } from "react";
import { Button, ConfirmModal, DetailGrid, Notice, Section } from "@deeptutor/admin-ui";
import { tenant } from "./fixtures";

type ActorState = "pending" | "matched" | "different" | "missing" | "mock";

const actorStatus: Record<ActorState, string> = {
  pending: "尚未接收到可用真实订阅事件，学校管理员保持零权（演示）",
  matched: "真实订阅事件 actor 已验签，学校管理员随 Webhook 即时开启（演示）",
  different: "当前登录者不是事件 actor；正式路径仍以 Webhook actor 直接建立首管，不允许人工替换（演示）",
  missing: "事件 actor 缺失或为 system/null，待核对且保持零权（演示）",
  mock: "控制台 mock 仅测试签名 URL，不得登记或开启管理员（演示）",
};

export default function TmsSchoolActivation({ onActivated }: { onActivated: () => void }) {
  const [actorState, setActorState] = useState<ActorState>("pending");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const actorSource = actorState === "mock"
    ? "控制台 mock（不登记身份）"
    : actorState === "missing"
      ? "真实事件缺失有效 actor（待核对）"
      : "合成场景：签名真实 subscription.created.actor.user_id";
  const actorIdentity = actorState === "mock" || actorState === "missing"
    ? "无可开启身份"
    : "本校订阅事件 actor（脱敏演示）";

  return <>
    <Section title="首位管理员 Webhook 开启">
      <DetailGrid rows={[
        { label: "学校", value: tenant.name },
        { label: "来源", value: actorSource },
        { label: "拟开启身份", value: actorIdentity },
        { label: "状态", value: actorStatus[actorState] },
        { label: "授权决策", value: "DeepTutor Enterprise 程序；PG 仅保存事实（演示）" },
      ]}/>
      <label className="form-field" style={{ maxWidth: 340 }}>演示订阅 actor 状态
        <select value={actorState} onChange={event => { setActorState(event.target.value as ActorState); setConfirmOpen(false); }}>
          <option value="pending">真实事件 · 待接收</option>
          <option value="matched">真实事件 · 已验签开启</option>
          <option value="different">真实事件 · 非 actor 登录</option>
          <option value="missing">事件无有效 actor</option>
          <option value="mock">控制台 mock</option>
        </select>
      </label>
      <Notice tone="warn">这里仅演示状态，不能靠切换选项取得真实权限。正式服务接收到真实已验签 subscription.created 后即开启学校与首位管理员；缺 HMAC、非 mock、应用/学校绑定或 actor 时保持零权，后续登录仍按本地 active principal 与授权版本校验。</Notice>
      {actorState === "matched" && <Button onClick={() => setConfirmOpen(true)}>模拟接收订阅 Webhook</Button>}
    </Section>
    {confirmOpen && <ConfirmModal title="确认 Webhook 开启" description={`${tenant.name} · 仅合成演示：真实订阅事件经 DeepTutor Enterprise 验签后立即开启学校与首位管理员；不会写入真实授权。`} onCancel={() => setConfirmOpen(false)} onConfirm={() => { setConfirmOpen(false); onActivated(); }}/ >}
  </>;
}
