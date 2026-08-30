"""Convenience wrapper for the ``llm-yuki`` CLI — forwards straight to ``llm_yuki.cli.main``.

Not a separate entry point: the packaged console script (registered in `pyproject.toml`'s
`[tool.poetry.scripts]`, `llm-yuki = "llm_yuki.cli:main"`) is the primary/supported way to run this pipeline
— `poetry run llm-yuki compile ...`. `cli.py` itself must stay inside `src/llm_yuki/` for that console script
to resolve (`module_path:function`), so it isn't moved here. This wrapper exists purely so the same command
can also be run as a plain script from a source checkout, mirroring `scripts/call_llm.py`'s pattern.

Usage:
    poetry run python scripts/cli.py compile <source_dir> <bundle_dir> [options]
"""

from __future__ import annotations

import sys

from llm_yuki.cli import main

if __name__ == "__main__":
    sys.exit(main())
