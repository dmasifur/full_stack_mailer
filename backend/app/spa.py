"""
Serving the built frontend from the API process.

The SPA is same-origin with the API on purpose: the session cookie stays
``SameSite=lax`` and production needs no CORS at all. See docs/architecture.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

# Client-side routes live under one prefix because the API owns the root
# namespace: /campaigns is the campaign list endpoint, so the campaign list
# *page* cannot also be /campaigns. Giving the SPA its own prefix keeps the two
# apart without moving every documented API path under /api — which would mean
# re-registering the OAuth redirect URI in Azure.
SPA_PREFIX = "app"


def mount_spa(app: FastAPI) -> None:
    """
    Serve the Vite build, if one is present.

    Absent in a backend-only checkout and before the first frontend build, so
    this is a no-op rather than a startup failure.
    """
    index = STATIC_DIR / "index.html"

    if not index.is_file():
        logger.info("No frontend build at %s — serving the API only.", STATIC_DIR)
        return

    # Every built file — hashed bundles, fonts, icons — is addressed under
    # /static, matching Vite's `base`. StaticFiles does the path containment
    # checks, so nothing here has to reason about "..".
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="spa-static")

    @app.get("/", include_in_schema=False)
    def spa_root() -> RedirectResponse:
        return RedirectResponse(f"/{SPA_PREFIX}", status_code=307)

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        """
        Serve the shell for a client-side route.

        An allowlist, not a blocklist: only paths under the SPA prefix get the
        shell, and everything else is a 404. A mistyped endpoint has to fail as
        a missing endpoint — answering 200 with HTML would make a client try to
        parse the shell as JSON.
        """
        if full_path.split("/", 1)[0] == SPA_PREFIX:
            return FileResponse(index)

        raise HTTPException(status_code=404, detail="Not found.")

    logger.info("Serving the frontend from %s", STATIC_DIR)
