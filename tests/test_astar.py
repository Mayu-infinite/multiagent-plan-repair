"""
Tests for Space-Time A* and reservation handling.
"""

from __future__ import annotations

from src.environment import (
    DynamicObstacleManager,
    Grid,
)
from src.planning import (
    ReservationTable,
    SpaceTimeAStar,
)


class TestSpaceTimeAStar:
    """Space-Time A* tests."""

    def test_basic_path(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
            allow_wait=True,
        )

        planner = SpaceTimeAStar(
            grid=grid,
            max_time_steps=50,
        )

        trajectory = planner.search(
            start=(0, 0),
            goal=(0, 3),
            start_time=0,
        )

        assert trajectory is not None

        assert trajectory[0] == (
            0,
            0,
            0,
        )

        assert trajectory[-1][:2] == (
            0,
            3,
        )

        # Three moves means the shortest trajectory contains
        # four states.
        assert len(trajectory) == 4

    def test_time_steps_are_consecutive(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
        )

        planner = SpaceTimeAStar(
            grid=grid,
            max_time_steps=50,
        )

        trajectory = planner.search(
            start=(0, 0),
            goal=(4, 4),
        )

        assert trajectory is not None

        for index in range(1, len(trajectory)):
            previous_time = trajectory[
                index - 1
            ][2]

            current_time = trajectory[
                index
            ][2]

            assert current_time == previous_time + 1

    def test_static_obstacle_avoidance(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
            allow_wait=True,
        )

        # Block the direct top-row route.
        grid.add_static_obstacle((0, 1))
        grid.add_static_obstacle((0, 2))
        grid.add_static_obstacle((0, 3))

        planner = SpaceTimeAStar(
            grid=grid,
            max_time_steps=50,
        )

        trajectory = planner.search(
            start=(0, 0),
            goal=(0, 4),
        )

        assert trajectory is not None

        positions = {
            (row, col)
            for row, col, _ in trajectory
        }

        assert (0, 1) not in positions
        assert (0, 2) not in positions
        assert (0, 3) not in positions

    def test_no_path_when_goal_blocked(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
        )

        grid.add_static_obstacle(
            (4, 4)
        )

        planner = SpaceTimeAStar(
            grid=grid,
            max_time_steps=50,
        )

        trajectory = planner.search(
            start=(0, 0),
            goal=(4, 4),
        )

        assert trajectory is None

    def test_dynamic_obstacle_avoidance(self) -> None:
        grid = Grid(
            rows=3,
            cols=4,
        )

        obstacles = DynamicObstacleManager(
            grid
        )

        obstacles.add_obstacle(
            position=(0, 1),
            start_time=1,
            duration=5,
            obstacle_id="D1",
        )

        planner = SpaceTimeAStar(
            grid=grid,
            obstacle_manager=obstacles,
            max_time_steps=50,
        )

        trajectory = planner.search(
            start=(0, 0),
            goal=(0, 3),
        )

        assert trajectory is not None

        for row, col, timestep in trajectory:
            assert not obstacles.is_temporarily_blocked(
                (row, col),
                timestep,
            )

    def test_wait_action_can_be_used(self) -> None:
        grid = Grid(
            rows=2,
            cols=3,
            allow_wait=True,
        )

        obstacles = DynamicObstacleManager(
            grid
        )

        obstacles.add_obstacle(
            position=(0, 1),
            start_time=1,
            duration=1,
            obstacle_id="D1",
        )

        planner = SpaceTimeAStar(
            grid=grid,
            obstacle_manager=obstacles,
            max_time_steps=20,
        )

        trajectory = planner.search(
            start=(0, 0),
            goal=(0, 2),
        )

        assert trajectory is not None

        # The planner should find some valid solution, potentially
        # involving a wait or a detour.
        assert trajectory[-1][:2] == (
            0,
            2,
        )

    def test_reservation_table_blocks_vertex(self) -> None:
        grid = Grid(
            rows=3,
            cols=3,
        )

        reservations = ReservationTable()

        reservations.reserve_position(
            position=(1, 1),
            timestep=2,
        )

        assert reservations.is_position_reserved(
            (1, 1),
            2,
        )

        assert not reservations.is_position_reserved(
            (1, 1),
            1,
        )

        planner = SpaceTimeAStar(
            grid=grid,
            max_time_steps=20,
        )

        trajectory = planner.search(
            start=(1, 0),
            goal=(1, 2),
            reservations=reservations,
        )

        assert trajectory is not None

        assert (1, 1, 2) not in trajectory

    def test_reservation_table_prevents_head_on_edge_collision(
        self,
    ) -> None:
        grid = Grid(
            rows=2,
            cols=3,
            allow_wait=True,
        )

        reservations = ReservationTable()

        # Another agent moves:
        #
        # (0,1) at t=0 -> (0,0) at t=1
        #
        # Therefore this direct move is forbidden:
        #
        # (0,0) at t=0 -> (0,1) at t=1
        reservations.add_trajectory(
            [
                (0, 1, 0),
                (0, 0, 1),
            ]
        )

        assert reservations.is_edge_conflict(
            source=(0, 0),
            destination=(0, 1),
            timestep=0,
        )

        planner = SpaceTimeAStar(
            grid=grid,
            max_time_steps=10,
        )

        trajectory = planner.search(
            start=(0, 0),
            goal=(0, 2),
            reservations=reservations,
        )

        # A valid detour exists through the second row.
        assert trajectory is not None

        # The forbidden head-on transition must not occur.
        assert trajectory[:2] != [
            (0, 0, 0),
            (0, 1, 1),
        ]

        # The trajectory must still reach the goal.
        assert trajectory[-1][:2] == (
            0,
            2,
        )

        # The resulting trajectory must be spatially and
        # temporally valid.
        assert planner.validate_trajectory(
            trajectory,
            grid,
        )

    def test_validate_trajectory(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
        )

        planner = SpaceTimeAStar(
            grid=grid,
        )

        valid = [
            (0, 0, 0),
            (0, 1, 1),
            (0, 2, 2),
        ]

        invalid_jump = [
            (0, 0, 0),
            (0, 2, 1),
        ]

        assert planner.validate_trajectory(
            valid,
            grid,
        )

        assert not planner.validate_trajectory(
            invalid_jump,
            grid,
        )
