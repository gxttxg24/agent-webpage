
# Bot-to-Bot Protocol

Structured messages use JSON envelopes defined in `src/tg_agent_bot/b2b/protocol.py`.
The dispatcher in `src/tg_agent_bot/b2b/dispatcher.py` routes payloads to calendar,
weather, slot matcher, or orchestrator workflow handlers.
