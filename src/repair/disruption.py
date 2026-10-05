"""
Disruption models for the dynamic warehouse.

The planning system creates an initial multi-agent solution, but the
environment may change during execution.

Supported disruption types
--------------------------
1. AGENT_FAILURE
2. DYNAMIC_OBSTACLE
3. EMERGENCY_TASK

A Disruption object contains all information required by the repair
manager to decide how the existing plan should be modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from ..agents import Position, Task


# ---------------------------------------------------------------------------
# Disruption type
# ---------------------------------------------------------------------------

class DisruptionType(Enum):
    """
    Types of unexpected events supported by the system.
    """

    AGENT_FAILURE = "agent_failure"
    DYNAMIC_OBSTACLE = "dynamic_obstacle"
    EMERGENCY_TASK = "emergency_task"

    @classmethod
    def from_string(
        cls,
        value: str,
    ) -> "DisruptionType":
        """
        Convert a string into a DisruptionType.
        """
        normalized = value.strip().lower()

        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported disruption type: {value}. "
                f"Supported types: "
                f"{[item.value for item in cls]}"
            ) from exc


# ---------------------------------------------------------------------------
# Disruption
# ---------------------------------------------------------------------------

@dataclass
class Disruption:
    """
    Represents one disruption event.

    Parameters
    ----------
    disruption_id:
        Unique identifier.

    disruption_type:
        Type of disruption.

    timestep:
        Simulation timestep when the disruption occurs.

    agent_id:
        Agent involved in the disruption.

        Used primarily for AGENT_FAILURE.

    position:
        Grid cell affected by the disruption.

        Used primarily for DYNAMIC_OBSTACLE.

    duration:
        Duration of a dynamic obstacle.

    task:
        New emergency task for EMERGENCY_TASK.

    metadata:
        Optional additional information.
    """

    disruption_id: str
    disruption_type: DisruptionType
    timestep: int

    agent_id: Optional[str] = None
    position: Optional[Position] = None

    duration: Optional[int] = None

    task: Optional[Task] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        """Validate the disruption."""
        if not self.disruption_id:
            raise ValueError(
                "disruption_id cannot be empty."
            )

        if self.timestep < 0:
            raise ValueError(
                "Disruption timestep cannot be negative."
            )

        if not isinstance(
            self.disruption_type,
            DisruptionType,
        ):
            self.disruption_type = DisruptionType.from_string(
                str(self.disruption_type)
            )

        if self.agent_id is not None and not self.agent_id:
            raise ValueError(
                "agent_id cannot be an empty string."
            )

        if self.position is not None:
            if (
                not isinstance(self.position, tuple)
                or len(self.position) != 2
                or not all(
                    isinstance(value, int)
                    for value in self.position
                )
            ):
                raise TypeError(
                    "position must be a tuple of two integers."
                )

        if self.duration is not None:
            if self.duration <= 0:
                raise ValueError(
                    "duration must be greater than zero."
                )

        self._validate_type_specific_fields()

    # -----------------------------------------------------------------------
    # Type-specific validation
    # -----------------------------------------------------------------------

    def _validate_type_specific_fields(self) -> None:
        """Validate fields required by each disruption type."""

        if self.disruption_type == DisruptionType.AGENT_FAILURE:
            if self.agent_id is None:
                raise ValueError(
                    "AGENT_FAILURE requires agent_id."
                )

        elif (
            self.disruption_type
            == DisruptionType.DYNAMIC_OBSTACLE
        ):
            if self.position is None:
                raise ValueError(
                    "DYNAMIC_OBSTACLE requires position."
                )

            if self.duration is None:
                raise ValueError(
                    "DYNAMIC_OBSTACLE requires duration."
                )

        elif (
            self.disruption_type
            == DisruptionType.EMERGENCY_TASK
        ):
            if self.task is None:
                raise ValueError(
                    "EMERGENCY_TASK requires task."
                )

    # -----------------------------------------------------------------------
    # Factory methods
    # -----------------------------------------------------------------------

    @classmethod
    def agent_failure(
        cls,
        disruption_id: str,
        agent_id: str,
        timestep: int,
        **metadata: Any,
    ) -> "Disruption":
        """
        Create an agent-failure disruption.
        """
        return cls(
            disruption_id=disruption_id,
            disruption_type=DisruptionType.AGENT_FAILURE,
            timestep=timestep,
            agent_id=agent_id,
            metadata=metadata,
        )

    @classmethod
    def dynamic_obstacle(
        cls,
        disruption_id: str,
        position: Position,
        timestep: int,
        duration: int,
        **metadata: Any,
    ) -> "Disruption":
        """
        Create a dynamic-obstacle disruption.
        """
        return cls(
            disruption_id=disruption_id,
            disruption_type=DisruptionType.DYNAMIC_OBSTACLE,
            timestep=timestep,
            position=position,
            duration=duration,
            metadata=metadata,
        )

    @classmethod
    def emergency_task(
        cls,
        disruption_id: str,
        task: Task,
        timestep: int,
        **metadata: Any,
    ) -> "Disruption":
        """
        Create an emergency-task disruption.
        """
        return cls(
            disruption_id=disruption_id,
            disruption_type=DisruptionType.EMERGENCY_TASK,
            timestep=timestep,
            task=task,
            metadata=metadata,
        )

    # -----------------------------------------------------------------------
    # Convenience properties
    # -----------------------------------------------------------------------

    @property
    def is_agent_failure(self) -> bool:
        """Return True for agent failure."""
        return (
            self.disruption_type
            == DisruptionType.AGENT_FAILURE
        )

    @property
    def is_dynamic_obstacle(self) -> bool:
        """Return True for dynamic obstacle."""
        return (
            self.disruption_type
            == DisruptionType.DYNAMIC_OBSTACLE
        )

    @property
    def is_emergency_task(self) -> bool:
        """Return True for emergency task."""
        return (
            self.disruption_type
            == DisruptionType.EMERGENCY_TASK
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the disruption into a JSON-serializable dictionary.
        """
        task_data: Optional[dict[str, Any]] = None

        if self.task is not None:
            task_data = {
                "task_id": self.task.task_id,
                "pickup_position": self.task.pickup_position,
                "delivery_position": self.task.delivery_position,
                "priority": int(self.task.priority),
                "status": self.task.status.value,
            }

        return {
            "disruption_id": self.disruption_id,
            "disruption_type": self.disruption_type.value,
            "timestep": self.timestep,
            "agent_id": self.agent_id,
            "position": self.position,
            "duration": self.duration,
            "task": task_data,
            "metadata": dict(self.metadata),
        }

    def __repr__(self) -> str:
        return (
            f"Disruption("
            f"id={self.disruption_id!r}, "
            f"type={self.disruption_type.value!r}, "
            f"timestep={self.timestep}"
            f")"
        )