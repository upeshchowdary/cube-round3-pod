"""Shared contracts and helpers. Every entry point (CLI, API, a standalone agent) imports this package first, so this
is where the repo's .env is loaded, once (see shared/utils/env.py)."""
from .utils.env import load_dotenv as _load_dotenv

_load_dotenv()
