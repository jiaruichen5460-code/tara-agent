"use client";

import {
  Activity, AlertTriangle, ArrowLeft, Bot, CheckCircle2, ChevronDown,
  Clock3, Database, FileJson, LoaderCircle, RotateCcw, Wrench,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getSessionTrace, listSessionTraces } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { DataSource, TraceDetail, TraceSpan, TraceSummary } from "@/lib/types";

type TraceWorkspaceProps = { sessionId: string; initialTraceId?: string };
type TraceTreeNode = { span: TraceSpan; children: TraceTreeNode[] };
const pollIntervalMs = 1_200;

export function TraceWorkspace({ sessionId, initialTraceId }: TraceWorkspaceProps) {
  const router = useRouter();
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedId, setSelectedId] = useState(initialTraceId);
  const [detail, setDetail] = useState<TraceDetail>();
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(Boolean(initialTraceId));
  const [error, setError] = useState<string>();
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listSessionTraces(sessionId, controller.signal)
      .then((response) => {
        setTraces(response.items);
        setError(undefined);
        const nextId = initialTraceId ?? response.items[0]?.id;
        setSelectedId(nextId);
        if (!initialTraceId && nextId) setLoadingDetail(true);
        if (!initialTraceId && nextId) {
          router.replace(tracePath(sessionId, nextId), { scroll: false });
        }
      })
      .catch((reason: unknown) => {
        if (!isAbortError(reason)) setError(errorMessage(reason, "无法加载链路记录"));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingList(false);
      });
    return () => controller.abort();
  }, [initialTraceId, refreshVersion, router, sessionId]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function loadDetail() {
      try {
        const response = await getSessionTrace(sessionId, selectedId!, controller.signal);
        setDetail(response);
        setTraces((current) => mergeTraceSummary(current, response));
        setError(undefined);
        setLoadingDetail(false);
        if (response.status === "running" && !controller.signal.aborted) {
          timer = setTimeout(loadDetail, pollIntervalMs);
        }
      } catch (reason) {
        if (!isAbortError(reason)) {
          setError(errorMessage(reason, "无法加载链路详情"));
          setLoadingDetail(false);
        }
      }
    }

    void loadDetail();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [refreshVersion, selectedId, sessionId]);

  function selectTrace(traceId: string) {
    if (traceId === selectedId) return;
    setSelectedId(traceId);
    setDetail(undefined);
    setLoadingDetail(true);
    setError(undefined);
    router.replace(tracePath(sessionId, traceId), { scroll: false });
  }

  return (
    <div className="trace-shell">
      <aside className="trace-list-panel">
        <Link className="trace-back-link" href="/"><ArrowLeft size={15} />返回对话</Link>
        <div className="trace-list-heading">
          <div><span className="context-label">当前会话</span><h1>链路追溯</h1></div>
          <button type="button" onClick={() => { setLoadingList(true); setRefreshVersion((value) => value + 1); }} aria-label="刷新链路记录" title="刷新">
            <RotateCcw size={15} />
          </button>
        </div>
        <div className="trace-session-id">Session <code>{shortId(sessionId)}</code></div>
        <div className="trace-list" aria-label="本会话的链路记录">
          {loadingList ? <div className="trace-loading"><LoaderCircle className="spin" />正在加载…</div> : null}
          {!loadingList && traces.length === 0 ? <div className="trace-empty">当前会话暂无链路记录。</div> : null}
          {traces.map((trace, index) => (
            <button key={trace.id} type="button" className={trace.id === selectedId ? "active" : undefined} onClick={() => selectTrace(trace.id)}>
              <span className={`status-dot ${statusClass(trace.status)}`} aria-hidden="true" />
              <strong>{trace.question ?? `第 ${traces.length - index} 次分析`}</strong>
              <small>
                <time dateTime={trace.started_at}>{formatDateTime(trace.started_at)}</time>
                <span>{trace.status === "running" ? "执行中" : formatDuration(trace.duration_ms)}</span>
              </small>
            </button>
          ))}
        </div>
      </aside>

      <main className="trace-detail-panel">
        {error ? <div className="trace-page-error"><AlertTriangle size={17} />{error}</div> : null}
        {loadingDetail ? <div className="trace-detail-loading"><LoaderCircle className="spin" />正在读取链路详情…</div> : null}
        {!loadingDetail && detail ? <TraceDetailView trace={detail} /> : null}
        {!loadingDetail && !detail && !error ? (
          <div className="trace-detail-empty"><Activity size={28} /><span>选择一条链路查看执行详情</span></div>
        ) : null}
      </main>
    </div>
  );
}

