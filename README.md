# Multi-Agent Plan Repair for an Autonomous Warehouse

## 1. Project Overview

This project implements **multi-agent planning and local plan repair for an automated warehouse**.

The warehouse is modeled as a 2D grid. Multiple autonomous robotic agents move between pickup and delivery locations while avoiding static obstacles and conflicts with other agents. Each agent initially receives a coordinated **space-time trajectory**. During execution, the environment can change through:

- agent failure,
- appearance of a dynamic obstacle,
- a high-priority/emergency task.

The central requirement is to repair the existing plan locally rather than discard the complete multi-agent solution and run global planning again. The repair objective is to preserve as much of the original multi-agent plan as possible while maintaining safe execution.

The assignment explicitly evaluates total completion time, the number of agents whose plans change for a disruption, scalability with respect to agent count, and performance as dynamic-obstacle density changes.

---

## 2. Objectives

1. Generate coordinated collision-free plans for multiple warehouse robots.
2. Represent robot motion in both space and time.
3. Execute the plans in a dynamic environment.
4. Detect disruptions during execution.
5. Identify affected agents.
6. Communicate with nearby agents.
7. Negotiate alternative trajectories.
8. Repair only local portions of existing plans.
9. Minimize the number of modified agents.
10. Continue execution after a disruption.
11. Measure makespan, completion time, path cost, repair time, conflicts and plan preservation.
12. Study scalability and dynamic-obstacle-density effects.
13. Provide simulation visualization.

---

## 3. High-Level Architecture

```text
                 YAML Configuration
                         |
                         v
             +-----------------------+
             |      Environment      |
             | Grid + Static/Dynamic  |
             |      Obstacles        |
             +-----------+-----------+
                         |
                         v
             +-----------------------+
             |       Agents          |
             | Robots + Tasks + State|
             +-----------+-----------+
                         |
                         v
             +-----------------------+
             |   Initial Planning    |
             |   Space-Time A*       |
             | Reservations /        |
             | Conflict Detection    |
             +-----------+-----------+
                         |
                         v
             +-----------------------+
             |      Simulation       |
             | Timestep Execution    |
             +-----------+-----------+
                         |
                 Disruption occurs
                         |
                         v
             +-----------------------+
             |     Plan Repair       |
             | Detect affected       |
             | -> Find neighbors     |
             | -> Generate local     |
             |    alternatives       |
             | -> Negotiate          |
             | -> Apply repair       |
             +-----------+-----------+
                         |
                         v
             +-----------------------+
             | Metrics + Visualization|
             +-----------------------+
```

---

## 4. Warehouse and State Representation

A grid position is represented by:

```text
(row, column)
```

A space-time state is:

```text
(row, column, t)
```

where `t` is the discrete simulation timestep.

A trajectory therefore has the form:

```text
T = [(r0,c0,0), (r1,c1,1), ..., (rn,cn,n)]
```

The time component is essential because two agents may safely occupy the same cell at different times, while occupying the same cell at the same time is a vertex conflict.

The default action set is four-connected movement plus waiting:

```text
UP
DOWN
LEFT
RIGHT
WAIT
```

The standard heuristic is Manhattan distance:

```text
h(n) = |r - r_goal| + |c - c_goal|
```

---

## 5. Initial Multi-Agent Planning

### Space-Time A*

The initial planner performs space-time search instead of purely spatial search. Each search state contains `(row, column, time)`.

For every step it considers valid neighboring states at `t+1`, including a wait action. Candidate states are rejected when they violate:

- static obstacles,
- known dynamic obstacles,
- reservations created by previously planned agents,
- vertex conflicts,
- edge conflicts.

### Prioritized planning

A practical coordination approach is used:

1. Choose an agent ordering.
2. Plan an agent with Space-Time A*.
3. Insert its trajectory into a reservation table.
4. Plan the next agent while respecting existing reservations.
5. Validate the final set of trajectories.
6. Perform additional final-goal safety checks where necessary.

The original trajectory of every agent is retained as a baseline:

```text
original_plan
```

