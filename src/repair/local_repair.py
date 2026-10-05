"""Local plan repair for the multi-agent warehouse.

This module modifies existing trajectories locally instead of invoking
the complete multi-agent planner again.

Core repair strategy:
1. Identify disrupted agent and collision point.
2. Generate local alternatives:
   a. Local detour reconnecting to a future state of the original trajectory,
      with a possible temporal delay shift.
   b. Task milestone sequential pathfinding using Space-Time A* around the
      disruption and reserved trajectories of unaffected agents.
   c. Wait-in-place until temporary obstacles expire.
3. For emergency tasks and failed-agent task transfer, plan paths through
   the required task waypoints while preserving unaffected trajectories.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from math import inf
from typing import Iterable, Mapping, Optional, Sequence

from ..agents import Agent, Task, TaskStatus
from ..agents.agent import Trajectory
from ..environment import DynamicObstacleManager, Grid, Position
from ..planning import ReservationTable, SpaceTimeAStar
from .disruption import Disruption, DisruptionType
from .negotiation import RepairProposal


@dataclass
class RepairCandidate:
    """Internal representation of one local repair candidate."""

    agent_id: str
    trajectory: Trajectory
    rejoin_index: Optional[int]
    changed_states: int
    additional_cost: float
    additional_delay: int
    description: str
    task: Optional[Task] = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class LocalRepairEngine:
    """Generates local repair proposals for disrupted agents."""

    def __init__(
        self,
        grid: Grid,
        pathfinder: SpaceTimeAStar,
        obstacle_manager: Optional[DynamicObstacleManager] = None,
        *,
        max_alternatives: int = 5,
        repair_horizon: int = 30,
    ) -> None:
        if max_alternatives <= 0:
            raise ValueError("max_alternatives must be greater than zero.")
        if repair_horizon <= 0:
            raise ValueError("repair_horizon must be greater than zero.")

        self.grid = grid
        self.pathfinder = pathfinder
        self.obstacle_manager = obstacle_manager
        self.max_alternatives = max_alternatives
        self.repair_horizon = repair_horizon

    def generate_proposals(
        self,
        agent: Agent,
        disruption: Disruption,
        reservations: ReservationTable,
        *,
        candidate_agent_id: Optional[str] = None,
    ) -> list[RepairProposal]:
        """Generate local repair proposals for one agent."""
        if candidate_agent_id is None:
            candidate_agent_id = agent.agent_id

        if disruption.is_dynamic_obstacle:
            candidates = self.repair_dynamic_obstacle(
                agent=agent,
                disruption=disruption,
                reservations=reservations,
            )
        elif disruption.is_emergency_task:
            candidates = self.insert_emergency_task(
                agent=agent,
                task=disruption.task,
                disruption_time=disruption.timestep,
                reservations=reservations,
            )
        else:
            candidates = []

        proposals: list[RepairProposal] = []
        for candidate in candidates:
            proposal = RepairProposal(
                proposer=candidate_agent_id,
                modified_agents={candidate.agent_id},
                trajectories={candidate.agent_id: candidate.trajectory},
                description=candidate.description,
                additional_delay=candidate.additional_delay,
                additional_path_cost=candidate.additional_cost,
                metadata=candidate.metadata,
            )
            proposals.append(proposal)

        return proposals

    def repair_dynamic_obstacle(
        self,
        agent: Agent,
        disruption: Disruption,
        reservations: ReservationTable,
    ) -> list[RepairCandidate]:
        """Repair an agent whose future trajectory intersects a dynamic obstacle."""
        if disruption.disruption_type != DisruptionType.DYNAMIC_OBSTACLE:
            raise ValueError("repair_dynamic_obstacle requires a DYNAMIC_OBSTACLE disruption.")

        trajectory = agent.current_plan
        if not trajectory:
            return []

        invalid_index = self._find_first_conflict_index(
            trajectory=trajectory,
            disruption=disruption,
        )
        if invalid_index is None:
            return []

        candidates: list[RepairCandidate] = []

        # Strategy 1: Local detour and rejoin
        rejoin_candidates = self._generate_rejoin_candidates(
            agent=agent,
            trajectory=trajectory,
            invalid_index=invalid_index,
            reservations=reservations,
            disruption=disruption,
        )
        candidates.extend(rejoin_candidates)

        # Strategy 2: Sequential path through remaining task milestones
        if len(candidates) < self.max_alternatives:
            milestone_candidate = self._generate_milestone_candidate(
                agent=agent,
                trajectory=trajectory,
                invalid_index=invalid_index,
                reservations=reservations,
                disruption=disruption,
            )
            if milestone_candidate is not None:
                candidates.append(milestone_candidate)

        # Strategy 3: Wait-in-place until obstacle clears
        if len(candidates) < self.max_alternatives:
            wait_candidate = self._generate_wait_candidate(
                agent=agent,
                trajectory=trajectory,
                invalid_index=invalid_index,
                reservations=reservations,
                disruption=disruption,
            )
            if wait_candidate is not None:
                candidates.append(wait_candidate)

        # Deduplicate and sort by additional cost/delay
        unique: list[RepairCandidate] = []
        seen: set[tuple[tuple[int, int, int], ...]] = set()
        for cand in candidates:
            key = tuple(cand.trajectory)
            if key not in seen:
                seen.add(key)
                unique.append(cand)

        unique.sort(key=lambda c: (c.additional_delay, c.additional_cost, c.changed_states))
        return unique[: self.max_alternatives]

    def _find_first_conflict_index(
        self,
        trajectory: Trajectory,
        disruption: Disruption,
    ) -> Optional[int]:
        """Find the index of the first state blocked by the disruption or dynamic obstacles."""
        disruption_time = disruption.timestep
        disruption_pos = disruption.position

        for index, (row, col, timestep) in enumerate(trajectory):
            if timestep < disruption_time:
                continue

            pos = (row, col)
            if disruption_pos is not None and pos == disruption_pos:
                return index

            if self.obstacle_manager is not None and self.obstacle_manager.is_temporarily_blocked(pos, timestep):
                return index

        return None

    def _generate_rejoin_candidates(
        self,
        agent: Agent,
        trajectory: Trajectory,
        invalid_index: int,
        reservations: ReservationTable,
        disruption: Optional[Disruption] = None,
    ) -> list[RepairCandidate]:
        """Generate detour candidates that rejoin the original plan further ahead."""
        if invalid_index < 0:
            return []

        # Find safe start index strictly before the conflict
        safe_index = max(0, invalid_index - 1)
        prefix = trajectory[: safe_index + 1]
        if not prefix:
            return []

        start_row, start_col, start_time = prefix[-1]
        start_position = (start_row, start_col)

        candidates: list[RepairCandidate] = []
        end_index = min(len(trajectory), invalid_index + self.repair_horizon)

        for rejoin_index in range(invalid_index, end_index):
            goal_row, goal_col, goal_time = trajectory[rejoin_index]
            goal_position = (goal_row, goal_col)

            # Check that rejoin state itself is not blocked
            if self._state_is_blocked(goal_position, goal_time):
                continue
            if reservations.is_position_reserved(goal_position, goal_time):
                continue

            # First check: exact-time path
            local_path = self.pathfinder.search(
                start=start_position,
                goal=goal_position,
                start_time=start_time,
                reservations=reservations,
                max_time_steps=goal_time,
            )

            if local_path is not None and local_path[-1][2] == goal_time:
                repaired = list(prefix) + list(local_path[1:]) + list(trajectory[rejoin_index + 1 :])
                if (
                    repaired != trajectory
                    and self.pathfinder.validate_trajectory(repaired, self.grid, self.obstacle_manager)
                    and self._preserves_task_progress(agent, repaired)
                ):
                    candidate = self._create_candidate(
                        agent=agent,
                        original=trajectory,
                        repaired=repaired,
                        rejoin_index=rejoin_index,
                        description=(
                            f"Agent {agent.agent_id} detoured around obstacle "
                            f"and rejoined at timestep {goal_time}."
                        ),
                        disruption=disruption,
                    )
                    candidates.append(candidate)
                    if len(candidates) >= self.max_alternatives:
                        break

            # Second check: delayed rejoin with time-shifted suffix
            elif local_path is not None and local_path[-1][2] > goal_time:
                arrival_time = local_path[-1][2]
                delta = arrival_time - goal_time
                shifted_suffix = [
                    (r, c, t + delta) for r, c, t in trajectory[rejoin_index + 1 :]
                ]

                # Ensure shifted suffix is conflict-free
                suffix_valid = True
                for r, c, t in shifted_suffix:
                    if not self.grid.is_walkable((r, c)):
                        suffix_valid = False
                        break
                    if self._state_is_blocked((r, c), t):
                        suffix_valid = False
                        break
                    if reservations.is_position_reserved((r, c), t):
                        suffix_valid = False
                        break

                if suffix_valid:
                    repaired = list(prefix) + list(local_path[1:]) + shifted_suffix
                    if (
                        repaired != trajectory
                        and self.pathfinder.validate_trajectory(repaired, self.grid, self.obstacle_manager)
                        and self._preserves_task_progress(agent, repaired)
                    ):
                        candidate = self._create_candidate(
                            agent=agent,
                            original=trajectory,
                            repaired=repaired,
                            rejoin_index=rejoin_index,
                            description=(
                                f"Agent {agent.agent_id} detoured around obstacle, "
                                f"rejoined at timestep {arrival_time} (delay +{delta})."
                            ),
                            disruption=disruption,
                        )
                        candidates.append(candidate)
                        if len(candidates) >= self.max_alternatives:
                            break

        return candidates

    def _generate_milestone_candidate(
        self,
        agent: Agent,
        trajectory: Trajectory,
        invalid_index: int,
        reservations: ReservationTable,
        disruption: Optional[Disruption] = None,
    ) -> Optional[RepairCandidate]:
        """Generate a complete path through remaining task milestones from the safe prefix."""
        safe_index = max(0, invalid_index - 1)
        prefix = trajectory[: safe_index + 1]
        if not prefix:
            return None

        start_row, start_col, start_time = prefix[-1]
        curr_pos = (start_row, start_col)
        curr_time = start_time

        milestones = self._get_remaining_milestones(agent, start_time)
        repaired_tail: list[tuple[int, int, int]] = []

        for milestone in milestones:
            if curr_pos == milestone:
                continue
            segment = self.pathfinder.search(
                start=curr_pos,
                goal=milestone,
                start_time=curr_time,
                reservations=reservations,
                max_time_steps=self.pathfinder.max_time_steps,
            )
            if segment is None:
                return None
            repaired_tail.extend(segment[1:])
            curr_pos = milestone
            curr_time = segment[-1][2]

        # If agent had no milestones left, simply hold safe position or final position
        if not milestones:
            final_pos = (trajectory[-1][0], trajectory[-1][1])
            if curr_pos != final_pos:
                segment = self.pathfinder.search(
                    start=curr_pos,
                    goal=final_pos,
                    start_time=curr_time,
                    reservations=reservations,
                    max_time_steps=self.pathfinder.max_time_steps,
                )
                if segment is None:
                    return None
                repaired_tail.extend(segment[1:])

        repaired = list(prefix) + repaired_tail
        if not self.pathfinder.validate_trajectory(repaired, self.grid, self.obstacle_manager):
            return None
        if not self._preserves_task_progress(agent, repaired):
            return None

        return self._create_candidate(
            agent=agent,
            original=trajectory,
            repaired=repaired,
            rejoin_index=None,
            description=f"Agent {agent.agent_id} replanned through remaining milestones.",
            disruption=disruption,
        )

    def _generate_wait_candidate(
        self,
        agent: Agent,
        trajectory: Trajectory,
        invalid_index: int,
        reservations: ReservationTable,
        disruption: Optional[Disruption] = None,
    ) -> Optional[RepairCandidate]:
        """Wait before the obstacle until it clears, then resume."""
        if disruption is None or disruption.duration is None:
            return None

        safe_index = max(0, invalid_index - 1)
        prefix = trajectory[: safe_index + 1]
        if not prefix:
            return None

        wait_pos = (prefix[-1][0], prefix[-1][1])
        wait_start_time = prefix[-1][2]
        obstacle_clear_time = disruption.timestep + disruption.duration + 1

        if obstacle_clear_time <= wait_start_time:
            return None

        wait_steps = obstacle_clear_time - wait_start_time
        wait_prefix = list(prefix)
        for step in range(1, wait_steps + 1):
            t = wait_start_time + step
            if self._state_is_blocked(wait_pos, t) or reservations.is_position_reserved(wait_pos, t):
                return None
            wait_prefix.append((wait_pos[0], wait_pos[1], t))

        # Shift the remaining original trajectory
        delta = wait_steps
        shifted_suffix = [(r, c, t + delta) for r, c, t in trajectory[safe_index + 1 :]]

        for r, c, t in shifted_suffix:
            if not self.grid.is_walkable((r, c)):
                return None
            if self._state_is_blocked((r, c), t) or reservations.is_position_reserved((r, c), t):
                return None

        repaired = wait_prefix + shifted_suffix
        if not self.pathfinder.validate_trajectory(repaired, self.grid, self.obstacle_manager):
            return None
        if not self._preserves_task_progress(agent, repaired):
            return None

        return self._create_candidate(
            agent=agent,
            original=trajectory,
            repaired=repaired,
            rejoin_index=safe_index,
            description=f"Agent {agent.agent_id} waited {wait_steps} timesteps until obstacle cleared.",
            disruption=disruption,
        )

    def insert_emergency_task(
        self,
        agent: Agent,
        task: Optional[Task],
        disruption_time: int,
        reservations: ReservationTable,
    ) -> list[RepairCandidate]:
        """Insert an emergency pickup-and-delivery task into an agent's plan."""
        if task is None:
            return []

        trajectory = agent.current_plan
        if not trajectory:
            return []

        start_state = self._state_at_or_after(trajectory, disruption_time)
        if start_state is None:
            return []

        start_index = trajectory.index(start_state)
        prefix = trajectory[: start_index + 1]
        start_pos = (start_state[0], start_state[1])
        start_time = start_state[2]

        # 1. Search path to emergency pickup
        to_pickup = self.pathfinder.search(
            start=start_pos,
            goal=task.pickup_position,
            start_time=start_time,
            reservations=reservations,
            max_time_steps=self.pathfinder.max_time_steps,
        )
        if to_pickup is None:
            return []

        pickup_time = to_pickup[-1][2]

        # 2. Search path to emergency delivery
        to_delivery = self.pathfinder.search(
            start=task.pickup_position,
            goal=task.delivery_position,
            start_time=pickup_time,
            reservations=reservations,
            max_time_steps=self.pathfinder.max_time_steps,
        )
        if to_delivery is None:
            return []

        emergency_segment = list(to_pickup) + list(to_delivery[1:])
        emergency_end_time = emergency_segment[-1][2]
        delivery_pos = task.delivery_position

        # 3. Search path from emergency delivery through remaining milestones
        remaining_milestones = self._get_remaining_milestones(agent, start_time)
        tail: list[tuple[int, int, int]] = []
        curr_pos = delivery_pos
        curr_time = emergency_end_time

        for m in remaining_milestones:
            if curr_pos == m:
                continue
            seg = self.pathfinder.search(
                start=curr_pos,
                goal=m,
                start_time=curr_time,
                reservations=reservations,
                max_time_steps=self.pathfinder.max_time_steps,
            )
            if seg is None:
                return []
            tail.extend(seg[1:])
            curr_pos = m
            curr_time = seg[-1][2]

        if not remaining_milestones:
            final_pos = (trajectory[-1][0], trajectory[-1][1])
            if curr_pos != final_pos:
                seg = self.pathfinder.search(
                    start=curr_pos,
                    goal=final_pos,
                    start_time=curr_time,
                    reservations=reservations,
                    max_time_steps=self.pathfinder.max_time_steps,
                )
                if seg is not None:
                    tail.extend(seg[1:])

        repaired = list(prefix) + list(emergency_segment[1:]) + tail
        if not self.pathfinder.validate_trajectory(repaired, self.grid, self.obstacle_manager):
            return []

        candidate = self._create_candidate(
            agent=agent,
            original=trajectory,
            repaired=repaired,
            rejoin_index=None,
            description=f"Agent {agent.agent_id} accepted emergency task {task.task_id}.",
            task=task,
        )
        return [candidate]

    def transfer_task_from_failed_agent(
        self,
        receiver: Agent,
        failed_agent: Agent,
        disruption_time: int,
        reservations: ReservationTable,
    ) -> list[RepairCandidate]:
        """Transfer unfinished tasks from a failed agent to a receiver agent."""
        transferred_tasks = [t for t in failed_agent.tasks if not t.is_completed]
        if not transferred_tasks:
            return []

        trajectory = receiver.current_plan
        if not trajectory:
            return []

        start_state = self._state_at_or_after(trajectory, disruption_time)
        if start_state is None:
            return []

        start_index = trajectory.index(start_state)
        prefix = trajectory[: start_index + 1]
        curr_pos = (start_state[0], start_state[1])
        curr_time = start_state[2]

        # Order of execution:
        # 1. Receiver's active task milestone (if carrying item, deliver it)
        # 2. Transferred tasks (for each: pickup then delivery)
        # 3. Receiver's remaining tasks (for each: pickup then delivery)
        milestones: list[Position] = []

        # Check receiver active task
        if receiver.current_task is not None and not receiver.current_task.is_completed:
            ct = receiver.current_task
            if ct.status in (TaskStatus.PICKED_UP, TaskStatus.GOING_TO_DELIVERY):
                milestones.append(ct.delivery_position)
            elif ct.status in (TaskStatus.PENDING, TaskStatus.GOING_TO_PICKUP):
                milestones.append(ct.pickup_position)
                milestones.append(ct.delivery_position)

        # Transferred tasks
        for task in transferred_tasks:
            milestones.append(task.pickup_position)
            milestones.append(task.delivery_position)

        # Receiver subsequent tasks
        for idx in range(receiver.current_task_index + 1, len(receiver.tasks)):
            t = receiver.tasks[idx]
            milestones.append(t.pickup_position)
            milestones.append(t.delivery_position)

        tail: list[tuple[int, int, int]] = []
        for m in milestones:
            if curr_pos == m:
                continue
            seg = self.pathfinder.search(
                start=curr_pos,
                goal=m,
                start_time=curr_time,
                reservations=reservations,
                max_time_steps=self.pathfinder.max_time_steps,
            )
            if seg is None:
                return []
            tail.extend(seg[1:])
            curr_pos = m
            curr_time = seg[-1][2]

        repaired = list(prefix) + tail
        if not self.pathfinder.validate_trajectory(repaired, self.grid, self.obstacle_manager):
            return []

        candidate = self._create_candidate(
            agent=receiver,
            original=trajectory,
            repaired=repaired,
            rejoin_index=None,
            description=(
                f"Agent {receiver.agent_id} took over "
                f"{len(transferred_tasks)} task(s) from failed agent {failed_agent.agent_id}."
            ),
            metadata={"transferred_tasks": [t.task_id for t in transferred_tasks]},
        )
        return [candidate]

    def _get_remaining_milestones(self, agent: Agent, after_time: int) -> list[Position]:
        """Collect all remaining pickup and delivery milestones for an agent."""
        milestones: list[Position] = []
        if agent.current_task_index >= len(agent.tasks):
            return milestones

        for idx in range(agent.current_task_index, len(agent.tasks)):
            task = agent.tasks[idx]
            if idx == agent.current_task_index:
                if task.status in (TaskStatus.PICKED_UP, TaskStatus.GOING_TO_DELIVERY):
                    milestones.append(task.delivery_position)
                elif not task.is_completed:
                    milestones.append(task.pickup_position)
                    milestones.append(task.delivery_position)
            else:
                milestones.append(task.pickup_position)
                milestones.append(task.delivery_position)

        return milestones

    def _preserves_task_progress(self, agent: Agent, trajectory: Trajectory) -> bool:
        """Ensure a repaired trajectory still reaches all remaining task milestones."""
        if not agent.tasks or agent.current_task_index >= len(agent.tasks):
            return True

        task_index = agent.current_task_index
        task_status = [t.status.value for t in agent.tasks]

        for row, col, _timestep in trajectory:
            if task_index >= len(agent.tasks):
                return True

            task = agent.tasks[task_index]
            status = task_status[task_index]
            pos = (row, col)

            if status in ("pending", "going_to_pickup"):
                if pos == task.pickup_position:
                    status = "going_to_delivery"
                    task_status[task_index] = status
            elif status in ("picked_up", "going_to_delivery"):
                if pos == task.delivery_position:
                    status = "completed"
                    task_status[task_index] = status
                    task_index += 1

        return task_index >= len(agent.tasks)

    def _state_at_or_after(
        self,
        trajectory: Trajectory,
        disruption_time: int,
    ) -> Optional[tuple[int, int, int]]:
        """Return the first trajectory state at or after disruption_time."""
        for state in trajectory:
            if state[2] >= disruption_time:
                return state
        return None

    def _state_is_blocked(self, position: Position, timestep: int) -> bool:
        """Check if a position is statically or dynamically blocked at timestep."""
        if not self.grid.is_walkable(position):
            return True
        if self.obstacle_manager is not None and self.obstacle_manager.is_temporarily_blocked(position, timestep):
            return True
        return False

    def _create_candidate(
        self,
        agent: Agent,
        original: Trajectory,
        repaired: Trajectory,
        rejoin_index: Optional[int],
        description: str,
        disruption: Optional[Disruption] = None,
        task: Optional[Task] = None,
        metadata: Optional[dict[str, object]] = None,
    ) -> RepairCandidate:
        """Build and populate a RepairCandidate."""
        changed_states = self._count_changed_states(original, repaired)
        original_cost = SpaceTimeAStar.path_cost(original, self.grid)
        repaired_cost = SpaceTimeAStar.path_cost(repaired, self.grid)
        additional_cost = max(0.0, repaired_cost - original_cost)

        original_makespan = original[-1][2] if original else 0
        repaired_makespan = repaired[-1][2] if repaired else 0
        additional_delay = max(0, repaired_makespan - original_makespan)

        meta: dict[str, object] = dict(metadata or {})
        if disruption is not None:
            meta["disruption_id"] = disruption.disruption_id
            meta["disruption_type"] = disruption.disruption_type.value

        return RepairCandidate(
            agent_id=agent.agent_id,
            trajectory=repaired,
            rejoin_index=rejoin_index,
            changed_states=changed_states,
            additional_cost=additional_cost,
            additional_delay=additional_delay,
            description=description,
            task=task,
            metadata=meta,
        )

    @staticmethod
    def _count_changed_states(original: Trajectory, repaired: Trajectory) -> int:
        """Count differences between original and repaired plans."""
        orig_map = {t: (r, c) for r, c, t in original}
        rep_map = {t: (r, c) for r, c, t in repaired}
        all_times = set(orig_map.keys()) | set(rep_map.keys())
        return sum(1 for t in all_times if orig_map.get(t) != rep_map.get(t))
