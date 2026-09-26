import { notFound } from "next/navigation";
import OmsPrototype from "../../../../src/OmsPrototype";

export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <OmsPrototype/>;
}
