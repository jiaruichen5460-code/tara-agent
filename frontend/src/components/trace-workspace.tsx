"use client";

import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Database,
  FileJson,
  LoaderCircle,
  RotateCcw,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { getTrace, listTraces } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { DataSource, TraceDetail, TraceSpan, TraceSummary } from "@/lib/types";

type TraceWorkspaceProps = {
  initialTraceId?: string;
  initialSessionId?: string;
};

export function TraceWorkspace({ initialTraceId, initialSessionId }: TraceWorkspaceProps) {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedId, setSelectedId] = useState(initialTraceId);
  const [detail, setDetail] = useState<TraceDetail>();
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(Boolean(initialTraceId));
  const [error, setError] = useState<string>();
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listTraces(initialSessionId, controller.signal)
      .then((response) => {
        setTraces(response.items);
        setError(undefined);
        const nextId = initialTraceId ?? response.items[0]?.id;
        if (nextId) {
          setLoadingDetail(true);
        }
        setSelectedId(nextId);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") {
          return;
        }
        setError(reason instanceof Error ? reason.message : "无法加载链路记录");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoadingList(false);
        }
      });
    return () => controller.abort();
  }, [initialSessionId, initialTraceId, refreshVersion]);

  useEffect(() => {
    if (!selectedId) {
      return;
    }
    const controller = new AbortController();
    getTrace(selectedId, controller.signal)
      .then((response) => {
        setDetail(response);
        setError(undefined);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") {
          return;
        }
        setError(reason instanceof Error ? reason.message : "无法加载链路详情");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoadingDetail(false);
        }
      });
    return () => controller.abort();
  }, [selectedId]);

  function selectTrace(traceId: string) {
    if (traceId === selectedId) {
      return;
    }
    setLoadingDetail(true);
    setError(undefined);
    setSelectedId(traceId);
    const query = new URLSearchParams({ trace_id: traceId });
    if (initialSessionId) {
      query.set("session_id", initialSessionId);
    }
    window.history.replaceState(null, "", `/traces?${query.toString()}`);
  }

  return (
    <div className="trace-shell">
      <aside className="trace-list-panel">
        <Link className="trace-back-link" href="/">
          <ArrowLeft size={15} />返回分析
        </Link>
        <div className="trace-list-heading">
          <div>
            <span className="context-label">OBSERVABILITY</span>
            <h1>链路追溯</h1>
          </div>
          <button
            type="button"
            onClick={() => {
              setLoadingList(true);
              setError(undefined);
              setRefreshVersion((value) => value + 1);
            }}
            aria-label="刷新链路记录"
            title="刷新链路记录"
          >
            <RotateCcw size={15} />
          </button>
        </div>
        {initialSessionId ? (
          <div className="trace-filter">
            当前会话
            <code>{shortId(initialSessionId)}</code>
            <Link href="/traces">清除</Link>
          </div>
        ) : null}
        <div className="trace-list" aria-label="链路记录">
          {loadingList ? <div className="trace-loading"><LoaderCircle className="spin" />正在加载…</div> : null}
          {!loadingList && traces.length === 0 ? (
            <div className="trace-empty">暂无链路记录。完成一次分析后即可在这里查看。</div>
          ) : null}
          {traces.map((trace) => (
            <button
              key={trace.id}
              type="button"
              className={trace.id === selectedId ? "active" : undefined}
              onClick={() => selectTrace(trace.id)}
            >
              <span className={`status-dot ${statusClass(trace.status)}`} aria-hidden="true" />
              <strong>{trace.question ?? "未记录问题"}</strong>
              <small>
                <time dateTime={trace.started_at}>{formatDateTime(trace.started_at)}</time>
                <span>{formatDuration(trace.duration_ms)}</span>
              </small>
            </button>
          ))}
        </div>
      </aside>

      <main className="trace-detail-panel">
        {error ? (
          <div className="trace-page-error"><AlertTriangle size={17} />{error}</div>
        ) : null}
        {loadingDetail ? (
          <div className="trace-detail-loading"><LoaderCircle className="spin" />正在读取链路详情…</div>
        ) : null}
        {!loadingDetail && detail ? <TraceDetailView trace={detail} /> : null}
        {!loadingDetail && !detail && !error ? (
          <div className="trace-detail-empty"><Activity size={28} /><span>选择一条链路查看执行详情</span></div>
        ) : null}
      </main>
    </div>
  );
}

