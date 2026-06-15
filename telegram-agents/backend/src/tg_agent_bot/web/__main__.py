from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "tg_agent_bot.web.server:app",
        host=os.getenv("WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("WEB_PORT", "8000")),
        reload=os.getenv("WEB_RELOAD", "0") == "1",
    )


if __name__ == "__main__":
    main()
