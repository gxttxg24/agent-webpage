
# Architecture

This refactor keeps the bot small while separating the main responsibilities:

- `app.py` wires settings, persistence, stores, LLM clients, and Telegram handlers.
- `telegram/` contains Telegram commands and message handlers.
- `b2b/` contains the bot-to-bot envelope protocol and dispatcher.
- `orchestrator/` contains planning, summaries, and multi-step workflows.
- `calendar/`, `weather/`, and `slot_matcher/` contain domain services.
