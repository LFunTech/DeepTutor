import { notFound } from "next/navigation";
import OmsFormalApp from "../../src/OmsFormalApp";

const RETIRED_SCHOOL_BOOTSTRAP_ROUTES = new Set([
  "tms-bootstrap",
  "tms-bootstrap-requests",
]);

export default async function Page({ params }: { params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params;
  if (slug?.[0] && RETIRED_SCHOOL_BOOTSTRAP_ROUTES.has(slug[0])) notFound();
  return <OmsFormalApp/>;
}
