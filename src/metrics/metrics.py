"""
Metrics collection and evaluation for the Multi-Agent Plan Repair system.

The metrics module is responsible for collecting quantitative measures
during simulation and plan repair.

Primary assignment metrics
--------------------------
1. Total completion time
2. Makespan
3. Number of modified agents
4. Modification ratio

Additional metrics
------------------
5. Total path cost
6. Repair computation time
7. Number of negotiation rounds
8. Number of conflicts
9. Disruption-induced delay

Design principle
----------------
This module does not perform planning or simulation itself.

It only records and computes measurements produced by those components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterable, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Position = tuple[int, int]
SpaceTimeState = tuple[int, int, int]
Trajectory = Sequence[SpaceTimeState]


# ---------------------------------------------------------------------------
# Per-agent execution metrics
# ---------------------------------------------------------------------------

@dataclass
class AgentMetrics:
    """
    Metrics associated with one agent.

    Attributes
    ----------
    agent_id:
        Unique agent identifier.

    completion_time:
        Timestep at which all tasks assigned to the agent were completed.
        None if the agent did not complete all tasks.

    path_cost:
        Total movement/wait cost accumulated by the agent.

    original_path_length:
        Number of movement states in the original plan.

    final_path_length:
        Number of movement states in the final/current plan.

    modified:
        Whether the agent's original plan was changed by plan repair.

    repair_count:
        Number of repair operations applied to this agent.

    delay:
        Additional delay associated with this agent.
    """

    agent_id: str

    completion_time: Optional[int] = None

    path_cost: float = 0.0

    original_path_length: int = 0
    final_path_length: int = 0

    modified: bool = False

    repair_count: int = 0

    delay: int = 0

    # Optional bookkeeping for analysis.
    task_count: int = 0
    completed_task_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to a serializable dictionary."""
        return {
            "agent_id": self.agent_id,
            "completion_time": self.completion_time,
            "path_cost": self.path_cost,
            "original_path_length": self.original_path_length,
            "final_path_length": self.final_path_length,
            "modified": self.modified,
            "repair_count": self.repair_count,
            "delay": self.delay,
            "task_count": self.task_count,
            "completed_task_count": self.completed_task_count,
        }


# ---------------------------------------------------------------------------
# Timer utility
# ---------------------------------------------------------------------------

class Timer:
    """
    Small utility for measuring elapsed wall-clock time.

    Primarily used for measuring plan-repair computation time.
    """

    def __init__(self) -> None:
        self._start_time: Optional[float] = None

    def start(self) -> None:
        """Start or restart the timer."""
        self._start_time = perf_counter()

    def stop(self) -> float:
        """
        Stop the timer and return elapsed seconds.

        Raises
        ------
        RuntimeError
            If the timer was never started.
        """
        if self._start_time is None:
            raise RuntimeError(
                "Timer.stop() called before Timer.start()."
            )

        elapsed = perf_counter() - self._start_time
        self._start_time = None

        return elapsed


# ---------------------------------------------------------------------------
# Metrics collector
# ---------------------------------------------------------------------------

