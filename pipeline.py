"""Part 1 pipeline entrypoint (wrapper). Real logic in pipeline_steps.py + pipeline_main.py."""
from __future__ import annotations
from pipeline_main import main, run

__all__ = ["main", "run"]

if __name__ == "__main__":
    raise SystemExit(main())

