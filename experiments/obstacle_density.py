"""
Dynamic obstacle density experiment.

Studies the effect of increasing dynamic-obstacle density
on multi-agent execution and plan repair.

Example densities:

    0.00
    0.05
    0.10
    0.15
    0.20
    0.25
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


def run_obstacle_density_experiment(
    config_path: str,
    densities: list[float],
    output_name: str = "obstacle_density",
) -> Path:
    """
    Run experiments for different dynamic obstacle densities.

    Parameters
    ----------
    config_path:
        Base YAML configuration.

    densities:
        Dynamic obstacle densities to test.

    output_name:
        CSV output name.

    Returns
    -------
    Path
        Generated CSV path.
    """

    results: list[dict[str, Any]] = []

    print("\n")
    print("=" * 80)
    print("DYNAMIC OBSTACLE DENSITY EXPERIMENT")
    print("=" * 80)

    for density in densities:
        if not 0.0 <= density <= 1.0:
            raise ValueError(
                f"Obstacle density must be between 0 and 1. Got {density}."
            )

        print(
            f"\nRunning experiment with "
            f"dynamic obstacle density = {density:.2f}"
        )

        overrides = {
            "dynamic_obstacles.density": density,
        }

        result = run_experiment(
            config_path=config_path,
            overrides=overrides,
            experiment_name=f"obstacle_density_{density:.2f}",
            save_result=True,
        )

        row: dict[str, Any] = {
            "dynamic_obstacle_density": density,
        }

        row.update(result)

        results.append(row)

    # -----------------------------------------------------------------------
    # Save combined results
    # -----------------------------------------------------------------------

    output_dir = PROJECT_ROOT / "results" / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{output_name}.csv"

    field_names = ["dynamic_obstacle_density"]

    metric_names: set[str] = set()

    for row in results:
        metric_names.update(
            key for key in row.keys()
            if key != "dynamic_obstacle_density"
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
    print("OBSTACLE DENSITY EXPERIMENT COMPLETE")
    print(f"Combined results: {output_path}")
    print("=" * 80)

    return output_path


def main() -> None:
    """
    Command-line interface.
    """

    parser = argparse.ArgumentParser(
        description="Run the dynamic obstacle density experiment."
    )

    parser.add_argument(
        "--config",
        type=str,
        default="configs/medium.yaml",
        help="Base YAML configuration.",
    )

    parser.add_argument(
        "--densities",
        type=float,
        nargs="+",
        default=[
            0.00,
            0.05,
            0.10,
            0.15,
            0.20,
            0.25,
        ],
        help="Dynamic obstacle densities to test.",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="obstacle_density",
        help="Output CSV name.",
    )

    args = parser.parse_args()

    run_obstacle_density_experiment(
        config_path=args.config,
        densities=args.densities,
        output_name=args.output,
    )


if __name__ == "__main__":
    main()