function TraceDetailView({ trace }: { trace: TraceDetail }) {
  const tree = useMemo(() => buildTraceTree(trace.spans), [trace.spans]);
  const [selectedSpanId, setSelectedSpanId] = useState<string>();
  const selectedSpan = trace.spans.find((span) => span.id === selectedSpanId)
    ?? deepestRunningSpan(trace.spans)
    ?? trace.spans[0];

  return (
    <div className="trace-detail-content">
      <header className="trace-detail-header">
        <div><span className="context-label">TRACE {shortId(trace.id)}</span><h2>{trace.question ?? "未记录问题"}</h2></div>
        <div className="trace-live-status">
          {trace.status === "running" ? <span><LoaderCircle className="spin" size={13} />实时更新</span> : null}
          <StatusBadge status={trace.status} />
        </div>
      </header>

      <section className="trace-summary-grid" aria-label="链路摘要">
        <SummaryItem label="开始时间" value={formatDateTime(trace.started_at)} />
        <SummaryItem label="总耗时" value={traceDuration(trace)} />
        <SummaryItem label="模型" value={trace.model_name ?? "未调用"} />
        <SummaryItem label="工作流" value={trace.workflow_name} />
        <SummaryItem label="数据集" value={sourceCountLabel(trace.data_sources)} />
        <SummaryItem label="样本数" value={trace.sample_count?.toLocaleString() ?? "—"} />
        <SummaryItem label="重试次数" value={String(trace.retry_count)} />
        <SummaryItem label="Trace ID" value={shortId(trace.id)} mono />
      </section>

      <AnalysisOverview trace={trace} />

      {trace.error_message ? (
        <section className="trace-error-detail"><AlertTriangle size={17} /><div><strong>{trace.error_code ?? "执行失败"}</strong><span>{trace.error_message}</span></div></section>
      ) : null}

      <section className="trace-section">
        <div className="trace-section-title"><Activity size={17} /><div><h3>执行链路</h3><p>{trace.spans.length} 个节点，按父子关系展示</p></div></div>
        {trace.spans.length > 0 ? (
          <div className="trace-workbench">
            <div className="trace-tree" role="tree" aria-label="执行链路节点">
              {tree.map((node) => <TraceTreeBranch key={node.span.id} node={node} depth={0} selectedSpanId={selectedSpan?.id} onSelect={setSelectedSpanId} />)}
            </div>
            {selectedSpan ? <SpanDetail span={selectedSpan} /> : null}
          </div>
        ) : <div className="trace-empty">执行节点尚未写入。</div>}
      </section>

      <section className="trace-section trace-context-section">
        <div className="trace-section-title"><FileJson size={17} /><div><h3>请求与最终输出</h3><p>用于核对本次分析的完整结构化记录</p></div></div>
        <div className="trace-json-grid"><JsonBlock title="请求输入" value={trace.input_data} /><JsonBlock title="最终输出" value={trace.output_data} /></div>
      </section>
    </div>
  );
}

