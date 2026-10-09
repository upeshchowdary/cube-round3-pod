from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from returns_manager.config import Settings
from returns_manager.llm.client import ModelClient
from returns_manager.llm.gemini_client import GeminiModelClient
from returns_manager.llm.replay_client import (
    RecordingModelClient,
    ReplayModelClient,
)


class LocalCaptureTransport(httpx.AsyncBaseTransport):
    """Custom HTTPX transport serving local files under input_dir at http://capture.local/<ref>.

    Never connects to the network (§4.4).
    """

    def __init__(self, input_dir: Path):
        self.input_dir = input_dir.resolve()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host != "capture.local":
            return httpx.Response(404, request=request)

        ref = url.path.lstrip("/")
        try:
            target = (self.input_dir / ref).resolve()
            if not target.is_relative_to(self.input_dir) or not target.is_file():
                return httpx.Response(404, request=request)

            data = target.read_bytes()
            ext = target.suffix.lower()
            mime = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/png" if ext == ".png" else "application/octet-stream")
            return httpx.Response(200, content=data, headers={"Content-Type": mime}, request=request)
        except Exception:
            return httpx.Response(404, request=request)


def run_sync(coro: Any) -> Any:
    """Executes an async coroutine synchronously, even if called inside an existing event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


def create_model_client(
    mode: str,
    org_id: str,
    unit_id: str,
    settings: Settings,
    cassettes_dir: Path,
) -> tuple[ModelClient, Path | None]:
    """Instantiates the appropriate model client for the active RETURNS_MODEL_MODE (§4.4)."""
    cassette_path = cassettes_dir / org_id / f"{unit_id}.jsonl"

    if mode == "replay":
        if not cassette_path.is_file():
            raise FileNotFoundError(f"no cassette found at {cassette_path}. Record one using tools/record_cassette.py")
        return ReplayModelClient(cassette_path), cassette_path

    if mode in ("live", "record"):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured in environment or .env file")
        # Same construction as Round 2 (inspection/runtime.py, cli/batch_commands.py): the key and the timeout, not the
        # settings object. Passing `settings` alone raised TypeError, so live and record mode never ran in Round 3.
        live_client = GeminiModelClient(settings.gemini_api_key.get_secret_value(), settings.rm_model_timeout_s)
        if mode == "record":
            return RecordingModelClient(live_client, cassette_path), cassette_path
        return live_client, None

    raise ValueError(f"unknown RETURNS_MODEL_MODE: {mode!r} (expected 'replay', 'live', or 'record')")
