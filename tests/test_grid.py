"""
Tests for the warehouse Grid environment.
"""

from __future__ import annotations

import pytest

from src.environment import Grid


class TestGridBasics:
    """Basic grid functionality."""

    def test_grid_dimensions(self) -> None:
        grid = Grid(
            rows=5,
            cols=7,
        )

        assert grid.rows == 5
        assert grid.cols == 7

    def test_in_bounds(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
        )

        assert grid.in_bounds((0, 0))
        assert grid.in_bounds((4, 4))

        assert not grid.in_bounds((-1, 0))
        assert not grid.in_bounds((0, 5))
        assert not grid.in_bounds((5, 0))

    def test_invalid_position_type(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
        )

        with pytest.raises(TypeError):
            grid.in_bounds([1, 2])  # type: ignore[arg-type]


class TestGridObstacles:
    """Static obstacle behavior."""

    def test_static_obstacle(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
        )

        grid.add_static_obstacle((2, 2))

        assert grid.is_static_obstacle((2, 2))
        assert not grid.is_walkable((2, 2))
        assert grid.is_walkable((1, 2))

    def test_remove_static_obstacle(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
        )

        grid.add_static_obstacle((2, 2))
        assert not grid.is_walkable((2, 2))

        grid.remove_static_obstacle((2, 2))

        assert not grid.is_static_obstacle((2, 2))
        assert grid.is_walkable((2, 2))

    def test_out_of_bounds_obstacle_rejected(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
        )

        with pytest.raises(ValueError):
            grid.add_static_obstacle((10, 10))


class TestGridNeighbors:
    """Neighbor generation."""

    def test_four_directional_neighbors(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
            allow_diagonal=False,
            allow_wait=False,
        )

        neighbors = set(
            grid.neighbors(
                (2, 2),
                include_wait=False,
            )
        )

        expected = {
            (1, 2),
            (3, 2),
            (2, 1),
            (2, 3),
        }

        assert neighbors == expected

    def test_wait_action(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
            allow_wait=True,
        )

        neighbors = set(
            grid.neighbors(
                (2, 2),
                include_wait=True,
            )
        )

        assert (2, 2) in neighbors

    def test_corner_neighbors(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
            allow_wait=False,
        )

        neighbors = set(
            grid.neighbors(
                (0, 0),
                include_wait=False,
            )
        )

        assert neighbors == {
            (1, 0),
            (0, 1),
        }

    def test_obstacle_removed_from_neighbors(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
            allow_wait=False,
        )

        grid.add_static_obstacle((1, 2))

        neighbors = set(
            grid.neighbors(
                (2, 2),
                include_wait=False,
            )
        )

        assert (1, 2) not in neighbors
        assert (3, 2) in neighbors


class TestGridCosts:
    """Movement and heuristic tests."""

    def test_movement_cost(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
            move_cost=2.0,
            wait_cost=0.5,
        )

        assert grid.movement_cost(
            (1, 1),
            (1, 2),
        ) == 2.0

        assert grid.movement_cost(
            (1, 1),
            (1, 1),
        ) == 0.5

    def test_manhattan_distance(self) -> None:
        assert Grid.manhattan_distance(
            (0, 0),
            (3, 4),
        ) == 7

        assert Grid.manhattan_distance(
            (4, 4),
            (1, 2),
        ) == 5

    def test_heuristic(self) -> None:
        grid = Grid(
            rows=10,
            cols=10,
            allow_diagonal=False,
        )

        assert grid.heuristic(
            (0, 0),
            (4, 5),
        ) == 9

    def test_invalid_wait_when_wait_disabled(self) -> None:
        grid = Grid(
            rows=5,
            cols=5,
            allow_wait=False,
        )

        with pytest.raises(ValueError):
            grid.movement_cost(
                (2, 2),
                (2, 2),
            )


class TestGridUtilities:
    """Utility methods."""

    def test_all_positions(self) -> None:
        grid = Grid(
            rows=2,
            cols=3,
        )

        positions = set(
            grid.all_positions()
        )

        expected = {
            (0, 0),
            (0, 1),
            (0, 2),
            (1, 0),
            (1, 1),
            (1, 2),
        }

        assert positions == expected

    def test_free_cell_count(self) -> None:
        grid = Grid(
            rows=3,
            cols=3,
        )

        grid.add_static_obstacle((1, 1))
        grid.add_static_obstacle((2, 2))

        assert grid.free_cell_count() == 7
        assert grid.obstacle_count() == 2

    def test_ascii_display(self) -> None:
        grid = Grid(
            rows=3,
            cols=3,
        )

        grid.add_static_obstacle((1, 1))

        output = grid.display_ascii(
            marked_positions={
                (0, 0): "A",
            }
        )

        assert "A" in output
        assert "#" in output
        assert "." in output