"""
Agent scaling experiment.

Studies how the Multi-Agent Plan Repair system behaves as
the number of agents increases.

Example:

    5 agents
    10 agents
    15 agents
    20 agents
    25 agents
    30 agents

Metrics are collected for every setting.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Make project root importable when running this file directly.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.run_experiment import run_experiment


def run_agent_scaling(
    config_path: str,
    agent_counts: list[int],
    output_name: str = "agent_scaling",
) -> Path:
    """
    Run experiments for different numbers of agents.

    Parameters
    ----------
    config_path:
        YAML configuration file.

    agent_counts:
        Number of agents to test.

    output_name:
        Name of the CSV output file.

    Returns
    -------
    Path
        CSV result path.
    """

    results: list[dict[str, Any]] = []

    print("\n")
    print("=" * 80)
    print("AGENT SCALING EXPERIMENT")
    print("=" * 80)

    for count in agent_counts:
        print(f"\nRunning experiment with {count} agents...")

        overrides = {
            "agents.count": count,
        }

        try:
            result = run_experiment(
                config_path=config_path,
                overrides=overrides,
                experiment_name=f"agent_scaling_{count}",
                save_result=True,
            )
        except Exception as exc:
            print(f"Experiment failed for {count} agents: {exc}")

            result = {
                "completed": False,
                "experiment_error": str(exc),
            }

        row: dict[str, Any] = {
            "agents": count,
        }

        row.update(result)

        results.append(row)

    # -----------------------------------------------------------------------
    # Save combined CSV
    # -----------------------------------------------------------------------

    output_dir = PROJECT_ROOT / "results" / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{output_name}.csv"

    # Collect all metric columns across all experiments.
    field_names = ["agents"]

    metric_names: set[str] = set()

    for row in results:
        metric_names.update(
            key for key in row.keys()
            if key != "agents"
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
    print("AGENT SCALING COMPLETE")
    print(f"Combined results: {output_path}")
    print("=" * 80)

    return output_path


def main() -> None:
    """
    Command-line interface.
    """

    parser = argparse.ArgumentParser(
        description="Run the agent scaling experiment."
    )

    parser.add_argument(
        "--config",
        type=str,
        default="configs/medium.yaml",
        help="Base YAML configuration.",
    )

    parser.add_argument(
        "--agents",
        type=int,
        nargs="+",
        default=[5, 10, 15, 20, 25, 30],
        help="Agent counts to evaluate.",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="agent_scaling",
        help="Output CSV name.",
    )

    args = parser.parse_args()

    if any(count <= 0 for count in args.agents):
        raise ValueError(
            "All agent counts must be positive integers."
        )

    run_agent_scaling(
        config_path=args.config,
        agent_counts=args.agents,
        output_name=args.output,
    )


if __name__ == "__main__":
    main()