while the trajectory being executed is:

```text
current_plan
```

This separation makes it possible to measure plan preservation.

---

## 6. Conflict Model

### Vertex conflict

Two agents occupy the same cell at the same timestep.

```text
A1(t) = A2(t)
```

### Edge conflict

Two agents exchange cells during one timestep.

```text
A1(t) = A2(t+1)
A2(t) = A1(t+1)
```

Both conflict types are checked during planning, after repair, and during execution.

---

## 7. Dynamic Environment

Static obstacles are present before the initial plan is generated.

Dynamic obstacles are represented by a cell and an active time interval:

```text
cell       = (r,c)
start_time = ts
end_time   = te
```

A cell is dynamically blocked whenever:

```text
ts <= t < te
```

The simulator updates the active obstacle set as time advances.

---

## 8. Plan Repair Strategy

The repair mechanism follows a local, disruption-driven workflow.

```text
Disruption
    |
    v
Identify affected agent(s)
    |
    v
Find nearby communicating agents
    |
    v
Generate alternative trajectories
    |
    +--> local detour and rejoin
    |
    +--> milestone-based continuation
    |
    +--> wait-until-clear
    |
    v
Validate candidate trajectories
    |
    v
Negotiation
    |
    v
Select minimum-cost feasible proposal
    |
    v
Modify current_plan only
    |
    v
Continue execution
```

### Local detour and rejoin

The repair engine identifies the first conflict in the affected trajectory. It preserves the safe prefix and tries to find a path from the state immediately before the disruption to a later state of the original trajectory.

Two rejoin modes are considered:

- exact-time rejoin,
- delayed rejoin with a time-shifted suffix.

This is the main plan-preservation mechanism.

### Milestone-based repair

If direct rejoining is not possible, the repair engine attempts to reconnect the agent through task milestones such as:

```text
pickup -> delivery
```

This preserves task ordering while allowing the trajectory itself to change.

### Wait-based repair

If the obstruction is temporary, waiting can be cheaper than taking a large detour. The search therefore also considers waiting until the obstacle clears, subject to reservation and safety constraints.

---

## 9. Negotiation

The affected agent communicates with neighboring agents inside a configured communication radius.

A neighbor is useful because it may be able to:

- keep its existing trajectory,
- accept a time shift,
- provide a feasible reservation context,
- negotiate a conflict-free local alternative.

A proposal contains the affected trajectory and the set of agents whose trajectories would change.

The selected proposal is chosen from feasible candidates using cost-oriented criteria such as:

1. additional delay,
2. additional path cost,
3. number of changed states,
4. number of modified agents.

The key optimization principle is:

> Prefer a feasible local repair that changes as few original plans as possible.

---

## 10. Agent Failure Handling

When an agent fails:

1. The failed agent stops executing movement.
2. Its unfinished tasks are identified.
3. Nearby healthy agents are considered as receivers.
4. A negotiation proposal transfers the unfinished work.
5. The receiver updates its task queue.
6. The receiver generates/uses a feasible continuation trajectory.
7. The failed agent's future reservations are removed from consideration.

The aim is to avoid reconstructing the complete fleet plan.

---

## 11. Emergency Task Handling

Emergency tasks have a higher priority than ordinary tasks.

The repair mechanism:

1. identifies an available healthy agent,
2. inserts the emergency task at the appropriate task position,
3. generates a local trajectory to the emergency pickup/delivery milestones,
4. preserves unaffected agents where possible,
5. returns the receiver to its previous work or final destination.

The task is modeled using an explicit state machine:

```text
PENDING
   |
   v
GOING_TO_PICKUP
   |
   v
PICKED_UP
   |
   v
GOING_TO_DELIVERY
   |
   v
COMPLETED
```

This prevents invalid task-state transitions.

---

## 12. Why the Approach Fits Multi-Agent Systems

The system demonstrates several central multi-agent-system principles.

### Distributed problem solving

The original problem is decomposed by assigning each robot its own trajectory, while coordination is handled through shared constraints and communication.

### Coordination

