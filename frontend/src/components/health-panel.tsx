"use client";

import { useEffect, useState } from "react";

type DatasetStatus = {
  key: string;
  filename: string;
  ready: boolean;
};

type HealthResponse = {
  status: "ok" | "degraded";
  data_ready: boolean;
  datasets: DatasetStatus[];
};

type ViewState =
  | { kind: "loading" }
  | { kind: "ready"; health: HealthResponse }
  | { kind: "error"; message: string };

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function HealthPanel() {
  const [state, setState] = useState<ViewState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    async function loadHealth() {
      try {
        const response = await fetch(`${apiBaseUrl}/api/v1/health`, {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const health = (await response.json()) as HealthResponse;
        setState({ kind: "ready", health });
      } catch (error) {
        if (!controller.signal.aborted) {
          const message = error instanceof Error ? error.message : "未知错误";
          setState({ kind: "error", message });
        }
      }
    }

    void loadHealth();
    return () => controller.abort();
  }, []);

  const isReady = state.kind === "ready" && state.health.data_ready;
  const statusClass = state.kind === "error" ? "status error" : isReady ? "status ready" : "status";
  const statusText =
    state.kind === "loading"
      ? "正在检查后端"
      : state.kind === "error"
        ? "后端尚未连接"
        : isReady
          ? "数据契约检查通过"
          : "数据契约需要处理";

  return (
    <section className="health-panel" aria-labelledby="health-title">
      <div>
        <p className="eyebrow">System status</p>
        <h2 id="health-title">基础状态</h2>
      </div>
      <div aria-live="polite">
        <p className={statusClass}>{statusText}</p>
        {state.kind === "ready" && (
          <ul className="dataset-list">
            {state.health.datasets.map((dataset) => (
              <li key={dataset.key}>
                {dataset.ready ? "✓" : "!"} {dataset.filename}
              </li>
            ))}
          </ul>
        )}
        <p className="health-note">
          {state.kind === "error"
            ? `请确认后端已启动（${state.message}）。`
            : "这里只检查文件存在性、表头和样本列约束，不会把大型 ASV 矩阵载入内存。"}
        </p>
      </div>
    </section>
  );
}

