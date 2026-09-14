"""Thin MCP adapters for deterministic Tara query and analysis services."""

from collections.abc import Callable
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from tara_agent.analysis.models import (
    FindSamplesQuery,
    FindSamplesResult,
    FindTaxaQuery,
    FindTaxaResult,
    SampleInfoResult,
)
from tara_agent.analysis.scientific import TaraScientificService
from tara_agent.analysis.scientific_models import (
    DiversityQuery,
    DiversityResult,
    EnvironmentAssociationQuery,
    EnvironmentAssociationResult,
    TaxonAbundanceQuery,
    TaxonAbundanceResult,
)
from tara_agent.analysis.service import AnalysisNotFoundError, TaraQueryService

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def register_tools(
    server: MCPServer,
    *,
    query_service: TaraQueryService,
    scientific_service: TaraScientificService,
) -> None:
    """Register the six MVP tools without adding business logic."""

    @server.tool(title="Find Tara samples", annotations=READ_ONLY)
    def find_samples(
        query: Annotated[
            FindSamplesQuery,
            Field(
                description="Bounded sample filters.",
                examples=[{"ocean_region_contains": "Mediterranean", "limit": 20}],
            ),
        ],
    ) -> FindSamplesResult:
        """Find sample contexts using explicit, bounded environmental filters."""

        return _call(lambda: query_service.find_samples(query))

    @server.tool(title="Get Tara sample information", annotations=READ_ONLY)
    def get_sample_info(
        sample_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=100,
                description="Exact PANGAEA sample ID.",
                examples=["TARA_A100000005"],
            ),
        ],
    ) -> SampleInfoResult:
        """Get the complete validated context for one exact PANGAEA sample ID."""

        return _call(lambda: query_service.get_sample_info(sample_id))

    @server.tool(title="Find Tara taxa", annotations=READ_ONLY)
    def find_taxa(
        query: Annotated[
            FindTaxaQuery,
            Field(
                description="Marker-specific taxonomy query.",
                examples=[{"marker": "v4", "taxon": "Bacillariophyta"}],
            ),
        ],
    ) -> FindTaxaResult:
        """Find matching ASVs and sample occurrences within one marker."""

        return _call(lambda: query_service.find_taxa(query))

    @server.tool(title="Calculate taxon abundance", annotations=READ_ONLY)
    def taxon_abundance(
        query: Annotated[
            TaxonAbundanceQuery,
            Field(
                description="Marker-specific abundance request.",
                examples=[{"marker": "v4", "taxon": "Bacillariophyta"}],
            ),
        ],
    ) -> TaxonAbundanceResult:
        """Calculate raw reads and within-sample relative abundance for one taxon."""

        return _call(lambda: scientific_service.taxon_abundance(query))

    @server.tool(title="Calculate Tara alpha diversity", annotations=READ_ONLY)
    def diversity_analysis(
        query: Annotated[
            DiversityQuery,
            Field(
                description="Marker-specific alpha diversity request.",
                examples=[{"marker": "v9", "group_by": "polar"}],
            ),
        ],
    ) -> DiversityResult:
        """Calculate unrarefied observed ASV richness and Shannon diversity."""

        return _call(lambda: scientific_service.diversity_analysis(query))

    @server.tool(title="Analyze a Tara environment association", annotations=READ_ONLY)
    def environment_association(
        query: Annotated[
            EnvironmentAssociationQuery,
            Field(
                description="One taxon and one allowlisted environmental variable.",
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
        """Calculate one pairwise-complete Spearman abundance association."""

        return _call(lambda: scientific_service.environment_association(query))


def _call[ResultT](operation: Callable[[], ResultT]) -> ResultT:
    """Expose errors that a model can correct while keeping other failures private."""

    try:
        return operation()
    except (AnalysisNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
