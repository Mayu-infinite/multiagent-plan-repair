"""

Low-level execution logic for warehouse agents.



This module is responsible for executing one timestep of an agent's

current trajectory and updating task state.



The module intentionally does not:

    - generate paths,

    - detect global multi-agent conflicts,

    - perform plan repair,

    - control the complete simulation.



Those responsibilities belong to the planning, repair, and simulator

modules respectively.

"""



from __future__ import annotations



from dataclasses import dataclass

from typing import Optional



from ..agents import (

    Agent,

    AgentStatus,

    TaskStatus,

)

from ..environment import Grid

from ..metrics import MetricsCollector





# ---------------------------------------------------------------------------

# Execution result

# ---------------------------------------------------------------------------



@dataclass

class ExecutionStep:

    """

        Result of executing one agent for one simulation timestep.



        Attributes

        ----------

        agent_id:

            Agent identifier.



        timestep:

            Simulation timestep.



        position:

            Agent position after execution.



        moved:

            Whether the agent changed position.



        waited:

            Whether the agent remained in the same cell.



        task_event:

            Optional task event generated during execution.



        completed_all_tasks:

            Whether the agent completed all assigned tasks.



        movement_cost:

            Cost incurred during this timestep.



        executed:

            Whether the agent actually performed a plan action.

    """



    agent_id: str

    timestep: int



    position: tuple[int, int]



    moved: bool

    waited: bool



    task_event: Optional[str]



    completed_all_tasks: bool



    movement_cost: float



    executed: bool





# ---------------------------------------------------------------------------

# Execution engine

# ---------------------------------------------------------------------------



class ExecutionEngine:

    """

        Executes individual agents against their current plans.



        Parameters

        ----------

        grid:

            Warehouse grid.



        metrics:

            Optional metrics collector.

    """



    def __init__(

        self,

        grid: Grid,

        metrics: Optional[MetricsCollector] = None,

    ) -> None:

        self.grid = grid

        self.metrics = metrics



# -----------------------------------------------------------------------

# Execute one agent

# -----------------------------------------------------------------------



    def execute_agent(

        self,

        agent: Agent,

        timestep: int,

    ) -> ExecutionStep:

        """

                Execute one timestep for one agent.



                The agent follows `agent.current_plan`, not

                `agent.original_plan`.



                This is important because repaired plans replace current_plan

                while original_plan remains unchanged for evaluation.

        """

        if timestep < 0:

            raise ValueError(

                "timestep cannot be negative."

            )



# -------------------------------------------------------------------

# Failed agents do not execute movement.

# -------------------------------------------------------------------



        if agent.status == AgentStatus.FAILED:

            agent.advance_time(timestep)



            return ExecutionStep(

                agent_id=agent.agent_id,

                timestep=timestep,

                position=agent.current_position,

                moved=False,

                waited=False,

                task_event=None,

                completed_all_tasks=False,

                movement_cost=0.0,

                executed=False,

            )



# -------------------------------------------------------------------

# Already completed agents remain stationary.

# -------------------------------------------------------------------



        if agent.status == AgentStatus.COMPLETED:



            agent.advance_time(timestep)



            return ExecutionStep(

                agent_id=agent.agent_id,

                timestep=timestep,

                position=agent.current_position,

                moved=False,

                waited=False,

                task_event=None,

                completed_all_tasks=True,

                movement_cost=0.0,

                executed=False,

            )



# -------------------------------------------------------------------

# No task case.

# -------------------------------------------------------------------



        if not agent.tasks:

            agent.mark_completed()

            agent.advance_time(timestep)



            if self.metrics is not None:

                self.metrics.record_agent_completion(

                    agent.agent_id,

                    timestep,

                )



            return ExecutionStep(

                agent_id=agent.agent_id,

                timestep=timestep,

                position=agent.current_position,

                moved=False,

                waited=False,

                task_event=None,

                completed_all_tasks=True,

                movement_cost=0.0,

                executed=False,

            )



# -------------------------------------------------------------------

# Ensure task execution has started.

# -------------------------------------------------------------------



        if agent.current_task is not None:



            if (

                agent.current_task.status

                == TaskStatus.PENDING

            ):

                agent.start_current_task()



# -------------------------------------------------------------------

# Find the planned state for this timestep.

# -------------------------------------------------------------------



        planned_state = agent.planned_state_at(

            timestep

        )



        if planned_state is None:

# There is no explicit state for this timestep.

#

# This can happen after a plan finishes. Keep the robot at

