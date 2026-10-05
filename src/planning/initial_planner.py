"""

Initial multi-agent planner.

This module constructs the initial warehouse plan before execution.

Planning strategy

-----------------

A prioritized Space-Time A* strategy is used:

    1. Determine agent planning order.

    2. Plan the first agent.

    3. Reserve its trajectory.

    4. Plan the next agent around existing reservations.

    5. Repeat for all agents.

    6. Validate the complete solution.

The resulting trajectories become each agent's ORIGINAL PLAN.

Important

---------

This module is for INITIAL planning.

The repair subsystem must not call \\\`plan_all()\\\` after every disruption.

Instead, it will use the same Space-Time A* primitive for local

trajectory repair.

"""

from __future__ import annotations

from dataclasses import dataclass

from typing import Iterable, Optional, Sequence

from ..agents import Agent, Task

from ..environment import (

    DynamicObstacleManager,

    Grid,

    Position,

)

from .conflict_detection import (

    Conflict,

    ConflictDetector,

)

from .space_time_astar import (

    ReservationTable,

    SpaceTimeAStar,

)

from ..agents.agent import Trajectory

# ---------------------------------------------------------------------------

# Planning exception

# ---------------------------------------------------------------------------

class PlanningError(RuntimeError):

    """Raised when an initial multi-agent plan cannot be constructed."""

# ---------------------------------------------------------------------------

# Planning result

# ---------------------------------------------------------------------------

@dataclass

class PlanningResult:

    """

    Result of initial multi-agent planning.

    Attributes

    ----------

    success:

        Whether plans were generated for all agents.

    trajectories:

        Mapping from agent ID to its trajectory.

    planning_order:

        Order in which agents were planned.

    conflicts:

        Conflicts detected after planning.

    failed_agents:

        Agents for which no trajectory could be generated.

    """

    success: bool

    trajectories: dict[str, Trajectory]

    planning_order: list[str]

    conflicts: list[Conflict]

    failed_agents: list[str]

    @property

    def all_agents_planned(self) -> bool:

        """Return True when every requested agent has a plan."""

        return self.success and not self.failed_agents

# ---------------------------------------------------------------------------

# Initial planner

# ---------------------------------------------------------------------------

class InitialPlanner:

    """

    Initial planner for the warehouse.

    Parameters

    ----------

    grid:

        Warehouse grid.

    obstacle_manager:

        Dynamic obstacle manager.

    max_time_steps:

        Planning horizon.

    max_search_nodes:

        Maximum Space-Time A* node expansions per search.

    heuristic:

        A* heuristic.

    priority_strategy:

        Agent planning order strategy.

        Supported:

            "input_order"

            "most_constrained"

            "high_priority"

    require_conflict_free:

        When True, planning raises PlanningError if the resulting

        trajectories still contain conflicts.

    """

    SUPPORTED_STRATEGIES = {

        "input_order",

        "most_constrained",

        "high_priority",

    }

    def __init__(

        self,

        grid: Grid,

        obstacle_manager: Optional[DynamicObstacleManager] = None,

        *,

        max_time_steps: int = 500,

        max_search_nodes: int = 50000,

        heuristic: str = "manhattan",

        priority_strategy: str = "most_constrained",

        require_conflict_free: bool = True,

    ) -> None:

        priority_strategy = priority_strategy.lower().strip()

        if priority_strategy not in self.SUPPORTED_STRATEGIES:

            raise ValueError(

                f"Unsupported priority strategy: "

                f"{priority_strategy}. "

                f"Supported: {sorted(self.SUPPORTED_STRATEGIES)}"

            )

        self.grid = grid

        self.obstacle_manager = obstacle_manager

        self.max_time_steps = max_time_steps

        self.max_search_nodes = max_search_nodes

        self.heuristic = heuristic

        self.priority_strategy = priority_strategy

        self.require_conflict_free = require_conflict_free

        self.pathfinder = SpaceTimeAStar(

            grid=grid,

            obstacle_manager=obstacle_manager,

            max_time_steps=max_time_steps,

            max_search_nodes=max_search_nodes,

            heuristic=heuristic,

        )

        self.conflict_detector = ConflictDetector(

            grid=grid,

            obstacle_manager=obstacle_manager,

        )

# -----------------------------------------------------------------------

# Main planning method

