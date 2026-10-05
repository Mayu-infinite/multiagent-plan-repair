"""Task representation for the multi-agent warehouse.

A warehouse task consists of:
    1. travelling to a pickup location,
    2. picking up an object,
    3. travelling to the delivery location,
    4. delivering the object.

Tasks also have priorities so that high-priority or emergency
tasks can be introduced as dynamic disruptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Tuple


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Position = Tuple[int, int]


# ---------------------------------------------------------------------------
# Task priority
# ---------------------------------------------------------------------------

class TaskPriority(IntEnum):
    """Priority levels for warehouse tasks."""

    NORMAL = 1
    HIGH = 2
    EMERGENCY = 3


# ---------------------------------------------------------------------------
# Task status
# ---------------------------------------------------------------------------

class TaskStatus(Enum):
    """Lifecycle of a warehouse task."""

    PENDING = "pending"
    GOING_TO_PICKUP = "going_to_pickup"
    PICKED_UP = "picked_up"
    GOING_TO_DELIVERY = "going_to_delivery"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """Represents one pickup-and-delivery task."""

    task_id: str
    pickup_position: Position
    delivery_position: Position
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING

    # -----------------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------------

    def __post_init__(self) -> None:
        """Validate task fields."""
        self._validate_position(
            self.pickup_position,
            "pickup_position",
        )
        self._validate_position(
            self.delivery_position,
            "delivery_position",
        )

        if self.pickup_position == self.delivery_position:
            raise ValueError(
                f"Task '{self.task_id}' has identical pickup and "
                "delivery positions."
            )

        if not isinstance(self.priority, TaskPriority):
            try:
                self.priority = TaskPriority(self.priority)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Invalid task priority: {self.priority}"
                ) from exc

    # -----------------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------------

    @property
    def is_completed(self) -> bool:
        """Return True when the task has been delivered."""
        return self.status == TaskStatus.COMPLETED

    @property
    def is_emergency(self) -> bool:
        """Return True when this is an emergency-priority task."""
        return self.priority == TaskPriority.EMERGENCY

    @property
    def is_active(self) -> bool:
        """Return True when the task is currently being executed."""
        return self.status in {
            TaskStatus.GOING_TO_PICKUP,
            TaskStatus.PICKED_UP,
            TaskStatus.GOING_TO_DELIVERY,
        }

    # -----------------------------------------------------------------------
    # State transitions
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """Start executing the task.

        Only PENDING tasks may transition into GOING_TO_PICKUP.
        Execution code checks the state before attempting to start
        a task, so an already-active task is not started twice.
        """
        if self.status != TaskStatus.PENDING:
            raise RuntimeError(
                f"Cannot start task '{self.task_id}' from state "
                f"'{self.status.value}'."
            )

        self.status = TaskStatus.GOING_TO_PICKUP

    def pickup(self) -> None:
        """Mark the object as picked up."""
        if self.status != TaskStatus.GOING_TO_PICKUP:
            raise RuntimeError(
                f"Cannot pick up task '{self.task_id}' from state "
                f"'{self.status.value}'."
            )

        self.status = TaskStatus.PICKED_UP

    def start_delivery(self) -> None:
        """Begin travelling toward the delivery location."""
        if self.status != TaskStatus.PICKED_UP:
            raise RuntimeError(
                f"Cannot start delivery for task '{self.task_id}' "
                f"from state '{self.status.value}'."
            )

        self.status = TaskStatus.GOING_TO_DELIVERY

    def complete(self) -> None:
        """Mark the task as completed."""
        if self.status != TaskStatus.GOING_TO_DELIVERY:
            raise RuntimeError(
                f"Cannot complete task '{self.task_id}' from state "
                f"'{self.status.value}'."
            )

        self.status = TaskStatus.COMPLETED

    # -----------------------------------------------------------------------
    # Utility methods
    # -----------------------------------------------------------------------

    @staticmethod
    def _validate_position(
        position: Position,
        field_name: str,
    ) -> None:
        """Validate that a position is a 2D integer coordinate."""
        if (
            not isinstance(position, tuple)
            or len(position) != 2
            or not all(isinstance(value, int) for value in position)
        ):
            raise TypeError(
                f"{field_name} must be a tuple of two integers. "
                f"Received: {position!r}"
            )

    def reset(self) -> None:
        """Reset the task to its initial pending state."""
        self.status = TaskStatus.PENDING

    def __repr__(self) -> str:
        """Human-readable task representation."""
        return (
            f"Task("
            f"id={self.task_id!r}, "
            f"pickup={self.pickup_position}, "
            f"delivery={self.delivery_position}, "
            f"priority={self.priority.name}, "
            f"status={self.status.value}"
            f")"
        )
