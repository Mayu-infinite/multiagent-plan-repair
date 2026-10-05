"""
Tests for local plan repair and negotiation.

The most important invariant tested here is:

    original_plan must remain unchanged after repair.

The repair system is allowed to modify current_plan, but it must
preserve the original trajectory as the baseline for measuring
plan-repair impact.
"""

from __future__ import annotations

from src.agents import (
    Agent,
    Task,
)
from src.environment import (
    DynamicObstacleManager,
    Grid,
)
from src.metrics import MetricsCollector
from src.repair import (
    Disruption,
    RepairManager,
)


class TestDynamicObstacleRepair:
    """Dynamic obstacle local-repair tests."""

    def setup_method(self) -> None:
        self.grid = Grid(
            rows=3,
            cols=3,
            allow_wait=True,
        )

        self.obstacles = DynamicObstacleManager(
            self.grid
        )

        self.metrics = MetricsCollector(
            total_agents=1
        )

        self.repair_manager = RepairManager(
            grid=self.grid,
            obstacle_manager=self.obstacles,
            metrics=self.metrics,
            max_negotiation_neighbors=2,
            max_negotiation_rounds=3,
            repair_horizon=5,
            max_alternatives=5,
            communication_distance=5,
            max_time_steps=20,
            max_search_nodes=5000,
        )

        self.agent = Agent(
            agent_id="A1",
            start_position=(0, 0),
        )

        # Original route:
        #
        # (0,0) -> (0,1) -> (1,1) -> (1,2)
        #
        # The direct first move will be blocked.
        #
        # A same-time local alternative exists:
        #
        # (0,0) -> (1,0) -> (1,1) -> (1,2)
        #
        self.original_plan = [
            (0, 0, 0),
            (0, 1, 1),
            (1, 1, 2),
            (1, 2, 3),
        ]

        self.agent.set_initial_plan(
            self.original_plan
        )

    def test_repair_finds_local_alternative(self) -> None:
        disruption = Disruption.dynamic_obstacle(
            disruption_id="D1",
            position=(0, 1),
            timestep=1,
            duration=1,
        )

        result = (
            self.repair_manager.handle_disruption(
                disruption=disruption,
                agents=[self.agent],
            )
        )

        assert result.success

        assert result.modified_agents == [
            "A1"
        ]

        assert self.agent.plan_modified

        # The current plan must differ from the original.
        assert (
            self.agent.current_plan
            != self.agent.original_plan
        )

    def test_original_plan_is_preserved(self) -> None:
        disruption = Disruption.dynamic_obstacle(
            disruption_id="D1",
            position=(0, 1),
            timestep=1,
            duration=1,
        )

        original_before = list(
            self.agent.original_plan
        )

        result = (
            self.repair_manager.handle_disruption(
                disruption=disruption,
                agents=[self.agent],
            )
        )

        assert result.success

        assert (
            self.agent.original_plan
            == original_before
        )

    def test_repaired_plan_avoids_disruption(self) -> None:
        disruption = Disruption.dynamic_obstacle(
            disruption_id="D1",
            position=(0, 1),
            timestep=1,
            duration=1,
        )

        result = (
            self.repair_manager.handle_disruption(
                disruption=disruption,
                agents=[self.agent],
            )
        )

        assert result.success

        for row, col, timestep in (
            self.agent.current_plan
        ):
            assert not self.obstacles.is_temporarily_blocked(
                (row, col),
                timestep,
            )

    def test_only_affected_agent_is_modified(self) -> None:
        agent_a = self.agent

        agent_b = Agent(
            agent_id="A2",
            start_position=(2, 0),
        )

        agent_b_plan = [
            (2, 0, 0),
            (2, 1, 1),
            (2, 2, 2),
        ]

        agent_b.set_initial_plan(
            agent_b_plan
        )

        disruption = Disruption.dynamic_obstacle(
            disruption_id="D1",
            position=(0, 1),
            timestep=1,
            duration=1,
        )

        result = (
            self.repair_manager.handle_disruption(
                disruption=disruption,
                agents=[
                    agent_a,
                    agent_b,
                ],
            )
        )

        assert result.success

        assert result.modified_agents == [
            "A1"
        ]

        assert agent_a.plan_modified
        assert not agent_b.plan_modified

        assert (
            agent_b.current_plan
            == agent_b.original_plan
        )

    def test_modification_metric_records_agent_once(self) -> None:
        disruption = Disruption.dynamic_obstacle(
            disruption_id="D1",
            position=(0, 1),
            timestep=1,
            duration=1,
        )

        result = (
            self.repair_manager.handle_disruption(
                disruption=disruption,
                agents=[self.agent],
            )
        )

        assert result.success

        # The repair manager records the agent in metrics.
        assert self.metrics.modified_agents == {
            "A1"
        }

        assert (
            self.metrics.modification_ratio
            == 1.0
        )


class TestNegotiation:
    """Basic negotiation behavior."""

    def test_neighbor_is_identified(self) -> None:
        grid = Grid(
            rows=10,
            cols=10,
        )

        obstacles = DynamicObstacleManager(
            grid
        )

        manager = RepairManager(
            grid=grid,
            obstacle_manager=obstacles,
            max_negotiation_neighbors=3,
            communication_distance=5,
        )

        agent_a = Agent(
            agent_id="A1",
            start_position=(2, 2),
        )

        agent_b = Agent(
            agent_id="A2",
            start_position=(2, 4),
        )

        agent_c = Agent(
            agent_id="A3",
            start_position=(8, 8),
        )

        neighbors = manager.find_neighbors(
            affected_agents=[agent_a],
            agents=[
                agent_a,
                agent_b,
                agent_c,
            ],
        )

        neighbor_ids = {
            agent.agent_id
            for agent in neighbors
        }

        assert "A2" in neighbor_ids
        assert "A3" not in neighbor_ids