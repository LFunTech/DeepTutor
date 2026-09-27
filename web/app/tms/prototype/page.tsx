import { notFound, redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function TmsPrototypePage() {
  if (process.env.NODE_ENV !== "development") notFound();
  // 本地 Web 的旧演示入口仅在开发态转到独立 TMS 原型；生产仍为 404。
  redirect("http://127.0.0.1:4311/tms/prototype");
}
