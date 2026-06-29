from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from alembic import command
from alembic.config import Config


def main() -> int:
    config = Config(str(PROJECT_ROOT / "content_hub" / "alembic.ini"))
    command.upgrade(config, "head")
    print("Alembic migrations applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
