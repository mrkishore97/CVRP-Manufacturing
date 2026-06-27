"""Unified pickup/delivery node-expansion tests."""

from decimal import Decimal

from backend.app.domain import DueEvent, StopKind, TaskType, validate_planning_payload
from backend.app.optimization import expand_task, expand_tasks
from backend.tests.fixtures.canonical import planning_payload


def test_all_task_types_expand_to_balanced_pickup_delivery_pairs() -> None:
    result = validate_planning_payload(planning_payload("A"))
    assert result.normalized_request is not None

    expanded = expand_tasks(result.normalized_request.tasks, "PLANT")

    assert len(expanded) == 6
    for task, pair in zip(result.normalized_request.tasks, expanded, strict=True):
        assert pair.pickup.kind is StopKind.PICKUP
        assert pair.delivery.kind is StopKind.DELIVERY
        assert pair.pickup.load_delta == task.quantity
        assert pair.delivery.load_delta == -task.quantity
        assert pair.pickup.load_delta + pair.delivery.load_delta == Decimal(0)
        assert pair.pickup.ready_at == task.ready_at


def test_plant_virtual_nodes_follow_business_task_type() -> None:
    result = validate_planning_payload(planning_payload("A"))
    assert result.normalized_request is not None
    pairs = {task.task_type: expand_task(task, "PLANT") for task in result.normalized_request.tasks}

    assert not pairs[TaskType.PICKUP].pickup.is_plant_node
    assert pairs[TaskType.PICKUP].delivery.is_plant_node
    assert pairs[TaskType.DROP].pickup.is_plant_node
    assert not pairs[TaskType.DROP].delivery.is_plant_node
    assert not pairs[TaskType.PICKUP_DROP].pickup.is_plant_node
    assert not pairs[TaskType.PICKUP_DROP].delivery.is_plant_node


def test_deadline_attaches_to_completion_event_only() -> None:
    result = validate_planning_payload(planning_payload("A"))
    assert result.normalized_request is not None
    task = result.normalized_request.tasks[0]
    assert task.due_event is DueEvent.DELIVERY_COMPLETE

    delivery_due = expand_task(task, "PLANT")
    pickup_due_task = task.model_copy(update={"due_event": DueEvent.PICKUP_COMPLETE})
    pickup_due = expand_task(pickup_due_task, "PLANT")

    assert delivery_due.pickup.completion_due_at is None
    assert delivery_due.delivery.completion_due_at == task.due_at
    assert pickup_due.pickup.completion_due_at == task.due_at
    assert pickup_due.delivery.completion_due_at is None


def test_service_minutes_are_converted_to_seconds() -> None:
    result = validate_planning_payload(planning_payload("A"))
    assert result.normalized_request is not None
    task = result.normalized_request.tasks[0]

    pair = expand_task(task, "PLANT")

    assert pair.pickup.service_seconds == task.pickup_service_minutes * 60
    assert pair.delivery.service_seconds == task.delivery_service_minutes * 60
