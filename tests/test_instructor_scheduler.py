from datetime import datetime, timezone

from modules.instructor.scheduler import _candidate_slots


def _profile(**overrides):
    values = {
        "timezone": "Asia/Seoul",
        "weekdays_json": [0, 1, 2, 3, 4, 5, 6],
        "publish_hour": 0,
        "publish_minute": 0,
        "lead_hours": 24,
        "semester_start_date": "2026-09-01",
        "semester_weeks": 15,
    }
    values.update(overrides)
    return values


def test_midnight_publish_hour_is_preserved(monkeypatch):
    monkeypatch.setenv("AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES", "0")
    now = datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc)  # 23:00 KST
    slots = _candidate_slots(_profile(), now)
    assert slots
    local = slots[0][0]
    assert local.hour == 0


def test_recent_missed_slot_is_caught_up(monkeypatch):
    monkeypatch.setenv("AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES", "120")
    # 2026-09-28 18:30 KST: the 18:00 slot is 30 minutes late and should be recovered.
    now = datetime(2026, 9, 28, 9, 30, tzinfo=timezone.utc)
    slots = _candidate_slots(_profile(publish_hour=18), now)
    assert any(
        slot.hour == 18 and slot.minute == 0 and slot.date().isoformat() == "2026-09-28"
        for slot, _ in slots
    )
