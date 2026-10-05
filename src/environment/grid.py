"""
Warehouse grid environment.

This module represents the static spatial structure of the warehouse.

Responsibilities
----------------
- Store grid dimensions.
- Store static obstacles.
- Validate grid positions.
- Return valid neighboring positions.
- Support four-directional movement.
- Optionally support waiting.
- Provide movement costs.
- Provide Manhattan-distance heuristic.

The grid does not know anything about agents or tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import inf
from typing import Iterable

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Position = tuple[int, int]


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

@dataclass
class Grid:
    """
    Two-dimensional warehouse grid.

    Parameters
    ----------
    rows:
        Number of rows in the warehouse.

    cols:
        Number of columns in the warehouse.

    static_obstacles:
        Optional iterable of cells that are blocked permanently.

    allow_diagonal:
        Whether diagonal movement is permitted.

    allow_wait:
        Whether an agent may remain in the same cell for one timestep.

    move_cost:
        Cost of moving to an adjacent cell.

    wait_cost:
        Cost of waiting for one timestep.
    """

    rows: int
    cols: int

    static_obstacles: set[Position] = field(default_factory=set)

    allow_diagonal: bool = False
    allow_wait: bool = True

    move_cost: float = 1.0
    wait_cost: float = 1.0

    # -----------------------------------------------------------------------
    # Initialization
    # -----------------------------------------------------------------------

    def __post_init__(self) -> None:
        """Validate the grid configuration."""
        if self.rows <= 0:
            raise ValueError("rows must be greater than zero.")

        if self.cols <= 0:
            raise ValueError("cols must be greater than zero.")

        if self.move_cost <= 0:
            raise ValueError("move_cost must be greater than zero.")

        if self.wait_cost <= 0:
            raise ValueError("wait_cost must be greater than zero.")

        # Always store obstacles as a set.
        self.static_obstacles = set(self.static_obstacles)

        invalid_obstacles = {
            position
            for position in self.static_obstacles
            if not self.in_bounds(position)
        }

        if invalid_obstacles:
            raise ValueError(
                "Static obstacles contain positions outside the grid: "
                f"{sorted(invalid_obstacles)}"
            )

    # -----------------------------------------------------------------------
    # Basic spatial queries
    # -----------------------------------------------------------------------

    def in_bounds(self, position: Position) -> bool:
        """
        Return True if a position lies inside the grid.

        Parameters
        ----------
        position:
            `(row, column)`.
        """
        row, col = self._validate_position(position)

        return (
            0 <= row < self.rows
            and 0 <= col < self.cols
        )

    def is_static_obstacle(self, position: Position) -> bool:
        """
        Return True if the position is permanently blocked.
        """
        self._validate_position(position)

        return position in self.static_obstacles

    def is_walkable(self, position: Position) -> bool:
        """
        Return True if a position is inside the warehouse and
        not occupied by a static obstacle.
        """
        return (
            self.in_bounds(position)
            and not self.is_static_obstacle(position)
        )

    # -----------------------------------------------------------------------
    # Obstacle modification
    # -----------------------------------------------------------------------

    def add_static_obstacle(self, position: Position) -> None:
        """
        Permanently block a grid cell.
        """
        self._validate_position(position)

        if not self.in_bounds(position):
            raise ValueError(
                f"Cannot add obstacle outside grid: {position}"
            )

        self.static_obstacles.add(position)

    def remove_static_obstacle(self, position: Position) -> None:
        """
        Remove a permanent obstacle from a grid cell.
        """
        self._validate_position(position)
        self.static_obstacles.discard(position)

    def clear_static_obstacles(self) -> None:
        """Remove all static obstacles."""
        self.static_obstacles.clear()

    # -----------------------------------------------------------------------
    # Neighbor generation
    # -----------------------------------------------------------------------

    def neighbors(
        self,
        position: Position,
        include_wait: bool | None = None,
    ) -> list[Position]:
        """
        Return valid positions reachable in one timestep.

        Movement is four-connected by default:

                    UP
                    ↑
              LEFT ← P → RIGHT
                    ↓
                   DOWN

        If diagonal movement is enabled, the four diagonal positions
        are also considered.

        If waiting is enabled, the current position itself is included.
        """
        if not self.is_walkable(position):
            return []

        row, col = position

        # Cardinal directions.
        directions: list[tuple[int, int]] = [
            (-1, 0),  # UP
            (1, 0),   # DOWN
            (0, -1),  # LEFT
            (0, 1),   # RIGHT
        ]

        # Optional diagonal movement.
        if self.allow_diagonal:
            directions.extend(
                [
                    (-1, -1),
                    (-1, 1),
                    (1, -1),
                    (1, 1),
                ]
            )

        result: list[Position] = []

        for d_row, d_col in directions:
            candidate = (
                row + d_row,
                col + d_col,
            )

            if self.is_walkable(candidate):
                result.append(candidate)

        # Waiting is represented by remaining in the same cell.
        if include_wait is None:
            include_wait = self.allow_wait

        if include_wait and self.is_walkable(position):
            result.append(position)

        return result

    # -----------------------------------------------------------------------
    # Costs
    # -----------------------------------------------------------------------

    def movement_cost(
        self,
        source: Position,
        destination: Position,
    ) -> float:
        """
        Return the cost of moving from source to destination.

        Waiting and movement can have different costs.
        """
        if not self.in_bounds(source):
            raise ValueError(
                f"Source position is outside grid: {source}"
            )

        if not self.in_bounds(destination):
            raise ValueError(
                f"Destination position is outside grid: {destination}"
            )

        if not self.is_walkable(destination):
            raise ValueError(
                f"Destination is a static obstacle: {destination}"
            )

        if source == destination:
            if not self.allow_wait:
                raise ValueError(
                    "Waiting is disabled for this grid."
                )

            return self.wait_cost

        if destination not in self.neighbors(
            source,
            include_wait=False,
        ):
            raise ValueError(
                f"Invalid movement from {source} to {destination}"
            )

        if self.allow_diagonal and self._is_diagonal(
            source,
            destination,
        ):
            # For now diagonal movement has the same configured
            # movement cost. Diagonal movement is disabled by default.
            return self.move_cost

        return self.move_cost

    # -----------------------------------------------------------------------
    # Heuristics
    # -----------------------------------------------------------------------

    @staticmethod
    def manhattan_distance(
        source: Position,
        destination: Position,
    ) -> int:
        """
        Return the Manhattan distance between two positions.

        h(n) = |x1 - x2| + |y1 - y2|

        This is the default heuristic used by Space-Time A* when
        diagonal movement is disabled.
        """
        Grid._validate_position(source)
        Grid._validate_position(destination)

        return (
            abs(source[0] - destination[0])
            + abs(source[1] - destination[1])
        )

    @staticmethod
    def chebyshev_distance(
        source: Position,
        destination: Position,
    ) -> int:
        """
        Return the Chebyshev distance.

        Useful when diagonal movement is enabled.
        """
        Grid._validate_position(source)
        Grid._validate_position(destination)

        return max(
            abs(source[0] - destination[0]),
            abs(source[1] - destination[1]),
        )

    def heuristic(
        self,
        source: Position,
        destination: Position,
    ) -> int:
        """
        Return the configured spatial heuristic.

        Manhattan distance is used for the default four-connected
        warehouse movement model.
        """
        if self.allow_diagonal:
            return self.chebyshev_distance(
                source,
                destination,
            )

        return self.manhattan_distance(
            source,
            destination,
        )

    # -----------------------------------------------------------------------
    # Cell enumeration
    # -----------------------------------------------------------------------

    def all_positions(self) -> Iterable[Position]:
        """
        Yield every cell in the grid.

        Useful for visualization, obstacle generation, and experiments.
        """
        for row in range(self.rows):
            for col in range(self.cols):
                yield (row, col)

    def walkable_positions(self) -> list[Position]:
        """
        Return all currently walkable cells considering only static
        obstacles.
        """
        return [
            position
            for position in self.all_positions()
            if self.is_walkable(position)
        ]

    def free_cell_count(self) -> int:
        """
        Return the number of walkable cells.
        """
        return len(self.walkable_positions())

    def obstacle_count(self) -> int:
        """
        Return the number of static obstacles.
        """
        return len(self.static_obstacles)

    # -----------------------------------------------------------------------
    # Utility
    # -----------------------------------------------------------------------

    def copy(self) -> Grid:
        """
        Return an independent copy of the grid.
        """
        return Grid(
            rows=self.rows,
            cols=self.cols,
            static_obstacles=set(self.static_obstacles),
            allow_diagonal=self.allow_diagonal,
            allow_wait=self.allow_wait,
            move_cost=self.move_cost,
            wait_cost=self.wait_cost,
        )

    def display_ascii(
        self,
        marked_positions: dict[Position, str] | None = None,
    ) -> str:
        """
        Return an ASCII representation of the warehouse.

        Symbols:
            # = static obstacle
            . = free cell
            custom symbols = marked positions

        This is useful for debugging before we build the graphical
        visualizer.
        """
        marked_positions = marked_positions or {}

        lines: list[str] = []

        for row in range(self.rows):
            cells: list[str] = []

            for col in range(self.cols):
                position = (row, col)

                if position in marked_positions:
                    cells.append(str(marked_positions[position])[:1])
                elif position in self.static_obstacles:
                    cells.append("#")
                else:
                    cells.append(".")

            lines.append(" ".join(cells))

        return "\n".join(lines)

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"Grid("
            f"rows={self.rows}, "
            f"cols={self.cols}, "
            f"static_obstacles={len(self.static_obstacles)}, "
            f"allow_diagonal={self.allow_diagonal}, "
            f"allow_wait={self.allow_wait}"
            f")"
        )

    # -----------------------------------------------------------------------
    # Internal validation
    # -----------------------------------------------------------------------

    @staticmethod
    def _validate_position(
        position: Position,
    ) -> Position:
        """
        Validate and return a position.
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

        return position

    @staticmethod
    def _is_diagonal(
        source: Position,
        destination: Position,
    ) -> bool:
        """
        Return True if source and destination differ in both dimensions.
        """
        return (
            abs(source[0] - destination[0]) == 1
            and abs(source[1] - destination[1]) == 1
        )