"""Root conftest: applies to tests/ and agents/*/tests/.

A developer's .env (API keys, live modes, model names) must never change test results. The Pod's own loader skips .env
under pytest (shared/utils/env.py), but the Returns agent's Round 2 settings read .env themselves through RM_ENV_FILE,
so point that at a file that does not exist before any agent is imported.
"""
import os
from pathlib import Path

os.environ["RM_ENV_FILE"] = str(Path(__file__).resolve().parent / ".env.no-such-file-under-pytest")
