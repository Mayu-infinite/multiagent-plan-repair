"""Repair manager for the multi-agent warehouse.

Coordinates disruption response:
1. Impact analysis (identifying affected agents).
2. Local proposal generation via LocalRepairEngine.
3. Cooperative negotiation via NegotiationEngine to minimize modified agents.
4. Plan validation and execution update.

The initial multi-agent planner is NEVER re-invoked from scratch.
"""

from __future__ import annotations

from copy import deepcopy
from time import perf_counter
from typing import Iterable, Optional

from ..agents import Agent, Task
from ..agents.agent import Trajectory
from ..environment import DynamicObstacleManager, Grid, Position
from ..metrics import MetricsCollector
from ..planning import ConflictDetector, ReservationTable, SpaceTimeAStar
from .disruption import Disruption, DisruptionType
from .local_repair import LocalRepairEngine, RepairCandidate
from .negotiation import NegotiationEngine, NegotiationResult, RepairProposal


class RepairResult:
    """Outcome of a plan repair operation."""

    def __init__(
        self,
        *,
        success: bool,
        disruption: Disruption,
        affected_agents: list[str],
        neighbor_agents: list[str],
        modified_agents: list[str],
        negotiation_result: NegotiationResult,
        reason: str,
        repair_time: float,
    ) -> None:
        self.success = success
        self.disruption = disruption
        self.affected_agents = affected_agents
        self.neighbor_agents = neighbor_agents
        self.modified_agents = modified_agents
        self.negotiation_result = negotiation_result
        self.reason = reason
        self.repair_time = repair_time

    @property
    def modified_agent_count(self) -> int:
        return len(self.modified_agents)

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "disruption": self.disruption.to_dict(),
            "affected_agents": self.affected_agents,
            "neighbor_agents": self.neighbor_agents,
            "modified_agents": self.modified_agents,
            "modified_agent_count": self.modified_agent_count,
            "negotiation": self.negotiation_result.to_dict(),
            "reason": self.reason,
            "repair_time": self.repair_time,
        }

    def __repr__(self) -> str:
        return (
            f"RepairResult("
            f"success={self.success}, "
            f"modified_agents={self.modified_agents}, "
            f"repair_time={self.repair_time:.6f}s"
            f")"
        )


