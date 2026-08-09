"""Dev entrypoint for Windows.

psycopg's async driver requires a selector event loop; Windows defaults to
ProactorEventLoop, and uvicorn's own loop factory hardcodes Proactor on
win32 regardless of the active policy, so the policy must be set and the
loop left alone (`loop="none"`) before uvicorn creates it.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True, loop="none")
