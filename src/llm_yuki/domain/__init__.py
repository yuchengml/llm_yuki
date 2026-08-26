"""Core pipeline logic: no filesystem or network I/O.

Everything in this package must be testable without touching a real filesystem — I/O goes through
``llm_yuki.ports`` interfaces, implemented by ``llm_yuki.adapters``. See root ARCHITECTURE.md.
"""
