"""Dev entry point. Use this instead of calling uvicorn directly.

Windows defaults to ProactorEventLoop, which psycopg's async mode cannot use. The policy has to
be set before uvicorn constructs its loop, so it cannot live in app/main.py — uvicorn imports
the app from inside an already-running loop. Hence this wrapper.

Linux/macOS default to SelectorEventLoop already, so this is a no-op there and in production.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
