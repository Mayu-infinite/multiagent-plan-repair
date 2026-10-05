"""

Space-Time A* for multi-agent path planning.

Unlike ordinary A*, which searches over spatial states:

    (row, column)

Space-Time A* searches over:

    (row, column, timestep)

This allows the planner to reason about:

    - dynamic obstacles,

    - waiting,

    - previously reserved agent trajectories,

    - vertex conflicts,

    - edge conflicts.

The same implementation can later be reused by the local plan-repair

module. The repair layer should call this planner only for the affected

local portion of a trajectory rather than rebuilding the entire MAPF plan.

"""

from __future__ import annotations

import heapq

from dataclasses import dataclass

from math import inf

from typing import Iterable, Optional

from ..environment import (

    DynamicObstacleManager,

    Grid,

    Position,

)

from ..agents.agent import (

    SpaceTimeState,

    Trajectory,

)

# ---------------------------------------------------------------------------

# Reservation table

# ---------------------------------------------------------------------------

class ReservationTable:

    """

    Stores space-time reservations made by already-planned agents.

    Vertex reservation

    ------------------

    A cell is occupied by another agent at a particular timestep.

        reservations[t] = {(r1, c1), (r2, c2), ...}

    Edge reservation

    ----------------

    An agent moves from one cell to another between two consecutive

    timesteps.

        edge_reservations[t] =

            {

                ((r1, c1), (r2, c2)),

                ...

            }

    A candidate move checks both:

        1. destination vertex reservation,

        2. reverse edge reservation.

    This prevents both vertex conflicts and head-on edge conflicts.

    """

    def __init__(self) -> None:

        self._vertex_reservations: dict[int, set[Position]] = {}

        self._edge_reservations: dict[

            int,

            set[tuple[Position, Position]],

        ] = {}

# -----------------------------------------------------------------------

# Add reservations

# -----------------------------------------------------------------------

    def reserve_position(

        self,

        position: Position,

        timestep: int,

    ) -> None:

        """Reserve one grid position at one timestep."""

        if timestep < 0:

            raise ValueError("timestep cannot be negative.")

        self._vertex_reservations.setdefault(

            timestep,

            set(),

        ).add(position)

    def reserve_edge(

        self,

        source: Position,

        destination: Position,

        timestep: int,

    ) -> None:

        """

        Reserve movement from source at timestep t to destination

        at timestep t+1.

        """

        if timestep < 0:

            raise ValueError("timestep cannot be negative.")

        self._edge_reservations.setdefault(

            timestep,

            set(),

        ).add((source, destination))

    def add_trajectory(

        self,

        trajectory: Iterable[SpaceTimeState],

        *,

        reserve_start: bool = True,

    ) -> None:

        """

        Add an entire trajectory to the reservation table.

        Parameters

        ----------

        trajectory:

            Sequence of (row, column, timestep).

        reserve_start:

            Whether to reserve the first state as well.

        """

        states = list(trajectory)

        if not states:

            return

        for index, (row, col, timestep) in enumerate(states):

            position = (row, col)

            if index > 0 or reserve_start:

                self.reserve_position(

                    position,

                    timestep,

                )

            if index > 0:

                previous_row, previous_col, previous_time = (

                    states[index - 1]

                )

# Consecutive states should represent consecutive

# timesteps.

                if timestep != previous_time + 1:

                    raise ValueError(

                        "Trajectory must contain consecutive timesteps "

                        "when inserted into the reservation table."

                    )

                self.reserve_edge(

                    source=(previous_row, previous_col),

                    destination=position,

                    timestep=previous_time,

                )

# -----------------------------------------------------------------------

# Queries

