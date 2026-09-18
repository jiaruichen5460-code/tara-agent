import { TraceWorkspace } from "@/components/trace-workspace";

type TracePageProps = {
  searchParams: Promise<{
    trace_id?: string;
    session_id?: string;
  }>;
};

export default async function TracePage({ searchParams }: TracePageProps) {
  const parameters = await searchParams;
  return (
    <TraceWorkspace
      initialTraceId={parameters.trace_id}
      initialSessionId={parameters.session_id}
    />
  );
}
