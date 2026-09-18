import { TraceWorkspace } from "@/components/trace-workspace";

type TraceDetailPageProps = {
  params: Promise<{ sessionId: string; traceId: string }>;
};

export default async function TraceDetailPage({ params }: TraceDetailPageProps) {
  const { sessionId, traceId } = await params;
  return <TraceWorkspace sessionId={sessionId} initialTraceId={traceId} />;
}
