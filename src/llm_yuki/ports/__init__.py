"""Abstract interfaces (input/output ports) that ``domain`` code depends on.

``domain`` must only ever import from here, never from ``llm_yuki.adapters`` directly — see root
ARCHITECTURE.md §3 (dependency flow) and AGENTS.md §4.
"""
