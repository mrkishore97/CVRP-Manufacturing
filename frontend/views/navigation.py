"""Page registry and the sidebar navigation of the single-script router."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import streamlit as st

from frontend.views import (
    advanced_json,
    fleet,
    locations,
    optimize,
    results,
    review,
    scenario,
    tasks,
    travel_times,
)
from frontend.views.components import PAGE_KEY, AppContext, go_to


@dataclass(frozen=True, slots=True)
class PageSpec:
    key: str
    title: str
    section: str
    render: Callable[[AppContext], None]


PAGES: tuple[PageSpec, ...] = (
    PageSpec("scenario", "Scenario", "Build", scenario.render),
    PageSpec("locations", "Locations", "Build", locations.render),
    PageSpec("fleet", "Fleet", "Build", fleet.render),
    PageSpec("tasks", "Tasks", "Build", tasks.render),
    PageSpec("review", "Review", "Plan", review.render),
    PageSpec("travel_times", "Travel times", "Plan", travel_times.render),
    PageSpec("optimize", "Optimize", "Plan", optimize.render),
    PageSpec("results", "Results", "Plan", results.render),
    PageSpec("json", "Advanced JSON", "Advanced", advanced_json.render),
)
PAGES_BY_KEY = {page.key: page for page in PAGES}
DEFAULT_PAGE = "scenario"


def current_page() -> PageSpec:
    """The page in session state, else the ``?page=`` parameter, else the default."""
    key = st.session_state.get(PAGE_KEY)
    if key not in PAGES_BY_KEY:
        key = st.query_params.get("page", DEFAULT_PAGE)
        if key not in PAGES_BY_KEY:
            key = DEFAULT_PAGE
        st.session_state[PAGE_KEY] = key
    return PAGES_BY_KEY[str(key)]


def render_navigation(current: PageSpec) -> None:
    for section in dict.fromkeys(page.section for page in PAGES):
        st.caption(section)
        for page in PAGES:
            if page.section != section:
                continue
            if st.button(
                page.title,
                key=f"nav-{page.key}",
                type="primary" if page.key == current.key else "secondary",
                use_container_width=True,
            ):
                go_to(page.key)
