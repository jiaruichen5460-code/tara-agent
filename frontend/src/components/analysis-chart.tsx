"use client";

import { useEffect, useRef } from "react";
import type { Config, Data, Layout } from "plotly.js";

import type { ChartSpec } from "@/lib/types";

type AnalysisChartProps = {
  chart: ChartSpec;
};

export function AnalysisChart({ chart }: AnalysisChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    let plotly: typeof import("plotly.js-dist-min").default | undefined;
    const element = chartRef.current;

    async function renderChart() {
      plotly = (await import("plotly.js-dist-min")).default;
      if (disposed || !element) {
        return;
      }
      await plotly.react(
        element,
        chartData(chart),
        chartLayout(chart),
        chartConfig,
      );
    }

    void renderChart();
    return () => {
      disposed = true;
      if (plotly && element) {
        plotly.purge(element);
      }
    };
  }, [chart]);

  return <div ref={chartRef} className="analysis-chart" aria-label={chart.title} />;
}

const chartConfig: Partial<Config> = {
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
};

function chartData(chart: ChartSpec): Data[] {
  if (chart.kind === "sample_map") {
    return [
      {
        type: "scattergeo",
        mode: "markers",
        lon: chart.x as number[],
        lat: chart.y,
        text: chart.labels,
        hovertemplate: "%{text}<br>Lon %{lon:.2f}<br>Lat %{lat:.2f}<extra></extra>",
        marker: { color: "#087f72", size: 8, line: { color: "#ffffff", width: 1 } },
      },
    ];
  }
  if (chart.kind === "bar") {
    return [
      {
        type: "bar",
        x: chart.x,
        y: chart.y,
        text: chart.labels,
        marker: { color: "#087f72" },
        hovertemplate: "%{x}<br>%{y:.4g}<extra></extra>",
      },
    ];
  }
  return [
    {
      type: "scatter",
      mode: "markers",
      x: chart.x,
      y: chart.y,
      text: chart.labels,
      marker: { color: "#d06b3c", size: 8, opacity: 0.78 },
      hovertemplate: "%{text}<br>x %{x:.4g}<br>y %{y:.4g}<extra></extra>",
    },
  ];
}

function chartLayout(chart: ChartSpec): Partial<Layout> {
  const shared: Partial<Layout> = {
    autosize: true,
    height: 340,
    margin: { l: 58, r: 24, t: 52, b: 68 },
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#ffffff",
    font: { family: "Inter, system-ui, sans-serif", color: "#18302e", size: 12 },
    title: { text: chart.title, x: 0.02, xanchor: "left", font: { size: 15 } },
  };
  if (chart.kind === "sample_map") {
    return {
      ...shared,
      margin: { l: 16, r: 16, t: 52, b: 16 },
      geo: {
        projection: { type: "natural earth" },
        showland: true,
        landcolor: "#e7ebe8",
        showocean: true,
        oceancolor: "#e8f3f4",
        showcountries: true,
        countrycolor: "#c5ceca",
      },
    };
  }
  return {
    ...shared,
    xaxis: { title: { text: chart.x_label }, gridcolor: "#e7ece9", automargin: true },
    yaxis: { title: { text: chart.y_label }, gridcolor: "#e7ece9", zeroline: false },
  };
}
