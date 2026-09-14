from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from tara_agent.analysis import (
    AnalysisNotFoundError,
    FindSamplesQuery,
    FindTaxaQuery,
    SamplingDepth,
    TaraQueryService,
    TaxonMatchMode,
)
from tara_agent.data.preprocess import preprocess
from tara_agent.data.store import ProcessedDataStore
from tara_agent.domain.contracts import Marker


@pytest.fixture
def query_service(preprocessable_dataset_dir: Path, tmp_path: Path) -> TaraQueryService:
    processed_dir = tmp_path / "processed"
    preprocess(
        preprocessable_dataset_dir,
        processed_dir,
        enforce_expected_shape=False,
    )
    return TaraQueryService(ProcessedDataStore(processed_dir))


def test_find_samples_combines_filters_and_returns_stable_page(
    query_service: TaraQueryService,
) -> None:
    query = FindSamplesQuery(
        ocean_region_contains="test ocean",
        polar=False,
        depths=["表层", "surface", "srf"],
        size_fractions=["0.8-5"],
        temperature_max=21.5,
        limit=10,
    )
    result = query_service.find_samples(query)

    assert query.depths == [SamplingDepth.SRF]
    assert result.page.total == 1
    assert result.items[0].sample_id_pangaea == "TARA_TEST_001"
    assert result.metadata.provenance.sample_count == 1
    assert result.metadata.provenance.excluded_sample_count == 1
    assert result.metadata.provenance.filters["depths"] == ["SRF"]


def test_find_samples_validates_temperature_range() -> None:
    with pytest.raises(ValidationError, match="temperature_min"):
        FindSamplesQuery(temperature_min=20, temperature_max=10)


def test_find_samples_warning_counts_missing_temperature_after_other_filters(
    query_service: TaraQueryService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = query_service.store.load_sample_context().with_columns(
        pl.when(pl.col("sample_id_pangaea") == "TARA_TEST_001")
        .then(pl.lit("Target Ocean"))
        .otherwise(pl.lit("Other Ocean"))
        .alias("ocean_region"),
        pl.lit(None, dtype=pl.Float64).alias("temperature"),
    )
    monkeypatch.setattr(
        query_service.store,
        "load_sample_context",
        lambda: context,
    )

    result = query_service.find_samples(
        FindSamplesQuery(ocean_region_contains="target", temperature_min=20)
    )

    assert result.page.total == 0
    assert len(result.metadata.warnings) == 1
    warning = result.metadata.warnings[0]
    assert warning.code == "missing_filter_values_excluded"
    assert warning.details == {
        "field": "temperature",
        "sample_count": 1,
        "candidate_sample_count": 1,
    }


def test_find_samples_rejects_unknown_depth() -> None:
    with pytest.raises(ValidationError):
        FindSamplesQuery(depths=["abyss"])


def test_get_sample_info_returns_complete_context(
    query_service: TaraQueryService,
) -> None:
    result = query_service.get_sample_info(" TARA_TEST_002 ")

    assert result.sample.sample_id_pangaea == "TARA_TEST_002"
    assert result.sample.temperature == 22
    assert result.sample.depth_bathy == -200
    assert result.metadata.provenance.sample_count == 1


def test_get_sample_info_rejects_unknown_sample(
    query_service: TaraQueryService,
) -> None:
    with pytest.raises(AnalysisNotFoundError, match="Unknown sample ID"):
        query_service.get_sample_info("TARA_UNKNOWN")


def test_find_taxa_matches_one_taxonomy_level_and_aggregates_occurrences(
    query_service: TaraQueryService,
) -> None:
    result = query_service.find_taxa(
        FindTaxaQuery(marker=Marker.V4, taxon="dinoflagellata")
    )

    assert result.asv_page.total == 1
    assert result.asvs[0].taxonomy.endswith("Dinoflagellata")
    assert [item.sample_id for item in result.sample_occurrences] == [
        "TARA_TEST_002",
        "TARA_TEST_001",
    ]
    assert [item.read_count for item in result.sample_occurrences] == [2, 1]
    assert result.metadata.warnings[0].code == "read_count_is_not_cell_abundance"


def test_taxonomy_contains_mode_is_explicit(query_service: TaraQueryService) -> None:
    exact_level = query_service.find_taxa(
        FindTaxaQuery(marker=Marker.V9, taxon="flagellata")
    )
    substring = query_service.find_taxa(
        FindTaxaQuery(
            marker=Marker.V9,
            taxon="flagellata",
            match_mode=TaxonMatchMode.CONTAINS,
        )
    )

    assert exact_level.asv_page.total == 0
    assert exact_level.metadata.provenance.excluded_sample_count == 2
    assert substring.asv_page.total == 1


def test_find_taxa_paginates_asvs_and_samples(query_service: TaraQueryService) -> None:
    result = query_service.find_taxa(
        FindTaxaQuery(
            marker=Marker.V4,
            taxon="Root",
            asv_offset=1,
            asv_limit=1,
            sample_offset=1,
            sample_limit=1,
        )
    )

    assert result.asv_page.total == 1
    assert result.asvs == []
    assert result.sample_page.total == 2
    assert len(result.sample_occurrences) == 1
    assert result.sample_occurrences[0].sample_id == "TARA_TEST_001"