# its current location.

            agent.advance_time(timestep)



            return ExecutionStep(

                agent_id=agent.agent_id,

                timestep=timestep,

                position=agent.current_position,

                moved=False,

                waited=False,

                task_event=None,

                completed_all_tasks=agent.all_tasks_completed,

                movement_cost=0.0,

                executed=False,

            )



        row, col, planned_time = planned_state



        if planned_time != timestep:

            raise RuntimeError(

                f"Agent {agent.agent_id} returned state for "

                f"timestep {planned_time}, requested {timestep}."

            )



        next_position = (

            row,

            col,

        )



        previous_position = agent.current_position



# -------------------------------------------------------------------

# Validate planned position.

# -------------------------------------------------------------------



        if not self.grid.in_bounds(next_position):

            raise RuntimeError(

                f"Agent {agent.agent_id} planned position "

                f"{next_position} outside the grid at timestep "

                f"{timestep}."

            )



        if not self.grid.is_walkable(next_position):

            raise RuntimeError(

                f"Agent {agent.agent_id} planned blocked position "

                f"{next_position} at timestep {timestep}."

            )



# -------------------------------------------------------------------

# Determine whether this is movement or waiting.

# -------------------------------------------------------------------



        moved = (

            previous_position

            != next_position

        )



        waited = (

            previous_position

            == next_position

        )



# -------------------------------------------------------------------

# Calculate execution cost.

# -------------------------------------------------------------------



        if moved:

            movement_cost = self.grid.movement_cost(

                previous_position,

                next_position,

            )

            agent.status = AgentStatus.MOVING



        else:

            movement_cost = self.grid.wait_cost

            agent.mark_waiting()



# -------------------------------------------------------------------

# Update physical state.

# -------------------------------------------------------------------



        agent.update_position(

            next_position,

            timestep=timestep,

        )



# -------------------------------------------------------------------

# Process task-related events.

# -------------------------------------------------------------------



        task_event = self._process_task_location(

            agent

        )



# -------------------------------------------------------------------

# Synchronize path cost with metrics.

# -------------------------------------------------------------------



        if self.metrics is not None:

            self.metrics.add_path_cost(

                agent.agent_id,

                movement_cost,

            )



# -------------------------------------------------------------------

# Completion.

# -------------------------------------------------------------------



        completed_all_tasks = agent.all_tasks_completed



        if completed_all_tasks:



            agent.mark_completed()



            if self.metrics is not None:

                self.metrics.record_agent_completion(

                    agent.agent_id,

                    timestep,

                )



        return ExecutionStep(

            agent_id=agent.agent_id,

            timestep=timestep,

            position=next_position,

            moved=moved,

            waited=waited,

            task_event=task_event,

            completed_all_tasks=completed_all_tasks,

            movement_cost=movement_cost,

            executed=True,

        )



# -----------------------------------------------------------------------

# Execute all agents

# -----------------------------------------------------------------------



    def execute_all(

        self,

        agents: list[Agent],

        timestep: int,

    ) -> list[ExecutionStep]:

        """

                Execute one timestep for every agent.



                Agents are executed in deterministic ID order.

        """

        ordered_agents = sorted(

            agents,

            key=lambda agent: agent.agent_id,

        )



        results: list[ExecutionStep] = []



        for agent in ordered_agents:

            result = self.execute_agent(

                agent,

                timestep,

            )



            results.append(result)



        return results



# -----------------------------------------------------------------------

# Task state processing

# -----------------------------------------------------------------------



    def _process_task_location(

        self,

        agent: Agent,

    ) -> Optional[str]:

        """

                Update the current task when the agent reaches a pickup or

                delivery location.



                Returns

                -------

                str | None

                    Event name when a task transition occurs.

        """

        task = agent.current_task



        if task is None:

            return None



        position = agent.current_position



# -------------------------------------------------------------------

# Pickup

# -------------------------------------------------------------------



        if (

            task.status

            == TaskStatus.GOING_TO_PICKUP

            and position == task.pickup_position

        ):

            task.pickup()

            task.start_delivery()



            agent.mark_delivering()



            return "pickup"



# -------------------------------------------------------------------

# Delivery

# -------------------------------------------------------------------



        if (

            task.status

            == TaskStatus.GOING_TO_DELIVERY

            and position == task.delivery_position

        ):

            task.complete()



            completed_task_id = task.task_id



# Advance to the next task.

            agent.current_task_index += 1



            if agent.current_task_index >= len(

                agent.tasks

            ):

                agent.mark_completed()

            else:

                next_task = agent.current_task



                if next_task is not None:

                    if next_task.status == TaskStatus.PENDING:
                        next_task.start()



                agent.status = AgentStatus.MOVING



            if self.metrics is not None:

                completed_count = sum(

                    task_item.is_completed

                    for task_item in agent.tasks

                )



                self.metrics.record_task_completion(

                    agent.agent_id,

                    completed_count,

                )



            return (

                f"delivery:{completed_task_id}"

            )



        return None
