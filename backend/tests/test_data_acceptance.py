from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tara_agent.analysis import (
    DiversityQuery,
    EnvironmentAssociationQuery,
    EnvironmentVariable,
    FindSamplesQuery,
    FindTaxaQuery,
    TaraComputeService,
    TaraQueryService,
    TaxonAbundanceQuery,
)
from tara_agent.data.catalog import DATASET_SPECS
from tara_agent.data.preprocess import preprocess
from tara_agent.data.reader import ProcessedDataReader
from tara_agent.domain.contracts import Marker


def _fingerprints(source_dir: Path) -> dict[str, tuple[int, int, str]]:
    fingerprints = {}
    for spec in DATASET_SPECS:
        path = source_dir / spec.filename
        stat = path.stat()
        fingerprints[spec.key] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return fingerprints


@pytest.mark.integration
def test_full_dataset_preprocessing_acceptance(tmp_path: Path) -> None:
    source_dir = Path(__file__).resolve().parents[2] / "Tara_4_Core_Datasets"
    if not source_dir.is_dir():
        pytest.skip("Local Tara datasets are not available")
    processed_dir = tmp_path / "processed"
    before = _fingerprints(source_dir)

    first = preprocess(source_dir, processed_dir)
    skipped = preprocess(source_dir, processed_dir)
    forced = preprocess(source_dir, processed_dir, force=True)

    assert first.status == "processed"
    assert skipped.status == "skipped"
    assert forced.status == "verified"
    assert first.manifest.coverage.context_samples == 1_434
    assert first.manifest.coverage.v4_samples == 1_011
    assert first.manifest.coverage.v9_samples == 1_069
    assert first.manifest.coverage.shared_marker_samples == 812
    assert first.manifest.coverage.v4_only_samples == 199
    assert first.manifest.coverage.v9_only_samples == 257
    assert first.manifest.coverage.context_without_marker_samples == 166
    assert first.manifest.coverage.marker_samples_missing_context == []
    assert first.manifest.metrics.elapsed_seconds > 0
    assert first.manifest.metrics.peak_memory_bytes > 0
    assert before == _fingerprints(source_dir)
    assert {
        key: artifact.sha256 for key, artifact in first.manifest.artifacts.items()
    } == {key: artifact.sha256 for key, artifact in forced.manifest.artifacts.items()}
    assert not list(processed_dir.glob(".staging-*"))

    store = ProcessedDataReader(processed_dir)
    assert store.load_sample_context().height == 1_434
    assert len(store.marker_sample_ids(Marker.V4)) == 1_011
    assert len(store.marker_sample_ids(Marker.V9)) == 1_069

    service = TaraQueryService(store)
    samples = service.find_samples(
        FindSamplesQuery(
            ocean_region_contains="Mediterranean",
            polar=False,
            depths=["SRF"],
            temperature_min=20,
            limit=20,
        )
    )
    assert samples.page.total > 0
    assert all(item.depth == "SRF" for item in samples.items)
    assert all(item.temperature is not None and item.temperature >= 20 for item in samples.items)

    sample = service.get_sample_info("TARA_A100000005")
    assert sample.sample.ocean_region.startswith("[MS] Mediterranean Sea")

    taxa = service.find_taxa(
        FindTaxaQuery(
            marker=Marker.V4,
            taxon="Bacillariophyta",
            asv_limit=5,
            sample_limit=5,
        )
    )
    assert taxa.asv_page.total == 5_173
    assert taxa.sample_page.total > 0
    assert all("Bacillariophyta" in item.taxonomy.split(";") for item in taxa.asvs)

    compute = TaraComputeService(store)
    marker_samples = store.marker_sample_ids(Marker.V4)[:100]
    abundance = compute.taxon_abundance(
        TaxonAbundanceQuery(
            marker=Marker.V4,
            taxon="Bacillariophyta",
            sample_ids=marker_samples,
            limit=5,
        )
    )
    assert abundance.matching_asv_count == 5_173
    assert all(
        item.relative_abundance is None or 0 <= item.relative_abundance <= 1
        for item in abundance.observations
    )

    diversity = compute.diversity_analysis(
        DiversityQuery(
            marker=Marker.V4,
            taxon="Bacillariophyta",
            sample_ids=marker_samples[:5],
            limit=5,
        )
    )
    assert all(item.observed_asv_richness > 0 for item in diversity.observations)
    assert all(item.shannon_index is not None for item in diversity.observations)

    association = compute.environment_association(
        EnvironmentAssociationQuery(
            marker=Marker.V4,
            taxon="Bacillariophyta",
            sample_ids=marker_samples,
            environment_variable=EnvironmentVariable.TEMPERATURE,
            point_limit=5,
        )
    )
    assert association.sample_count >= 3
    assert association.rho is not None
    assert association.p_value is not None
    assert "asymptotic_p_value_caution" in {
        warning.code for warning in association.metadata.warnings
    }

    all_zero = compute.environment_association(
        EnvironmentAssociationQuery(
            marker=Marker.V4,
            taxon="NotATaxon",
            sample_ids=marker_samples[:3],
            environment_variable=EnvironmentVariable.TEMPERATURE,
        )
    )
    assert all_zero.rho is None
    assert all_zero.p_value is None
    assert {"taxon_not_found", "constant_input"} <= {
        warning.code for warning in all_zero.metadata.warnings
    }