class RepairManager:
    """Manages local plan repair and neighbor negotiation for all disruption events."""

    def __init__(
        self,
        grid: Grid,
        obstacle_manager: Optional[DynamicObstacleManager] = None,
        metrics: Optional[MetricsCollector] = None,
        *,
        max_negotiation_neighbors: int = 4,
        max_negotiation_rounds: int = 5,
        repair_horizon: int = 30,
        max_alternatives: int = 5,
        communication_distance: int = 8,
        max_time_steps: int = 500,
        max_search_nodes: int = 50000,
        heuristic: str = "manhattan",
    ) -> None:
        self.grid = grid
        self.obstacle_manager = obstacle_manager
        self.metrics = metrics
        self.max_negotiation_neighbors = max_negotiation_neighbors
        self.max_negotiation_rounds = max_negotiation_rounds
        self.repair_horizon = repair_horizon
        self.max_alternatives = max_alternatives
        self.communication_distance = communication_distance
        self.max_time_steps = max_time_steps
        self.max_search_nodes = max_search_nodes
        self.heuristic = heuristic

        self.pathfinder = SpaceTimeAStar(
            grid=grid,
            obstacle_manager=obstacle_manager,
            heuristic=heuristic,
            max_time_steps=max_time_steps,
            max_search_nodes=max_search_nodes,
        )

        self.conflict_detector = ConflictDetector(
            grid=grid,
            obstacle_manager=obstacle_manager,
        )

        self.repair_engine = LocalRepairEngine(
            grid=grid,
            pathfinder=self.pathfinder,
            obstacle_manager=obstacle_manager,
            max_alternatives=max_alternatives,
            repair_horizon=repair_horizon,
        )

        self.negotiator = NegotiationEngine(
            conflict_detector=self.conflict_detector,
            max_rounds=max_negotiation_rounds,
            max_neighbors=max_negotiation_neighbors,
        )

    def handle_disruption(
        self,
        disruption: Disruption,
        agents: Iterable[Agent],
    ) -> RepairResult:
        """Handle a disruption event without global replanning."""
        start_time = perf_counter()
        agent_list = list(agents)

        if not agent_list:
            empty_neg = NegotiationResult(
                success=False,
                selected_proposal=None,
                rounds=0,
                participating_agents=[],
                rejected_proposals=0,
                reason="No agents available.",
            )
            return RepairResult(
                success=False,
                disruption=disruption,
                affected_agents=[],
                neighbor_agents=[],
                modified_agents=[],
                negotiation_result=empty_neg,
                reason="No agents are available for repair.",
                repair_time=perf_counter() - start_time,
            )

        if self.metrics is not None:
            self.metrics.record_disruption(disruption.disruption_type.value)

        if disruption.is_dynamic_obstacle:
            result = self._handle_dynamic_obstacle(disruption, agent_list, start_time)
        elif disruption.is_agent_failure:
            result = self._handle_agent_failure(disruption, agent_list, start_time)
        elif disruption.is_emergency_task:
            result = self._handle_emergency_task(disruption, agent_list, start_time)
        else:
            raise ValueError(f"Unknown disruption type: {disruption.disruption_type}")

        if self.metrics is not None:
            self.metrics.add_repair_time(result.repair_time)
            self.metrics.record_negotiation(result.negotiation_result.rounds)

        return result

    def _handle_dynamic_obstacle(
        self,
        disruption: Disruption,
        agents: list[Agent],
        start_time: float,
    ) -> RepairResult:
        """Repair agents whose paths collide with dynamic obstacle(s)."""
        self._apply_dynamic_obstacle(disruption)

        affected = self.identify_affected_agents(disruption, agents)
        affected_ids = [a.agent_id for a in affected]

        if not affected:
            neg = NegotiationResult(
                success=True,
                selected_proposal=None,
                rounds=0,
                participating_agents=[],
                rejected_proposals=0,
                reason="No agents affected by dynamic obstacle.",
            )
            return RepairResult(
                success=True,
                disruption=disruption,
                affected_agents=[],
                neighbor_agents=[],
                modified_agents=[],
                negotiation_result=neg,
                reason="No agents were affected by the disruption.",
                repair_time=perf_counter() - start_time,
            )

        modified_agents: list[str] = []
        all_neighbor_ids: set[str] = set()
        total_rounds = 0
        last_neg_result: Optional[NegotiationResult] = None

        # Prioritized sequential repair of each affected agent
        for affected_agent in affected:
            if affected_agent.status.value == "failed":
                continue

            # Build reservations containing all other agents (unaffected + previously repaired)
            reservations = self._build_repair_reservations(
                agents,
                excluded_agent_ids={affected_agent.agent_id},
            )

            neighbors = self.negotiator.find_neighbors(
                affected_agent,
                agents,
                communication_distance=self.communication_distance,
            )
            neighbor_ids = [n.agent_id for n in neighbors]
            all_neighbor_ids.update(neighbor_ids)

            # Generate proposals for this affected agent
            proposals = self.repair_engine.generate_proposals(
                agent=affected_agent,
                disruption=disruption,
                reservations=reservations,
                candidate_agent_id=affected_agent.agent_id,
            )

            # Validate each proposal against base trajectories
            base_trajectories = {
                a.agent_id: list(a.current_plan)
                for a in agents
                if a.agent_id != affected_agent.agent_id and a.status.value != "failed"
            }

            for prop in proposals:
                self.negotiator.validate_proposal(prop, base_trajectories)

            participating = sorted(set([affected_agent.agent_id] + neighbor_ids))
            neg_result = self.negotiator.negotiate(proposals, participating_agents=participating)
            total_rounds += max(1, neg_result.rounds)
            last_neg_result = neg_result

            if neg_result.success and neg_result.selected_proposal is not None:
                prop = neg_result.selected_proposal
                self._apply_proposal(prop, agents, disruption)
                for mid in prop.modified_agents:
                    if mid not in modified_agents:
                        modified_agents.append(mid)
            else:
                # Direct milestone fallback
                milestone_cand = self.repair_engine._generate_milestone_candidate(
                    agent=affected_agent,
                    trajectory=affected_agent.current_plan,
                    invalid_index=0,
                    reservations=reservations,
                    disruption=disruption,
                )
                if milestone_cand is not None:
                    affected_agent.current_plan = list(milestone_cand.trajectory)
                    affected_agent.plan_modified = True
                    affected_agent.repair_count += 1
                    if affected_agent.agent_id not in modified_agents:
                        modified_agents.append(affected_agent.agent_id)

        for agent_id in affected_ids:
            agent = self._find_agent(agents, agent_id)
            if agent is not None and self._ensure_task_continuation(agent, agents, disruption.timestep):
                if agent_id not in modified_agents:
                    modified_agents.append(agent_id)

        # Validate final multi-agent plans
        valid = self.validate_plans(agents)
        elapsed = perf_counter() - start_time

        if last_neg_result is None:
            last_neg_result = NegotiationResult(
                success=valid,
                selected_proposal=None,
                rounds=total_rounds,
                participating_agents=sorted(set(affected_ids) | all_neighbor_ids),
                rejected_proposals=0,
                reason="Sequential repair executed.",
            )

        return RepairResult(
            success=valid,
            disruption=disruption,
            affected_agents=affected_ids,
            neighbor_agents=sorted(all_neighbor_ids),
            modified_agents=modified_agents,
            negotiation_result=last_neg_result,
            reason=(
                "Local dynamic-obstacle repair succeeded. "
                "Unaffected agents retained their existing plans."
                if valid
                else "Repaired trajectory conflict detected."
            ),
            repair_time=elapsed,
        )

    def _ensure_task_continuation(self, agent, agents, timestep):
        """Ensure a repaired agent still has a route to its current task goal."""

        task = agent.current_task
        if task is None or task.is_completed:
            return False

        if task.status.value in {"pending", "going_to_pickup"}:
            goal = task.pickup_position
        elif task.status.value in {"picked_up", "going_to_delivery"}:
            goal = task.delivery_position
        else:
            return False

        reservations = ReservationTable()
        for other in agents:
            if other.agent_id != agent.agent_id and other.status.value != "failed":
                reservations.add_trajectory(other.current_plan)

        future_plan = [state for state in agent.current_plan if state[2] >= timestep]

        if future_plan:
            last_state = future_plan[-1]
            last_position = (last_state[0], last_state[1])
            last_time = last_state[2]

            if last_position == goal:
                return False

            route = self.repair_engine.pathfinder.search(
                start=last_position,
                goal=goal,
                start_time=last_time,
                reservations=reservations,
                max_time_steps=last_time + 200,
            )
            if route is None:
                return False

            combined = future_plan + route[1:]

        else:
            start_time = max(timestep, agent.current_time)
            route = self.repair_engine.pathfinder.search(
                start=agent.current_position,
                goal=goal,
                start_time=start_time,
                reservations=reservations,
                max_time_steps=start_time + 200,
            )

            if route is None:
                return False

            combined = route

        if not self.repair_engine.pathfinder.validate_trajectory(
            combined, self.grid, self.obstacle_manager
        ):
            return False

        agent.current_plan = list(combined)
        agent.plan_modified = True
        agent.repair_count += 1
        return True

    def _handle_agent_failure(
        self,
        disruption: Disruption,
        agents: list[Agent],
        start_time: float,
    ) -> RepairResult:
        """Handle agent breakdown by transferring unfinished tasks to a healthy neighbor."""
        failed_agent = self._find_agent(agents, disruption.agent_id)
        if failed_agent is None:
            empty_neg = NegotiationResult(
                success=False,
                selected_proposal=None,
                rounds=0,
                participating_agents=[],
                rejected_proposals=0,
                reason=f"Failed agent {disruption.agent_id} not found.",
            )
            return RepairResult(
                success=False,
                disruption=disruption,
                affected_agents=[],
                neighbor_agents=[],
                modified_agents=[],
                negotiation_result=empty_neg,
                reason="Failed agent not found.",
                repair_time=perf_counter() - start_time,
            )

        failed_agent.mark_failed()

        # Add permanent obstacle at failed agent's position
        if self.obstacle_manager is not None:
            self.obstacle_manager.add_obstacle(
                position=failed_agent.current_position,
                start_time=disruption.timestep,
                duration=self.max_time_steps,
                obstacle_id=f"failure-{failed_agent.agent_id}",
            )

        unfinished_tasks = [t for t in failed_agent.tasks if not t.is_completed]
        if not unfinished_tasks:
            neg = NegotiationResult(
                success=True,
                selected_proposal=None,
                rounds=0,
                participating_agents=[failed_agent.agent_id],
                rejected_proposals=0,
                reason="Failed agent had no pending tasks.",
            )
            return RepairResult(
                success=True,
                disruption=disruption,
                affected_agents=[failed_agent.agent_id],
                neighbor_agents=[],
                modified_agents=[],
                negotiation_result=neg,
                reason="Failed agent had no pending tasks.",
                repair_time=perf_counter() - start_time,
            )

        # Candidate receivers: healthy neighbors first, then nearest healthy agents
        neighbors = self.negotiator.find_neighbors(
            failed_agent,
            agents,
            communication_distance=self.communication_distance,
        )
        candidates = [n for n in neighbors if n.status.value != "failed"]

        if not candidates:
            healthy = [a for a in agents if a.status.value != "failed"]
            healthy.sort(
                key=lambda a: self._manhattan(a.current_position, failed_agent.current_position)
            )
            candidates = healthy[: max(1, self.max_negotiation_neighbors * 2)]

        proposals: list[RepairProposal] = []
        base_trajectories = {
            a.agent_id: list(a.current_plan)
            for a in agents
            if a.status.value != "failed"
        }

        for candidate in candidates:
            reservations = self._build_repair_reservations(
                agents,
                excluded_agent_ids={candidate.agent_id},
            )
            transfer_cands = self.repair_engine.transfer_task_from_failed_agent(
                receiver=candidate,
                failed_agent=failed_agent,
                disruption_time=disruption.timestep,
                reservations=reservations,
            )
            for cand in transfer_cands:
                proposal = RepairProposal(
                    proposer=candidate.agent_id,
                    modified_agents={candidate.agent_id},
                    trajectories={candidate.agent_id: cand.trajectory},
                    description=cand.description,
                    additional_delay=cand.additional_delay,
                    additional_path_cost=cand.additional_cost,
                    metadata={"transferred_task": unfinished_tasks[0].task_id},
                )
                self.negotiator.validate_proposal(
                    proposal,
                    {aid: t for aid, t in base_trajectories.items() if aid != candidate.agent_id},
                )
                proposals.append(proposal)

        participating = sorted(set([failed_agent.agent_id] + [c.agent_id for c in candidates]))
        neg_result = self.negotiator.negotiate(proposals, participating_agents=participating)

        modified_agents: list[str] = []
        if neg_result.success and neg_result.selected_proposal is not None:
            proposal = neg_result.selected_proposal
            receiver_id = proposal.proposer
            receiver = self._find_agent(agents, receiver_id)
            if receiver is not None:
                receiver.current_plan = list(proposal.trajectories[receiver_id])
                receiver.plan_modified = True
                receiver.repair_count += 1
                for task in unfinished_tasks:
                    receiver.add_task(task)
                modified_agents.append(receiver_id)

                # Mark transferred tasks as completed on failed agent so simulator won't block
                for task in unfinished_tasks:
                    task.status = Task.status.default if hasattr(Task, "status") else task.status

        valid = self.validate_plans(agents)
        elapsed = perf_counter() - start_time

        return RepairResult(
            success=neg_result.success and valid,
            disruption=disruption,
            affected_agents=[failed_agent.agent_id],
            neighbor_agents=[c.agent_id for c in candidates],
            modified_agents=modified_agents,
            negotiation_result=neg_result,
            reason=neg_result.reason,
            repair_time=elapsed,
        )

    def _handle_emergency_task(
        self,
        disruption: Disruption,
        agents: list[Agent],
        start_time: float,
    ) -> RepairResult:
        """Assign an emergency task to the optimal candidate robot."""
        if disruption.task is None:
            empty_neg = NegotiationResult(
                success=False,
                selected_proposal=None,
                rounds=0,
                participating_agents=[],
                rejected_proposals=0,
                reason="Emergency task is missing.",
            )
            return RepairResult(
                success=False,
                disruption=disruption,
                affected_agents=[],
                neighbor_agents=[],
                modified_agents=[],
                negotiation_result=empty_neg,
                reason="Emergency task is missing.",
                repair_time=perf_counter() - start_time,
            )

        pickup = disruption.task.pickup_position
        healthy = [a for a in agents if a.status.value != "failed"]
        healthy.sort(key=lambda a: self._manhattan(a.current_position, pickup))
        candidates = healthy[: max(1, self.max_negotiation_neighbors * 2)]

        proposals: list[RepairProposal] = []
        base_trajectories = {
            a.agent_id: list(a.current_plan)
            for a in agents
            if a.status.value != "failed"
        }

        for candidate in candidates:
            reservations = self._build_repair_reservations(
                agents,
                excluded_agent_ids={candidate.agent_id},
            )
            cands = self.repair_engine.insert_emergency_task(
                agent=candidate,
                task=disruption.task,
                disruption_time=disruption.timestep,
                reservations=reservations,
            )
            for cand in cands:
                prop = RepairProposal(
                    proposer=candidate.agent_id,
                    modified_agents={candidate.agent_id},
                    trajectories={candidate.agent_id: cand.trajectory},
                    description=cand.description,
                    additional_delay=cand.additional_delay,
                    additional_path_cost=cand.additional_cost,
                    metadata={"task_id": disruption.task.task_id},
                )
                self.negotiator.validate_proposal(
                    prop,
                    {aid: t for aid, t in base_trajectories.items() if aid != candidate.agent_id},
                )
                proposals.append(prop)

        participating = sorted([c.agent_id for c in candidates])
        neg_result = self.negotiator.negotiate(proposals, participating_agents=participating)

        modified_agents: list[str] = []
        if neg_result.success and neg_result.selected_proposal is not None:
            prop = neg_result.selected_proposal
            assigned = self._find_agent(agents, prop.proposer)
            if assigned is not None:
                assigned.current_plan = list(prop.trajectories[assigned.agent_id])
                assigned.plan_modified = True
                assigned.repair_count += 1
                assigned.add_task(disruption.task)
                modified_agents.append(assigned.agent_id)

        valid = self.validate_plans(agents)
        elapsed = perf_counter() - start_time

        return RepairResult(
            success=neg_result.success and valid,
            disruption=disruption,
            affected_agents=modified_agents,
            neighbor_agents=[c.agent_id for c in candidates],
            modified_agents=modified_agents,
            negotiation_result=neg_result,
            reason=neg_result.reason,
            repair_time=elapsed,
        )

    def identify_affected_agents(
        self,
        disruption: Disruption,
        agents: Iterable[Agent],
    ) -> list[Agent]:
        """Identify agents whose current or future execution is invalidated by the disruption."""
        agent_list = list(agents)

        if disruption.is_agent_failure:
            return [a for a in agent_list if a.agent_id == disruption.agent_id]

        if disruption.is_dynamic_obstacle:
            result: list[Agent] = []
            for agent in agent_list:
                if agent.status.value == "failed":
                    continue
                if self._trajectory_hits_dynamic_obstacle(agent.current_plan, disruption):
                    result.append(agent)
            return result

        if disruption.is_emergency_task:
            healthy = [a for a in agent_list if a.status.value != "failed"]
            if disruption.task is not None:
                pickup = disruption.task.pickup_position
                healthy.sort(key=lambda a: self._manhattan(a.current_position, pickup))
            return healthy[:1]

        return []

    def _trajectory_hits_dynamic_obstacle(
        self,
        trajectory: Trajectory,
        disruption: Disruption,
    ) -> bool:
        """Check if trajectory visits disruption position or any dynamic obstacle."""
        disruption_time = disruption.timestep
        disruption_pos = disruption.position

        for row, col, timestep in trajectory:
            if timestep < disruption_time:
                continue
            pos = (row, col)
            if disruption_pos is not None and pos == disruption_pos:
                return True
            if self.obstacle_manager is not None and self.obstacle_manager.is_temporarily_blocked(pos, timestep):
                return True
        return False

    def find_neighbors(
        self,
        affected_agents: Iterable[Agent],
        agents: Iterable[Agent],
    ) -> list[Agent]:
        """Identify agents relevant to the affected set for negotiation."""
        affected_list = list(affected_agents)
        all_agents = list(agents)
        neighbors: list[Agent] = []
        seen = {a.agent_id for a in affected_list}

        for affected in affected_list:
            found = self.negotiator.find_neighbors(
                focal_agent=affected,
                agents=all_agents,
                communication_distance=self.communication_distance,
            )
            for n in found:
                if n.agent_id not in seen:
                    seen.add(n.agent_id)
                    neighbors.append(n)

        return neighbors

    def generate_proposals(
        self,
        disruption: Disruption,
        affected_agents: Iterable[Agent],
        neighbor_agents: Iterable[Agent],
        all_agents: Iterable[Agent],
    ) -> list[RepairProposal]:
        """Generate candidate repair proposals for negotiation."""
        affected = list(affected_agents)
        all_agent_list = list(all_agents)
        proposals: list[RepairProposal] = []

        for agent in affected:
            reservations = self._build_repair_reservations(
                all_agent_list,
                excluded_agent_ids={agent.agent_id},
            )
            agent_proposals = self.repair_engine.generate_proposals(
                agent=agent,
                disruption=disruption,
                reservations=reservations,
            )
            proposals.extend(agent_proposals)

        return proposals

    def validate_plans(self, agents: Iterable[Agent]) -> bool:
        """Validate all non-failed agents' trajectories for collisions."""
        active_agents = [a for a in agents if a.status.value != "failed"]
        trajectory_map: dict[str, Trajectory] = {}

        for a in active_agents:
            trajectory_map[a.agent_id] = list(a.current_plan)

        for traj in trajectory_map.values():
            if not self.conflict_detector.validate_trajectory(traj):
                return False

        conflicts = self.conflict_detector.detect(trajectory_map)
        return len(conflicts) == 0

    def _apply_proposal(
        self,
        proposal: RepairProposal,
        agents: list[Agent],
        disruption: Disruption,
    ) -> list[str]:
        """Apply the selected repair proposal to agents."""
        modified: list[str] = []
        for agent_id, traj in proposal.trajectories.items():
            agent = self._find_agent(agents, agent_id)
            if agent is None:
                continue
            if agent.current_plan != traj:
                agent.current_plan = list(traj)
                agent.plan_modified = True
                agent.repair_count += 1
                modified.append(agent_id)
                if self.metrics is not None:
                    self.metrics.record_plan_modification(agent_id=agent_id, repair_count=agent.repair_count, original_path_length=len(agent.original_plan), final_path_length=len(agent.current_plan))

        return modified

    def _apply_dynamic_obstacle(self, disruption: Disruption) -> None:
        """Register the dynamic obstacle with obstacle_manager."""
        if self.obstacle_manager is None:
            return
        if disruption.position is None or disruption.duration is None:
            return
        self.obstacle_manager.add_obstacle(
            position=disruption.position,
            start_time=disruption.timestep,
            duration=disruption.duration,
            obstacle_id=disruption.disruption_id,
        )

    def _build_repair_reservations(
        self,
        agents: Iterable[Agent],
        *,
        excluded_agent_ids: Optional[set[str]] = None,
    ) -> ReservationTable:
        """Build reservation table from current trajectories of other agents."""
        excluded = set(excluded_agent_ids or set())
        reservations = ReservationTable()
        for a in agents:
            if a.agent_id in excluded or a.status.value == "failed":
                continue
            reservations.add_trajectory(a.current_plan)
        return reservations

    @staticmethod
    def _find_agent(agents: Iterable[Agent], agent_id: Optional[str]) -> Optional[Agent]:
        if agent_id is None:
            return None
        for a in agents:
            if a.agent_id == agent_id:
                return a
        return None

    @staticmethod
    def _manhattan(pos_a: Position, pos_b: Position) -> int:
        return abs(pos_a[0] - pos_b[0]) + abs(pos_a[1] - pos_b[1])