# -----------------------------------------------------------------------

    def plan_all(

        self,

        agents: Sequence[Agent] | Iterable[Agent],

    ) -> PlanningResult:

        """

        Generate initial plans for all agents.

        Every successfully planned trajectory is stored as both:

            agent.current_plan

            agent.original_plan

        because this is the baseline used later by plan repair.

        Parameters

        ----------

        agents:

            Warehouse agents.

        Returns

        -------

        PlanningResult

        """

        agent_list = list(agents)

        if not agent_list:

            return PlanningResult(

                success=True,

                trajectories={},

                planning_order=[],

                conflicts=[],

                failed_agents=[],

            )

        self._validate_agents(agent_list)

        ordered_agents = self.order_agents(

            agent_list,

        )

        reservations = ReservationTable()

        trajectories: dict[str, Trajectory] = {}

        planning_order: list[str] = []

        failed_agents: list[str] = []

# -------------------------------------------------------------------

# Prioritized planning.

# -------------------------------------------------------------------

        for agent in ordered_agents:

            trajectory = self.plan_agent(

                agent=agent,

                reservations=reservations,

            )

            if trajectory is None:

                failed_agents.append(

                    agent.agent_id

                )

                continue

            trajectories[agent.agent_id] = trajectory

            planning_order.append(agent.agent_id)

# Important:

#

# This trajectory is now part of the reservation table.

#

# Future agents will plan around it.

            reservations.add_trajectory(

                trajectory,

                reserve_start=True,

            )

# Agents remain stationary after reaching their final goal in

# the simulator. Reserve the final cell for the rest of the

# planning horizon so later agents cannot be planned through

# a completed agent's occupied goal cell.

            final_row, final_col, final_time = trajectory[-1]

            for hold_time in range(

                final_time + 1,

                self.max_time_steps + 1,

            ):

                reservations.reserve_position(

                    (final_row, final_col),

                    hold_time,

                )

# Establish baseline plan.

            agent.set_initial_plan(

                trajectory

            )

# -------------------------------------------------------------------

# Independent validation.

# -------------------------------------------------------------------

        # -------------------------------------------------------------------
        # Final-goal occupancy validation
        # -------------------------------------------------------------------
        #
        # Completed agents remain stationary at their final delivery cell.
        # Therefore a later trajectory must not enter that cell afterward.
        # This pass performs local replanning only; it never reruns plan_all().
        # -------------------------------------------------------------------

        max_goal_repairs = max(1, len(agent_list) * 2)

        for _ in range(max_goal_repairs):
            goal_conflict_found = False

            planned_agents = [
                agent
                for agent in ordered_agents
                if agent.agent_id in trajectories
            ]

            for holder in planned_agents:
                holder_trajectory = trajectories[holder.agent_id]
                holder_row, holder_col, holder_final_time = holder_trajectory[-1]
                holder_goal = (holder_row, holder_col)

                for other in planned_agents:
                    if other.agent_id == holder.agent_id:
                        continue

                    other_trajectory = trajectories[other.agent_id]

                    conflict_after_completion = any(
                        timestep > holder_final_time
                        and (row, col) == holder_goal
                        for row, col, timestep in other_trajectory
                    )

                    if not conflict_after_completion:
                        continue

                    # Replan only the later-conflicting trajectory around all
                    # other current trajectories and their stationary goals.
                    local_reservations = ReservationTable()

                    for peer_id, peer_trajectory in trajectories.items():
                        if peer_id == other.agent_id:
                            continue

                        local_reservations.add_trajectory(
                            peer_trajectory,
                            reserve_start=True,
                        )

                        peer_row, peer_col, peer_final_time = peer_trajectory[-1]
                        peer_goal = (peer_row, peer_col)

                        for hold_time in range(
                            peer_final_time + 1,
                            self.max_time_steps + 1,
                        ):
                            local_reservations.reserve_position(
                                peer_goal,
                                hold_time,
                            )

                    repaired = self.plan_agent(
                        agent=other,
                        reservations=local_reservations,
                    )

                    if repaired is None:
                        raise PlanningError(
                            "Could not repair final-goal occupancy conflict "
                            f"for {other.agent_id}."
                        )

                    trajectories[other.agent_id] = repaired
                    other.set_initial_plan(repaired)

                    goal_conflict_found = True
                    break

                if goal_conflict_found:
                    break

            if not goal_conflict_found:
                break

        conflicts = self.conflict_detector.detect(

            trajectories

        )

        success = (

            len(failed_agents) == 0

            and len(conflicts) == 0

        )

        result = PlanningResult(

            success=success,

            trajectories=trajectories,

            planning_order=planning_order,

            conflicts=conflicts,

            failed_agents=failed_agents,

        )

        if self.require_conflict_free and not result.all_agents_planned:

            reason_parts: list[str] = []

            if failed_agents:

                reason_parts.append(

                    "No feasible path for: "

                    + ", ".join(failed_agents)

                )

            if conflicts:

                reason_parts.append(

                    f"{len(conflicts)} conflict(s) detected."

                )

            raise PlanningError(

                "Initial multi-agent planning failed. "

                + " ".join(reason_parts)

            )

        return result