# -----------------------------------------------------------------------

    def is_position_reserved(

        self,

        position: Position,

        timestep: int,

    ) -> bool:

        """Return True if a position is reserved at a timestep."""

        return position in self._vertex_reservations.get(

            timestep,

            set(),

        )

    def is_edge_reserved(

        self,

        source: Position,

        destination: Position,

        timestep: int,

    ) -> bool:

        """

        Return True if another agent is using the same edge.

        This checks the exact directed edge.

        """

        return (

            source,

            destination,

        ) in self._edge_reservations.get(

            timestep,

            set(),

        )

    def is_edge_conflict(

        self,

        source: Position,

        destination: Position,

        timestep: int,

    ) -> bool:

        """

        Check whether moving source -> destination at timestep t

        would create an edge conflict.

        A conflict occurs when another agent moves:

            destination -> source

        during the same timestep interval.

        """

        edges = self._edge_reservations.get(

            timestep,

            set(),

        )

        return (

            source,

            destination,

        ) in edges or (

            destination,

            source,

        ) in edges

    def clear(self) -> None:

        """Remove every reservation."""

        self._vertex_reservations.clear()

        self._edge_reservations.clear()

    @property

    def vertex_count(self) -> int:

        """Return total number of vertex reservations."""

        return sum(

            len(values)

            for values in self._vertex_reservations.values()

        )

    @property

    def edge_count(self) -> int:

        """Return total number of edge reservations."""

        return sum(

            len(values)

            for values in self._edge_reservations.values()

        )

    def __repr__(self) -> str:

        return (

            f"ReservationTable("

            f"vertices={self.vertex_count}, "

            f"edges={self.edge_count}"

            f")"

        )

# ---------------------------------------------------------------------------

# A* search state

# ---------------------------------------------------------------------------

@dataclass(frozen=True)

class _SearchState:

    """

    Internal A* state.

    \`position\` and \`timestep\` together represent a space-time state.

    """

    position: Position

    timestep: int

# ---------------------------------------------------------------------------

# Space-Time A*

# ---------------------------------------------------------------------------

class SpaceTimeAStar:

    """

    Space-Time A* path planner.

    Parameters

    ----------

    grid:

        Warehouse grid.

    obstacle_manager:

        Optional dynamic obstacle manager.

    max_time_steps:

        Maximum timestep to explore.

    max_search_nodes:

        Maximum number of expanded search states.

    heuristic:

        Currently supported:

            "manhattan"

            "chebyshev"

    """

    def __init__(

        self,

        grid: Grid,

        obstacle_manager: Optional[DynamicObstacleManager] = None,

        *,

        max_time_steps: int = 500,

        max_search_nodes: int = 50000,

        heuristic: str = "manhattan",

    ) -> None:

        if max_time_steps < 0:

            raise ValueError(

                "max_time_steps cannot be negative."

            )

        if max_search_nodes <= 0:

            raise ValueError(

                "max_search_nodes must be greater than zero."

            )

        heuristic = heuristic.lower().strip()

        if heuristic not in {

            "manhattan",

            "chebyshev",

        }:

            raise ValueError(

                "Unsupported heuristic. Use 'manhattan' or 'chebyshev'."

            )

        self.grid = grid

        self.obstacle_manager = obstacle_manager

        self.max_time_steps = max_time_steps

        self.max_search_nodes = max_search_nodes

        self.heuristic_name = heuristic

# -----------------------------------------------------------------------

# Public search interface

# -----------------------------------------------------------------------

    def search(

        self,

        start: Position,

        goal: Position,

        *,

        start_time: int = 0,

        reservations: Optional[ReservationTable] = None,

        max_time_steps: Optional[int] = None,

        require_goal_hold: bool = False,

    ) -> Optional[Trajectory]:

        """

        Find a collision-free space-time path from start to goal.

        Parameters

        ----------

        start:

            Starting position.

        goal:

            Goal position.

        start_time:

            Time at which the agent occupies start.

        reservations:

            Existing trajectories of other agents.

        max_time_steps:

            Optional search horizon overriding the configured value.

        Returns

        -------

        list[(row, col, timestep)] | None

            A valid trajectory, or None when no path is found.

        """

        self._validate_position(start, "start")

        self._validate_position(goal, "goal")

        if not self.grid.in_bounds(start):

            raise ValueError(

                f"Start is outside the grid: {start}"

            )

        if not self.grid.in_bounds(goal):

            raise ValueError(

                f"Goal is outside the grid: {goal}"

            )

        if start_time < 0:

            raise ValueError(

                "start_time cannot be negative."

            )

        if not self.grid.is_walkable(start):

            return None

        if not self.grid.is_walkable(goal):

            return None

        if max_time_steps is None:

            horizon = self.max_time_steps

        else:

            if max_time_steps < start_time:

                return None

            horizon = max_time_steps

        if start_time > horizon:

            return None

        if reservations is None:

            reservations = ReservationTable()

