
# Workflows

The orchestrator supports three main flows:

- Calendar requests: user -> orchestrator -> CalendarBot -> orchestrator -> user.
- Weather requests: user -> orchestrator -> WeatherBot -> orchestrator -> user.
- Weather-aware scheduling: orchestrator combines WeatherBot, CalendarBot, and SlotMatcherBot.
