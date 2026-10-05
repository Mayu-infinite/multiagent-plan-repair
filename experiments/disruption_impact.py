"""
Disruption impact experiment.

Measures the effect of a SINGLE disruption on the existing
multi-agent plan.

Supported disruption types:

    1. agent_failure
    2. dynamic_obstacle
    3. emergency_task

The primary metric is:

    number of modified agents

and:

    modification ratio
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.run_experiment import run_experiment


SUPPORTED_DISRUPTIONS = [
    "agent_failure",
    "dynamic_obstacle",
    "emergency_task",
]


def run_disruption_impact_experiment(
    config_path: str,
    disruption_types: list[str],
    output_name: str = "disruption_impact",
) -> Path:
    """
    Measure the impact of a single disruption.

    Parameters
    ----------
    config_path:
        YAML configuration file.

    disruption_types:
        Disruption types to evaluate.

    output_name:
        CSV output name.

    Returns
    -------
    Path
        Generated CSV file.
    """

    results: list[dict[str, Any]] = []

    print("\n")
    print("=" * 80)
    print("SINGLE-DISRUPTION IMPACT EXPERIMENT")
    print("=" * 80)

    for disruption_type in disruption_types:

        if disruption_type not in SUPPORTED_DISRUPTIONS:
            raise ValueError(
                f"Unsupported disruption type: {disruption_type}. "
                f"Supported types: {SUPPORTED_DISRUPTIONS}"
            )

        print(
            f"\nRunning disruption experiment: "
            f"{disruption_type}"
        )

        # -------------------------------------------------------------------
        # Force exactly one disruption and force the desired disruption type.
        #
        # The simulator/DisruptionManager will later read these fields.
        # -------------------------------------------------------------------

        overrides = {
            "dynamic_obstacles.events_per_run": 1,
            "disruptions.enabled": True,
            "disruptions.types": [disruption_type],
        }

        # Since only one type is enabled, its probability becomes 1.0.
        overrides.update(
            {
                "disruptions.probabilities.agent_failure": (
                    1.0 if disruption_type == "agent_failure" else 0.0
                ),
                "disruptions.probabilities.dynamic_obstacle": (
                    1.0 if disruption_type == "dynamic_obstacle" else 0.0
                ),
                "disruptions.probabilities.emergency_task": (
                    1.0 if disruption_type == "emergency_task" else 0.0
                ),
            }
        )

        result = run_experiment(
            config_path=config_path,
            overrides=overrides,
            experiment_name=f"disruption_{disruption_type}",
            save_result=True,
        )

        row: dict[str, Any] = {
            "disruption_type": disruption_type,
            "number_of_disruptions": 1,
        }

        row.update(result)

        results.append(row)

    # -----------------------------------------------------------------------
    # Save combined CSV
    # -----------------------------------------------------------------------

    output_dir = PROJECT_ROOT / "results" / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{output_name}.csv"

    field_names = [
        "disruption_type",
        "number_of_disruptions",
    ]

    metric_names: set[str] = set()

    for row in results:
        metric_names.update(
            key for key in row.keys()
            if key not in field_names
        )

    field_names.extend(sorted(metric_names))

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=field_names,
        )

        writer.writeheader()
        writer.writerows(results)

    print("\n")
    print("=" * 80)
    print("DISRUPTION IMPACT EXPERIMENT COMPLETE")
    print(f"Combined results: {output_path}")
    print("=" * 80)

    return output_path


def main() -> None:
    """
    Command-line interface.
    """

    parser = argparse.ArgumentParser(
        description="Measure the impact of a single disruption."
    )

    parser.add_argument(
        "--config",
        type=str,
        default="configs/medium.yaml",
        help="Base YAML configuration.",
    )

    parser.add_argument(
        "--types",
        nargs="+",
        choices=SUPPORTED_DISRUPTIONS,
        default=SUPPORTED_DISRUPTIONS,
        help="Disruption types to test.",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="disruption_impact",
        help="Output CSV name.",
    )

    args = parser.parse_args()

    run_disruption_impact_experiment(
        config_path=args.config,
        disruption_types=args.types,
        output_name=args.output,
    )


if __name__ == "__main__":
    main()