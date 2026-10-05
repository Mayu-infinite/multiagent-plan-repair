"""
Cooperative negotiation for local plan repair.

The negotiation layer allows affected and neighboring agents to
evaluate alternative repair proposals.

The main optimization principle is lexicographic:

    1. Minimize number of modified agents.
    2. Minimize introduced conflicts.
    3. Minimize additional delay.
    4. Minimize additional path cost.
    5. Minimize trajectory changes.

This means preserving existing plans is preferred over making
unnecessary changes elsewhere.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from ..agents import Agent
from ..agents.agent import Trajectory
from ..planning.conflict_detection import (
    Conflict,
    ConflictDetector,
)


# ---------------------------------------------------------------------------
# Repair proposal
# ---------------------------------------------------------------------------

@dataclass
class RepairProposal:
    """
    Candidate solution proposed during local negotiation.

    Parameters
    ----------
    proposer:
        Agent proposing the repair.

    modified_agents:
        Agents whose current plans would change.

    trajectories:
        New trajectories for modified agents.

    description:
        Human-readable proposal description.

    additional_delay:
        Estimated additional delay.

    additional_path_cost:
        Additional path cost compared with the baseline.

    conflicts:
        Conflicts introduced by the proposal.

    metadata:
        Optional additional proposal information.
    """

    proposer: str

    modified_agents: set[str]

    trajectories: dict[str, Trajectory]

    description: str = ""

    additional_delay: int = 0

    additional_path_cost: float = 0.0

    conflicts: list[Conflict] = field(
        default_factory=list
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    # -----------------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------------

    def __post_init__(self) -> None:
        if not self.proposer:
            raise ValueError(
                "Proposal proposer cannot be empty."
            )

        if self.additional_delay < 0:
            raise ValueError(
                "additional_delay cannot be negative."
            )

        if self.additional_path_cost < 0:
            raise ValueError(
                "additional_path_cost cannot be negative."
            )

        trajectory_agents = set(
            self.trajectories.keys()
        )

        if not trajectory_agents.issubset(
            self.modified_agents
        ):
            raise ValueError(
                "Every trajectory in a proposal must belong to "
                "a modified agent."
            )

    @property
    def modified_agent_count(self) -> int:
        """Number of agents changed by this proposal."""
        return len(self.modified_agents)

    @property
    def conflict_count(self) -> int:
        """Number of conflicts in this proposal."""
        return len(self.conflicts)

    @property
    def is_feasible(self) -> bool:
        """Return True when the proposal introduces no conflicts."""
        return self.conflict_count == 0

    def score(self) -> tuple:
        """
        Return the negotiation score.

        Lower is better.

        The first component is deliberately the number of modified
        agents because plan preservation is the primary objective.
        """
        return (
            self.modified_agent_count,
            self.conflict_count,
            self.additional_delay,
            self.additional_path_cost,
            self._trajectory_change_count(),
        )

    def _trajectory_change_count(self) -> int:
        """
        Return the total number of states in the proposed trajectories.

        This acts as a final tie-breaker.
        """
        return sum(
            len(trajectory)
            for trajectory in self.trajectories.values()
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the proposal to a serializable structure."""
        return {
            "proposer": self.proposer,
            "modified_agents": sorted(
                self.modified_agents
            ),
            "trajectories": {
                agent_id: list(trajectory)
                for agent_id, trajectory
                in self.trajectories.items()
            },
            "description": self.description,
            "additional_delay": self.additional_delay,
            "additional_path_cost": self.additional_path_cost,
            "conflicts": [
                conflict.to_dict()
                for conflict in self.conflicts
            ],
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Negotiation result
# ---------------------------------------------------------------------------

@dataclass
class NegotiationResult:
    """
    Result of a negotiation session.
    """

    success: bool

    selected_proposal: Optional[RepairProposal]

    rounds: int

    participating_agents: list[str]

    rejected_proposals: int = 0

    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert result to a serializable dictionary."""
        return {
            "success": self.success,
            "selected_proposal": (
                self.selected_proposal.to_dict()
                if self.selected_proposal is not None
                else None
            ),
            "rounds": self.rounds,
            "participating_agents": self.participating_agents,
            "rejected_proposals": self.rejected_proposals,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Negotiation engine
# ---------------------------------------------------------------------------

class NegotiationEngine:
    """
    Coordinates local negotiation between agents.

    The engine itself does not generate paths. It evaluates proposals
    produced by the local repair layer.

    Parameters
    ----------
    conflict_detector:
        Used to independently validate proposed trajectories.

    max_rounds:
        Maximum number of negotiation rounds.

    max_neighbors:
        Maximum number of relevant neighboring agents.
    """

    def __init__(
        self,
        conflict_detector: ConflictDetector,
        *,
        max_rounds: int = 5,
        max_neighbors: int = 4,
    ) -> None:
        if max_rounds <= 0:
            raise ValueError(
                "max_rounds must be greater than zero."
            )

        if max_neighbors <= 0:
            raise ValueError(
                "max_neighbors must be greater than zero."
            )

        self.conflict_detector = conflict_detector

        self.max_rounds = max_rounds
        self.max_neighbors = max_neighbors

    # -----------------------------------------------------------------------
    # Neighbor discovery
    # -----------------------------------------------------------------------

    def find_neighbors(
        self,
        focal_agent: Agent,
        agents: Iterable[Agent],
        *,
        communication_distance: int = 8,
    ) -> list[Agent]:
        """
        Identify agents relevant to a focal agent.

        Two agents are considered neighbors when either:

        1. Their current positions are within the communication distance.
        2. Their future trajectories intersect in space-time.

        The result is limited by max_neighbors.
        """
        if communication_distance < 0:
            raise ValueError(
                "communication_distance cannot be negative."
            )

        candidates: list[
            tuple[int, Agent]
        ] = []

        for agent in agents:

            if agent.agent_id == focal_agent.agent_id:
                continue

            distance = (
                abs(
                    agent.current_position[0]
                    - focal_agent.current_position[0]
                )
                + abs(
                    agent.current_position[1]
                    - focal_agent.current_position[1]
                )
            )

            trajectory_overlap = self._trajectories_interact(
                focal_agent.current_plan,
                agent.current_plan,
            )

            if (
                distance <= communication_distance
                or trajectory_overlap
            ):
                # Trajectory interaction gets priority over
                # simple spatial proximity.
                priority_distance = (
                    0 if trajectory_overlap else 1
                )

                candidates.append(
                    (
                        priority_distance * 1000 + distance,
                        agent,
                    )
                )

        candidates.sort(
            key=lambda item: (
                item[0],
                item[1].agent_id,
            )
        )

        return [
            agent
            for _, agent in candidates[: self.max_neighbors]
        ]

    # -----------------------------------------------------------------------
    # Proposal validation
    # -----------------------------------------------------------------------

    def validate_proposal(
        self,
        proposal: RepairProposal,
        base_trajectories: Mapping[str, Trajectory],
    ) -> RepairProposal:
        """
        Validate a proposal against the unchanged trajectories.

        The proposal is evaluated together with all unaffected plans.
        """
        combined = {
            agent_id: deepcopy(trajectory)
            for agent_id, trajectory
            in base_trajectories.items()
        }

        for agent_id, trajectory in proposal.trajectories.items():
            combined[agent_id] = deepcopy(trajectory)

        conflicts = self.conflict_detector.detect(
            combined
        )

        proposal.conflicts = conflicts

        return proposal

    # -----------------------------------------------------------------------
    # Negotiation
    # -----------------------------------------------------------------------

    def negotiate(
        self,
        proposals: Iterable[RepairProposal],
        *,
        participating_agents: Optional[Iterable[str]] = None,
    ) -> NegotiationResult:
        """
        Select the best feasible proposal.

        The engine models bounded cooperative negotiation by evaluating
        proposals in rounds. Each round can be interpreted as agents
        exchanging and rejecting/accepting possible alternatives.

        Parameters
        ----------
        proposals:
            Candidate repair proposals.

        participating_agents:
            Agent identifiers taking part in negotiation.
        """
        proposal_list = list(proposals)

        if participating_agents is None:
            participants: set[str] = set()

            for proposal in proposal_list:
                participants.add(
                    proposal.proposer
                )

                participants.update(
                    proposal.modified_agents
                )

            participating = sorted(
                participants
            )

        else:
            participating = sorted(
                set(participating_agents)
            )

        if not proposal_list:
            return NegotiationResult(
                success=False,
                selected_proposal=None,
                rounds=0,
                participating_agents=participating,
                rejected_proposals=0,
                reason="No repair proposals were generated.",
            )

        feasible = [
            proposal
            for proposal in proposal_list
            if proposal.is_feasible
        ]

        if not feasible:
            return NegotiationResult(
                success=False,
                selected_proposal=None,
                rounds=min(
                    len(proposal_list),
                    self.max_rounds,
                ),
                participating_agents=participating,
                rejected_proposals=len(proposal_list),
                reason=(
                    "All proposals were rejected because they "
                    "were infeasible."
                ),
            )

        # ---------------------------------------------------------------
        # Lexicographic agreement:
        # lowest score wins.
        # ---------------------------------------------------------------

        feasible.sort(
            key=lambda proposal: proposal.score()
        )

        selected = feasible[0]

        rejected = len(proposal_list) - 1

        rounds = min(
            max(1, len(proposal_list)),
            self.max_rounds,
        )

        return NegotiationResult(
            success=True,
            selected_proposal=selected,
            rounds=rounds,
            participating_agents=participating,
            rejected_proposals=rejected,
            reason=(
                "Selected the minimum-impact feasible "
                "repair proposal."
            ),
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _trajectories_interact(
        trajectory_a: Trajectory,
        trajectory_b: Trajectory,
    ) -> bool:
        """
        Return True if two trajectories have a spatial-temporal
        interaction.

        Both vertex and edge interactions are considered.
        """
        states_a = {
            timestep: (row, col)
            for row, col, timestep in trajectory_a
        }

        states_b = {
            timestep: (row, col)
            for row, col, timestep in trajectory_b
        }

        common_times = (
            set(states_a.keys())
            & set(states_b.keys())
        )

        for timestep in common_times:
            if states_a[timestep] == states_b[timestep]:
                return True

        # Edge interactions.
        ordered_a = sorted(
            trajectory_a,
            key=lambda state: state[2],
        )

        ordered_b = sorted(
            trajectory_b,
            key=lambda state: state[2],
        )

        transitions_a = {
            time: (
                (ordered_a[index][0], ordered_a[index][1]),
                (
                    ordered_a[index + 1][0],
                    ordered_a[index + 1][1],
                ),
            )
            for index in range(len(ordered_a) - 1)
            for time in [ordered_a[index][2]]
            if ordered_a[index + 1][2]
            == ordered_a[index][2] + 1
        }

        transitions_b = {
            time: (
                (ordered_b[index][0], ordered_b[index][1]),
                (
                    ordered_b[index + 1][0],
                    ordered_b[index + 1][1],
                ),
            )
            for index in range(len(ordered_b) - 1)
            for time in [ordered_b[index][2]]
            if ordered_b[index + 1][2]
            == ordered_b[index][2] + 1
        }

        common_transition_times = (
            set(transitions_a.keys())
            & set(transitions_b.keys())
        )

        for timestep in common_transition_times:
            source_a, destination_a = (
                transitions_a[timestep]
            )

            source_b, destination_b = (
                transitions_b[timestep]
            )

            if (
                source_a == destination_b
                and source_b == destination_a
            ):
                return True

        return False