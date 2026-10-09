"""One process for a hosted demo (Render, Docker): the API under /api and the built UI at /.

  cd ui && npm run build && cd ..
  uvicorn orchestration.web:app --port 8100      -> open http://localhost:8100

The UI calls /api/... in production exactly as it does behind the Vite dev proxy, so nothing in the UI changes.
Local development keeps using `uvicorn orchestration.api:app` + `npm run dev`.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .api import app as api
from .orchestrator import ROOT

# The slim Docker image has no /etc/mime.types, so these would go out as application/octet-stream.
for _type, _ext in (("image/webp", ".webp"), ("font/woff2", ".woff2"), ("font/woff", ".woff")):
    mimetypes.add_type(_type, _ext)

DIST = Path(os.environ.get("UI_DIST") or ROOT / "ui" / "dist").resolve()

app = FastAPI(title="CUBE Pod 05", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/api", api)

if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def ui(path: str):
    """A file from the build (cover images, favicon), else index.html so client-side routes like /workflows/x load."""
    index = DIST / "index.html"
    if not index.is_file():
        return PlainTextResponse("UI not built: run `npm run build` in ui/ (the API is at /api).", status_code=503)
    target = (DIST / path).resolve()
    if path and target.is_file() and DIST in target.parents:
        return FileResponse(target)
    return FileResponse(index)
