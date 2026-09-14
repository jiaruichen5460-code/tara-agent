"""Command-line entrypoint for Tara data preprocessing."""

from __future__ import annotations

import argparse
import json

from tara_agent.config import Settings
from tara_agent.data.preprocess import PreprocessingError, preprocess


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and preprocess Tara MVP datasets")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate and verify outputs even when sources are unchanged",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = Settings()
    try:
        result = preprocess(
            settings.dataset_dir,
            settings.processed_data_dir,
            force=args.force,
        )
    except (OSError, PreprocessingError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "status": result.status,
                "manifest": str(result.manifest_path),
                "generation": result.manifest.generation,
                "metrics": result.manifest.metrics.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
