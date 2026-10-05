"""

Main discrete-time simulation for the Multi-Agent Plan Repair system.



The simulator integrates:



    Configuration

        ↓

    Environment

        ↓

    Agent + Task generation

        ↓

    Initial Space-Time A* planning

        ↓

    Plan execution

        ↓

    Dynamic disruption

        ↓

    Local plan repair + negotiation

        ↓

    Continued execution

        ↓

    Metrics



The simulator does NOT perform global replanning after a disruption.



Instead, it delegates recovery to RepairManager, which performs

local plan repair.

"""
from __future__ import annotations
import random
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Optional
from ..agents import Agent, AgentStatus, Task, TaskPriority
from ..environment import DynamicObstacleManager, Grid, Position
from ..metrics import MetricsCollector
from ..planning import ConflictDetector, InitialPlanner, PlanningError
from ..repair import Disruption, DisruptionType, RepairManager, RepairResult
from .execution import ExecutionEngine, ExecutionStep

@dataclass
class ScheduledDisruption:
    """

    Disruption prepared for a particular simulation timestep.



    The object is created after initial planning so that disruptions

    can intentionally interact with existing trajectories.

    """
    disruption: Disruption

class Simulator:
    """

    End-to-end warehouse simulator.



    Parameters

    ----------

    config:

        Complete configuration dictionary loaded from YAML.



    The dictionary follows the schema established in configs/*.yaml.

    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        project_config = config.get('project', {})
        self.seed = int(project_config.get('seed', 42))
        self.rng = random.Random(self.seed)
        self.environment_config = config.get('environment', {})
        self.agent_config = config.get('agents', {})
        self.task_config = config.get('tasks', {})
        self.planning_config = config.get('planning', {})
        self.dynamic_obstacle_config = config.get('dynamic_obstacles', {})
        self.disruption_config = config.get('disruptions', {})
        self.repair_config = config.get('repair', {})
        self.simulation_config = config.get('simulation', {})
        self.max_steps = int(self.simulation_config.get('max_steps', self.planning_config.get('max_time_steps', 500)))
        self.grid: Optional[Grid] = None
        self.obstacle_manager: Optional[DynamicObstacleManager] = None
        self.agents: list[Agent] = []
        self.metrics = MetricsCollector()
        self.execution_engine: Optional[ExecutionEngine] = None
        self.initial_planner: Optional[InitialPlanner] = None
        self.repair_manager: Optional[RepairManager] = None
        self.conflict_detector: Optional[ConflictDetector] = None
        self.current_timestep: int = 0
        self.initial_planning_completed = False
        self.scheduled_disruptions: dict[int, list[ScheduledDisruption]] = {}
        self.repair_results: list[RepairResult] = []
        self.execution_history: list[dict[str, Any]] = []
        self.completed = False
        self._has_run = False

    def run(self) -> dict[str, Any]:
        """

        Run one complete simulation.



        Returns

        -------

        dict

            Metrics dictionary consumed by experiment scripts.

        """
        if self._has_run:
            raise RuntimeError('This Simulator instance has already been run. Create a new Simulator for another experiment.')
        self._has_run = True
        self.setup()
        assert self.grid is not None
        assert self.execution_engine is not None
        assert self.obstacle_manager is not None
        self.metrics.start_simulation()
        self._record_history(timestep=0, execution_steps=[])
        for timestep in range(0, self.max_steps + 1):
            self.current_timestep = timestep
            self.metrics.update_timestep(timestep)
            if timestep > 0:
                self.obstacle_manager.remove_expired(timestep)
            # Execute the current timestep first. A disruption observed at
            # this timestep changes the trajectory for subsequent timesteps.
            execution_steps = self.execution_engine.execute_all(agents=self.agents, timestep=timestep)
            self._validate_execution(timestep=timestep)
            self._record_history(timestep=timestep, execution_steps=execution_steps)

            # Apply disruptions after the current state has been executed.
            # This keeps the disruption from invalidating the state that has
            # already physically occurred at timestep t. Repair affects future
            # trajectory states, while the obstacle can remain active from t.
            scheduled = self.scheduled_disruptions.get(timestep, [])
            for scheduled_event in scheduled:
                repair_result = self.repair_manager.handle_disruption(disruption=scheduled_event.disruption, agents=self.agents)
                self.repair_results.append(repair_result)
                self._normalize_special_task_after_repair(scheduled_event.disruption, repair_result)
            if self._all_tasks_complete():
                self.completed = True
                break
        final_timestep = self._determine_final_timestep()
        self.metrics.update_timestep(final_timestep)
        self.metrics.synchronize_agents(self.agents)
        self.metrics.stop_simulation()
        result = self.metrics.finalize(agents=self.agents, final_timestep=final_timestep)
        result.update({'completed': self.completed, 'initial_planning_completed': self.initial_planning_completed, 'scheduled_disruptions': sum((len(events) for events in self.scheduled_disruptions.values())), 'successful_repairs': sum((result_item.success for result_item in self.repair_results)), 'failed_repairs': sum((not result_item.success for result_item in self.repair_results))})
        return result

    def setup(self) -> None:
        """

        Build the environment, agents, tasks, planner, metrics,

        and initial multi-agent plan.

        """
        self._build_scenario()
        assert self.grid is not None
        assert self.obstacle_manager is not None
        self.initial_planner = InitialPlanner(grid=self.grid, obstacle_manager=self.obstacle_manager, max_time_steps=int(self.planning_config.get('max_time_steps', self.max_steps)), max_search_nodes=int(self.planning_config.get('max_search_nodes', 50000)), heuristic=str(self.planning_config.get('heuristic', 'manhattan')), priority_strategy=str(self.planning_config.get('priority_strategy', 'most_constrained')), require_conflict_free=True)
        self.conflict_detector = ConflictDetector(grid=self.grid, obstacle_manager=self.obstacle_manager)
        self.metrics.register_agents(self.agents)
        planning_result = self.initial_planner.plan_all(self.agents)
        if not planning_result.success:
            raise PlanningError('Initial planner returned an unsuccessful result.')
        self.initial_planning_completed = True
        self.metrics.register_agents(self.agents)
        self.execution_engine = ExecutionEngine(grid=self.grid, metrics=self.metrics)
        self.repair_manager = RepairManager(grid=self.grid, obstacle_manager=self.obstacle_manager, metrics=self.metrics, max_negotiation_neighbors=int(self.repair_config.get('max_negotiation_neighbors', 4)), max_negotiation_rounds=int(self.repair_config.get('max_negotiation_rounds', 5)), repair_horizon=int(self.repair_config.get('repair_horizon', 30)), max_alternatives=int(self.repair_config.get('max_alternatives', 5)), communication_distance=int(self.repair_config.get('communication_distance', 8)), max_time_steps=int(self.planning_config.get('max_time_steps', self.max_steps)), max_search_nodes=int(self.planning_config.get('max_search_nodes', 50000)), heuristic=str(self.planning_config.get('heuristic', 'manhattan')))
        if self.disruption_config.get('enabled', True):
            self._schedule_disruptions()

    def _build_scenario(self, max_attempts: int=20) -> None:
        """

        Generate a reproducible scenario.



        Random static obstacles and task/start positions are regenerated

        when the chosen configuration produces an infeasible initial

        planning problem.

        """
        rows = int(self.environment_config.get('grid', {}).get('rows', 20))
        cols = int(self.environment_config.get('grid', {}).get('cols', 20))
        static_density = float(self.environment_config.get('static_obstacle_density', 0.08))
        movement_config = self.environment_config.get('movement', {})
        allow_diagonal = bool(movement_config.get('allow_diagonal', False))
        allow_wait = bool(movement_config.get('wait_action', True))
        move_cost = float(self.agent_config.get('move_cost', 1.0))
        wait_cost = float(self.agent_config.get('wait_cost', 1.0))
        for attempt in range(max_attempts):
            scenario_rng = random.Random(self.seed + attempt)
            empty_grid = Grid(rows=rows, cols=cols, static_obstacles=set(), allow_diagonal=allow_diagonal, allow_wait=allow_wait, move_cost=move_cost, wait_cost=wait_cost)
            all_cells = empty_grid.walkable_positions()
            if not all_cells:
                raise RuntimeError('Warehouse contains no free cells.')
            agent_count = int(self.agent_config.get('count', 10))
            tasks_per_agent = int(self.agent_config.get('tasks_per_agent', 1))
            required_cells = agent_count + agent_count * tasks_per_agent * 2
            if required_cells > len(all_cells):
                raise RuntimeError('Not enough warehouse cells to assign unique start, pickup, and delivery positions.')
            shuffled_cells = list(all_cells)
            scenario_rng.shuffle(shuffled_cells)
            starts = shuffled_cells[:agent_count]
            reserved_positions = set(starts)
            agents = []
            cell_cursor = agent_count
            for agent_index in range(agent_count):
                tasks: list[Task] = []
                for task_index in range(tasks_per_agent):
                    pickup, delivery, cell_cursor = self._select_task_locations(cells=shuffled_cells, cursor=cell_cursor, reserved=reserved_positions, rng=scenario_rng)
                    reserved_positions.add(pickup)
                    reserved_positions.add(delivery)
                    task = Task(task_id=f'A{agent_index + 1}-T{task_index + 1}', pickup_position=pickup, delivery_position=delivery, priority=TaskPriority.NORMAL)
                    tasks.append(task)
                agent = Agent(agent_id=f'A{agent_index + 1}', start_position=starts[agent_index], tasks=tasks, move_cost=move_cost, wait_cost=wait_cost)
                agents.append(agent)
            free_candidates = [cell for cell in all_cells if cell not in reserved_positions]
            obstacle_count = int(round(len(all_cells) * static_density))
            obstacle_count = min(obstacle_count, len(free_candidates))
            static_obstacles = set(scenario_rng.sample(free_candidates, obstacle_count))
            grid = Grid(rows=rows, cols=cols, static_obstacles=static_obstacles, allow_diagonal=allow_diagonal, allow_wait=allow_wait, move_cost=move_cost, wait_cost=wait_cost)
            obstacle_manager = DynamicObstacleManager(grid)
            self.grid = grid
            self.obstacle_manager = obstacle_manager
            self.agents = agents
            try:
                test_planner = InitialPlanner(grid=grid, obstacle_manager=obstacle_manager, max_time_steps=int(self.planning_config.get('max_time_steps', self.max_steps)), max_search_nodes=int(self.planning_config.get('max_search_nodes', 50000)), heuristic=str(self.planning_config.get('heuristic', 'manhattan')), priority_strategy=str(self.planning_config.get('priority_strategy', 'most_constrained')), require_conflict_free=True)
                planning_result = test_planner.plan_all(agents)
                if planning_result.success:
                    for agent in agents:
                        agent.reset_to_original_plan()
                    return
            except PlanningError:
                pass
        raise RuntimeError(f'Could not generate a feasible warehouse scenario after {max_attempts} attempts. Try reducing agent/task count or obstacle density.')

    def _select_task_locations(self, cells: list[Position], cursor: int, reserved: set[Position], rng: random.Random) -> tuple[Position, Position, int]:
        """

        Select pickup and delivery locations satisfying the configured

        Manhattan-distance constraint.

        """
        minimum_distance = int(self.task_config.get('pickup_delivery_distance_min', 5))
        maximum_distance = int(self.task_config.get('pickup_delivery_distance_max', 15))
        if minimum_distance <= 0:
            raise ValueError('pickup_delivery_distance_min must be positive.')
        if maximum_distance < minimum_distance:
            raise ValueError('pickup_delivery_distance_max must be >= pickup_delivery_distance_min.')
        candidate_positions = [cell for cell in cells if cell not in reserved]
        if len(candidate_positions) < 2:
            raise RuntimeError('Not enough unused cells to create another task.')
        attempts = min(200, len(candidate_positions) * 4)
        for _ in range(attempts):
            pickup = rng.choice(candidate_positions)
            delivery = rng.choice(candidate_positions)
            if pickup == delivery:
                continue
            distance = abs(pickup[0] - delivery[0]) + abs(pickup[1] - delivery[1])
            if minimum_distance <= distance <= maximum_distance:
                pickup_index = cells.index(pickup)
                delivery_index = cells.index(delivery)
                next_cursor = max(cursor, pickup_index + 1, delivery_index + 1)
                return (pickup, delivery, next_cursor)
        for pickup_index in range(0, len(cells)):
            pickup = cells[pickup_index]
            if pickup in reserved:
                continue
            for delivery_index in range(pickup_index + 1, len(cells)):
                delivery = cells[delivery_index]
                if delivery in reserved:
                    continue
                distance = abs(pickup[0] - delivery[0]) + abs(pickup[1] - delivery[1])
                if minimum_distance <= distance <= maximum_distance:
                    return (pickup, delivery, delivery_index + 1)
        raise RuntimeError('Could not find pickup and delivery positions satisfying the configured distance constraints.')

    def _schedule_disruptions(self) -> None:
        """

        Prepare disruption events after the initial plans exist.



        The events are deliberately prepared after planning so that

        the dynamic obstacle disruption can target an actual future

        trajectory state.

        """
        assert self.grid is not None
        event_count = int(self.dynamic_obstacle_config.get('events_per_run', 1))
        event_count = max(0, event_count)
        if event_count == 0:
            return
        min_step = int(self.dynamic_obstacle_config.get('min_step', 10))
        max_step = int(self.dynamic_obstacle_config.get('max_step', max(min_step, self.max_steps // 2)))
        min_step = max(0, min_step)
        max_step = min(self.max_steps, max_step)

        latest_plan_time = max(
            (
                state[2]
                for agent in self.agents
                for state in agent.current_plan
            ),
            default=0,
        )

        # Keep scheduled disruptions inside the active initial-plan horizon.
        # This guarantees that a disruption can actually interact with at
        # least one planned future state.
        if latest_plan_time > 0:
            max_step = min(max_step, latest_plan_time - 1)

        if max_step < min_step:
            min_step = max(0, max_step)

        disruption_types = self._select_disruption_types()
        for event_index in range(event_count):
            timestep = self.rng.randint(min_step, max_step)
            disruption_type = disruption_types[event_index % len(disruption_types)]
            disruption = self._create_disruption(disruption_type=disruption_type, timestep=timestep, event_index=event_index)
            if disruption is None:
                continue
            self.scheduled_disruptions.setdefault(timestep, []).append(ScheduledDisruption(disruption=disruption))

    def _select_disruption_types(self) -> list[str]:
        """

        Select disruption types according to configured probabilities.



        When the experiments specify exactly one disruption type,

        that type is selected deterministically.

        """
        configured_types = self.disruption_config.get('types', ['agent_failure', 'dynamic_obstacle', 'emergency_task'])
        configured_types = [str(item).strip().lower() for item in configured_types]
        valid = {item.value for item in DisruptionType}
        configured_types = [item for item in configured_types if item in valid]
        if not configured_types:
            return [DisruptionType.DYNAMIC_OBSTACLE.value]
        if len(configured_types) == 1:
            return configured_types
        probabilities = self.disruption_config.get('probabilities', {})
        weights = [float(probabilities.get(disruption_type, 0.0)) for disruption_type in configured_types]
        total_weight = sum((max(weight, 0.0) for weight in weights))
        if total_weight <= 0:
            return configured_types
        selected = self.rng.choices(configured_types, weights=[max(weight, 0.0) for weight in weights], k=1)
        return selected

    def _create_disruption(self, disruption_type: str, timestep: int, event_index: int) -> Optional[Disruption]:
        """

        Create one disruption targeting the current scenario.

        """
        disruption_enum = DisruptionType.from_string(disruption_type)
        disruption_id = f'D{event_index + 1}'
        if disruption_enum == DisruptionType.AGENT_FAILURE:
            candidates = [agent for agent in self.agents if agent.status != AgentStatus.COMPLETED]
            if not candidates:
                return None
            selected = self.rng.choice(candidates)
            return Disruption.agent_failure(disruption_id=disruption_id, agent_id=selected.agent_id, timestep=timestep)
        if disruption_enum == DisruptionType.DYNAMIC_OBSTACLE:
            target = self._choose_future_trajectory_cell(timestep=timestep)
            if target is None:
                return None
            duration_min = int(self.dynamic_obstacle_config.get('duration_min', 5))
            duration_max = int(self.dynamic_obstacle_config.get('duration_max', 20))
            if duration_max < duration_min:
                duration_max = duration_min
            duration = self.rng.randint(duration_min, duration_max)
            density = float(self.dynamic_obstacle_config.get('density', 0.1))
            density = min(max(density, 0.0), 1.0)
            occupied_current = {agent.current_position for agent in self.agents if agent.status != AgentStatus.FAILED}
            active_start = timestep + 1
            active_end = active_start + duration

            # Extra dynamic obstacles are sampled from all currently
            # walkable cells except the selected disruption target and
            # cells occupied at the disruption timestep. Future planned
            # cells are intentionally eligible so obstacle density can
            # genuinely create route interference for the experiment.
            eligible = [
                position
                for position in self.grid.walkable_positions()
                if position != target
                and position not in occupied_current
            ]
            additional_count = int(round(len(eligible) * density))
            additional_count = min(additional_count, len(eligible))
            extra_positions = self.rng.sample(eligible, min(additional_count, len(eligible)))
            if self.obstacle_manager is not None:
                for index, position in enumerate(extra_positions):
                    self.obstacle_manager.add_obstacle(position=position, start_time=timestep + 1, duration=duration, obstacle_id=f'{disruption_id}-extra-{index + 1}')
            return Disruption.dynamic_obstacle(disruption_id=disruption_id, position=target, timestep=timestep, duration=duration)
        if disruption_enum == DisruptionType.EMERGENCY_TASK:
            pickup = self._random_walkable_position(avoid_current_agents=True)
            if pickup is None:
                return None
            delivery = self._random_walkable_position(avoid_positions={pickup}, avoid_current_agents=True)
            if delivery is None:
                return None
            emergency_task = Task(task_id=f'EMERGENCY-{event_index + 1}', pickup_position=pickup, delivery_position=delivery, priority=TaskPriority.EMERGENCY)
            return Disruption.emergency_task(disruption_id=disruption_id, task=emergency_task, timestep=timestep)
        return None

    def _choose_future_trajectory_cell(self, timestep: int) -> Optional[Position]:
        """

        Select a future position from an existing trajectory.



        This makes the dynamic-obstacle experiment meaningful because

        the disruption is guaranteed to interact with at least one

        planned route whenever possible.

        """
        candidates: list[tuple[str, tuple[int, int, int]]] = []
        occupied_at_timestep: set[Position] = set()
        for agent in self.agents:
            if agent.status == AgentStatus.FAILED:
                continue
            position = agent.planned_position_at(timestep)
            if position is not None:
                occupied_at_timestep.add(position)
        for agent in self.agents:
            if agent.status == AgentStatus.FAILED:
                continue
            for state in agent.current_plan:
                row, col, time = state
                if time <= timestep:
                    continue
                position = (row, col)
                if position in occupied_at_timestep:
                    continue
                candidates.append((agent.agent_id, state))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (abs(item[1][2] - timestep), item[0], item[1][2]))
        shortlist = candidates[:min(20, len(candidates))]
        _, selected_state = self.rng.choice(shortlist)
        return (selected_state[0], selected_state[1])

    def _random_walkable_position(self, *, avoid_positions: Optional[set[Position]]=None, avoid_current_agents: bool=False) -> Optional[Position]:
        """

        Choose a random currently walkable position.

        """
        assert self.grid is not None
        avoid = set(avoid_positions or set())
        if avoid_current_agents:
            avoid.update((agent.current_position for agent in self.agents if agent.status != AgentStatus.FAILED))
        candidates = [position for position in self.grid.walkable_positions() if position not in avoid]
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def _normalize_special_task_after_repair(self, disruption: Disruption, repair_result: RepairResult) -> None:
        """

        Keep task ordering consistent with the repaired trajectory.



        The repair layer can append a transferred/emergency task to

        an agent's task list. Since the corresponding repaired trajectory

        executes that task immediately, move that task to the agent's

        current task position.



        This does not modify trajectory planning.

        It only keeps task bookkeeping aligned with execution.

        """
        if not repair_result.success:
            return
        if disruption.disruption_type not in {DisruptionType.EMERGENCY_TASK, DisruptionType.AGENT_FAILURE}:
            return
        selected_agent_ids = repair_result.modified_agents
        if not selected_agent_ids:
            return
        task_id: Optional[str] = None
        if disruption.is_emergency_task:
            if disruption.task is not None:
                task_id = disruption.task.task_id
        elif disruption.is_agent_failure:
            proposal = repair_result.negotiation_result.selected_proposal
            if proposal is not None:
                transferred = proposal.metadata.get('transferred_task')
                if transferred is not None:
                    task_id = str(transferred)
        if task_id is None:
            return
        for agent in self.agents:
            if agent.agent_id not in selected_agent_ids:
                continue
            matching_index = next((index for index, task in enumerate(agent.tasks) if task.task_id == task_id), None)
            if matching_index is None:
                continue
            task = agent.tasks.pop(matching_index)
            insertion_index = min(agent.current_task_index, len(agent.tasks))
            agent.tasks.insert(insertion_index, task)
            task.reset()

    def _validate_execution(self, timestep: int) -> None:
        """

        Ensure that currently occupied positions are valid.



        Multi-agent trajectory validation is performed by the conflict

        detector. This method additionally checks the actual state of

        the robots after execution.

        """
        if self.grid is None:
            return
        if self.obstacle_manager is None:
            return
        occupancy: dict[Position, str] = {}
        for agent in self.agents:
            if agent.status == AgentStatus.FAILED:
                continue
            position = agent.current_position
            if not self.grid.is_walkable(position):
                raise RuntimeError(f'Agent {agent.agent_id} is on a blocked cell {position} at timestep {timestep}.')
            if self.obstacle_manager.is_temporarily_blocked(position, timestep):
                raise RuntimeError(f'Agent {agent.agent_id} is on a dynamically blocked cell {position} at timestep {timestep}.')
            if position in occupancy:
                other_agent = occupancy[position]
                raise RuntimeError(f'Runtime vertex collision at {position} between {agent.agent_id} and {other_agent} at timestep {timestep}.')
            occupancy[position] = agent.agent_id

    def _all_tasks_complete(self) -> bool:
        """

        Return True when every required task has been completed.



        Failed agents prevent normal global completion if they still

        have unfinished tasks. The repair mechanism is responsible for

        transferring such tasks.

        """
        for agent in self.agents:
            if agent.status == AgentStatus.FAILED:
                if agent.has_pending_tasks:
                    return False
            elif agent.has_pending_tasks:
                return False
        return True

    def _determine_final_timestep(self) -> int:
        """

        Determine the final timestep for metrics.

        """
        completion_times = [
            metrics.completion_time
            for metrics in self.metrics.agent_metrics.values()
            if metrics.completion_time is not None
        ]
        if completion_times:
            return max(
                self.current_timestep,
                max(completion_times),
            )
        return self.current_timestep

    def _record_history(self, timestep: int, execution_steps: list[ExecutionStep]) -> None:
        """

        Record a snapshot of the simulation state.

        """
        if not bool(self.simulation_config.get('record_history', True)):
            return
        obstacles: list[dict[str, Any]] = []
        if self.obstacle_manager is not None:
            for obstacle in self.obstacle_manager.active_obstacles(timestep):
                obstacles.append({'id': obstacle.obstacle_id, 'position': obstacle.position, 'start_time': obstacle.start_time, 'end_time': obstacle.end_time})
        agent_states: dict[str, dict[str, Any]] = {}
        execution_by_id = {step.agent_id: step for step in execution_steps}
        for agent in sorted(self.agents, key=lambda item: item.agent_id):
            step = execution_by_id.get(agent.agent_id)
            current_task = agent.current_task
            agent_states[agent.agent_id] = {'position': agent.current_position, 'status': agent.status.value, 'task_id': current_task.task_id if current_task is not None else None, 'task_status': current_task.status.value if current_task is not None else None, 'moved': step.moved if step is not None else False, 'waited': step.waited if step is not None else False, 'task_event': step.task_event if step is not None else None, 'plan_modified': agent.plan_modified, 'repair_count': agent.repair_count}
        self.execution_history.append({'timestep': timestep, 'agents': agent_states, 'dynamic_obstacles': obstacles})

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """

        Return an agent by ID.

        """
        for agent in self.agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def get_history(self) -> list[dict[str, Any]]:
        """

        Return the recorded simulation history.



        The visualization module will consume this structure.

        """
        return deepcopy(self.execution_history)

    def get_repair_results(self) -> list[RepairResult]:
        """

        Return repair results from all disruption events.

        """
        return list(self.repair_results)

    def current_state(self) -> dict[str, Any]:
        """

        Return a compact current simulation snapshot.

        """
        return {'timestep': self.current_timestep, 'completed': self.completed, 'agents': {agent.agent_id: {'position': agent.current_position, 'status': agent.status.value, 'plan_modified': agent.plan_modified} for agent in self.agents}}
