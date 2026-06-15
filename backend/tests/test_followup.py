from __future__ import annotations

from tg_agent_bot.orchestrator.followup import (
    append_pending_followup,
    make_pending_slot,
    pending_prompt_text,
)


def test_pending_followups_are_accumulated_into_one_prompt() -> None:
    pending = make_pending_slot("calendar", "安排一个任务", "缺少日期")

    assert pending_prompt_text(pending) == "安排一个任务"

    assert append_pending_followup(pending, "明天") == "安排一个任务\n用户补充信息：\n- 明天"
    assert append_pending_followup(pending, "一小时") == "安排一个任务\n用户补充信息：\n- 明天\n- 一小时"
    assert pending == {
        "service": "calendar",
        "original_text": "安排一个任务",
        "followups": ["明天", "一小时"],
        "ask_user": "缺少日期",
        "last_user_text": "一小时",
    }
