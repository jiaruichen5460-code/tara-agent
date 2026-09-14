"use client";

import { Database, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import type { HealthResponse } from "@/lib/types";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function SystemStatus() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);

  async function refresh() {
    setFailed(false);
    try {
      setHealth(await requestHealth());
    } catch {
      setHealth(null);
      setFailed(true);
    }
  }

  useEffect(() => {
    let active = true;
    void requestHealth().then(
      (result) => {
        if (active) setHealth(result);
      },
      () => {
        if (active) setFailed(true);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  const ready = health?.data_ready && health.agent_ready;

  return (
    <section className="system-status" aria-label="系统状态">
      <div className="status-heading">
        <Database size={16} aria-hidden="true" />
        <span>运行状态</span>
        <button type="button" className="icon-button" onClick={() => void refresh()} title="刷新状态">
          <RefreshCw size={15} aria-hidden="true" />
          <span className="sr-only">刷新状态</span>
        </button>
      </div>
      <p className={ready ? "readiness ready" : "readiness"}>
        <span aria-hidden="true" />
        {failed ? "后端未连接" : ready ? "分析服务已就绪" : "等待配置完成"}
      </p>
      {health && (
        <dl className="status-details">
          <div>
            <dt>模型</dt>
            <dd>{health.model}</dd>
          </div>
          <div>
            <dt>数据集</dt>
            <dd>{health.datasets.filter((item) => item.ready).length} / 4</dd>
          </div>
        </dl>
      )}
    </section>
  );
}

async function requestHealth(): Promise<HealthResponse> {
  const response = await fetch(`${apiBaseUrl}/api/v1/health`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json() as Promise<HealthResponse>;
}