# -----------------------------------------------------------------------

# Single-agent planning

# -----------------------------------------------------------------------

    def plan_agent(

        self,

        agent: Agent,

        reservations: Optional[ReservationTable] = None,

        *,

        start_position: Optional[Position] = None,

        start_time: int = 0,

        tasks: Optional[Sequence[Task]] = None,

    ) -> Optional[Trajectory]:

        """

        Generate a complete initial trajectory for one agent.

        The trajectory includes:

            start → pickup → delivery → next pickup → next delivery ...

        Parameters

        ----------

        agent:

            Agent being planned.

        reservations:

            Previously planned trajectories.

        start_position:

            Optional override, mainly useful for controlled tests

            and future repair operations.

        start_time:

            Time at which planning begins.

        tasks:

            Optional task sequence. Defaults to agent.tasks.

        Returns

        -------

        Trajectory | None

        """

        if reservations is None:

            reservations = ReservationTable()

        if start_position is None:

            start_position = agent.start_position

        if tasks is None:

            tasks = agent.tasks

        tasks = list(tasks)

        if not self.grid.in_bounds(start_position):

            raise ValueError(

                f"Agent {agent.agent_id} starts outside grid: "

                f"{start_position}"

            )

        if not self.grid.is_walkable(start_position):

            return None

# -------------------------------------------------------------------

# No tasks.

# -------------------------------------------------------------------

        if not tasks:

            if self.obstacle_manager is not None:

                if self.obstacle_manager.is_blocked(

                    start_position,

                    start_time,

                ):

                    return None

            if reservations.is_position_reserved(

                start_position,

                start_time,

            ):

                return None

            return [

                (

                    start_position[0],

                    start_position[1],

                    start_time,

                )

            ]

# -------------------------------------------------------------------

# Build route one task waypoint at a time.

# -------------------------------------------------------------------

        complete_trajectory: Trajectory = []

        current_position = start_position

        current_time = start_time

        for task in tasks:

            waypoints = [

                task.pickup_position,

                task.delivery_position,

            ]

            for waypoint_index, waypoint in enumerate(

                waypoints

            ):

                self._validate_waypoint(

                    task=task,

                    waypoint=waypoint,

                    waypoint_index=waypoint_index,

                )

                is_final_delivery = (

                    task is tasks[-1]

                    and waypoint_index == 1

                )

                segment = self.pathfinder.search(

                    start=current_position,

                    goal=waypoint,

                    start_time=current_time,

                    reservations=reservations,

                    max_time_steps=self.max_time_steps,

                    require_goal_hold=is_final_delivery,

                )

                if segment is None:

                    return None
                if is_final_delivery:
                    goal_index = next(
                        (index for index, state in enumerate(segment) if (state[0], state[1]) == waypoint),
                        None,
                    )
                    if goal_index is None:
                        return None
                    segment = segment[:goal_index + 1]

# Append the first segment completely.

#

# For subsequent segments, exclude the first state because

# it is identical to the previous segment's final state.

                if not complete_trajectory:

                    complete_trajectory.extend(

                        segment

                    )

                else:

                    complete_trajectory.extend(

                        segment[1:]

                    )

                final_row, final_col, final_time = (

                    segment[-1]

                )

                current_position = (

                    final_row,

                    final_col,

                )

                current_time = final_time

# -------------------------------------------------------------------

# Final validation.

# -------------------------------------------------------------------

        if not self.pathfinder.validate_trajectory(

            complete_trajectory,

            self.grid,

            self.obstacle_manager,

        ):

            return None

        return complete_trajectory

# -----------------------------------------------------------------------

# Agent ordering