# -------------------------------------------------------------------

# Immediate start/goal case.

# -------------------------------------------------------------------

        if start == goal:

            if not self._state_is_available(

                position=start,

                timestep=start_time,

                reservations=reservations,

            ):

                return None

            if self._dynamic_obstacle_blocks(

                position=start,

                timestep=start_time,

            ):

                return None

            if require_goal_hold:

                for future_time in range(

                    start_time + 1,

                    horizon + 1,

                ):

                    if reservations.is_position_reserved(

                        start,

                        future_time,

                    ):

                        return None

            return [

                (

                    start[0],

                    start[1],

                    start_time,

                )

            ]

# -------------------------------------------------------------------

# A* initialization.

# -------------------------------------------------------------------

        start_state = _SearchState(

            position=start,

            timestep=start_time,

        )

        open_heap: list[

            tuple[

                float,

                float,

                int,

                _SearchState,

            ]

        ] = []

# Counter gives deterministic tie breaking when f and g are equal.

        counter = 0

        start_h = self.heuristic(

            start,

            goal,

        )

        heapq.heappush(

            open_heap,

            (

                float(start_h),

                0.0,

                counter,

                start_state,

            ),

        )

        g_score: dict[_SearchState, float] = {

            start_state: 0.0,

        }

        parent: dict[

            _SearchState,

            Optional[_SearchState],

        ] = {

            start_state: None,

        }

        closed: set[_SearchState] = set()

        expanded_nodes = 0

# -------------------------------------------------------------------

# Search.

# -------------------------------------------------------------------

        while open_heap:

            (

                _f_score,

                current_g,

                _counter,

                current_state,

            ) = heapq.heappop(open_heap)

            if current_state in closed:

                continue

            closed.add(current_state)

            expanded_nodes += 1

            if expanded_nodes > self.max_search_nodes:

                return None

            current_position = current_state.position

            current_time = current_state.timestep

# ----------------------------------------------------------------

# Goal test.

# ----------------------------------------------------------------

            if current_position == goal:

                if not require_goal_hold:

                    return self._reconstruct_path(

                        parent,

                        current_state,

                    )

                goal_is_safe = True

                for future_time in range(

                    current_time + 1,

                    horizon + 1,

                ):

                    if reservations.is_position_reserved(

                        goal,

                        future_time,

                    ):

                        goal_is_safe = False

                        break

                if goal_is_safe:

                    return self._reconstruct_path(

                        parent,

                        current_state,

                    )

            if current_time >= horizon:

                continue

            next_time = current_time + 1

# ----------------------------------------------------------------

# Explore valid one-step actions.

# ----------------------------------------------------------------

            for next_position in self.grid.neighbors(

                current_position,

                include_wait=True,

            ):

# Grid-level movement validation.

                if not self._valid_transition(

                    current_position,

                    next_position,

                ):

                    continue

# Dynamic obstacle check at arrival time.

                if self._dynamic_obstacle_blocks(

                    position=next_position,

                    timestep=next_time,

                ):

                    continue

# Vertex reservation.

                if reservations.is_position_reserved(

                    next_position,

                    next_time,

                ):

                    continue

# Edge reservation / head-on collision.

                if reservations.is_edge_conflict(

                    source=current_position,

                    destination=next_position,

                    timestep=current_time,

                ):

                    continue

                next_state = _SearchState(

                    position=next_position,

                    timestep=next_time,

                )

                if next_state in closed:

                    continue

                transition_cost = self.grid.movement_cost(

                    current_position,

                    next_position,

                )

                tentative_g = (

                    current_g

                    + transition_cost

                )

                previous_g = g_score.get(

                    next_state,

                    inf,

                )

                if tentative_g >= previous_g:

                    continue

                g_score[next_state] = tentative_g

                parent[next_state] = current_state

                h_score = self.heuristic(

                    next_position,

                    goal,

                )

                f_score = tentative_g + h_score

                counter += 1

                heapq.heappush(

                    open_heap,

                    (

                        f_score,

                        tentative_g,

                        counter,

                        next_state,

                    ),

                )

# No solution found.

        return None

# -----------------------------------------------------------------------

