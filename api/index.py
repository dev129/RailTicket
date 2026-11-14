"""Vercel serverless entrypoint.

Vercel's Python runtime serves a module-level ASGI ``app``. We reuse the exact
same FastAPI app as Cloud Run / local — only the hosting wrapper differs.
"""

import os
import sys

# Ensure the repo root (which contains the `railengine` package) is importable
# from inside the bundled /api function.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from railengine.api import app  # noqa: E402  (path set up above)

# Vercel looks for `app`.
__all__ = ["app"]
