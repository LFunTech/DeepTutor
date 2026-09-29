import TmsFormalApp from "../../../../src/TmsFormalApp";

export default async function Page({ params }: { params: Promise<{ schoolCode: string }> }) {
  const { schoolCode } = await params;
  return <TmsFormalApp schoolCode={schoolCode}/>;
}
