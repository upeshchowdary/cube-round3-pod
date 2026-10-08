"""Load the repo's .env into os.environ, so the keys and modes the README tells you to put there reach every agent.

Before this, only the Returns agent read .env (through its Round 2 settings); the orchestrator, Receiving, Pack and
Recovery read os.environ only, so e.g. GROQ_API_KEY or RECOVERY_MODEL_MODE=live in .env did nothing.

Rules: a real environment variable always wins over .env; empty values are skipped; nothing is logged but the names.
Not applied under pytest, so a developer's own keys or live modes can never change test results (CI has no .env).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_COMMENT = re.compile(r"\s+#.*$")


def load_dotenv(path: str | Path | None = None) -> list[str]:
    """Set each KEY=VALUE from .env that is not already set. Returns the names it set (never the values)."""
    if "pytest" in sys.modules or os.environ.get("POD_DOTENV", "1") == "0":
        return []
    path = Path(path or os.environ.get("POD_ENV_FILE") or ROOT / ".env")
    if not path.is_file():
        return []
    loaded = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] in ("'", '"') and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        else:
            value = _COMMENT.sub("", value).strip()
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
