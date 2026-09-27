"use client";

import { useState } from "react";
import { Button, ConfirmModal, DetailGrid, Notice, Section } from "@deeptutor/admin-ui";
import { tenant } from "./fixtures";

type ActorState = "pending" | "matched" | "different" | "missing" | "mock";

const actorStatus: Record<ActorState, string> = {
  pending: "真实订阅事件 actor 已登记，等待本人登录匹配（演示）",
  matched: "真实订阅事件 actor 与本人登录身份、当前学校均匹配（演示）",
  different: "登录身份与订阅事件 actor 不同，不可激活（演示）",
  missing: "事件 actor 缺失或为 system/null，待核对且保持零权（演示）",
  mock: "控制台 mock 仅测试签名 URL，不得登记或激活管理员（演示）",
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
    ? "无可激活身份"
    : "本校事件 actor 本人（脱敏演示）";

  return <>
    <Section title="首位管理员身份引导">
      <DetailGrid rows={[
        { label: "学校", value: tenant.name },
        { label: "来源", value: actorSource },
        { label: "拟激活身份", value: actorIdentity },
        { label: "状态", value: actorStatus[actorState] },
        { label: "授权决策", value: "DeepTutor Enterprise 程序；PG 仅保存事实（演示）" },
      ]}/>
      <label className="form-field" style={{ maxWidth: 340 }}>演示订阅 actor 状态
        <select value={actorState} onChange={event => { setActorState(event.target.value as ActorState); setConfirmOpen(false); }}>
          <option value="pending">真实事件 · 待本人登录</option>
          <option value="matched">真实事件 · 本人已匹配</option>
          <option value="different">真实事件 · 其他人登录</option>
          <option value="missing">事件无有效 actor</option>
          <option value="mock">控制台 mock</option>
        </select>
      </label>
      <Notice tone="warn">这里仅演示状态，不能靠切换选项取得真实权限。正式服务须核验 HMAC、非 mock、应用/学校绑定、一次性事件栅栏及本人 OIDC 身份；缺任一条件保持零权。</Notice>
      {actorState === "matched" && <Button onClick={() => setConfirmOpen(true)}>模拟本人登录匹配</Button>}
    </Section>
    {confirmOpen && <ConfirmModal title="确认本人激活" description={`${tenant.name} · 仅合成演示：事件 actor 与本人 OIDC 身份匹配后，由 DeepTutor Enterprise 授权服务激活一次性学校管理员；不会写入真实授权。`} onCancel={() => setConfirmOpen(false)} onConfirm={() => { setConfirmOpen(false); onActivated(); }}/ >}
  </>;
}