function AnalysisOverview({ trace }: { trace: TraceDetail }) {
  const toolSpans = trace.spans.filter((span) => span.span_kind === "tool");
  const understandingSpan = trace.spans.find((span) => (
    span.span_kind === "llm"
    && (recordText(span.output_data, "rationale") || recordText(span.output_data, "summary"))
  ));
  const understanding = recordText(understandingSpan?.output_data, "rationale")
    ?? recordText(understandingSpan?.output_data, "summary")
    ?? "尚未完成问题理解";
  const conclusion = recordText(trace.output_data, "answer") ?? "尚未生成结论";
  const sources = [...new Set(
    [...trace.data_sources, ...toolSpans.flatMap((span) => span.data_sources)]
      .map((source) => source.filename)
      .filter((value): value is string => Boolean(value)),
  )];
  const filters = toolSpans.flatMap((span) => (
    Object.entries(span.filters).map(([key, value]) => ({ spanId: span.id, key, value }))
  ));
  const methods = [...new Set(
    toolSpans.map((span) => span.tool_name).filter((name): name is string => Boolean(name)),
  )];

  return (
    <section className="trace-section" aria-label="分析记录">
      <div className="trace-section-title"><Database size={17} /><div><h3>分析记录</h3><p>问题理解、数据条件、分析方法与结论</p></div></div>
      <div className="trace-analysis-overview">
        <div><span>问题理解</span><MarkdownContent content={understanding} /></div>
        <div>
          <span>数据与筛选</span>
          <p>{sources.length > 0 ? sources.join("、") : "尚未读取数据"}</p>
          {filters.length > 0 ? <div className="trace-filter-tags">{filters.map(({ spanId, key, value }) => <code key={`${spanId}-${key}`}>{key}: {String(value)}</code>)}</div> : null}
        </div>
        <div><span>分析方法</span><p>{methods.length > 0 ? methods.map(toolLabel).join("、") : "尚未调用分析工具"}</p></div>
        <div className="trace-conclusion"><span>分析结论</span><MarkdownContent content={conclusion} /></div>
      </div>
    </section>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return <div className="trace-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown></div>;
}

function TraceTreeBranch({ node, depth, selectedSpanId, onSelect }: { node: TraceTreeNode; depth: number; selectedSpanId?: string; onSelect: (spanId: string) => void }) {
  const { span, children } = node;
  const Icon = span.span_kind === "llm" ? Bot : span.span_kind === "tool" ? Wrench : Activity;
  return (
    <div className="trace-tree-branch" role="treeitem" aria-level={depth + 1} aria-selected={span.id === selectedSpanId}>
      <button type="button" className={span.id === selectedSpanId ? "active" : undefined} style={{ marginLeft: `${depth * 18}px` }} onClick={() => onSelect(span.id)}>
        <span className={`trace-node-icon ${statusClass(span.status)}`}><Icon size={14} /></span>
        <span className="trace-node-name"><strong>{span.name}</strong><small>{spanKindLabel(span.span_kind)}</small></span>
        <span className="trace-node-time">{span.status === "running" ? "执行中" : formatDuration(span.duration_ms)}</span>
      </button>
      {children.length > 0 ? <div className="trace-tree-children" role="group">{children.map((child) => <TraceTreeBranch key={child.span.id} node={child} depth={depth + 1} selectedSpanId={selectedSpanId} onSelect={onSelect} />)}</div> : null}
    </div>
  );
}

function SpanDetail({ span }: { span: TraceSpan }) {
  return (
    <article className="trace-node-detail">
      <header><div><span>{spanKindLabel(span.span_kind)}</span><h3>{span.name}</h3></div><StatusBadge status={span.status} compact /></header>
      <div className="span-facts">
        <Fact label="开始时间" value={formatDateTime(span.started_at)} />
        <Fact label="耗时" value={span.status === "running" ? "执行中" : formatDuration(span.duration_ms)} />
        {span.model_name ? <Fact label="模型" value={span.model_name} /> : null}
        {span.tool_name ? <Fact label="工具" value={span.tool_name} mono /> : null}
        {span.total_tokens !== null ? <Fact label="Token" value={`${span.total_tokens.toLocaleString()}  输入 ${span.input_tokens ?? 0}  输出 ${span.output_tokens ?? 0}`} /> : null}
        <Fact label="重试次数" value={String(span.retry_count)} />
      </div>
      {Object.keys(span.filters).length > 0 ? <KeyValues title="筛选条件" value={span.filters} /> : null}
      {span.marker ? <KeyValues title="分析对象" value={{ marker: span.marker }} /> : null}
      {span.sample_count !== null ? <FactBlock label="样本数" value={span.sample_count.toLocaleString()} /> : null}
      {span.sample_ids.length > 0 ? <FactBlock label="样本 ID" value={span.sample_ids.join("、")} /> : null}
      {span.data_sources.length > 0 ? <SourceFiles sources={span.data_sources} /> : null}
      {span.error_message ? <div className="span-error"><AlertTriangle size={15} />{span.error_message}</div> : null}
      <div className="trace-json-grid"><JsonBlock title="节点输入" value={span.input_data} /><JsonBlock title="节点输出" value={span.output_data} /></div>
    </article>
  );
}

function SummaryItem({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div><span>{label}</span><strong className={mono ? "mono" : undefined}>{value}</strong></div>;
}
function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div><span>{label}</span><strong className={mono ? "mono" : undefined}>{value}</strong></div>;
}
function FactBlock({ label, value }: { label: string; value: string }) {
  return <div className="span-fact-block"><strong>{label}</strong><span>{value}</span></div>;
}
function KeyValues({ title, value }: { title: string; value: Record<string, unknown> }) {
  return <div className="span-key-values"><strong>{title}</strong><div>{Object.entries(value).map(([key, item]) => <code key={key}>{key}: {String(item)}</code>)}</div></div>;
}
function SourceFiles({ sources }: { sources: DataSource[] }) {
  const filenames = [...new Set(sources.map((source) => source.filename).filter((value): value is string => Boolean(value)))];
  if (filenames.length === 0) return null;
  return <div className="span-sources"><Database size={15} /><strong>数据来源</strong>{filenames.map((filename) => <code key={filename}>{filename}</code>)}</div>;
}
function JsonBlock({ title, value }: { title: string; value: Record<string, unknown> | null }) {
  if (!value || Object.keys(value).length === 0) return null;
  return <details className="json-block"><summary>{title}<ChevronDown size={14} /></summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}
function StatusBadge({ status, compact = false }: { status: string; compact?: boolean }) {
  const Icon = status === "completed" ? CheckCircle2 : status === "failed" ? AlertTriangle : Clock3;
  return <span className={`status-badge ${statusClass(status)}${compact ? " compact" : ""}`}><Icon size={compact ? 12 : 14} />{statusLabel(status)}</span>;
}

function buildTraceTree(spans: TraceSpan[]): TraceTreeNode[] {
  const nodes = new Map(spans.map((span) => [span.id, { span, children: [] as TraceTreeNode[] }]));
  const roots: TraceTreeNode[] = [];
  for (const span of [...spans].sort((left, right) => left.sequence_no - right.sequence_no)) {
    const node = nodes.get(span.id)!;
    const parent = span.parent_span_id ? nodes.get(span.parent_span_id) : undefined;
    if (parent) parent.children.push(node); else roots.push(node);
  }
  return roots;
}
function deepestRunningSpan(spans: TraceSpan[]): TraceSpan | undefined {
  return [...spans].reverse().find((span) => span.status === "running");
}
function mergeTraceSummary(current: TraceSummary[], detail: TraceDetail): TraceSummary[] {
  if (!current.some((trace) => trace.id === detail.id)) return [detail, ...current];
  return current.map((trace) => trace.id === detail.id ? detail : trace);
}
function tracePath(sessionId: string, traceId: string): string {
  return `/sessions/${encodeURIComponent(sessionId)}/traces/${encodeURIComponent(traceId)}`;
}
function traceDuration(trace: TraceSummary): string {
  if (trace.duration_ms !== null) return formatDuration(trace.duration_ms);
  if (trace.status !== "running") return "—";
  return formatDuration(Math.max(0, Date.now() - new Date(trace.started_at).getTime()));
}
function sourceCountLabel(sources: DataSource[]): string {
  const count = new Set(sources.map((source) => source.filename).filter(Boolean)).size;
  return count > 0 ? `${count} 个文件` : "—";
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
  if (kind === "workflow") return "工作流";
  if (kind === "llm") return "模型调用";
  if (kind === "tool") return "工具调用";
  return kind;
}
function toolLabel(name: string): string {
  const labels: Record<string, string> = {
    find_samples: "筛选样本",
    get_sample_info: "查询样本详情",
    find_taxa: "查询分类群",
    taxon_abundance: "计算分类群丰度",
    diversity_analysis: "分析生物多样性",
    environment_association: "分析丰度与环境的关联",
  };
  return labels[name] ?? name;
}
function recordText(value: Record<string, unknown> | null | undefined, key: string): string | undefined {
  const item = value?.[key];
  return typeof item === "string" && item.trim() ? item : undefined;
}
function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}
function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}
function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}
