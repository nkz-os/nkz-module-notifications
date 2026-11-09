"""Weekly report scheduling: pure decision, timezone, ISO week, runner."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.digest.weekly import schedule
from app.digest.weekly.schedule import Action, decide, iso_week, pick_timezone

MAD = ZoneInfo("Europe/Madrid")
MON = date(2026, 11, 9)  # a Monday


def at(h, m=0, d=MON, tz=MAD):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=tz)


def d(local_now, status=None, delivered=False, build=None):
    return decide(local_now=local_now, status=status, delivered=delivered, build_status=build)


# ---- decide: one test per row of the table ----

def test_not_monday_nothing():
    assert d(at(10, d=date(2026, 11, 10)), build="complete") is Action.NOTHING
    assert d(at(10, d=date(2026, 11, 8)), build="complete") is Action.NOTHING


def test_before_seven_nothing():
    assert d(at(6, 59), build="complete") is Action.NOTHING


def test_miss_after_20_undelivered():
    assert d(at(20), build="complete") is Action.MISS
    assert d(at(23, 50), build=None) is Action.MISS


def test_after_20_delivered_nothing():
    assert d(at(20), status="complete", delivered=True, build="complete") is Action.NOTHING


def test_complete_sends():
    assert d(at(7), build="complete") is Action.SEND


def test_no_sources_saves_only():
    assert d(at(8), build="no_sources") is Action.SAVE_ONLY


def test_all_failed_waits():
    assert d(at(8), build="all_failed") is Action.WAIT
    assert d(at(15), build="all_failed") is Action.WAIT


def test_partial_before_nine_waits():
    assert d(at(8, 59), build="partial") is Action.WAIT


def test_partial_from_nine_sends():
    assert d(at(9), build="partial") is Action.SEND


def test_delivered_partial_now_complete_refreshes():
    assert d(at(12), status="partial", delivered=True, build="complete") is Action.REFRESH


def test_delivered_partial_still_partial_nothing():
    assert d(at(12), status="partial", delivered=True, build="partial") is Action.NOTHING


def test_delivered_complete_nothing_without_rebuild():
    assert d(at(12), status="complete", delivered=True, build=None) is Action.NOTHING
    assert d(at(12), status="complete", delivered=True, build="complete") is Action.NOTHING


def test_stored_no_sources_not_rebuilt():
    assert d(at(12), status="no_sources", build=None) is Action.NOTHING
    assert d(at(12), status="no_sources", build="complete") is Action.NOTHING


def test_stored_missed_nothing():
    assert d(at(21), status="missed") is Action.NOTHING


def test_unbuilt_in_window_asks_for_build():
    assert d(at(8), build=None) is Action.WAIT


def test_tuesday_never_sends():
    tue = date(2026, 11, 10)
    for h in (0, 7, 9, 12, 19, 20, 23):
        for build in (None, "complete", "partial", "no_sources", "all_failed"):
            assert d(at(h, d=tue), build=build) is Action.NOTHING


def test_dst_day():
    # Monday after the autumn change in Madrid (2026-10-25): UTC+1 from then on.
    mon = date(2026, 10, 26)
    assert d(at(6, 59, d=mon), build="complete") is Action.NOTHING
    assert d(at(7, 0, d=mon), build="complete") is Action.SEND
    # same through the instant -> local conversion
    assert datetime(2026, 10, 26, 5, 59, tzinfo=timezone.utc).astimezone(MAD).hour == 6
    assert datetime(2026, 10, 26, 6, 0, tzinfo=timezone.utc).astimezone(MAD).hour == 7


# ---- iso_week / pick_timezone ----

def test_iso_week_year_boundary():
    assert iso_week(date(2026, 12, 28)) == "2026-W53"
    assert iso_week(date(2027, 1, 4)) == "2027-W01"


def test_pick_timezone_most_frequent():
    z = pick_timezone(["Europe/Madrid", "Atlantic/Canary", "Atlantic/Canary"], "UTC")
    assert z == ZoneInfo("Atlantic/Canary")


def test_tie_alphabetical():
    z = pick_timezone(["Europe/Madrid", "Atlantic/Canary"], "UTC")
    assert z == ZoneInfo("Atlantic/Canary")


def test_invalid_zone_ignored():
    z = pick_timezone(["Mars/Olympus", "", "Europe/Madrid", "../etc"], "UTC")
    assert z == MAD


def test_none_uses_default():
    assert pick_timezone([], "Europe/Madrid") == MAD
    assert pick_timezone([], "garbage") == ZoneInfo("UTC")


def test_scan_window():
    u = lambda dd, h: datetime(2026, 11, dd, h, tzinfo=timezone.utc)  # 8 Nov = Sunday
    assert not schedule.in_scan_window(u(8, 9))
    assert schedule.in_scan_window(u(8, 17))
    assert schedule.in_scan_window(u(9, 12))
    assert schedule.in_scan_window(u(10, 7))
    assert not schedule.in_scan_window(u(10, 9))
    assert not schedule.in_scan_window(u(12, 12))


# ---- runner ----

T, T2 = "tenant-a", "tenant-b"
MON_UTC = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)  # 09:00 Madrid


class World:
    def __init__(self, monkeypatch, enabled=True):
        from app.config import get_settings

        self.saved, self.delivered, self.missed, self.calls = [], [], [], []
        self.row = {}
        self.sent = set()
        self.build_status = "complete"
        self.deliver_result = True
        self.deliver_raises = False
        self.tz_fail = set()
        self.gather_fail = set()
        s = get_settings()
        monkeypatch.setattr(s, "weekly_report_enabled", enabled)
        monkeypatch.setattr(s, "weekly_report_default_tz", "Europe/Madrid")
        sm = schedule
        monkeypatch.setattr(sm.sources, "parcel_timezones", self._tz)
        monkeypatch.setattr(sm.sources, "gather", self._gather)
        monkeypatch.setattr(sm.compose, "build", self._build)
        monkeypatch.setattr(sm.store, "get_report", lambda t: self.row.get(t))
        monkeypatch.setattr(sm.store, "save_report", lambda *a: self.saved.append(a))
        monkeypatch.setattr(sm.store, "mark_delivered", lambda t, w: self.delivered.append((t, w)))
        monkeypatch.setattr(sm.store, "has_sent_delivery", lambda t, w: (t, w) in self.sent)
        monkeypatch.setattr(sm.store, "mark_missed", lambda *a: self.missed.append(a))
        monkeypatch.setattr(sm.deliver, "deliver", self._deliver)
        monkeypatch.setattr(sm, "active_tenants", lambda: [T, T2])

    def _tz(self, t):
        self.calls.append(("tz", t))
        if t in self.tz_fail:
            raise RuntimeError("orion down")
        return ["Europe/Madrid"]

    def _gather(self, t, ws):
        self.calls.append(("gather", t))
        if t in self.gather_fail:
            raise RuntimeError("boom")
        return object()

    def _build(self, g, ws, iw):
        return {"status": self.build_status, "iso_week": iw, "week_start": ws.isoformat(), "tasks": []}

    def _deliver(self, t, report, **kw):
        self.calls.append(("deliver", t, kw))
        if self.deliver_raises:
            raise RuntimeError("smtp")
        return self.deliver_result


@pytest.fixture()
def world(monkeypatch):
    return World(monkeypatch)


def test_complete_report_saved_then_delivered(world):
    out = schedule.run_tenant(T, now=MON_UTC)
    assert out["action"] == "SEND"
    assert len(world.saved) == 1 and world.saved[0][:3] == (T, "2026-W46", date(2026, 11, 9))
    assert ("deliver", T, {"include_zulip": True}) in world.calls
    assert world.delivered == [(T, "2026-W46")]


def test_failed_delivery_not_marked_delivered(world):
    world.deliver_result = False
    schedule.run_tenant(T, now=MON_UTC)
    assert world.delivered == []


def test_saved_before_delivery(world):
    world.deliver_raises = True
    out = schedule.run_tenant(T, now=MON_UTC)
    assert len(world.saved) == 1
    assert world.delivered == []
    assert out["action"] == "SEND" and out["delivered"] is False


def test_orion_down_for_tz_skips_tenant(world):
    world.tz_fail = {T}
    out = schedule.run_once(MON_UTC)
    assert out[T]["action"] == "SKIP"
    assert out[T2]["action"] == "SEND"


def test_one_tenant_failure_does_not_stop_others(world):
    world.gather_fail = {T}
    out = schedule.run_once(MON_UTC)
    assert out[T]["action"] == "ERROR"
    assert out[T2]["action"] == "SEND"


def test_disabled_flag_does_nothing(monkeypatch):
    w = World(monkeypatch, enabled=False)
    assert schedule.run_once(MON_UTC) == {}
    assert w.calls == [] and w.saved == []


def test_outside_window_no_orion_calls(world):
    wed = datetime(2026, 11, 11, 8, tzinfo=timezone.utc)
    assert schedule.run_once(wed) == {}
    assert world.calls == []


def test_finished_tenant_skipped_without_io(world):
    world.row[T] = {"iso_week": "2026-W46", "week_start": date(2026, 11, 9), "status": "complete",
                    "delivered_at": datetime(2026, 11, 9, 6, tzinfo=timezone.utc), "content": {}}
    out = schedule.run_once(MON_UTC)
    assert out[T]["action"] == "NOTHING"
    assert ("tz", T) not in world.calls


def test_tuesday_run_tenant_sends_nothing(world):
    tue = datetime(2026, 11, 10, 8, tzinfo=timezone.utc)
    out = schedule.run_tenant(T, now=tue)
    assert out["action"] == "NOTHING"
    assert world.saved == [] and not any(c[0] == "deliver" for c in world.calls)


def test_dst_monday_via_run_tenant(world):
    before = datetime(2026, 10, 26, 5, 59, tzinfo=timezone.utc)  # 06:59 Madrid
    at7 = datetime(2026, 10, 26, 6, 0, tzinfo=timezone.utc)  # 07:00 Madrid
    assert schedule.run_tenant(T, now=before)["action"] == "NOTHING"
    assert schedule.run_tenant(T, now=at7)["action"] == "SEND"


def test_partial_before_nine_not_saved(world):
    world.build_status = "partial"
    out = schedule.run_tenant(T, now=datetime(2026, 11, 9, 7, 30, tzinfo=timezone.utc))  # 08:30
    assert out["action"] == "WAIT" and world.saved == []


def test_no_sources_saved_not_delivered(world):
    world.build_status = "no_sources"
    out = schedule.run_tenant(T, now=MON_UTC)
    assert out["action"] == "SAVE_ONLY" and len(world.saved) == 1
    assert not any(c[0] == "deliver" for c in world.calls)


def test_refresh_saves_without_delivering(world):
    world.row[T] = {"iso_week": "2026-W46", "week_start": date(2026, 11, 9), "status": "partial",
                    "delivered_at": datetime(2026, 11, 9, 8, tzinfo=timezone.utc), "content": {}}
    out = schedule.run_tenant(T, now=datetime(2026, 11, 9, 11, tzinfo=timezone.utc))
    assert out["action"] == "REFRESH" and len(world.saved) == 1
    assert not any(c[0] == "deliver" for c in world.calls)


def test_after_20_sent_to_someone_marks_delivered_not_miss(world):
    world.row[T] = {"iso_week": "2026-W46", "week_start": date(2026, 11, 9), "status": "complete",
                    "delivered_at": None, "content": {}}
    world.sent.add((T, "2026-W46"))
    out = schedule.run_tenant(T, now=datetime(2026, 11, 9, 19, 30, tzinfo=timezone.utc))  # 20:30
    assert out["action"] == "NOTHING"
    assert world.delivered == [(T, "2026-W46")] and world.missed == []


def test_after_20_nothing_sent_is_miss(world):
    out = schedule.run_tenant(T, now=datetime(2026, 11, 9, 19, 30, tzinfo=timezone.utc))
    assert out["action"] == "MISS"
    assert world.missed == [(T, "2026-W46", date(2026, 11, 9))]
    assert not any(c[0] == "gather" for c in world.calls)


def test_dry_run_no_writes_no_sends(world):
    out = schedule.run_tenant(T, now=datetime(2026, 11, 11, 8, tzinfo=timezone.utc), dry_run=True)  # Wednesday
    assert out["report"]["status"] == "complete" and out["report"]["iso_week"] == "2026-W46"
    assert world.saved == [] and world.delivered == [] and world.missed == []
    assert not any(c[0] == "deliver" for c in world.calls)


def test_manual_send_saves_delivers_one_user_never_marks(world):
    out = schedule.run_manual(T, now=datetime(2026, 11, 11, 8, tzinfo=timezone.utc), only_user_id="u1", include_zulip=True)
    assert out["sent"] is True and len(world.saved) == 1
    assert ("deliver", T, {"only_user_id": "u1", "include_zulip": True}) in world.calls
    assert world.delivered == []


def test_manual_send_skips_when_nothing_to_say(world):
    world.build_status = "all_failed"
    out = schedule.run_manual(T, now=MON_UTC, only_user_id="u1")
    assert out["sent"] is False and world.saved == []


def test_scheduler_survives_exceptions(monkeypatch, world):
    import asyncio

    n = {"c": 0}

    def boom(now):
        n["c"] += 1
        raise RuntimeError("x")

    monkeypatch.setattr(schedule, "run_once", boom)
    monkeypatch.setattr(schedule, "INTERVAL_S", 0)

    async def go():
        task = asyncio.create_task(schedule.run_weekly_scheduler())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert n["c"] >= 2


def test_saved_report_carries_time_zone(world):
    schedule.run_tenant(T, now=MON_UTC)
    assert world.saved[0][4]["time_zone"] == "Europe/Madrid"


def test_scheduler_logs_only_exception_type(monkeypatch, world, caplog):
    import asyncio
    import logging

    def boom(now):
        raise RuntimeError("secret-detail user@example.org")

    monkeypatch.setattr(schedule, "run_once", boom)
    monkeypatch.setattr(schedule, "INTERVAL_S", 0)

    async def go():
        task = asyncio.create_task(schedule.run_weekly_scheduler())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with caplog.at_level(logging.ERROR):
        asyncio.run(go())
    assert "RuntimeError" in caplog.text
    assert "secret-detail" not in caplog.text and "user@example.org" not in caplog.text
