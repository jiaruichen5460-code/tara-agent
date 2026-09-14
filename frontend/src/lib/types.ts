export type DatasetStatus = {
  key: string;
  filename: string;
  ready: boolean;
};

export type HealthResponse = {
  status: "ok" | "degraded";
  data_ready: boolean;
  agent_ready: boolean;
  model: string;
  datasets: DatasetStatus[];
};

export type AgentStep = {
  stage: "understand" | "execute" | "answer";
  title: string;
  detail: string;
};

export type ResultWarning = {
  code: string;
  message: string;
  details: Record<string, unknown>;
};

export type ChartSpec = {
  kind: "sample_map" | "bar" | "scatter";
  title: string;
  x: Array<string | number>;
  y: number[];
  labels: string[];
  x_label: string;
  y_label: string;
};

export type AgentResponse = {
  question: string;
  reasoning: string;
  answer: string;
  model: string;
  tool: {
    name: string;
    arguments: Record<string, unknown>;
    summary: string;
  };
  steps: AgentStep[];
  result: Record<string, unknown>;
  charts: ChartSpec[];
  warnings: ResultWarning[];
  sources: string[];
};

export type AgentStreamEvent = {
  event: "step" | "reasoning_delta" | "answer_delta" | "complete" | "error";
  step?: AgentStep;
  delta?: string;
  response?: AgentResponse;
  error?: string;
};