# Heuristic

# -----------------------------------------------------------------------

    def heuristic(

        self,

        source: Position,

        goal: Position,

    ) -> int:

        """

        Calculate the spatial heuristic.

        """

        if self.heuristic_name == "chebyshev":

            return self.grid.chebyshev_distance(

                source,

                goal,

            )

        return self.grid.manhattan_distance(

            source,

            goal,

        )

# -----------------------------------------------------------------------

# Path utilities

# -----------------------------------------------------------------------

    @staticmethod

    def path_cost(

        trajectory: Trajectory,

        grid: Grid,

    ) -> float:

        """

        Calculate the total movement/wait cost of a trajectory.

        """

        if len(trajectory) <= 1:

            return 0.0

        total_cost = 0.0

        for index in range(1, len(trajectory)):

            row1, col1, time1 = trajectory[index - 1]

            row2, col2, time2 = trajectory[index]

            if time2 != time1 + 1:

                raise ValueError(

                    "Trajectory must have consecutive timesteps."

                )

            total_cost += grid.movement_cost(

                (row1, col1),

                (row2, col2),

            )

        return total_cost

    @staticmethod

    def validate_trajectory(

        trajectory: Trajectory,

        grid: Grid,

        obstacle_manager: Optional[DynamicObstacleManager] = None,

    ) -> bool:

        """

        Validate spatial and temporal consistency of a trajectory.

        """

        if not trajectory:

            return False

        for index, state in enumerate(trajectory):

            row, col, timestep = state

            position = (row, col)

            if not grid.in_bounds(position):

                return False

            if not grid.is_walkable(position):

                return False

            if timestep < 0:

                return False

            if index == 0:

                continue

            previous_row, previous_col, previous_time = (

                trajectory[index - 1]

            )

            if timestep != previous_time + 1:

                return False

            previous_position = (

                previous_row,

                previous_col,

            )

            if position not in grid.neighbors(

                previous_position,

                include_wait=True,

            ):

                return False

            if obstacle_manager is not None:

                if obstacle_manager.is_blocked(

                    position,

                    timestep,

                ):

                    return False

        return True

# -----------------------------------------------------------------------

# Internal methods

# -----------------------------------------------------------------------

    def _state_is_available(

        self,

        position: Position,

        timestep: int,

        reservations: ReservationTable,

    ) -> bool:

        """

        Check whether a state can be occupied.

        """

        if reservations.is_position_reserved(

            position,

            timestep,

        ):

            return False

        if self._dynamic_obstacle_blocks(

            position,

            timestep,

        ):

            return False

        return True

    def _dynamic_obstacle_blocks(

        self,

        position: Position,

        timestep: int,

    ) -> bool:

        """

        Check dynamic and static occupancy.

        Static obstacle checking is already handled by Grid, but

        keeping that responsibility here makes this method robust.

        """

        if self.grid.is_static_obstacle(position):

            return True

        if self.obstacle_manager is None:

            return False

        return self.obstacle_manager.is_temporarily_blocked(

            position,

            timestep,

        )

    def _valid_transition(

        self,

        source: Position,

        destination: Position,

    ) -> bool:

        """

        Check whether one grid action is spatially valid.

        """

        if not self.grid.is_walkable(destination):

            return False

        return destination in self.grid.neighbors(

            source,

            include_wait=True,

        )

    @staticmethod

    def _validate_position(

        position: Position,

        name: str,

    ) -> None:

        """

        Validate a position.

        """

        if (

            not isinstance(position, tuple)

            or len(position) != 2

            or not all(isinstance(v, int) for v in position)

        ):

            raise TypeError(

                f"{name} must be a tuple of two integers. "

                f"Received: {position!r}"

            )

    @staticmethod

    def _reconstruct_path(

        parent: dict[

            _SearchState,

            Optional[_SearchState],

        ],

        goal_state: _SearchState,

    ) -> Trajectory:

        """

        Reconstruct a trajectory from A* parent pointers.

        """

        states: list[SpaceTimeState] = []

        current: Optional[_SearchState] = goal_state

        while current is not None:

            states.append(

                (

                    current.position[0],

                    current.position[1],

                    current.timestep,

                )

            )

            current = parent[current]

        states.reverse()

        return states
