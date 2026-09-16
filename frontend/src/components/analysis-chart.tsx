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
      const theme = chartTheme();
      await plotly.react(
        element,
        chartData(chart, theme),
        chartLayout(chart, theme),
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

type ChartTheme = {
  ink: string;
  accent: string;
  coral: string;
  line: string;
  lineStrong: string;
  ocean: string;
  land: string;
};

function chartTheme(): ChartTheme {
  const styles = getComputedStyle(document.documentElement);
  const color = (name: string) => styles.getPropertyValue(name).trim();
  return {
    ink: color("--ink"),
    accent: color("--accent"),
    coral: color("--coral"),
    line: color("--line"),
    lineStrong: color("--line-strong"),
    ocean: color("--accent-soft"),
    land: color("--map-land"),
  };
}

function chartData(chart: ChartSpec, theme: ChartTheme): Data[] {
  if (chart.kind === "sample_map") {
    return [
      {
        type: "scattergeo",
        mode: "markers",
        lon: chart.x as number[],
        lat: chart.y,
        text: chart.labels,
        hovertemplate: "%{text}<br>经度 %{lon:.2f}<br>纬度 %{lat:.2f}<extra></extra>",
        marker: { color: theme.accent, size: 8, line: { color: "#ffffff", width: 1 } },
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
        marker: { color: theme.accent },
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
      marker: { color: theme.coral, size: 8, opacity: 0.78 },
      hovertemplate: "%{text}<br>x %{x:.4g}<br>y %{y:.4g}<extra></extra>",
    },
  ];
}

function chartLayout(chart: ChartSpec, theme: ChartTheme): Partial<Layout> {
  const shared: Partial<Layout> = {
    autosize: true,
    height: 340,
    margin: { l: 58, r: 24, t: 52, b: 68 },
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#ffffff",
    font: { family: "Inter, system-ui, sans-serif", color: theme.ink, size: 12 },
    title: { text: chart.title, x: 0.02, xanchor: "left", font: { size: 15 } },
  };
  if (chart.kind === "sample_map") {
    return {
      ...shared,
      margin: { l: 16, r: 16, t: 52, b: 16 },
      geo: {
        projection: { type: "natural earth" },
        showland: true,
        landcolor: theme.land,
        showocean: true,
        oceancolor: theme.ocean,
        showcountries: true,
        countrycolor: theme.lineStrong,
      },
    };
  }
  return {
    ...shared,
    xaxis: { title: { text: chart.x_label }, gridcolor: theme.line, automargin: true },
    yaxis: { title: { text: chart.y_label }, gridcolor: theme.line, zeroline: false },
  };
}
