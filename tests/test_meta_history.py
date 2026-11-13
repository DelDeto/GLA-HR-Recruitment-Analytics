from dataclasses import replace
from datetime import date
import pytest
from src.meta_history import capture, collect, month_windows, TAB
from src.meta_sync import SyncError, google_serial, sync
from tests.test_meta_sync import FakeMeta, FakeSheets, make_settings


def test_calendar_month_bounds_and_range_limit():
    assert list(month_windows(date(2026, 1, 15), date(2026, 3, 2))) == [
        (date(2026, 1, 15), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 3, 1), date(2026, 3, 2))]
    with pytest.raises(SyncError):
        list(month_windows(date(2025, 1, 1), date(2026, 3, 1)))


class HistoryMeta(FakeMeta):
    def _request(self, endpoint, params):
        return {"id": endpoint, "name": "Example account", "currency": "VND", "timezone_name": "Asia/Ho_Chi_Minh"}
    def insights(self, account, begin, end, currency):
        if account == "111" or begin.month == 2:
            return []
        return super().insights(account, begin, end, currency)


def test_history_keeps_verified_empty_months_and_accounts_without_fake_rows():
    rows, scopes, names = collect(HistoryMeta(), ["111", "222"], date(2026,1,1), date(2026,3,2), "private timestamp")
    assert len(rows) == 2
    assert scopes[0][-1] == "VERIFIED_NO_ROWS"
    assert scopes[0][4:6] == [0, 0]
    assert scopes[1][4:6] == [2, 200]
    assert all(row[8] == "222" for row in rows)


class HistorySheets:
    def __init__(self):
        self.writes, self.requests = [], []
    def _request(self, method, endpoint, **kwargs):
        if method == "GET": return {"sheets": []}
        self.requests.append((method, endpoint, kwargs))
        return {}
    def write_ranges(self, ranges, mode="RAW"):
        self.writes.extend(ranges)


def test_historical_preview_and_target_guard_do_not_write():
    sheet = HistorySheets()
    result = capture(replace(make_settings(True), accounts=["222"]), date(2026,1,1), date(2026,1,31), "test-sheet", HistoryMeta(), sheet)
    assert result["fetched"] == 1 and not sheet.writes and not sheet.requests
    with pytest.raises(SyncError):
        capture(make_settings(False), date(2026,1,1), date(2026,1,31), "other-sheet", HistoryMeta(), sheet)
    assert not sheet.writes


def test_capture_writes_only_hidden_private_staging_and_commit_marker_last():
    sheet = HistorySheets()
    capture(replace(make_settings(False), accounts=["222"]), date(2026,1,1), date(2026,1,31), "test-sheet", HistoryMeta(), sheet)
    assert sheet.requests[0][1] == ":batchUpdate"
    assert sheet.requests[0][2]["json"]["requests"][0]["addSheet"]["properties"]["hidden"] is True
    assert all(ran.startswith("'" + TAB + "'!") for ran, _ in sheet.writes)
    assert sheet.writes[-1][0].endswith("M2:W2")
    assert sheet.writes[-1][1][0][-1] == "COMPLETE"


def test_inactive_account_does_not_block_other_daily_accounts():
    class Inactive(FakeMeta):
        def insights(self, account, begin, end, currency):
            return [] if account == "111" else super().insights(account, begin, end, currency)
    sheet = FakeSheets()
    result = sync(replace(make_settings(False), accounts=["111", "222"]), Inactive(), sheet)
    assert result["fetched"] == 1
    assert sheet.changes[-1][1][0][1][0][3] == "SUCCESS"


def test_disappearing_positive_account_is_held_without_any_writes():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.meta_sync import RAW_COLS
    class PreviouslyPositive(FakeSheets):
        def read(self, tab, a1):
            if tab == "META_RAW":
                today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
                return [RAW_COLS, [google_serial(today), "123", "example", 10, 1, 1, 0, "VND", "111"]]
            return super().read(tab, a1)
    class Empty(FakeMeta):
        def insights(self, *args): return []
    sheet = PreviouslyPositive()
    with pytest.raises(SyncError, match="previously positive"):
        sync(replace(make_settings(False), accounts=["111", "222"]), Empty(), sheet)
    assert not sheet.changes