@dataclass
class MetricsCollector:
    """
    Collects system-level metrics throughout one simulation.

    The collector is intentionally independent from Agent, Grid,
    Planner, and Simulator implementations.

    Parameters
    ----------
    total_agents:
        Number of agents participating in the experiment.
    """

    total_agents: int = 0

    # -----------------------------------------------------------------------
    # Core timing
    # -----------------------------------------------------------------------

    simulation_start_time: Optional[float] = field(
        default=None,
        init=False,
    )

    simulation_runtime: Optional[float] = field(
        default=None,
        init=False,
    )

    # Last simulation timestep observed.
    current_timestep: int = field(default=0, init=False)

    # Maximum completion timestep among completed agents.
    makespan: Optional[int] = field(default=None, init=False)

    # Sum of completion times for completed agents.
    total_completion_time: int = field(default=0, init=False)

    # -----------------------------------------------------------------------
    # Plan metrics
    # -----------------------------------------------------------------------

    total_path_cost: float = field(default=0.0, init=False)

    modified_agents: set[str] = field(
        default_factory=set,
        init=False,
    )

    # Count every repair event, even when multiple events affect
    # the same agent.
    total_repair_operations: int = field(default=0, init=False)

    # -----------------------------------------------------------------------
    # Repair metrics
    # -----------------------------------------------------------------------

    repair_time: float = field(default=0.0, init=False)

    negotiation_rounds: int = field(default=0, init=False)

    negotiation_events: int = field(default=0, init=False)

    # -----------------------------------------------------------------------
    # Conflict metrics
    # -----------------------------------------------------------------------

    conflicts: int = field(default=0, init=False)

    vertex_conflicts: int = field(default=0, init=False)

    edge_conflicts: int = field(default=0, init=False)

    obstacle_conflicts: int = field(default=0, init=False)

    # -----------------------------------------------------------------------
    # Disruption metrics
    # -----------------------------------------------------------------------

    disruptions: int = field(default=0, init=False)

    disruption_types: dict[str, int] = field(
        default_factory=dict,
        init=False,
    )

    delay: int = field(default=0, init=False)

    # -----------------------------------------------------------------------
    # Per-agent data
    # -----------------------------------------------------------------------

    agent_metrics: dict[str, AgentMetrics] = field(
        default_factory=dict,
        init=False,
    )

    # -----------------------------------------------------------------------
    # Simulation lifecycle
    # -----------------------------------------------------------------------

    def start_simulation(self) -> None:
        """
        Start wall-clock timing for the simulation.
        """
        self.simulation_start_time = perf_counter()

    def update_timestep(self, timestep: int) -> None:
        """
        Record the latest simulation timestep.
        """
        if timestep < 0:
            raise ValueError(
                "Simulation timestep cannot be negative."
            )

        if timestep < self.current_timestep:
            raise ValueError(
                "Simulation timestep cannot move backwards."
            )

        self.current_timestep = timestep

    def stop_simulation(self) -> None:
        """
        Stop wall-clock timing.
        """
        if self.simulation_start_time is None:
            return

        self.simulation_runtime = (
            perf_counter() - self.simulation_start_time
        )

        self.simulation_start_time = None

    # -----------------------------------------------------------------------
    # Agent registration
    # -----------------------------------------------------------------------

    def register_agent(
        self,
        agent_id: str,
        *,
        task_count: int = 0,
        original_path_length: int = 0,
    ) -> AgentMetrics:
        """
        Register an agent with the metrics collector.

        Calling this multiple times for the same agent updates its
        task/path information instead of creating duplicates.
        """
        if not agent_id:
            raise ValueError("agent_id cannot be empty.")

        if task_count < 0:
            raise ValueError(
                "task_count cannot be negative."
            )

        if original_path_length < 0:
            raise ValueError(
                "original_path_length cannot be negative."
            )

        if agent_id not in self.agent_metrics:
            self.agent_metrics[agent_id] = AgentMetrics(
                agent_id=agent_id,
                task_count=task_count,
                original_path_length=original_path_length,
            )
        else:
            metrics = self.agent_metrics[agent_id]

            metrics.task_count = task_count

            if original_path_length > 0:
                metrics.original_path_length = (
                    original_path_length
                )

        if self.total_agents == 0:
            self.total_agents = len(self.agent_metrics)

        return self.agent_metrics[agent_id]

    def register_agents(
        self,
        agents: Iterable[Any],
    ) -> None:
        """
        Register multiple Agent-like objects.

        The method intentionally uses duck typing to avoid making
        metrics.py depend on src.agents.agent.Agent.
        """
        agent_list = list(agents)

        for agent in agent_list:
            agent_id = str(agent.agent_id)

            current_metrics = self.register_agent(
                agent_id=agent_id,
                task_count=len(getattr(agent, "tasks", [])),
                original_path_length=len(
                    getattr(agent, "original_plan", [])
                ),
            )

            current_metrics.final_path_length = len(
                getattr(agent, "current_plan", [])
            )

        self.total_agents = max(
            self.total_agents,
            len(agent_list),
        )

    # -----------------------------------------------------------------------
    # Agent completion
    # -----------------------------------------------------------------------

    def record_agent_completion(
        self,
        agent_id: str,
        completion_time: int,
    ) -> None:
        """
        Record the completion time of one agent.

        Parameters
        ----------
        agent_id:
            Agent identifier.

        completion_time:
            Simulation timestep at which all its tasks were completed.
        """
        if completion_time < 0:
            raise ValueError(
                "completion_time cannot be negative."
            )

        metrics = self._get_or_create_agent(agent_id)

        # Do not overwrite an earlier completion time accidentally.
        if (
            metrics.completion_time is None
            or completion_time < metrics.completion_time
        ):
            metrics.completion_time = completion_time

        # Recompute aggregate completion statistics.
        self._recompute_completion_metrics()

    def record_task_completion(
        self,
        agent_id: str,
        completed_tasks: int,
    ) -> None:
        """
        Record the number of completed tasks for an agent.
        """
        if completed_tasks < 0:
            raise ValueError(
                "completed_tasks cannot be negative."
            )

        metrics = self._get_or_create_agent(agent_id)

        metrics.completed_task_count = completed_tasks

    # -----------------------------------------------------------------------
    # Path metrics
    # -----------------------------------------------------------------------

    def record_agent_path_cost(
        self,
        agent_id: str,
        path_cost: float,
    ) -> None:
        """
        Set the path cost for an agent.

        This is intended to represent the final accumulated execution
        cost for the agent.
        """
        if path_cost < 0:
            raise ValueError(
                "path_cost cannot be negative."
            )

        metrics = self._get_or_create_agent(agent_id)
        metrics.path_cost = float(path_cost)

        self._recompute_total_path_cost()

    def add_path_cost(
        self,
        agent_id: str,
        cost: float,
    ) -> None:
        """
        Add incremental execution cost to an agent.
        """
        if cost < 0:
            raise ValueError(
                "cost cannot be negative."
            )

        metrics = self._get_or_create_agent(agent_id)

        metrics.path_cost += float(cost)

        self.total_path_cost += float(cost)

    # -----------------------------------------------------------------------
    # Plan modification metrics
    # -----------------------------------------------------------------------

    def record_plan_modification(
        self,
        agent_id: str,
        *,
        repair_count: int | None = None,
        original_path_length: int | None = None,
        final_path_length: int | None = None,
    ) -> None:
        """
        Record that an agent's original plan was modified.

        The agent is counted only once in `modified_agents`, even if
        multiple repair operations modify it.
        """
        metrics = self._get_or_create_agent(agent_id)

        self.modified_agents.add(agent_id)

        metrics.modified = True

        if repair_count is not None:
            if repair_count < 0:
                raise ValueError(
                    "repair_count cannot be negative."
                )

            metrics.repair_count = repair_count
        else:
            metrics.repair_count += 1

        if original_path_length is not None:
            if original_path_length < 0:
                raise ValueError(
                    "original_path_length cannot be negative."
                )

            metrics.original_path_length = original_path_length

        if final_path_length is not None:
            if final_path_length < 0:
                raise ValueError(
                    "final_path_length cannot be negative."
                )

            metrics.final_path_length = final_path_length

        self.total_repair_operations += 1

    @property
    def modification_ratio(self) -> float:
        """
        Return the fraction of agents whose plans were modified.

        modification_ratio =
            modified_agents / total_agents
        """
        if self.total_agents <= 0:
            return 0.0

        return len(self.modified_agents) / self.total_agents

    @property
    def plan_preservation_ratio(self) -> float:
        """
        Return the fraction of agents whose original plans were preserved.

        plan_preservation_ratio =
            1 - modification_ratio
        """
        return 1.0 - self.modification_ratio

    # -----------------------------------------------------------------------
    # Repair computation time
    # -----------------------------------------------------------------------

    def add_repair_time(
        self,
        elapsed_seconds: float,
    ) -> None:
        """
        Add wall-clock time spent performing plan repair.
        """
        if elapsed_seconds < 0:
            raise ValueError(
                "elapsed_seconds cannot be negative."
            )

        self.repair_time += float(elapsed_seconds)

    def start_repair_timer(self) -> Timer:
        """
        Create and start a repair timer.

        Usage:

            timer = metrics.start_repair_timer()

            ...
            
            metrics.add_repair_time(timer.stop())
        """
        timer = Timer()
        timer.start()
        return timer

    # -----------------------------------------------------------------------
    # Negotiation metrics
    # -----------------------------------------------------------------------

    def record_negotiation(
        self,
        rounds: int,
    ) -> None:
        """
        Record one negotiation event.

        Parameters
        ----------
        rounds:
            Number of negotiation rounds used.
        """
        if rounds < 0:
            raise ValueError(
                "rounds cannot be negative."
            )

        self.negotiation_rounds += rounds
        self.negotiation_events += 1

    # -----------------------------------------------------------------------
    # Conflict metrics
    # -----------------------------------------------------------------------

    def record_conflict(
        self,
        conflict_type: str = "unknown",
        count: int = 1,
    ) -> None:
        """
        Record one or more conflicts.

        Supported conflict types:
            vertex
            edge
            obstacle
            unknown
        """
        if count < 0:
            raise ValueError(
                "Conflict count cannot be negative."
            )

        normalized_type = conflict_type.lower().strip()

        self.conflicts += count

        if normalized_type == "vertex":
            self.vertex_conflicts += count

        elif normalized_type == "edge":
            self.edge_conflicts += count

        elif normalized_type == "obstacle":
            self.obstacle_conflicts += count

    def record_conflicts(
        self,
        conflicts: Iterable[Any],
    ) -> None:
        """
        Record a collection of conflict objects/dictionaries.

        The method supports simple strings as well as dictionaries
        containing a `type` field.
        """
        for conflict in conflicts:

            if isinstance(conflict, str):
                conflict_type = conflict

            elif isinstance(conflict, Mapping):
                conflict_type = str(
                    conflict.get("type", "unknown")
                )

            else:
                conflict_type = str(
                    getattr(conflict, "type", "unknown")
                )

            self.record_conflict(
                conflict_type=conflict_type,
                count=1,
            )

    # -----------------------------------------------------------------------
    # Disruption metrics
    # -----------------------------------------------------------------------

    def record_disruption(
        self,
        disruption_type: str,
    ) -> None:
        """
        Record a disruption event.
        """
        normalized_type = disruption_type.strip().lower()

        if not normalized_type:
            normalized_type = "unknown"

        self.disruptions += 1

        self.disruption_types[normalized_type] = (
            self.disruption_types.get(normalized_type, 0) + 1
        )

    # -----------------------------------------------------------------------
    # Delay metrics
    # -----------------------------------------------------------------------

    def record_agent_delay(
        self,
        agent_id: str,
        delay: int,
    ) -> None:
        """
        Record additional delay experienced by an agent.
        """
        if delay < 0:
            raise ValueError(
                "delay cannot be negative."
            )

        metrics = self._get_or_create_agent(agent_id)

        metrics.delay += delay

        self.delay += delay

    def add_delay(
        self,
        delay: int,
    ) -> None:
        """
        Add system-level delay.
        """
        if delay < 0:
            raise ValueError(
                "delay cannot be negative."
            )

        self.delay += delay

    # -----------------------------------------------------------------------
    # Bulk synchronization from agents
    # -----------------------------------------------------------------------

    def synchronize_agents(
        self,
        agents: Iterable[Any],
    ) -> None:
        """
        Synchronize final agent state into the metrics collector.

        This is intended to be called at the end of simulation.

        Expected Agent-like attributes:
            agent_id
            tasks
            original_plan
            current_plan
            plan_modified
            repair_count
        """
        agent_list = list(agents)

        self.total_agents = max(
            self.total_agents,
            len(agent_list),
        )

        for agent in agent_list:
            agent_id = str(agent.agent_id)

            metrics = self._get_or_create_agent(agent_id)

            tasks = list(getattr(agent, "tasks", []))

            metrics.task_count = len(tasks)

            metrics.completed_task_count = sum(
                bool(getattr(task, "is_completed", False))
                for task in tasks
            )

            metrics.original_path_length = len(
                getattr(agent, "original_plan", [])
            )

            metrics.final_path_length = len(
                getattr(agent, "current_plan", [])
            )

            metrics.repair_count = int(
                getattr(agent, "repair_count", 0)
            )

            metrics.modified = bool(
                getattr(agent, "plan_modified", False)
            )

            if metrics.modified:
                self.modified_agents.add(agent_id)

            # When an agent's current plan is already marked as modified,
            # this module should not increment total_repair_operations again.
            # That value is maintained by record_plan_modification().

        self._recompute_total_path_cost()

    # -----------------------------------------------------------------------
    # Finalization
    # -----------------------------------------------------------------------

    def finalize(
        self,
        agents: Optional[Iterable[Any]] = None,
        final_timestep: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Finalize and return all system-level metrics.

        Parameters
        ----------
        agents:
            Optional agents used to synchronize final state.

        final_timestep:
            Optional final simulation timestep.

        Returns
        -------
        dict
            Flat dictionary suitable for CSV/JSON output.

        Notes
        -----
        This dictionary matches the metrics contract used by:

            experiments/run_experiment.py
        """
        if agents is not None:
            self.synchronize_agents(agents)

        if final_timestep is not None:
            self.update_timestep(final_timestep)

        self._recompute_completion_metrics()

        if self.simulation_start_time is not None:
            self.stop_simulation()

        # If no explicit makespan is known but the simulation timestep
        # represents the final completion moment, use it as a fallback.
        if self.makespan is None:
            self.makespan = self.current_timestep

        return self.to_dict()

    # -----------------------------------------------------------------------
    # Dictionary representation
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """
        Return a flat dictionary of experiment-level metrics.

        This is the canonical output consumed by experiment scripts.
        """
        return {
            # Primary assignment metrics.
            "total_completion_time": self.total_completion_time,
            "makespan": self.makespan
            if self.makespan is not None
            else 0,
            "total_path_cost": round(
                self.total_path_cost,
                6,
            ),
            "modified_agents": len(self.modified_agents),
            "modification_ratio": round(
                self.modification_ratio,
                6,
            ),

            # Repair metrics.
            "repair_time": round(
                self.repair_time,
                6,
            ),
            "negotiation_rounds": self.negotiation_rounds,
            "negotiation_events": self.negotiation_events,
            "total_repair_operations": self.total_repair_operations,

            # Conflict metrics.
            "conflicts": self.conflicts,
            "vertex_conflicts": self.vertex_conflicts,
            "edge_conflicts": self.edge_conflicts,
            "obstacle_conflicts": self.obstacle_conflicts,

            # Disruption metrics.
            "disruptions": self.disruptions,
            "disruption_types": dict(self.disruption_types),

            # Delay and preservation.
            "delay": self.delay,
            "plan_preservation_ratio": round(
                self.plan_preservation_ratio,
                6,
            ),

            # Simulation-level information.
            "total_agents": self.total_agents,
            "simulation_timesteps": self.current_timestep,
            "simulation_runtime": (
                round(self.simulation_runtime, 6)
                if self.simulation_runtime is not None
                else 0.0
            ),
        }

    def agent_results(self) -> list[dict[str, Any]]:
        """
        Return detailed per-agent metrics.

        Useful for CSV files containing agent-level analysis.
        """
        return [
            self.agent_metrics[agent_id].to_dict()
            for agent_id in sorted(self.agent_metrics)
        ]

    # -----------------------------------------------------------------------
    # Reset
    # -----------------------------------------------------------------------

    def reset(self) -> None:
        """
        Reset all collected metrics.
        """
        self.current_timestep = 0

        self.makespan = None
        self.total_completion_time = 0

        self.total_path_cost = 0.0

        self.modified_agents.clear()
        self.total_repair_operations = 0

        self.repair_time = 0.0

        self.negotiation_rounds = 0
        self.negotiation_events = 0

        self.conflicts = 0
        self.vertex_conflicts = 0
        self.edge_conflicts = 0
        self.obstacle_conflicts = 0

        self.disruptions = 0
        self.disruption_types.clear()

        self.delay = 0

        self.agent_metrics.clear()

        self.simulation_start_time = None
        self.simulation_runtime = None

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _get_or_create_agent(
        self,
        agent_id: str,
    ) -> AgentMetrics:
        """
        Retrieve an existing AgentMetrics object or create one.
        """
        if not agent_id:
            raise ValueError("agent_id cannot be empty.")

        if agent_id not in self.agent_metrics:
            self.agent_metrics[agent_id] = AgentMetrics(
                agent_id=agent_id
            )

            self.total_agents = max(
                self.total_agents,
                len(self.agent_metrics),
            )

        return self.agent_metrics[agent_id]

    def _recompute_completion_metrics(self) -> None:
        """
        Recompute aggregate agent completion statistics.
        """
        completed_times = [
            metrics.completion_time
            for metrics in self.agent_metrics.values()
            if metrics.completion_time is not None
        ]

        if not completed_times:
            self.total_completion_time = 0
            return

        self.total_completion_time = sum(
            completed_times
        )

        self.makespan = max(
            completed_times
        )

    def _recompute_total_path_cost(self) -> None:
        """
        Recompute total path cost from per-agent values.

        This method is useful after synchronize_agents().
        """
        self.total_path_cost = sum(
            metrics.path_cost
            for metrics in self.agent_metrics.values()
        )


# ---------------------------------------------------------------------------
# Standalone utility functions
# ---------------------------------------------------------------------------

def calculate_makespan(
    completion_times: Iterable[int],
) -> int:
    """
    Calculate the makespan from agent completion times.

    Returns 0 for an empty collection.
    """
    times = list(completion_times)

    if not times:
        return 0

    if any(time < 0 for time in times):
        raise ValueError(
            "Completion times cannot be negative."
        )

    return max(times)


def calculate_modification_ratio(
    modified_agents: int,
    total_agents: int,
) -> float:
    """
    Calculate:

        modified_agents / total_agents

    Returns 0 when total_agents is zero.
    """
    if modified_agents < 0:
        raise ValueError(
            "modified_agents cannot be negative."
        )

    if total_agents < 0:
        raise ValueError(
            "total_agents cannot be negative."
        )

    if modified_agents > total_agents and total_agents > 0:
        raise ValueError(
            "modified_agents cannot exceed total_agents."
        )

    if total_agents == 0:
        return 0.0

    return modified_agents / total_agents


def calculate_plan_preservation_ratio(
    modified_agents: int,
    total_agents: int,
) -> float:
    """
    Calculate the fraction of agents whose plans were preserved.
    """
    return 1.0 - calculate_modification_ratio(
        modified_agents,
        total_agents,
    )


def calculate_delay(
    baseline_completion_time: int,
    actual_completion_time: int,
) -> int:
    """
    Calculate disruption-induced delay.

    Negative delay is clamped to zero because completing earlier
    than the baseline does not represent a disruption delay.
    """
    if baseline_completion_time < 0:
        raise ValueError(
            "baseline_completion_time cannot be negative."
        )

    if actual_completion_time < 0:
        raise ValueError(
            "actual_completion_time cannot be negative."
        )

    return max(
        0,
        actual_completion_time - baseline_completion_time,
    )