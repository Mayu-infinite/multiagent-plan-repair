"""
End-to-end tests for the warehouse simulator.
"""

from __future__ import annotations

from src.simulation import Simulator


def make_test_config() -> dict:
    """
    Build a small deterministic simulation configuration.

    Disruptions are disabled here because the purpose of this file is
    to validate the normal execution pipeline. Plan-repair behavior is
    tested independently in test_repair.py.
    """
    return {
        "project": {
            "name": "test-simulation",
            "seed": 42,
        },

        "environment": {
            "grid": {
                "rows": 8,
                "cols": 8,
            },
            "static_obstacle_density": 0.0,
            "reserve_task_cells": True,
            "movement": {
                "allow_diagonal": False,
                "wait_action": True,
            },
        },

        "agents": {
            "count": 2,
            "tasks_per_agent": 1,
            "move_cost": 1.0,
            "wait_cost": 1.0,
        },

        "tasks": {
            "pickup_delivery_distance_min": 2,
            "pickup_delivery_distance_max": 10,
            "priority": {
                "normal": 1,
                "high": 2,
                "emergency": 3,
            },
            "emergency_task_probability": 0.0,
        },

        "planning": {
            "algorithm": "space_time_astar",
            "heuristic": "manhattan",
            "max_time_steps": 100,
            "max_search_nodes": 10000,
            "priority_strategy": "most_constrained",
            "allow_waiting": True,
        },

        "conflicts": {
            "detect_vertex_conflicts": True,
            "detect_edge_conflicts": True,
            "detect_obstacle_conflicts": True,
        },

        "dynamic_obstacles": {
            "enabled": False,
            "density": 0.0,
            "events_per_run": 0,
            "min_step": 10,
            "max_step": 50,
            "duration_min": 5,
            "duration_max": 10,
        },

        "disruptions": {
            "enabled": False,
            "types": [
                "agent_failure",
                "dynamic_obstacle",
                "emergency_task",
            ],
            "probabilities": {
                "agent_failure": 0.4,
                "dynamic_obstacle": 0.4,
                "emergency_task": 0.2,
            },
        },

        "repair": {
            "enabled": True,
            "objective": "minimize_modified_agents",
            "max_negotiation_neighbors": 3,
            "max_negotiation_rounds": 3,
            "repair_horizon": 15,
            "max_alternatives": 3,
            "local_search_algorithm": "space_time_astar",
            "preserve_unaffected_plans": True,
        },

        "simulation": {
            "max_steps": 100,
            "stop_when_all_tasks_complete": True,
            "collision_checking": True,
            "record_history": True,
        },

        "metrics": {
            "record_total_completion_time": True,
            "record_makespan": True,
            "record_total_path_cost": True,
            "record_modified_agents": True,
            "record_modification_ratio": True,
            "record_repair_time": True,
            "record_negotiation_rounds": True,
            "record_conflicts": True,
            "record_delay": True,
        },

        "visualization": {
            "enabled": False,
            "show_grid": True,
            "show_static_obstacles": True,
            "show_dynamic_obstacles": True,
            "show_agent_paths": True,
            "show_agent_ids": True,
            "show_tasks": True,
            "animate": False,
            "save_animation": False,
            "animation_fps": 5,
        },

        "output": {
            "results_dir": "results",
            "raw_dir": "results/raw",
            "plots_dir": "results/plots",
            "logs_dir": "results/logs",
            "save_json": False,
            "save_csv": False,
        },
    }


class TestSimulator:
    """End-to-end simulator tests."""

    def test_simulator_completes(self) -> None:
        config = make_test_config()

        simulator = Simulator(
            config
        )

        result = simulator.run()

        assert result["initial_planning_completed"]
        assert result["completed"]

    def test_correct_agent_count(self) -> None:
        config = make_test_config()

        simulator = Simulator(
            config
        )

        result = simulator.run()

        assert result["total_agents"] == 2

    def test_no_disruptions_in_normal_run(self) -> None:
        config = make_test_config()

        simulator = Simulator(
            config
        )

        result = simulator.run()

        assert result["disruptions"] == 0
        assert result["successful_repairs"] == 0
        assert result["failed_repairs"] == 0

    def test_plans_exist_after_setup(self) -> None:
        config = make_test_config()

        simulator = Simulator(
            config
        )

        simulator.setup()

        assert simulator.initial_planning_completed

        for agent in simulator.agents:
            assert agent.current_plan
            assert agent.original_plan

    def test_history_is_recorded(self) -> None:
        config = make_test_config()

        simulator = Simulator(
            config
        )

        simulator.run()

        history = simulator.get_history()

        assert history
        assert all(
            "timestep" in frame
            for frame in history
        )

    def test_repair_results_are_accessible(self) -> None:
        config = make_test_config()

        simulator = Simulator(
            config
        )

        simulator.run()

        assert isinstance(
            simulator.get_repair_results(),
            list,
        )

    def test_final_metrics_have_required_fields(self) -> None:
        config = make_test_config()

        simulator = Simulator(
            config
        )

        result = simulator.run()

        required_metrics = {
            "total_completion_time",
            "makespan",
            "total_path_cost",
            "modified_agents",
            "modification_ratio",
            "repair_time",
            "negotiation_rounds",
            "conflicts",
            "delay",
        }

        assert required_metrics.issubset(
            result.keys()
        )