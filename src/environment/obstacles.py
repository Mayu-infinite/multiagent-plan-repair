"""
Dynamic obstacle management for the warehouse environment.

Static obstacles belong to Grid.

Dynamic obstacles are temporary blocked cells that are active
only during a particular time interval.

A dynamic obstacle is represented as:

    position = (row, column)
    start_time = t_start
    end_time = t_end

The obstacle is active when:

    start_time <= t < end_time

This convention makes the duration exactly:

    end_time - start_time
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, Optional

from .grid import Grid, Position


# ---------------------------------------------------------------------------
# Dynamic obstacle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DynamicObstacle:
    """
    A temporary obstacle occupying one grid cell.

    Parameters
    ----------
    obstacle_id:
        Unique identifier.

    position:
        Grid cell occupied by the obstacle.

    start_time:
        First timestep at which the obstacle is active.

    end_time:
        First timestep after the obstacle stops being active.

    Example
    -------
    start_time = 10
    end_time = 15

    The obstacle is active at:
        10, 11, 12, 13, 14

    Duration = 5 timesteps.
    """

    obstacle_id: str
    position: Position
    start_time: int
    end_time: int

    def __post_init__(self) -> None:
        """Validate the obstacle."""
        if (
            not isinstance(self.position, tuple)
            or len(self.position) != 2
            or not all(isinstance(v, int) for v in self.position)
        ):
            raise TypeError(
                "Obstacle position must be a tuple of two integers."
            )

        if self.start_time < 0:
            raise ValueError(
                "start_time cannot be negative."
            )

        if self.end_time <= self.start_time:
            raise ValueError(
                "end_time must be greater than start_time."
            )

    @property
    def duration(self) -> int:
        """Return obstacle duration."""
        return self.end_time - self.start_time

    def is_active(self, timestep: int) -> bool:
        """
        Return True if the obstacle is active at a timestep.
        """
        if timestep < 0:
            raise ValueError(
                "timestep cannot be negative."
            )

        return (
            self.start_time
            <= timestep
            < self.end_time
        )

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"DynamicObstacle("
            f"id={self.obstacle_id!r}, "
            f"position={self.position}, "
            f"start={self.start_time}, "
            f"end={self.end_time}"
            f")"
        )


# ---------------------------------------------------------------------------
# Dynamic obstacle manager
# ---------------------------------------------------------------------------

class DynamicObstacleManager:
    """
    Maintains all dynamic obstacles in the warehouse.

    The manager does not modify static obstacles in Grid.

    Parameters
    ----------
    grid:
        Warehouse Grid instance.
    """

    def __init__(
        self,
        grid: Grid,
    ) -> None:
        self.grid = grid

        self._obstacles: dict[str, DynamicObstacle] = {}

        self._next_id: int = 1

    # -----------------------------------------------------------------------
    # Obstacle registration
    # -----------------------------------------------------------------------

    def add_obstacle(
        self,
        position: Position,
        start_time: int,
        duration: int,
        obstacle_id: Optional[str] = None,
    ) -> DynamicObstacle:
        """
        Add a dynamic obstacle.

        Parameters
        ----------
        position:
            Grid cell to block.

        start_time:
            First active timestep.

        duration:
            Number of active timesteps.

        obstacle_id:
            Optional explicit identifier.

        Returns
        -------
        DynamicObstacle
            The newly created obstacle.
        """
        self._validate_position(position)

        if not self.grid.in_bounds(position):
            raise ValueError(
                f"Dynamic obstacle is outside grid: {position}"
            )

        if self.grid.is_static_obstacle(position):
            raise ValueError(
                f"Cannot create dynamic obstacle on static obstacle: "
                f"{position}"
            )

        if start_time < 0:
            raise ValueError(
                "start_time cannot be negative."
            )

        if duration <= 0:
            raise ValueError(
                "duration must be greater than zero."
            )

        if obstacle_id is None:
            obstacle_id = self._generate_id()

        if obstacle_id in self._obstacles:
            raise ValueError(
                f"Dynamic obstacle ID already exists: {obstacle_id}"
            )

        obstacle = DynamicObstacle(
            obstacle_id=obstacle_id,
            position=position,
            start_time=start_time,
            end_time=start_time + duration,
        )

        self._obstacles[obstacle_id] = obstacle

        return obstacle

    def remove_obstacle(
        self,
        obstacle_id: str,
    ) -> bool:
        """
        Remove an obstacle by ID.

        Returns True when an obstacle was removed and False if
        the ID did not exist.
        """
        if obstacle_id in self._obstacles:
            del self._obstacles[obstacle_id]
            return True

        return False

    def clear(self) -> None:
        """Remove all dynamic obstacles."""
        self._obstacles.clear()

    # -----------------------------------------------------------------------
    # Queries
    # -----------------------------------------------------------------------

    def get_obstacle(
        self,
        obstacle_id: str,
    ) -> Optional[DynamicObstacle]:
        """
        Return an obstacle by ID.
        """
        return self._obstacles.get(obstacle_id)

    def all_obstacles(self) -> list[DynamicObstacle]:
        """
        Return all registered dynamic obstacles.
        """
        return list(self._obstacles.values())

    def active_obstacles(
        self,
        timestep: int,
    ) -> list[DynamicObstacle]:
        """
        Return all obstacles active at a timestep.
        """
        return [
            obstacle
            for obstacle in self._obstacles.values()
            if obstacle.is_active(timestep)
        ]

    def blocked_positions(
        self,
        timestep: int,
    ) -> set[Position]:
        """
        Return the set of cells dynamically blocked at a timestep.
        """
        return {
            obstacle.position
            for obstacle in self.active_obstacles(timestep)
        }

    def is_blocked(
        self,
        position: Position,
        timestep: int,
    ) -> bool:
        """
        Return True if a position is blocked by a dynamic obstacle
        at the specified timestep.

        Static obstacles are also considered blocked.
        """
        self._validate_position(position)

        if not self.grid.in_bounds(position):
            return True

        if self.grid.is_static_obstacle(position):
            return True

        return position in self.blocked_positions(timestep)

    def is_temporarily_blocked(
        self,
        position: Position,
        timestep: int,
    ) -> bool:
        """
        Check only dynamic obstacles, excluding static obstacles.
        """
        self._validate_position(position)

        return any(
            obstacle.position == position
            and obstacle.is_active(timestep)
            for obstacle in self._obstacles.values()
        )

    def position_has_future_blockage(
        self,
        position: Position,
        start_time: int,
        end_time: int,
    ) -> bool:
        """
        Return True if a position has a dynamic obstacle active at
        any point in [start_time, end_time).

        Useful for plan validation and repair.
        """
        self._validate_position(position)

        if end_time <= start_time:
            raise ValueError(
                "end_time must be greater than start_time."
            )

        for obstacle in self._obstacles.values():
            if obstacle.position != position:
                continue

            # Intervals [a,b) and [c,d) overlap iff:
            #
            # a < d and c < b
            if (
                obstacle.start_time < end_time
                and start_time < obstacle.end_time
            ):
                return True

        return False

    # -----------------------------------------------------------------------
    # Random obstacle generation
    # -----------------------------------------------------------------------

    def generate_random_obstacles(
        self,
        density: float,
        current_time: int,
        duration_min: int,
        duration_max: int,
        reserved_positions: Optional[Iterable[Position]] = None,
        rng: Optional[random.Random] = None,
        replace_existing: bool = False,
    ) -> list[DynamicObstacle]:
        """
        Generate dynamic obstacles according to a density.

        Parameters
        ----------
        density:
            Fraction of eligible free cells to temporarily block.

            Example:
                density = 0.10
                means approximately 10% of eligible cells.

        current_time:
            Time at which generated obstacles begin.

        duration_min:
            Minimum duration.

        duration_max:
            Maximum duration.

        reserved_positions:
            Cells that must not be blocked.

            This will later be used to protect active task cells,
            agent positions, pickup locations, and delivery locations
            when appropriate.

        rng:
            Optional random number generator.

        replace_existing:
            If True, remove all existing dynamic obstacles before
            generating new ones.

        Returns
        -------
        list[DynamicObstacle]
            Newly generated obstacles.
        """
        if not 0.0 <= density <= 1.0:
            raise ValueError(
                "density must be between 0.0 and 1.0."
            )

        if current_time < 0:
            raise ValueError(
                "current_time cannot be negative."
            )

        if duration_min <= 0:
            raise ValueError(
                "duration_min must be greater than zero."
            )

        if duration_max < duration_min:
            raise ValueError(
                "duration_max must be greater than or equal "
                "to duration_min."
            )

        if reserved_positions is None:
            reserved: set[Position] = set()
        else:
            reserved = set(reserved_positions)

        for position in reserved:
            self._validate_position(position)

        if replace_existing:
            self.clear()

        if rng is None:
            rng = random

        eligible_positions = [
            position
            for position in self.grid.walkable_positions()
            if position not in reserved
            and position not in self.blocked_positions(current_time)
        ]

        if not eligible_positions:
            return []

        number_to_generate = int(
            round(len(eligible_positions) * density)
        )

        # For a non-zero density, ensure that we can create at least
        # one obstacle when there is at least one eligible position.
        if density > 0.0 and number_to_generate == 0:
            number_to_generate = 1

        number_to_generate = min(
            number_to_generate,
            len(eligible_positions),
        )

        selected_positions = rng.sample(
            eligible_positions,
            number_to_generate,
        )

        generated: list[DynamicObstacle] = []

        for position in selected_positions:
            duration = rng.randint(
                duration_min,
                duration_max,
            )

            obstacle = self.add_obstacle(
                position=position,
                start_time=current_time,
                duration=duration,
            )

            generated.append(obstacle)

        return generated

    # -----------------------------------------------------------------------
    # Maintenance
    # -----------------------------------------------------------------------

    def remove_expired(
        self,
        current_time: int,
    ) -> list[str]:
        """
        Remove obstacles that are no longer active and return their IDs.

        An obstacle is considered expired when:

            end_time <= current_time
        """
        expired_ids = [
            obstacle.obstacle_id
            for obstacle in self._obstacles.values()
            if obstacle.end_time <= current_time
        ]

        for obstacle_id in expired_ids:
            del self._obstacles[obstacle_id]

        return expired_ids

    # -----------------------------------------------------------------------
    # Statistics
    # -----------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Return the number of registered dynamic obstacles."""
        return len(self._obstacles)

    def active_count(
        self,
        timestep: int,
    ) -> int:
        """Return the number of active dynamic obstacles."""
        return len(self.active_obstacles(timestep))

    # -----------------------------------------------------------------------
    # Utility
    # -----------------------------------------------------------------------

    def snapshot(
        self,
        timestep: int,
    ) -> dict[str, object]:
        """
        Return a simple environment snapshot for logging and
        visualization.
        """
        active = self.active_obstacles(timestep)

        return {
            "timestep": timestep,
            "active_obstacle_count": len(active),
            "active_obstacles": [
                {
                    "id": obstacle.obstacle_id,
                    "position": obstacle.position,
                    "start_time": obstacle.start_time,
                    "end_time": obstacle.end_time,
                }
                for obstacle in active
            ],
        }

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"DynamicObstacleManager("
            f"obstacles={len(self._obstacles)}"
            f")"
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _validate_position(
        position: Position,
    ) -> None:
        """
        Validate a 2D grid position.
        """
        if (
            not isinstance(position, tuple)
            or len(position) != 2
            or not all(isinstance(value, int) for value in position)
        ):
            raise TypeError(
                "Position must be a tuple of two integers. "
                f"Received: {position!r}"
            )

    def _generate_id(self) -> str:
        """
        Generate a unique dynamic-obstacle identifier.
        """
        while True:
            obstacle_id = f"dyn-{self._next_id}"
            self._next_id += 1

            if obstacle_id not in self._obstacles:
                return obstacle_id