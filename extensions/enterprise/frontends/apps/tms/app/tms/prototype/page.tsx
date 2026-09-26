import { notFound, redirect } from "next/navigation";
import { demoSchoolContext } from "../../../src/demo-school";

export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  redirect(`/tms/prototype/${demoSchoolContext(process.env).schoolCode}`);
}
