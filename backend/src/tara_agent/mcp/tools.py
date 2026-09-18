"""确定性 Tara 查询与分析服务的轻量 MCP 适配层。"""

from collections.abc import Callable
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from tara_agent.analysis.compute import TaraComputeService
from tara_agent.analysis.compute_models import (
    DiversityQuery,
    DiversityResult,
    EnvironmentAssociationQuery,
    EnvironmentAssociationResult,
    TaxonAbundanceQuery,
    TaxonAbundanceResult,
)
from tara_agent.analysis.models import (
    FindSamplesQuery,
    FindSamplesResult,
    FindTaxaQuery,
    FindTaxaResult,
    SampleInfoResult,
)
from tara_agent.analysis.service import AnalysisNotFoundError, TaraQueryService

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def register_tools(
    server: MCPServer,
    *,
    query_service: TaraQueryService,
    compute_service: TaraComputeService,
) -> None:
    """注册六个 MVP 工具，不增加业务逻辑。"""

    @server.tool(title="查询 Tara 样本", annotations=READ_ONLY)
    def find_samples(
        query: Annotated[
            FindSamplesQuery,
            Field(
                description="受限的样本筛选条件。",
                examples=[{"ocean_region_contains": "Mediterranean", "limit": 20}],
            ),
        ],
    ) -> FindSamplesResult:
        """使用明确且受限的环境条件查询样本背景信息。"""

        return _call(lambda: query_service.find_samples(query))

    @server.tool(title="获取 Tara 样本信息", annotations=READ_ONLY)
    def get_sample_info(
        sample_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=100,
                description="准确的 PANGAEA 样本 ID。",
                examples=["TARA_A100000005"],
            ),
        ],
    ) -> SampleInfoResult:
        """根据准确的 PANGAEA 样本 ID 获取完整且已校验的背景信息。"""

        return _call(lambda: query_service.get_sample_info(sample_id))

    @server.tool(title="查询 Tara 分类单元", annotations=READ_ONLY)
    def find_taxa(
        query: Annotated[
            FindTaxaQuery,
            Field(
                description="针对指定标记的分类学查询。",
                examples=[{"marker": "v4", "taxon": "Bacillariophyta"}],
            ),
        ],
    ) -> FindTaxaResult:
        """在指定标记中查询匹配的 ASV 及其样本出现情况。"""

        return _call(lambda: query_service.find_taxa(query))

    @server.tool(title="计算分类单元丰度", annotations=READ_ONLY)
    def taxon_abundance(
        query: Annotated[
            TaxonAbundanceQuery,
            Field(
                description="针对指定标记的丰度计算请求。",
                examples=[{"marker": "v4", "taxon": "Bacillariophyta"}],
            ),
        ],
    ) -> TaxonAbundanceResult:
        """计算一个分类单元的原始测序读数和样本内相对丰度。"""

        return _call(lambda: compute_service.taxon_abundance(query))

    @server.tool(title="计算 Tara Alpha 多样性", annotations=READ_ONLY)
    def diversity_analysis(
        query: Annotated[
            DiversityQuery,
            Field(
                description="针对指定标记的 Alpha 多样性计算请求。",
                examples=[{"marker": "v9", "group_by": "polar"}],
            ),
        ],
    ) -> DiversityResult:
        """计算未稀释抽样的观测 ASV 丰富度与 Shannon 多样性。"""

        return _call(lambda: compute_service.diversity_analysis(query))

    @server.tool(title="分析 Tara 环境关联", annotations=READ_ONLY)
    def environment_association(
        query: Annotated[
            EnvironmentAssociationQuery,
            Field(
                description="一个分类单元和一个允许使用的环境变量。",
                examples=[
                    {
                        "marker": "v4",
                        "taxon": "Bacillariophyta",
                        "environment_variable": "temperature",
                    }
                ],
            ),
        ],
    ) -> EnvironmentAssociationResult:
        """计算一次基于成对完整观测值的 Spearman 丰度关联。"""

        return _call(lambda: compute_service.environment_association(query))


def _call[ResultT](operation: Callable[[], ResultT]) -> ResultT:
    """仅暴露模型可以纠正的错误，其他故障不对外公开。"""

    try:
        return operation()
    except (AnalysisNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
