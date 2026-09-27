import { notFound } from "next/navigation";
import OmsPrototype from "../../../../src/OmsPrototype";

export default async function Page({ params }: { params: Promise<{ slug?: string[] }> }) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { slug } = await params;
  if (slug?.[0] === "tms-bootstrap") notFound();
  return <OmsPrototype/>;
}
