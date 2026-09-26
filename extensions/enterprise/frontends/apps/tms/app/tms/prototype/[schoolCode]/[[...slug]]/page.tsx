import { notFound } from "next/navigation";
import TmsPrototype from "../../../../../src/TmsPrototype";
import { demoSchoolContext, isDemoSchoolRoute } from "../../../../../src/demo-school";

export default async function Page({ params }: { params: Promise<{ schoolCode: string; slug?: string[] }> }) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { schoolCode } = await params;
  const context = demoSchoolContext(process.env);
  if (!isDemoSchoolRoute(schoolCode, context)) notFound();
  return <TmsPrototype schoolCode={context.schoolCode}/>;
}