Agents cannot independently optimize their routes without considering others because shared cells and shared time create coupled decisions.

### Communication

The repair process uses neighboring agents as participants in the recovery process.

### Negotiation

Alternative trajectory proposals are evaluated and a feasible proposal is selected rather than centrally replanning the entire fleet.

### Locality

Only agents affected by the disruption and their relevant neighbors are considered for repair. This reduces unnecessary changes.

### Task allocation

Agent failure and emergency tasks require reallocating unfinished work among agents.

### Rational action selection

Candidate repairs are evaluated according to operational cost, delay and plan-change impact.

### Robustness

The system is designed to maintain useful behavior after environmental change rather than assuming the world remains static.

---

## 13. Metrics

### Total completion time

Sum of completion times of completed agents:

```text
T_total = Σ_i C_i
```

### Makespan

Maximum completion time:

```text
M = max_i C_i
```

### Total path cost

Total movement/waiting cost accumulated by agents.

### Modified-agent count

Number of agents whose original plan is changed because of the disruption.

### Modification ratio

```text
modified_agents / total_agents
```

### Plan preservation ratio

```text
1 - modification_ratio
```

### Repair time

Wall-clock computation time spent in the repair mechanism.

### Negotiation rounds

Number of negotiation rounds required to select a feasible repair.

### Conflicts

Number of detected conflicts, including:

- vertex conflicts,
- edge conflicts,
- obstacle conflicts.

### Delay

Additional completion time relative to the baseline.

---

## 14. Experimental Design

### A. Single-disruption impact

Run one disruption at a time for:

- Agent failure
- Dynamic obstacle
- Emergency task

Report:

- total completion time,
- makespan,
- path cost,
- modified agents,
- modification ratio,
- repair time,
- negotiation rounds,
- total repair operations,
- conflicts,
- plan preservation.

### B. Agent scaling

Evaluate increasing fleet size, e.g.:

```text
5, 10, 15, 20, 25, 30 agents
```

The expected result is increased computational and coordination effort as the number of agents increases.

### C. Dynamic obstacle density

Evaluate:

```text
0.00, 0.05, 0.10, 0.15, 0.20, 0.25
```

The expected result is greater repair difficulty and larger plan modification impact as obstacle density becomes higher.

---

## 15. Results

### 15.1 Verified successful disruption runs

| Disruption | Total completion time | Makespan | Path cost | Modified agents | Modification ratio | Repair time (s) | Negotiation rounds | Plan preservation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Agent failure | 46 | 23 | 56.0 | 1 | 0.25 | 0.0061 | 2 | 0.75 |
| Dynamic obstacle* | 45 | 13 | 49.0 | 1 | 0.25 | 0.0021 | 1 | 0.75 |
| Emergency task | 59 | 25 | 63.0 | 1 | 0.25 | 0.0205 | 3 | 0.75 |

`*` Dynamic-obstacle row is the successful earlier density=0.00 dynamic-obstacle run available in the supplied logs.

All three successful rows report zero detected vertex, edge and obstacle conflicts and one successful repair operation.

### 15.2 Dynamic-obstacle density

A successful earlier sweep produced a stable baseline-style reference across densities 0.00–0.25:

| Density | Total completion time | Makespan | Path cost | Modified agents | Modification ratio | Plan preservation |
|---:|---:|---:|---:|---:|---:|---:|
| 0.00 | 45 | 13 | 49.0 | 1 | 0.25 | 0.75 |
| 0.05 | 45 | 13 | 49.0 | 1 | 0.25 | 0.75 |
| 0.10 | 45 | 13 | 49.0 | 1 | 0.25 | 0.75 |
| 0.15 | 45 | 13 | 49.0 | 1 | 0.25 | 0.75 |
| 0.20 | 45 | 13 | 49.0 | 1 | 0.25 | 0.75 |
| 0.25 | 45 | 13 | 49.0 | 1 | 0.25 | 0.75 |

This table is useful as a controlled baseline/reference, but the latest code revision produced different behavior at higher densities. The raw file is therefore preserved separately.

### 15.3 Verified scaling point

