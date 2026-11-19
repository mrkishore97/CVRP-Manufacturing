"""Pure frontend state: the canonical scenario, its derived artifacts, and freshness.

Nothing in this package imports Streamlit or talks to the backend, so every rule here
is unit-tested directly. Views read and write these structures through
``st.session_state``.
"""
