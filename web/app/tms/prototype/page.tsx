import { notFound, redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function TmsPrototypePage() {
  if (process.env.NODE_ENV !== "development") notFound();
  redirect("http://127.0.0.1:4311/tms/prototype");
}
