"""Drive the Fleet and Tasks forms through ``AppTest`` the way a planner fills them in.

Shared by the fake-backend page tests and the real-backend gate test, so both build
scenarios through exactly the same widgets. Widget keys follow the views: add forms use
a round counter that changes after every add, so each add starts from empty fields.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, time
from typing import Any

from streamlit.testing.v1 import AppTest

from frontend.state.workspace import Workspace


def ok(app: AppTest) -> None:
    assert not app.exception, app.exception


def click(app: AppTest, label: str) -> None:
    matches = [button for button in app.button if button.label == label]
    assert matches, f"no button {label!r}: {[button.label for button in app.button]}"
    matches[0].click().run()
    ok(app)


def click_starting(app: AppTest, prefix: str) -> None:
    matches = [button for button in app.button if str(button.label).startswith(prefix)]
    assert matches, f"no button starting {prefix!r}"
    matches[0].click().run()
    ok(app)


def go(app: AppTest, page: str) -> None:
    app.button(key=f"nav-{page}").click().run()
    ok(app)


def workspace(app: AppTest) -> Workspace:
    value = app.session_state["workspace"]
    assert isinstance(value, Workspace)
    return value


def scenario(app: AppTest) -> dict[str, Any]:
    return workspace(app).scenario


def _round(app: AppTest, key: str) -> int:
    try:
        return int(app.session_state[key])
    except KeyError:
        return 0


def add_truck(
    app: AppTest,
    *,
    name: str,
    capacity: float,
    tags: str = "",
    max_time: str = "",
    max_km: float | None = None,
    enabled: bool = True,
) -> None:
    prefix = f"truck-add-{_round(app, 'fleet_truck_add_round')}"
    app.text_input(key=f"{prefix}-name").input(name)
    app.number_input(key=f"{prefix}-capacity").set_value(float(capacity))
    if tags:
        app.text_input(key=f"{prefix}-tags").input(tags)
    if max_time:
        app.text_input(key=f"{prefix}-max-time").input(max_time)
    if max_km is not None:
        app.number_input(key=f"{prefix}-max-km").set_value(float(max_km))
    if not enabled:
        app.checkbox(key=f"{prefix}-enabled").uncheck()
    click(app, "Add truck")


def generate_shifts(
    app: AppTest,
    *,
    trucks: Sequence[str],
    first: date,
    last: date,
    weekdays: Sequence[int] = (0, 1, 2, 3, 4),
    start: time = time(7, 0),
    end: time = time(17, 0),
    end_location: str | None = None,
    apply: bool = True,
) -> None:
    app.multiselect(key="generator-trucks").set_value(list(trucks))
    app.date_input(key="generator-first").set_value(first)
    app.date_input(key="generator-last").set_value(last)
    app.multiselect(key="generator-weekdays").set_value(list(weekdays))
    app.time_input(key="generator-start").set_value(start)
    app.time_input(key="generator-end").set_value(end)
    if end_location is not None:
        app.selectbox(key="generator-to").set_value(end_location)
    click(app, "Preview shifts")
    if apply:
        app.button(key="generator-apply").click().run()
        ok(app)


def choose_movement(app: AppTest, movement: str) -> str:
    """Pick the movement outside the form; returns the add form's key prefix."""
    app.radio(key="tasks_add_movement").set_value(movement).run()
    ok(app)
    return f"task-add-{_round(app, 'tasks_add_round')}-{movement}"


def add_task(
    app: AppTest,
    *,
    movement: str,
    po: str,
    origin: str | None = None,
    destination: str | None = None,
    quantity: float = 1,
    day: date,
    ready: time = time(7, 0),
    due: time = time(17, 0),
    due_day: date | None = None,
    priority: int = 1,
    tags: Sequence[str] = (),
) -> None:
    prefix = choose_movement(app, movement)
    app.text_input(key=f"{prefix}-po").input(po)
    if origin is not None:
        app.selectbox(key=f"{prefix}-from").set_value(origin)
    if destination is not None:
        app.selectbox(key=f"{prefix}-to").set_value(destination)
    app.number_input(key=f"{prefix}-quantity").set_value(float(quantity))
    app.date_input(key=f"{prefix}-ready-day").set_value(day)
    app.time_input(key=f"{prefix}-ready").set_value(ready)
    app.date_input(key=f"{prefix}-due-day").set_value(due_day or day)
    app.time_input(key=f"{prefix}-due").set_value(due)
    app.selectbox(key=f"{prefix}-priority").set_value(priority)
    if tags:
        app.multiselect(key=f"{prefix}-tags").set_value(list(tags))
    click(app, "Add task")
