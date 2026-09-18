import math
from pathlib import Path

import pytest

from tara_agent.analysis import (
    DiversityGroup,
    DiversityQuery,
    EnvironmentAssociationQuery,
    EnvironmentVariable,
    TaraComputeService,
    TaxonAbundanceQuery,
)
from tara_agent.data.catalog import DATASET_SPECS, DatasetKind
from tara_agent.data.preprocess import preprocess
from tara_agent.data.reader import ProcessedDataReader
from tara_agent.domain.contracts import Marker


@pytest.fixture
def compute_service(
    preprocessable_dataset_dir: Path, tmp_path: Path
) -> TaraComputeService:
    second_asv = (
        "fedcba9876543210fedcba9876543210\tRoot;Eukaryota;Other\t100;99;98"
        "\t1\t1\tACGT\t1\t0\n"
    )
    for spec in DATASET_SPECS:
        if spec.kind is DatasetKind.AMPLICON:
            path = preprocessable_dataset_dir / spec.filename
            path.write_text(path.read_text(encoding="utf-8") + second_asv, encoding="utf-8")

    processed_dir = tmp_path / "processed"
    preprocess(
        preprocessable_dataset_dir,
        processed_dir,
        enforce_expected_shape=False,
    )
    return TaraComputeService(ProcessedDataReader(processed_dir))


def test_taxon_abundance_returns_raw_and_within_sample_relative_values(
    compute_service: TaraComputeService,
) -> None:
    result = compute_service.taxon_abundance(
        TaxonAbundanceQuery(marker=Marker.V4, taxon="Dinoflagellata")
    )

    assert result.matching_asv_count == 1
    assert result.page.total == 2
    assert result.observations[0].sample_id == "TARA_TEST_001"
    assert result.observations[0].taxon_read_count == 1
    assert result.observations[0].sample_total_read_count == 2
    assert result.observations[0].relative_abundance == 0.5
    assert result.observations[1].relative_abundance == 1.0


def test_taxon_abundance_keeps_zero_samples_and_warns_for_unknown_taxon(
    compute_service: TaraComputeService,
) -> None:
    result = compute_service.taxon_abundance(
        TaxonAbundanceQuery(marker=Marker.V9, taxon="NotATaxon")
    )

    assert result.page.total == 2
    assert all(item.taxon_read_count == 0 for item in result.observations)
    assert all(item.relative_abundance == 0 for item in result.observations)
    assert "taxon_not_found" in {warning.code for warning in result.metadata.warnings}


def test_diversity_returns_observed_richness_and_natural_log_shannon(
    compute_service: TaraComputeService,
) -> None:
    result = compute_service.diversity_analysis(
        DiversityQuery(marker=Marker.V4, group_by=DiversityGroup.POLAR)
    )

    first, second = result.observations
    assert first.sample_id == "TARA_TEST_001"
    assert first.observed_asv_richness == 2
    assert first.shannon_index == pytest.approx(math.log(2))
    assert second.observed_asv_richness == 1
    assert second.shannon_index == 0
    assert result.groups[0].group == "Non polar"
    assert result.groups[0].sample_count == 2
    assert result.groups[0].shannon_sample_count == 2
    assert result.groups[0].richness_mean == 1.5
    assert "unrarefied_diversity" in {
        warning.code for warning in result.metadata.warnings
    }


def test_diversity_can_be_limited_to_one_taxon(
    compute_service: TaraComputeService,
) -> None:
    result = compute_service.diversity_analysis(
        DiversityQuery(marker=Marker.V4, taxon="Dinoflagellata")
    )

    assert result.matching_asv_count == 1
    assert all(item.observed_asv_richness == 1 for item in result.observations)
    assert all(item.shannon_index == 0 for item in result.observations)


def test_environment_association_requires_three_complete_samples(
    compute_service: TaraComputeService,
) -> None:
    result = compute_service.environment_association(
        EnvironmentAssociationQuery(
            marker=Marker.V4,
            taxon="Dinoflagellata",
            environment_variable=EnvironmentVariable.TEMPERATURE,
        )
    )

    assert result.sample_count == 2
    assert result.rho is None
    assert result.p_value is None
    assert "insufficient_samples" in {
        warning.code for warning in result.metadata.warnings
    }


def test_compute_service_rejects_unknown_context_sample(
    compute_service: TaraComputeService,
) -> None:
    with pytest.raises(ValueError, match="Unknown sample IDs"):
        compute_service.diversity_analysis(
            DiversityQuery(marker=Marker.V4, sample_ids=["TARA_UNKNOWN"])
        )