One completed 5-agent scaling run recorded:

```text
total_completion_time = 61
makespan = 15
path_cost = 66
modified_agents = 1
modification_ratio = 0.20
plan_preservation_ratio = 0.80
repair_time = 0.006344 s
negotiation_rounds = 3
```

A complete 5–30 agent sweep was not successfully completed in the final revision.

---

## 16. Tests and Validation

The latest code revision passed:

```text
47 passed
```

The test suite covers the major components including:

- grid behavior,
- Space-Time A*,
- conflict detection,
- repair logic,
- simulation behavior.

---

## 17. Visualization

Simulation outputs include:

```text
results/plots/smoke_animation.gif
results/plots/smoke_final.png
```

The animation is useful for demonstrating:

- agent movement,
- task progression,
- collision avoidance,
- disruption occurrence,
- plan repair.

---

## 18. Running the Project

From the repository root:

```fish
PYTHONPATH=. uv run pytest -q
```

Basic experiment:

```fish
PYTHONPATH=. uv run python experiments/run_experiment.py --config configs/small.yaml
```

Disruption comparison:

```fish
PYTHONPATH=. uv run python experiments/disruption_impact.py \
  --config configs/small.yaml \
  --types agent_failure dynamic_obstacle emergency_task \
  --output all_disruptions_fixed
```

Agent scaling:

```fish
PYTHONPATH=. uv run python experiments/agent_scaling.py \
  --config configs/small.yaml
```

Obstacle density:

```fish
PYTHONPATH=. uv run python experiments/obstacle_density.py \
  --config configs/small.yaml
```

---

## 19. Repository Structure

```text
multiagent-plan-repair/
├── README.md
├── requirements.txt
├── .gitignore
├── configs/
│   ├── default.yaml
│   ├── small.yaml
│   ├── medium.yaml
│   └── large.yaml
├── src/
│   ├── environment/
│   │   ├── grid.py
│   │   └── obstacles.py
│   ├── agents/
│   │   ├── agent.py
│   │   └── task.py
│   ├── planning/
│   │   ├── space_time_astar.py
│   │   ├── initial_planner.py
│   │   ├── conflict_detection.py
│   │   └── ...
│   ├── repair/
│   │   ├── disruption.py
│   │   ├── negotiation.py
│   │   ├── local_repair.py
│   │   └── repair_manager.py
│   ├── simulation/
│   │   ├── simulator.py
│   │   └── execution.py
│   ├── metrics/
│   │   └── metrics.py
│   └── visualization/
│       └── visualizer.py
├── experiments/
│   ├── run_experiment.py
│   ├── agent_scaling.py
│   ├── obstacle_density.py
│   └── disruption_impact.py
├── results/
│   ├── raw/
│   ├── plots/
│   └── logs/
├── tests/
└── docs/
```

---

## 20. References

1. M. Wooldridge, *An Introduction to MultiAgent Systems*, 2nd ed., Wiley, 2009.
2. D. Silver, “Cooperative Pathfinding,” in *Proceedings of the AAAI Conference on Artificial Intelligence and Interactive Digital Entertainment*, 2005.
3. G. Sharon, R. Stern, A. Felner, and N. R. Sturtevant, “Conflict-Based Search for Optimal Multi-Agent Pathfinding,” *Artificial Intelligence*, vol. 219, pp. 40–66, 2015.
4. J. Yu and S. M. LaValle, “Planning Optimal Paths for Multiple Robots on Graphs,” in *2013 IEEE International Conference on Robotics and Automation (ICRA)*, 2013.
5. D. S. Bernstein, R. Givan, N. Immerman, and S. Zilberstein, “The Complexity of Decentralized Control of Markov Decision Processes,” *Mathematics of Operations Research*, 2002.

---

## 21. Important Results Note

The repository should distinguish **measured results** from **illustrative target values**. The files under `results/raw/*_verified.csv` are based on successful runs present in the supplied terminal logs. The file under `results/illustrative/` is included only to demonstrate a complete scalability dataset and plotting workflow; it is not a measured run.

