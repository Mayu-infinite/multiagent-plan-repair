"""
Base experiment runner for the Multi-Agent Plan Repair project.

This module provides the common infrastructure used by all
experiment scripts.

Expected simulator interface
----------------------------
The simulation layer will expose:

    Simulator(config).run()

where:
    config -> Python dictionary loaded from YAML
    run() -> dictionary containing simulation metrics

Example returned metrics:

{
    "total_completion_time": 120,
    "makespan": 42,
    "total_path_cost": 137.0,
    "modified_agents": 2,
    "modification_ratio": 0.20,
    "repair_time": 0.031,
    "negotiation_rounds": 3,
    "conflicts": 1,
    "delay": 7
}
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml


# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Configuration utilities
# ---------------------------------------------------------------------------

def load_config(config_path: str | Path) -> dict[str, Any]:
    """
    Load a YAML configuration file.

    Parameters
    ----------
    config_path:
        Path to the YAML configuration file.

    Returns
    -------
    dict
        Parsed configuration.
    """
    path = Path(config_path)

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError(f"Configuration must contain a YAML mapping: {path}")

    return config


def set_nested_value(
    config: dict[str, Any],
    key_path: str,
    value: Any,
) -> None:
    """
    Set a nested configuration value.

    Example
    -------
    set_nested_value(
        config,
        "agents.count",
        20
    )

    modifies:

        config["agents"]["count"] = 20
    """
    keys = key_path.split(".")

    current = config

    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}

        current = current[key]

    current[keys[-1]] = value


def apply_overrides(
    config: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return a copy of config with nested overrides applied.

    Parameters
    ----------
    config:
        Original configuration.

    overrides:
        Mapping such as:
            {
                "agents.count": 20,
                "dynamic_obstacles.density": 0.15
            }

    Returns
    -------
    dict
        Modified configuration copy.
    """
    modified_config = copy.deepcopy(config)

    if not overrides:
        return modified_config

    for key_path, value in overrides.items():
        set_nested_value(modified_config, key_path, value)

    return modified_config


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

def set_random_seed(seed: int) -> None:
    """
    Set seeds for the Python and NumPy random generators.
    """
    random.seed(seed)
    np.random.seed(seed)


# ---------------------------------------------------------------------------
# Simulator interface
# ---------------------------------------------------------------------------

def run_simulation(config: dict[str, Any]) -> dict[str, Any]:
    """
    Create and execute the simulator.

    The simulation layer implemented later must expose:

        Simulator(config).run()

    Returns
    -------
    dict
        Simulation metrics.
    """
    try:
        from src.simulation.simulator import Simulator
    except ImportError as exc:
        raise ImportError(
            "Could not import Simulator from "
            "'src.simulation.simulator'. "
            "The simulation module must be implemented before "
            "running experiments."
        ) from exc

    simulator = Simulator(config)
    result = simulator.run()

    if result is None:
        raise RuntimeError(
            "Simulator.run() returned None. "
            "It must return a dictionary containing metrics."
        )

    if not isinstance(result, dict):
        raise TypeError(
            "Simulator.run() must return a dictionary of metrics."
        )

    return result


# ---------------------------------------------------------------------------
# Result handling
# ---------------------------------------------------------------------------

def create_output_directories() -> None:
    """
    Create the configured results directories.
    """
    directories = [
        PROJECT_ROOT / "results",
        PROJECT_ROOT / "results" / "raw",
        PROJECT_ROOT / "results" / "plots",
        PROJECT_ROOT / "results" / "logs",
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def save_json_result(
    result: dict[str, Any],
    config: dict[str, Any],
    experiment_name: str = "experiment",
) -> Path:
    """
    Save a single experiment result as JSON.

    Returns
    -------
    Path
        Path of the generated JSON file.
    """
    create_output_directories()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    file_name = f"{experiment_name}_{timestamp}.json"

    output_path = (
        PROJECT_ROOT
        / config.get("output", {}).get("raw_dir", "results/raw")
        / file_name
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "experiment": experiment_name,
        "timestamp": timestamp,
        "config": config,
        "metrics": result,
    }

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            output_data,
            file,
            indent=2,
            default=str,
        )

    return output_path


# ---------------------------------------------------------------------------
# Public experiment API
# ---------------------------------------------------------------------------

def run_experiment(
    config_path: str | Path,
    overrides: dict[str, Any] | None = None,
    experiment_name: str = "experiment",
    save_result: bool = True,
) -> dict[str, Any]:
    """
    Execute a single configured experiment.

    Parameters
    ----------
    config_path:
        YAML configuration path.

    overrides:
        Optional configuration overrides.

    experiment_name:
        Name used in output files.

    save_result:
        Whether to save the result to results/raw/.

    Returns
    -------
    dict
        Simulation metrics.
    """
    base_config = load_config(config_path)

    config = apply_overrides(base_config, overrides)

    seed = int(
        config.get("project", {}).get("seed", 42)
    )

    set_random_seed(seed)

    print("=" * 70)
    print(f"Experiment: {experiment_name}")
    print(f"Configuration: {config_path}")
    print(f"Random seed: {seed}")
    print("=" * 70)

    result = run_simulation(config)

    if save_result:
        output_path = save_json_result(
            result=result,
            config=config,
            experiment_name=experiment_name,
        )

        print(f"\nResult saved to: {output_path}")

    print("\nMetrics")
    print("-" * 70)

    for key, value in result.items():
        print(f"{key:<30}: {value}")

    print("=" * 70)

    return result


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------

def parse_value(value: str) -> Any:
    """
    Convert command-line override values into Python types.

    Examples
    --------
    "10"      -> 10
    "0.15"    -> 0.15
    "true"    -> True
    "false"   -> False
    "hello"   -> "hello"
    """
    lowered = value.lower()

    if lowered == "true":
        return True

    if lowered == "false":
        return False

    if lowered == "null":
        return None

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        pass

    return value


def parse_overrides(
    override_arguments: list[str] | None,
) -> dict[str, Any]:
    """
    Parse arguments in the form:

        key=value

    Example:

        agents.count=15
        dynamic_obstacles.density=0.20
    """
    overrides: dict[str, Any] = {}

    if not override_arguments:
        return overrides

    for argument in override_arguments:
        if "=" not in argument:
            raise ValueError(
                f"Invalid override '{argument}'. "
                "Expected format key=value."
            )

        key, value = argument.split("=", 1)

        key = key.strip()

        if not key:
            raise ValueError(
                f"Invalid override '{argument}': empty key."
            )

        overrides[key] = parse_value(value.strip())

    return overrides


def main() -> None:
    """
    Command-line entry point.
    """
    parser = argparse.ArgumentParser(
        description="Run a single Multi-Agent Plan Repair experiment."
    )

    parser.add_argument(
        "--config",
        type=str,
        default="configs/default.yaml",
        help="Path to YAML configuration file.",
    )

    parser.add_argument(
        "--name",
        type=str,
        default="experiment",
        help="Experiment name.",
    )

    parser.add_argument(
        "--override",
        nargs="*",
        default=[],
        help=(
            "Optional configuration overrides. "
            "Example: agents.count=15 dynamic_obstacles.density=0.20"
        ),
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save experiment results.",
    )

    args = parser.parse_args()

    overrides = parse_overrides(args.override)

    run_experiment(
        config_path=args.config,
        overrides=overrides,
        experiment_name=args.name,
        save_result=not args.no_save,
    )


if __name__ == "__main__":
    main()