# -----------------------------------------------------------------------

    def order_agents(

        self,

        agents: Sequence[Agent],

    ) -> list[Agent]:

        """

        Determine the order in which agents receive planning priority.

        \\\`most_constrained\\\` is implemented as a deterministic heuristic

        using:

            - highest task priority,

            - number of assigned tasks,

            - estimated travel distance.

        This is a practical prioritized-planning strategy rather than

        an exact constrained-MAPF optimization.

        """

        if self.priority_strategy == "input_order":

            return list(agents)

        if self.priority_strategy == "high_priority":

            return sorted(

                agents,

                key=lambda agent: (

                    -self._highest_task_priority(agent),

                    -len(agent.tasks),

                    agent.agent_id,

                ),

            )

# ---------------------------------------------------------------

# most_constrained

# ---------------------------------------------------------------

        return sorted(

            agents,

            key=lambda agent: (

                -self._highest_task_priority(agent),

                -len(agent.tasks),

                -self._estimated_agent_distance(agent),

                agent.agent_id,

            ),

        )

    def _highest_task_priority(

        self,

        agent: Agent,

    ) -> int:

        """

        Return the highest priority among an agent's tasks.

        """

        if not agent.tasks:

            return 0

        return max(

            int(task.priority)

            for task in agent.tasks

        )

    def _estimated_agent_distance(

        self,

        agent: Agent,

    ) -> int:

        """

        Calculate a lower-bound estimate of the distance covered

        by the agent's complete task sequence.

        This is used only for planning priority.

        """

        if not agent.tasks:

            return 0

        total_distance = 0

        current_position = agent.start_position

        for task in agent.tasks:

            total_distance += self.grid.manhattan_distance(

                current_position,

                task.pickup_position,

            )

            total_distance += self.grid.manhattan_distance(

                task.pickup_position,

                task.delivery_position,

            )

            current_position = task.delivery_position

        return total_distance

# -----------------------------------------------------------------------

# Validation helpers

# -----------------------------------------------------------------------

    def _validate_agents(

        self,

        agents: Sequence[Agent],

    ) -> None:

        """

        Validate agent identifiers and starting positions.

        """

        identifiers: set[str] = set()

        for agent in agents:

            if agent.agent_id in identifiers:

                raise ValueError(

                    f"Duplicate agent ID: {agent.agent_id}"

                )

            identifiers.add(agent.agent_id)

            if not self.grid.in_bounds(

                agent.start_position

            ):

                raise ValueError(

                    f"Agent {agent.agent_id} starts outside "

                    f"the grid: {agent.start_position}"

                )

            if not self.grid.is_walkable(

                agent.start_position

            ):

                raise ValueError(

                    f"Agent {agent.agent_id} starts on a blocked "

                    f"cell: {agent.start_position}"

                )

            for task in agent.tasks:

                self._validate_task(

                    task

                )

    def _validate_task(

        self,

        task: Task,

    ) -> None:

        """

        Validate pickup and delivery locations.

        """

        if not self.grid.in_bounds(

            task.pickup_position

        ):

            raise ValueError(

                f"Task {task.task_id} pickup position "

                f"is outside the grid: "

                f"{task.pickup_position}"

            )

        if not self.grid.in_bounds(

            task.delivery_position

        ):

            raise ValueError(

                f"Task {task.task_id} delivery position "

                f"is outside the grid: "

                f"{task.delivery_position}"

            )

        if not self.grid.is_walkable(

            task.pickup_position

        ):

            raise ValueError(

                f"Task {task.task_id} pickup position is blocked: "

                f"{task.pickup_position}"

            )

        if not self.grid.is_walkable(

            task.delivery_position

        ):

            raise ValueError(

                f"Task {task.task_id} delivery position is blocked: "

                f"{task.delivery_position}"

            )

    def _validate_waypoint(

        self,

        task: Task,

        waypoint: Position,

        waypoint_index: int,

    ) -> None:

        """

        Validate an individual task waypoint.

        """

        if not self.grid.in_bounds(waypoint):

            waypoint_type = (

                "pickup"

                if waypoint_index == 0

                else "delivery"

            )

            raise ValueError(

                f"Task {task.task_id} {waypoint_type} "

                f"is outside the grid: {waypoint}"

            )

        if not self.grid.is_walkable(waypoint):

            waypoint_type = (

                "pickup"

                if waypoint_index == 0

                else "delivery"

            )

            raise ValueError(

                f"Task {task.task_id} {waypoint_type} "

                f"is blocked: {waypoint}"

            )
