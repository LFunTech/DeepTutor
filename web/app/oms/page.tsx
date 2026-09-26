import { notFound } from "next/navigation";

// 云端 OMS 是独立前端；DeepTutor 本地 Web 不承载其正式管理入口。
export default function OmsPage() {
  notFound();
}
