"""根据结构化工具结果确定性地生成图表数据。"""

from __future__ import annotations

from typing import Any

from tara_agent.agent.models import ChartKind, ChartSpec, ToolName


def build_charts(tool_name: ToolName, result: dict[str, Any]) -> list[ChartSpec]:
    if tool_name is ToolName.FIND_SAMPLES:
        return _sample_map(result)
    if tool_name is ToolName.FIND_TAXA:
        return _occurrence_chart(result)
    if tool_name is ToolName.TAXON_ABUNDANCE:
        return _abundance_chart(result)
    if tool_name is ToolName.DIVERSITY_ANALYSIS:
        return _diversity_chart(result)
    if tool_name is ToolName.ENVIRONMENT_ASSOCIATION:
        return _association_chart(result)
    return []


def _sample_map(result: dict[str, Any]) -> list[ChartSpec]:
    items = result.get("items", [])
    if not items:
        return []
    return [
        ChartSpec(
            kind=ChartKind.SAMPLE_MAP,
            title="样本分布",
            x=[float(item["event_longitude"]) for item in items],
            y=[float(item["event_latitude"]) for item in items],
            labels=[str(item["sample_id_pangaea"]) for item in items],
            x_label="经度",
            y_label="纬度",
        )
    ]


def _occurrence_chart(result: dict[str, Any]) -> list[ChartSpec]:
    items = result.get("sample_occurrences", [])[:20]
    return _bar_chart(
        items,
        value_key="read_count",
        title="分类群测序 reads 排名",
        y_label="Raw read count",
    )


def _abundance_chart(result: dict[str, Any]) -> list[ChartSpec]:
    observations = result.get("observations", [])
    items = sorted(
        observations,
        key=lambda item: item.get("relative_abundance") or 0,
        reverse=True,
    )[:20]
    return _bar_chart(
        items,
        value_key="relative_abundance",
        title="分类群相对丰度排名",
        y_label="Relative abundance",
    )


def _diversity_chart(result: dict[str, Any]) -> list[ChartSpec]:
    items = [
        item for item in result.get("observations", []) if item.get("shannon_index") is not None
    ][:20]
    return _bar_chart(
        items,
        value_key="shannon_index",
        title="样本 Shannon 多样性",
        y_label="Shannon index",
    )


def _association_chart(result: dict[str, Any]) -> list[ChartSpec]:
    points = result.get("points", [])
    if not points:
        return []
    variable = str(result.get("environment_variable", "environment"))
    return [
        ChartSpec(
            kind=ChartKind.SCATTER,
            title=f"{variable} 与相对丰度",
            x=[float(point["environment_value"]) for point in points],
            y=[float(point["relative_abundance"]) for point in points],
            labels=[str(point["sample_id"]) for point in points],
            x_label=variable,
            y_label="Relative abundance",
        )
    ]


def _bar_chart(
    items: list[dict[str, Any]],
    *,
    value_key: str,
    title: str,
    y_label: str,
) -> list[ChartSpec]:
    plotted = [item for item in items if item.get(value_key) is not None]
    if not plotted:
        return []
    return [
        ChartSpec(
            kind=ChartKind.BAR,
            title=title,
            x=[str(item["sample_id"]) for item in plotted],
            y=[float(item[value_key]) for item in plotted],
            x_label="Sample ID",
            y_label=y_label,
        )
    ]
