"""Expand user-facing task rows into consistent internal pickup/delivery nodes."""

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from backend.app.domain.enums import DueEvent, StopKind
from backend.app.domain.models import DomainModel, Identifier, Task


class ExpandedTaskNode(DomainModel):
    """One solver-facing node generated from a positive-quantity task."""

    node_id: Identifier
    task_id: Identifier
    kind: StopKind
    location_id: Identifier
    load_delta: Decimal
    service_seconds: int = Field(ge=0)
    ready_at: datetime | None = None
    completion_due_at: datetime | None = None
    is_plant_node: bool


class ExpandedTask(DomainModel):
    """The paired internal representation shared by every business task type."""

    task_id: Identifier
    pickup: ExpandedTaskNode
    delivery: ExpandedTaskNode


def expand_task(task: Task, plant_location_id: str) -> ExpandedTask:
    """Generate pickup/delivery nodes with load and deadline semantics."""
    pickup_due = task.due_at if task.due_event is DueEvent.PICKUP_COMPLETE else None
    delivery_due = task.due_at if task.due_event is DueEvent.DELIVERY_COMPLETE else None
    pickup = ExpandedTaskNode(
        node_id=f"{task.task_id}::pickup",
        task_id=task.task_id,
        kind=StopKind.PICKUP,
        location_id=task.origin_location_id,
        load_delta=task.quantity,
        service_seconds=task.pickup_service_minutes * 60,
        ready_at=task.ready_at,
        completion_due_at=pickup_due,
        is_plant_node=task.origin_location_id == plant_location_id,
    )
    delivery = ExpandedTaskNode(
        node_id=f"{task.task_id}::delivery",
        task_id=task.task_id,
        kind=StopKind.DELIVERY,
        location_id=task.destination_location_id,
        load_delta=-task.quantity,
        service_seconds=task.delivery_service_minutes * 60,
        completion_due_at=delivery_due,
        is_plant_node=task.destination_location_id == plant_location_id,
    )
    return ExpandedTask(task_id=task.task_id, pickup=pickup, delivery=delivery)


def expand_tasks(tasks: tuple[Task, ...], plant_location_id: str) -> tuple[ExpandedTask, ...]:
    """Expand tasks in stable request order."""
    return tuple(expand_task(task, plant_location_id) for task in tasks)
