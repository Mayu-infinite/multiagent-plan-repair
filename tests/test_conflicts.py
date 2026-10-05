"""
Tests for multi-agent conflict detection.
"""

from __future__ import annotations

from src.environment import (
    DynamicObstacleManager,
    Grid,
)
from src.planning import (
    ConflictDetector,
)


class TestConflictDetector:
    """Conflict detector tests."""

    def setup_method(self) -> None:
        self.grid = Grid(
            rows=5,
            cols=5,
        )

        self.obstacles = DynamicObstacleManager(
            self.grid
        )

        self.detector = ConflictDetector(
            grid=self.grid,
            obstacle_manager=self.obstacles,
        )

    def test_no_conflicts(self) -> None:
        trajectories = {
            "A1": [
                (0, 0, 0),
                (0, 1, 1),
                (0, 2, 2),
            ],
            "A2": [
                (2, 0, 0),
                (2, 1, 1),
                (2, 2, 2),
            ],
        }

        conflicts = self.detector.detect(
            trajectories
        )

        assert conflicts == []

    def test_vertex_conflict(self) -> None:
        trajectories = {
            "A1": [
                (0, 0, 0),
                (1, 1, 1),
            ],
            "A2": [
                (2, 2, 0),
                (1, 1, 1),
            ],
        }

        conflicts = (
            self.detector.detect_vertex_conflicts(
                trajectories
            )
        )

        assert len(conflicts) == 1

        conflict = conflicts[0]

        assert conflict.conflict_type == "vertex"
        assert conflict.timestep == 1
        assert {
            conflict.agent_a,
            conflict.agent_b,
        } == {
            "A1",
            "A2",
        }

        assert conflict.position_a == (
            1,
            1,
        )

    def test_edge_conflict(self) -> None:
        trajectories = {
            "A1": [
                (0, 0, 0),
                (0, 1, 1),
            ],
            "A2": [
                (0, 1, 0),
                (0, 0, 1),
            ],
        }

        conflicts = (
            self.detector.detect_edge_conflicts(
                trajectories
            )
        )

        # We only care that the head-on swap is identified.
        # Multiple equivalent representations should not change
        # the semantic conclusion.
        edge_conflicts = [
            conflict
            for conflict in conflicts
            if conflict.conflict_type == "edge"
        ]

        assert edge_conflicts

        conflict_agents = {
            frozenset(
                (
                    conflict.agent_a,
                    conflict.agent_b,
                )
            )
            for conflict in edge_conflicts
        }

        assert frozenset(
            {"A1", "A2"}
        ) in conflict_agents

    def test_static_obstacle_conflict(self) -> None:
        self.grid.add_static_obstacle(
            (1, 1)
        )

        trajectories = {
            "A1": [
                (0, 0, 0),
                (1, 1, 1),
            ]
        }

        conflicts = (
            self.detector.detect_obstacle_conflicts(
                trajectories
            )
        )

        assert len(conflicts) == 1

        assert conflicts[0].conflict_type == (
            "obstacle"
        )

        assert conflicts[0].agent_a == "A1"

    def test_dynamic_obstacle_conflict(self) -> None:
        self.obstacles.add_obstacle(
            position=(1, 1),
            start_time=2,
            duration=3,
            obstacle_id="D1",
        )

        trajectories = {
            "A1": [
                (0, 0, 0),
                (0, 1, 1),
                (1, 1, 2),
            ]
        }

        conflicts = (
            self.detector.detect_obstacle_conflicts(
                trajectories
            )
        )

        assert len(conflicts) == 1
        assert conflicts[0].timestep == 2

    def test_has_conflicts(self) -> None:
        trajectories = {
            "A1": [
                (0, 0, 0),
                (1, 1, 1),
            ],
            "A2": [
                (2, 2, 0),
                (1, 1, 1),
            ],
        }

        assert self.detector.has_conflicts(
            trajectories
        )

    def test_validate_all(self) -> None:
        valid_trajectories = {
            "A1": [
                (0, 0, 0),
                (0, 1, 1),
            ],
            "A2": [
                (2, 0, 0),
                (2, 1, 1),
            ],
        }

        invalid_trajectories = {
            "A1": [
                (0, 0, 0),
                (1, 1, 1),
            ],
            "A2": [
                (2, 2, 0),
                (1, 1, 1),
            ],
        }

        assert self.detector.validate_all(
            valid_trajectories
        )

        assert not self.detector.validate_all(
            invalid_trajectories
        )

    def test_involved_agents(self) -> None:
        trajectories = {
            "A1": [
                (0, 0, 0),
                (1, 1, 1),
            ],
            "A2": [
                (2, 2, 0),
                (1, 1, 1),
            ],
        }

        conflicts = self.detector.detect(
            trajectories
        )

        involved = (
            self.detector.involved_agents(
                conflicts
            )
        )

        assert involved == {
            "A1",
            "A2",
        }