"""Structured JSON logging. One line per event, always with ids, never with secrets or image bytes.

  LOG_LEVEL=INFO|DEBUG   LOG_FORMAT=json|text
  log = get_logger("orchestrator"); log.info("stage_done", extra={"ctx": {"case_id": ..., "agent": ...}})
"""
from __future__ import annotations

import json
import logging
import os
import sys

REDACT = ("key", "token", "secret", "password", "authorization")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = getattr(record, "ctx", {}) or {}
        ctx = {k: ("***" if any(w in k.lower() for w in REDACT) else v) for k, v in ctx.items()}
        return json.dumps({"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                           "logger": record.name, "event": record.getMessage(), **ctx}, default=str)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"cube.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        if os.environ.get("LOG_FORMAT", "json") == "json":
            handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        level = os.environ.get("LOG_LEVEL", "WARNING").strip().upper()
        logger.setLevel(level if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else "WARNING")  # a typo must not crash
        logger.propagate = False
    return logger
