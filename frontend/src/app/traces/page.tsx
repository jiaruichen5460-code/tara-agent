import { redirect } from "next/navigation";

import { LegacyTraceRedirect } from "@/components/legacy-trace-redirect";

type TracePageProps = {
  searchParams: Promise<{
    trace_id?: string;
    session_id?: string;
  }>;
};

export default async function TracePage({ searchParams }: TracePageProps) {
  const parameters = await searchParams;
  if (parameters.session_id) {
    const base = `/sessions/${encodeURIComponent(parameters.session_id)}/traces`;
    redirect(parameters.trace_id ? `${base}/${encodeURIComponent(parameters.trace_id)}` : base);
  }
  if (parameters.trace_id) return <LegacyTraceRedirect traceId={parameters.trace_id} />;
  redirect("/");
}
