"use client";

import {
  AlertTriangle,
  ArrowUp,
  BrainCircuit,
  Braces,
  ChevronDown,
  Database,
  FlaskConical,
  LoaderCircle,
  Map,
  Network,
} from "lucide-react";
import dynamic from "next/dynamic";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { ResultTable } from "@/components/result-table";
import { SystemStatus } from "@/components/system-status";
import type { AgentResponse, AgentStep, AgentStreamEvent } from "@/lib/types";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const AnalysisChart = dynamic(
  () => import("@/components/analysis-chart").then((module) => module.AnalysisChart),
  { ssr: false, loading: () => <div className="analysis-chart chart-loading">正在加载图表…</div> },
);

const examples = [
  { label: "样本与环境", question: "找地中海表层且温度至少 20 度的样本", icon: Map },
  { label: "分类群", question: "V4 中有哪些 Bacillariophyta ASV？", icon: Braces },
  { label: "多样性", question: "按极地分组比较 V9 的 Shannon 多样性", icon: Database },
  { label: "环境关联", question: "V4 Bacillariophyta 丰度和温度是否相关？", icon: FlaskConical },
];

type Run = {
  id: string;
  question: string;
  steps: AgentStep[];
  streamedReasoning: string;
  streamedAnswer: string;
  response?: AgentResponse;
  error?: string;
};

export function ChatWorkspace() {
  const [question, setQuestion] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);
  const followOutput = useRef(true);
  const canSubmit = question.trim().length > 0 && !busy;

  useEffect(() => {
    function updateFollowPreference() {
      const remaining = document.documentElement.scrollHeight - window.scrollY - window.innerHeight;
      followOutput.current = remaining < 180;
    }

    window.addEventListener("scroll", updateFollowPreference, { passive: true });
    return () => window.removeEventListener("scroll", updateFollowPreference);
  }, []);

  useEffect(() => {
    if (!followOutput.current) {
      return;
    }
    const frame = requestAnimationFrame(() => {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "auto" });
    });
    return () => cancelAnimationFrame(frame);
  }, [runs]);

  async function submit(nextQuestion: string) {
    const normalized = nextQuestion.trim();
    if (!normalized || busy) {
      return;
    }
    const id = crypto.randomUUID();
    followOutput.current = true;
    setRuns((current) => [
      ...current,
      { id, question: normalized, steps: [], streamedReasoning: "", streamedAnswer: "" },
    ]);
    setQuestion("");
    setBusy(true);

    let pendingDelta = "";
    let pendingEvent: "reasoning_delta" | "answer_delta" | null = null;
    let animationFrame: number | null = null;

    const applyToRun = (event: AgentStreamEvent) => {
      setRuns((current) =>
        current.map((run) => (run.id === id ? applyEvent(run, event) : run)),
      );
    };

    const flushDelta = () => {
      animationFrame = null;
      if (!pendingDelta || !pendingEvent) {
        return;
      }
      const delta = pendingDelta;
      const event = pendingEvent;
      pendingDelta = "";
      pendingEvent = null;
      applyToRun({ event, delta });
    };

    const handleEvent = (event: AgentStreamEvent) => {
      if (
        (event.event === "reasoning_delta" || event.event === "answer_delta") &&
        event.delta
      ) {
        if (pendingEvent !== null && pendingEvent !== event.event) {
          if (animationFrame !== null) {
            cancelAnimationFrame(animationFrame);
          }
          flushDelta();
        }
        pendingEvent = event.event;
        pendingDelta += event.delta;
        if (animationFrame === null) {
          animationFrame = requestAnimationFrame(flushDelta);
        }
        return;
      }

      if (animationFrame !== null) {
        cancelAnimationFrame(animationFrame);
      }
      flushDelta();
      applyToRun(event);
    };

    try {
      await streamQuestion(normalized, handleEvent);
    } catch (error) {
      const message = error instanceof Error ? error.message : "请求失败";
      setRuns((current) =>
        current.map((run) => (run.id === id ? { ...run, error: message } : run)),
      );
    } finally {
      if (animationFrame !== null) {
        cancelAnimationFrame(animationFrame);
      }
      flushDelta();
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit(question);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true"><Network size={20} /></div>
          <div>
            <strong>Tara-Agent</strong>
            <span>Oceans analysis MVP</span>
          </div>
        </div>

        <nav className="example-nav" aria-label="示例问题">
          <p className="sidebar-label">示例问题</p>
          {examples.map((example) => {
            const Icon = example.icon;
            return (
              <button key={example.label} type="button" onClick={() => void submit(example.question)} disabled={busy}>
                <Icon size={16} aria-hidden="true" />
                <span>{example.question}</span>
              </button>
            );
          })}
        </nav>

        <SystemStatus />
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <span className="context-label">研究工作台</span>
            <h1>Tara Oceans 数据分析</h1>
          </div>
          <div className="marker-note"><span />18S V4 / V9 分开分析</div>
        </header>

        <div className="conversation" aria-live="polite">
          {runs.length === 0 ? <EmptyState onExample={submit} /> : null}
          {runs.map((run) => <AnalysisRun key={run.id} run={run} />)}
        </div>

        <div className="composer-wrap">
          <form className="composer" onSubmit={onSubmit}>
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  if (canSubmit) {
                    void submit(question);
                  }
                }
              }}
              maxLength={2000}
              rows={2}
              placeholder="询问样本、分类群、丰度、多样性或环境关联…"
              aria-label="输入 Tara 数据问题"
            />
            <button className="send-button" type="submit" disabled={!canSubmit}>
              {busy ? <LoaderCircle className="spin" size={18} /> : <ArrowUp size={18} />}
              <span>{busy ? "分析中" : "发送"}</span>
            </button>
          </form>
          <p>结果来自确定性分析工具；模型不读取原始数据，也不执行任意代码或 SQL。</p>
        </div>
      </main>
    </div>
  );
}

