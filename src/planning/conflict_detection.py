"""
Conflict detection for multi-agent trajectories.

This module independently validates planned trajectories.

The detector identifies:

1. Vertex conflicts
   Two agents occupy the same cell at the same timestep.

2. Edge conflicts
   Two agents exchange positions during the same timestep.

3. Obstacle conflicts
   An agent enters a static or dynamic obstacle.

The detector does not modify plans. It only reports conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

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
# Conflict representation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Conflict:
    """
    Represents one detected conflict.

    Attributes
    ----------
    conflict_type:
        One of:
            "vertex"
            "edge"
            "obstacle"

    timestep:
        Timestep at which the conflict occurs.

    agent_a:
        First involved agent.

    agent_b:
        Second involved agent, or None for an obstacle conflict.

    position_a:
        Relevant position of agent A.

    position_b:
        Relevant position of agent B, when applicable.

    description:
        Human-readable description.
    """

    conflict_type: str
    timestep: int

    agent_a: str
    agent_b: Optional[str]

    position_a: Position
    position_b: Optional[Position]

    description: str

    def to_dict(self) -> dict[str, object]:
        """Convert conflict to a serializable dictionary."""
        return {
            "type": self.conflict_type,
            "timestep": self.timestep,
            "agent_a": self.agent_a,
            "agent_b": self.agent_b,
            "position_a": self.position_a,
            "position_b": self.position_b,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Conflict detector
# ---------------------------------------------------------------------------

class ConflictDetector:
    """
    Detect conflicts between multi-agent trajectories.

    Parameters
    ----------
    grid:
        Warehouse grid.

    obstacle_manager:
        Optional dynamic obstacle manager.
    """

    def __init__(
        self,
        grid: Grid,
        obstacle_manager: Optional[DynamicObstacleManager] = None,
    ) -> None:
        self.grid = grid
        self.obstacle_manager = obstacle_manager

    # -----------------------------------------------------------------------
    # Main API
    # -----------------------------------------------------------------------

    def detect(
        self,
        trajectories: Mapping[str, Trajectory],
    ) -> list[Conflict]:
        """
        Detect all enabled conflict types.

        Returns
        -------
        list[Conflict]
            All detected conflicts.
        """
        conflicts: list[Conflict] = []

        conflicts.extend(
            self.detect_vertex_conflicts(
                trajectories,
            )
        )

        conflicts.extend(
            self.detect_edge_conflicts(
                trajectories,
            )
        )

        conflicts.extend(
            self.detect_obstacle_conflicts(
                trajectories,
            )
        )

        return conflicts

    def has_conflicts(
        self,
        trajectories: Mapping[str, Trajectory],
    ) -> bool:
        """Return True when at least one conflict exists."""
        return bool(self.detect(trajectories))

    # -----------------------------------------------------------------------
    # Vertex conflicts
    # -----------------------------------------------------------------------

    def detect_vertex_conflicts(
        self,
        trajectories: Mapping[str, Trajectory],
    ) -> list[Conflict]:
        """
        Detect vertex conflicts.

        A vertex conflict occurs when:

            position(A, t) == position(B, t)

        at the same timestep.
        """
        occupancy: dict[
            int,
            dict[Position, list[str]],
        ] = {}

        for agent_id, trajectory in trajectories.items():
            for row, col, timestep in trajectory:
                position = (row, col)

                occupancy.setdefault(
                    timestep,
                    {},
                ).setdefault(
                    position,
                    [],
                ).append(agent_id)

        conflicts: list[Conflict] = []

        for timestep in sorted(occupancy):
            for position, agent_ids in occupancy[timestep].items():

                if len(agent_ids) <= 1:
                    continue

                # Produce one pairwise conflict for every pair.
                for index in range(len(agent_ids)):
                    for second_index in range(
                        index + 1,
                        len(agent_ids),
                    ):
                        agent_a = agent_ids[index]
                        agent_b = agent_ids[second_index]

                        conflicts.append(
                            Conflict(
                                conflict_type="vertex",
                                timestep=timestep,
                                agent_a=agent_a,
                                agent_b=agent_b,
                                position_a=position,
                                position_b=position,
                                description=(
                                    f"Agents {agent_a} and {agent_b} "
                                    f"occupy cell {position} at "
                                    f"timestep {timestep}."
                                ),
                            )
                        )

        return conflicts

    # -----------------------------------------------------------------------
    # Edge conflicts
    # -----------------------------------------------------------------------

    def detect_edge_conflicts(
        self,
        trajectories: Mapping[str, Trajectory],
    ) -> list[Conflict]:
        """
        Detect head-on edge conflicts.

        A conflict occurs when:

            A(t) = B(t+1)
            B(t) = A(t+1)

        during the same timestep transition.
        """
        transitions: dict[
            int,
            dict[tuple[Position, Position], list[str]],
        ] = {}

        for agent_id, trajectory in trajectories.items():

            for index in range(1, len(trajectory)):
                row1, col1, time1 = trajectory[index - 1]
                row2, col2, time2 = trajectory[index]

                if time2 != time1 + 1:
                    # Invalid temporal structure is handled by the
                    # trajectory validator. Skip it here.
                    continue

                source = (row1, col1)
                destination = (row2, col2)

                transitions.setdefault(
                    time1,
                    {},
                ).setdefault(
                    (source, destination),
                    [],
                ).append(agent_id)

        conflicts: list[Conflict] = []
        processed: set[
            tuple[
                int,
                str,
                str,
                Position,
                Position,
            ]
        ] = set()

        for timestep in sorted(transitions):
            edges = transitions[timestep]

            for (
                source,
                destination,
            ), agent_ids in edges.items():

                reverse_edge = (
                    destination,
                    source,
                )

                reverse_agents = edges.get(
                    reverse_edge,
                    [],
                )

                for agent_a in agent_ids:
                    for agent_b in reverse_agents:

                        if agent_a == agent_b:
                            continue

                        pair = tuple(
                            sorted(
                                (
                                    agent_a,
                                    agent_b,
                                )
                            )
                        )

                        key = (
                            timestep,
                            pair[0],
                            pair[1],
                            source,
                            destination,
                        )

                        if key in processed:
                            continue

                        processed.add(key)

                        conflicts.append(
                            Conflict(
                                conflict_type="edge",
                                timestep=timestep,
                                agent_a=pair[0],
                                agent_b=pair[1],
                                position_a=source,
                                position_b=destination,
                                description=(
                                    f"Agents {pair[0]} and {pair[1]} "
                                    f"swap cells {source} and "
                                    f"{destination} between "
                                    f"timesteps {timestep} and "
                                    f"{timestep + 1}."
                                ),
                            )
                        )

        return conflicts

    # -----------------------------------------------------------------------
    # Obstacle conflicts
    # -----------------------------------------------------------------------

    def detect_obstacle_conflicts(
        self,
        trajectories: Mapping[str, Trajectory],
    ) -> list[Conflict]:
        """
        Detect trajectories that enter blocked cells.

        Static obstacles are checked through Grid.

        Dynamic obstacles are checked through DynamicObstacleManager.
        """
        conflicts: list[Conflict] = []

        for agent_id, trajectory in trajectories.items():

            for row, col, timestep in trajectory:
                position = (row, col)

                if not self.grid.in_bounds(position):
                    conflicts.append(
                        Conflict(
                            conflict_type="obstacle",
                            timestep=timestep,
                            agent_a=agent_id,
                            agent_b=None,
                            position_a=position,
                            position_b=None,
                            description=(
                                f"Agent {agent_id} is outside the "
                                f"warehouse at {position}."
                            ),
                        )
                    )

                    continue

                if self.grid.is_static_obstacle(position):
                    conflicts.append(
                        Conflict(
                            conflict_type="obstacle",
                            timestep=timestep,
                            agent_a=agent_id,
                            agent_b=None,
                            position_a=position,
                            position_b=None,
                            description=(
                                f"Agent {agent_id} enters static "
                                f"obstacle cell {position} at "
                                f"timestep {timestep}."
                            ),
                        )
                    )

                    continue

                if self.obstacle_manager is not None:
                    if self.obstacle_manager.is_temporarily_blocked(
                        position,
                        timestep,
                    ):
                        conflicts.append(
                            Conflict(
                                conflict_type="obstacle",
                                timestep=timestep,
                                agent_a=agent_id,
                                agent_b=None,
                                position_a=position,
                                position_b=None,
                                description=(
                                    f"Agent {agent_id} enters dynamic "
                                    f"obstacle cell {position} at "
                                    f"timestep {timestep}."
                                ),
                            )
                        )

        return conflicts

    # -----------------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------------

    def validate_trajectory(
        self,
        trajectory: Trajectory,
    ) -> bool:
        """
        Validate a single trajectory.

        Checks:
            - non-empty trajectory,
            - valid positions,
            - non-negative time,
            - consecutive timesteps,
            - legal grid transitions,
            - obstacle avoidance.
        """
        if not trajectory:
            return False

        previous_time: Optional[int] = None
        previous_position: Optional[Position] = None

        for row, col, timestep in trajectory:
            position = (row, col)

            if not self.grid.in_bounds(position):
                return False

            if self.grid.is_static_obstacle(position):
                return False

            if timestep < 0:
                return False

            if previous_time is not None:

                if timestep != previous_time + 1:
                    return False

                assert previous_position is not None

                if position not in self.grid.neighbors(
                    previous_position,
                    include_wait=True,
                ):
                    return False

            if self.obstacle_manager is not None:
                if self.obstacle_manager.is_blocked(
                    position,
                    timestep,
                ):
                    return False

            previous_time = timestep
            previous_position = position

        return True

    def validate_all(
        self,
        trajectories: Mapping[str, Trajectory],
    ) -> bool:
        """
        Return True only when all trajectories are individually valid
        and the agents have no inter-agent conflicts.
        """
        for trajectory in trajectories.values():
            if not self.validate_trajectory(trajectory):
                return False

        return not self.has_conflicts(trajectories)

    # -----------------------------------------------------------------------
    # Utility
    # -----------------------------------------------------------------------

    @staticmethod
    def conflict_counts(
        conflicts: Iterable[Conflict],
    ) -> dict[str, int]:
        """
        Return conflict counts grouped by type.
        """
        counts = {
            "vertex": 0,
            "edge": 0,
            "obstacle": 0,
        }

        for conflict in conflicts:
            if conflict.conflict_type in counts:
                counts[conflict.conflict_type] += 1

        return counts

    @staticmethod
    def involved_agents(
        conflicts: Iterable[Conflict],
    ) -> set[str]:
        """
        Return all agents involved in at least one conflict.
        """
        agents: set[str] = set()

        for conflict in conflicts:
            agents.add(conflict.agent_a)

            if conflict.agent_b is not None:
                agents.add(conflict.agent_b)

        return agents