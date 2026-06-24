#!/usr/bin/env python3
"""Compile the Dresma XGBoost training pipeline to a Vertex AI–ready YAML spec."""

from __future__ import annotations

import sys
from pathlib import Path

from kfp.compiler import Compiler

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from dresma_ml.pipelines.training_pipeline import training_pipeline  # noqa: E402

_OUTPUT_PATH = _REPO_ROOT / "dresma_training_pipeline.yaml"


def main() -> None:
    Compiler().compile(
        pipeline_func=training_pipeline,
        package_path=str(_OUTPUT_PATH),
    )
    print(f"Successfully compiled pipeline to {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