function EmptyState({ onExample }: { onExample: (question: string) => Promise<void> }) {
  return (
    <section className="empty-state">
      <div className="empty-icon"><Database size={26} aria-hidden="true" /></div>
      <p className="context-label">TARA OCEANS · 可追溯分析</p>
      <h2>从一个海洋数据问题开始</h2>
      <p>查询样本和分类群，探索丰度、多样性及环境关联。分析过程与数据来源会随结果展示。</p>
      <div className="example-grid" aria-label="选择一个示例问题">
        {examples.map((example) => {
          const Icon = example.icon;
          return (
            <button key={example.label} type="button" onClick={() => void onExample(example.question)}>
              <span className="example-card-label"><Icon size={16} aria-hidden="true" />{example.label}</span>
              <span className="example-card-question">{example.question}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function AnalysisRun({ run }: { run: Run }) {
  const inProgress = !run.response && !run.error;
  const reasoningActive = inProgress && !run.streamedAnswer;

  return (
    <article className="analysis-run">
      <div className="user-message">{run.question}</div>
      <div className="agent-response">
        <div className="agent-avatar" aria-hidden="true"><Network size={17} /></div>
        <div className="response-content">
          {inProgress ? (
            <RunningSteps
              steps={run.steps}
              hasReasoning={Boolean(run.streamedReasoning)}
              hasAnswer={Boolean(run.streamedAnswer)}
            />
          ) : null}
          {run.streamedReasoning ? (
            <ReasoningPanel reasoning={run.streamedReasoning} active={reasoningActive} />
          ) : null}
          {inProgress && run.streamedAnswer ? (
            <StreamingAnswer answer={run.streamedAnswer} />
          ) : null}
          {run.error ? (
            <>
              {run.streamedAnswer ? <MarkdownAnswer answer={run.streamedAnswer} /> : null}
              <div className="request-error"><AlertTriangle size={17} />{run.error}</div>
            </>
          ) : null}
          {run.response ? <CompletedResponse response={run.response} /> : null}
        </div>
      </div>
    </article>
  );
}

type RunningStepsProps = {
  steps: AgentStep[];
  hasReasoning: boolean;
  hasAnswer: boolean;
};

function RunningSteps({ steps, hasReasoning, hasAnswer }: RunningStepsProps) {
  const isPreparingAnswer = steps.some((step) => step.stage === "answer");
  let status = "正在执行分析流程";
  if (isPreparingAnswer) {
    status = "正在准备回答";
  }
  if (hasReasoning) {
    status = "正在思考";
  }
  if (hasAnswer) {
    status = "正在生成回答";
  }

  return (
    <div className={`running-steps${isPreparingAnswer ? " answering" : ""}`}>
      <p>
        <LoaderCircle className="spin" size={16} />
        {status}
      </p>
      <ol>
        {steps.map((step) => <li key={step.stage}><strong>{step.title}</strong><span>{step.detail}</span></li>)}
      </ol>
    </div>
  );
}

function ReasoningPanel({ reasoning, active }: { reasoning: string; active: boolean }) {
  const [open, setOpen] = useState(active);
  const previousActive = useRef(active);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (previousActive.current !== active) {
      setOpen(active);
      previousActive.current = active;
    }
  }, [active]);

  useEffect(() => {
    if (!active || !open) {
      return;
    }
    const content = contentRef.current;
    content?.scrollTo({ top: content.scrollHeight, behavior: "auto" });
  }, [active, open, reasoning]);

  return (
    <details
      className={`reasoning-panel${active ? " active" : ""}`}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <BrainCircuit size={16} />
        <span>{active ? "正在思考" : "模型思考"}</span>
        <ChevronDown size={16} />
      </summary>
      <div ref={contentRef} className="reasoning-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{reasoning}</ReactMarkdown>
      </div>
    </details>
  );
}

function StreamingAnswer({ answer }: { answer: string }) {
  return (
    <div className="streaming-answer">
      <MarkdownAnswer answer={answer} />
      <span className="stream-caret" aria-hidden="true" />
    </div>
  );
}

function MarkdownAnswer({ answer }: { answer: string }) {
  return (
    <div className="answer-text">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown>
    </div>
  );
}

function CompletedResponse({ response }: { response: AgentResponse }) {
  const serializedArguments = useMemo(
    () => JSON.stringify(response.tool.arguments, null, 2),
    [response.tool.arguments],
  );

  return (
    <>
      <MarkdownAnswer answer={response.answer} />

      <details className="trace-details">
        <summary><Network size={16} />分析轨迹<ChevronDown size={16} /></summary>
        <ol>
          {response.steps.map((step) => (
            <li key={step.stage}><strong>{step.title}</strong><span>{step.detail}</span></li>
          ))}
        </ol>
        <div className="tool-call">
          <span>调用工具</span><code>{response.tool.name}</code>
          <pre>{serializedArguments}</pre>
        </div>
      </details>

      {response.warnings.length > 0 ? (
        <section className="warnings" aria-label="分析警告">
          {response.warnings.map((warning) => (
            <div key={warning.code}><AlertTriangle size={16} /><p><strong>{warning.code}</strong>{warning.message}</p></div>
          ))}
        </section>
      ) : null}

      {response.charts.map((chart) => <AnalysisChart key={`${chart.kind}-${chart.title}`} chart={chart} />)}
      <ResultTable result={response.result} />

      <footer className="provenance">
        <span>模型 {response.model}</span>
        <span>来源 {response.sources.length > 0 ? response.sources.join(" · ") : "未声明"}</span>
      </footer>
    </>
  );
}

function applyEvent(run: Run, event: AgentStreamEvent): Run {
  if (event.event === "step" && event.step) {
    return { ...run, steps: [...run.steps, event.step] };
  }
  if (event.event === "answer_delta" && event.delta) {
    return { ...run, streamedAnswer: run.streamedAnswer + event.delta };
  }
  if (event.event === "reasoning_delta" && event.delta) {
    return { ...run, streamedReasoning: run.streamedReasoning + event.delta };
  }
  if (event.event === "complete" && event.response) {
    return {
      ...run,
      response: event.response,
      steps: event.response.steps,
      streamedReasoning: event.response.reasoning,
      streamedAnswer: event.response.answer,
    };
  }
  if (event.event === "error") {
    return { ...run, error: event.error ?? "分析失败" };
  }
  return run;
}

async function streamQuestion(
  question: string,
  onEvent: (event: AgentStreamEvent) => void,
) {
  const response = await fetch(`${apiBaseUrl}/api/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `请求失败（HTTP ${response.status}）`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminalEventReceived = false;

  function emitBlock(block: string) {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) {
      return;
    }
    const event = JSON.parse(data) as AgentStreamEvent;
    if (event.event === "complete" || event.event === "error") {
      terminalEventReceived = true;
    }
    onEvent(event);
  }

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      emitBlock(block);
    }
    if (done) {
      break;
    }
  }
  if (buffer.trim()) {
    emitBlock(buffer);
  }
  if (!terminalEventReceived) {
    throw new Error("流式响应意外中断，请重试");
  }
}
