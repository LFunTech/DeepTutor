"use client";

import { useState } from "react";
import { Button, DataTable, FormModal, Notice, StatePanel } from "@deeptutor/admin-ui";
import { members, tenant } from "./fixtures";

type DirectoryScenario = "ready" | "forbidden" | "policy-empty" | "empty" | "token-expired" | "subscription-expired" | "error";

// 仅为原型演练目录响应；真实搜索必须由当前学校、授权码用户令牌和数据策略共同约束。
const sampleAccounts = [
  { id: "account-02", name: "周老师", identity: "教职工", department: "数学教研组", schoolId: tenant.id, memberId: "m-02" },
  { id: "account-05", name: "赵老师", identity: "教职工", department: "语文教研组", schoolId: tenant.id, memberId: null },
  { id: "account-other", name: "外校账号", identity: "教职工", department: "外校", schoolId: "other-school", memberId: null },
];

const unavailable: Partial<Record<DirectoryScenario, { state: "empty" | "error" | "forbidden"; message: string }>> = {
  forbidden: { state: "forbidden", message: "没有账号目录访问权限；这不代表本校没有用户。" },
  "policy-empty": { state: "forbidden", message: "数据策略未开放可见范围；请核对应用和当前用户的数据授权。" },
  empty: { state: "empty", message: "当前关键词没有匹配账号；不代表学校账号总数为零。" },
  "token-expired": { state: "error", message: "用户登录凭证已失效；请重新登录后再查询。" },
  "subscription-expired": { state: "forbidden", message: "学校应用订阅已失效；当前不能读取账号目录。" },
  error: { state: "error", message: "账号目录暂不可用；请稍后重试，不能按空列表处理。" },
};

export default function TmsMemberLookup({ onClose, onOpenMember }: { onClose: () => void; onOpenMember: (memberId: string) => void }) {
  const [scenario, setScenario] = useState<DirectoryScenario>("ready");
  const response = unavailable[scenario];
  const accounts = sampleAccounts.filter(account => account.schoolId === tenant.id && (!account.memberId || members.some(member => member.id === account.memberId && member.status === "正常")));

  return <FormModal title="查找本校账号" onClose={onClose}>
    <Notice>合成账号目录演练，不连接 EduPlus2；搜索结果仅帮助辨认，不能直接授权。正式查询需当前学校的数据策略许可。</Notice>
    <label className="form-field">演示目录响应
      <select aria-label="演示目录响应" value={scenario} onChange={event => setScenario(event.target.value as DirectoryScenario)}>
        <option value="ready">正常</option><option value="forbidden">无目录权限</option><option value="policy-empty">策略无可见范围</option>
        <option value="empty">无匹配结果</option><option value="token-expired">登录凭证过期</option>
        <option value="subscription-expired">订阅失效</option><option value="error">上游故障</option>
      </select>
    </label>
    {response ? <StatePanel state={response.state} message={response.message}/> : <DataTable
      rows={accounts}
      searchLabel="搜索可见账号"
      searchText={row => `${row.name} ${row.identity} ${row.department}`}
      emptyText="当前关键词没有匹配账号；不代表学校账号总数为零。"
      columns={[{ key: "name", label: "姓名", render: row => row.name }, { key: "identity", label: "人员类别", render: row => row.identity }, { key: "department", label: "部门", render: row => row.department }, { key: "binding", label: "基座登记", render: row => row.memberId ? "已本人登录（演示）" : "请本人先登录基座" }]}
      rowActions={row => row.memberId ? [{ label: "查看成员资料", onClick: () => onOpenMember(row.memberId!) }] : []}
    />}
    <div className="form-actions"><Button onClick={onClose}>关闭</Button></div>
  </FormModal>;
}
