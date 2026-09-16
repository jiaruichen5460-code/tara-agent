from pathlib import Path

from benchmarks.query_formats import benchmark_query_formats
from tara_agent.data.preprocess import preprocess


def test_query_format_benchmark_is_an_explicit_development_task(
    preprocessable_dataset_dir: Path, tmp_path: Path
) -> None:
    processed_dir = tmp_path / "processed"
    result = preprocess(
        preprocessable_dataset_dir,
        processed_dir,
        enforce_expected_shape=False,
    )

    report = benchmark_query_formats(preprocessable_dataset_dir, processed_dir)

    assert report["status"] == "passed"
    assert report["query"]["result_verified_equal"] is True
    assert report["query"]["selected_sample_count"] == 2
    assert result.manifest.benchmark_report is None
    assert not (processed_dir / result.manifest.generation / "benchmark.json").exists()
