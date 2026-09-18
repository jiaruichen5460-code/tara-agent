import { TraceWorkspace } from "@/components/trace-workspace";

type SessionTracesPageProps = {
  params: Promise<{ sessionId: string }>;
};

export default async function SessionTracesPage({ params }: SessionTracesPageProps) {
  const { sessionId } = await params;
  return <TraceWorkspace sessionId={sessionId} />;
}