function TraceDetailView({ trace }: { trace: TraceDetail }) {
  return (
    <div className="trace-detail-content">
      <header className="trace-detail-header">
        <div>
          <span className="context-label">TRACE {shortId(trace.id)}</span>
          <h2>{trace.question ?? "未记录问题"}</h2>
        </div>
        <StatusBadge status={trace.status} />
      </header>

      <section className="trace-summary-grid" aria-label="链路摘要">
        <SummaryItem label="开始时间" value={formatDateTime(trace.started_at)} />
        <SummaryItem label="总耗时" value={formatDuration(trace.duration_ms)} />
        <SummaryItem label="模型" value={trace.model_name ?? "未调用"} />
        <SummaryItem label="工作流" value={trace.workflow_name} />
        <SummaryItem label="Marker" value={trace.markers.join("、") || "—"} />
        <SummaryItem label="样本数" value={trace.sample_count?.toLocaleString() ?? "—"} />
        <SummaryItem label="重试次数" value={String(trace.retry_count)} />
        <SummaryItem label="会话 ID" value={shortId(trace.session_id)} mono />
      </section>

      {trace.error_message ? (
        <section className="trace-error-detail">
          <AlertTriangle size={17} />
          <div><strong>{trace.error_code ?? "执行失败"}</strong><span>{trace.error_message}</span></div>
        </section>
      ) : null}

      <section className="trace-section">
        <div className="trace-section-title">
          <Activity size={17} />
          <div><h3>执行时间线</h3><p>{trace.spans.length} 个节点，按实际执行顺序排列</p></div>
        </div>
        <div className="span-timeline">
          {trace.spans.map((span, index) => (
            <SpanCard key={span.id} span={span} index={index} />
          ))}
        </div>
      </section>

      <section className="trace-section trace-context-section">
        <div className="trace-section-title">
          <FileJson size={17} />
          <div><h3>请求与最终输出</h3><p>用于复现和核对本次请求的结构化记录</p></div>
        </div>
        <div className="trace-json-grid">
          <JsonBlock title="请求输入" value={trace.input_data} />
          <JsonBlock title="最终输出" value={trace.output_data} />
        </div>
      </section>
    </div>
  );
}

function SpanCard({ span, index }: { span: TraceSpan; index: number }) {
  const Icon = span.span_kind === "llm" ? Bot : span.span_kind === "tool" ? Wrench : Activity;
  return (
    <details className="span-card" open={index === 0}>
      <summary>
        <span className="span-sequence">{span.sequence_no + 1}</span>
        <Icon size={16} />
        <span className="span-name"><strong>{span.name}</strong><small>{spanKindLabel(span.span_kind)}</small></span>
        <span className="span-duration"><StatusBadge status={span.status} compact />{formatDuration(span.duration_ms)}</span>
        <ChevronDown size={16} />
      </summary>
      <div className="span-body">
        <div className="span-facts">
          {span.model_name ? <Fact label="模型" value={span.model_name} /> : null}
          {span.tool_name ? <Fact label="工具" value={span.tool_name} mono /> : null}
          {span.marker ? <Fact label="Marker" value={span.marker} /> : null}
          {span.sample_count !== null ? <Fact label="样本数" value={span.sample_count.toLocaleString()} /> : null}
          {span.total_tokens !== null ? <Fact label="Token" value={`${span.total_tokens.toLocaleString()}（输入 ${span.input_tokens ?? 0} / 输出 ${span.output_tokens ?? 0}）`} /> : null}
          <Fact label="开始时间" value={formatDateTime(span.started_at)} />
          <Fact label="重试次数" value={String(span.retry_count)} />
        </div>

        {Object.keys(span.filters).length > 0 ? <KeyValues title="筛选条件" value={span.filters} /> : null}
        {span.sample_ids.length > 0 ? (
          <div className="span-samples">
            <strong>实际返回的样本 ID</strong>
            <span>{span.sample_ids.join("、")}</span>
          </div>
        ) : null}
        {span.data_sources.length > 0 ? <SourceFiles sources={span.data_sources} /> : null}
        {span.error_message ? (
          <div className="span-error"><AlertTriangle size={15} />{span.error_message}</div>
        ) : null}
        <div className="trace-json-grid">
          <JsonBlock title="节点输入" value={span.input_data} />
          <JsonBlock title="节点输出" value={span.output_data} />
        </div>
      </div>
    </details>
  );
}

function SummaryItem({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div><span>{label}</span><strong className={mono ? "mono" : undefined}>{value}</strong></div>;
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div><span>{label}</span><strong className={mono ? "mono" : undefined}>{value}</strong></div>;
}

function KeyValues({ title, value }: { title: string; value: Record<string, unknown> }) {
  return (
    <div className="span-key-values">
      <strong>{title}</strong>
      <div>{Object.entries(value).map(([key, item]) => <code key={key}>{key}: {String(item)}</code>)}</div>
    </div>
  );
}

function SourceFiles({ sources }: { sources: DataSource[] }) {
  const filenames = sources
    .map((source) => source.filename)
    .filter((value): value is string => typeof value === "string");
  if (filenames.length === 0) {
    return null;
  }
  return (
    <div className="span-sources">
      <Database size={15} />
      <strong>数据来源</strong>
      {filenames.map((filename) => <code key={filename}>{filename}</code>)}
    </div>
  );
}

function JsonBlock({ title, value }: { title: string; value: Record<string, unknown> | null }) {
  if (!value || Object.keys(value).length === 0) {
    return null;
  }
  return (
    <details className="json-block">
      <summary>{title}<ChevronDown size={14} /></summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

function StatusBadge({ status, compact = false }: { status: string; compact?: boolean }) {
  const Icon = status === "completed" ? CheckCircle2 : status === "failed" ? AlertTriangle : Clock3;
  return (
    <span className={`status-badge ${statusClass(status)}${compact ? " compact" : ""}`}>
      <Icon size={compact ? 12 : 14} />{statusLabel(status)}
    </span>
  );
}

function statusClass(status: string): string {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  return "running";
}

function statusLabel(status: string): string {
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "running") return "执行中";
  return status;
}

function spanKindLabel(kind: string): string {
  if (kind === "llm") return "模型调用";
  if (kind === "tool") return "工具调用";
  return kind;
}

function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}
