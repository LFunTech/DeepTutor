import { notFound, redirect } from "next/navigation";

// 生产环境必须按请求返回真正的 404，不能把静态预渲染的 404 页面以 200 发送。
export const dynamic = "force-dynamic";

export default function OmsPrototypePage() {
  if (process.env.NODE_ENV !== "development") notFound();
  // 旧 Token 计费演示退役，开发态进入独立 OMS 前端。
  redirect("http://127.0.0.1:4310/oms/prototype");
}
