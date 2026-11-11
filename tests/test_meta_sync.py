from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from argparse import Namespace
from dataclasses import replace

import pytest

from src.meta_sync import (
    GoogleSheets, MetaClient, Settings, SyncError,
    campaign_updates, google_serial, group_changes, iso_date,
    normalize_id, parse_accounts, parse_meta_leads, parse_meta_result,
    plan_upserts, record_key, sync, account_signature, successful_dates,
    health_target_row, lookback_days, HEALTH_COLS,
)


DEFAULT_ACCOUNT = "999001"  # fake ID for isolated unit tests

def test_excel_date_roundtrip():
    assert google_serial(date(2026, 11, 11)) == 46337
    assert iso_date(google_serial(date(2026, 11, 11))) == "2026-11-11"
    assert iso_date("11/11/2026") == "2026-11-11"
    assert iso_date("2026-11-11") == "2026-11-11"


def test_account_ids_unique_and_numeric():
    assert parse_accounts("act_123,123,456") == ["123", "456"]
    with pytest.raises(SyncError):
        normalize_id("aaa")
    with pytest.raises(SyncError, match="No Meta ad account"):
        parse_accounts(None)


def test_meta_actions_are_not_double_counted():
    records = [
        {"action_type": "lead", "value": "8"},
        {"action_type": "onsite_conversion.lead_grouped", "value": "6"},
    ]
    assert parse_meta_leads(records) == 8
    assert parse_meta_leads([{"action_type": "onsite_conversion.lead_grouped", "value": "5"}]) == 5
    assert parse_meta_leads(None) == 0


def test_meta_result_columns_and_currency():
    row = parse_meta_result("123", "VND", {
        "date_start": "2026-11-11", "campaign_id": "120253361557590202", "campaign_name": "Pegatron",
        "spend": "1234.56", "impressions": "340", "clicks": "9", "actions": [{"action_type":"lead","value":"2"}],
    })
    assert row == [46337, "120253361557590202", "Pegatron", 1234.56, 340, 9, 2, "VND", "123"]


def test_upsert_existing_and_append_other_account_without_duplicate():
    old = [[46337, "120253361557590202", "Pegatron", 100, 100, 1, 0, "VND", DEFAULT_ACCOUNT]]
    updated = [46337, "120253361557590202", "Pegatron", 200, 100, 2, 1, "VND", DEFAULT_ACCOUNT]
    second = [46337, "120253361557590202", "Pegatron", 999, 500, 5, 1, "VND", "123"]
    changes, appended = plan_upserts(old, [updated, second], DEFAULT_ACCOUNT, 1600)
    assert changes == [(2, updated), (3, second)]
    assert appended == 1


def test_duplicate_historical_rows_fail_closed():
    old = [[46337, "123", "A", 10, 20, 1, 0, "VND"],
           [46337, "123", "A", 10, 20, 1, 0, "VND"]]
    with pytest.raises(SyncError, match="Duplicate existing"):
        plan_upserts(old, [], DEFAULT_ACCOUNT, 1600)


def test_max_cap_prevents_any_data_write():
    raw = [[46337, "123", "A", 10, 20, 1, 0, "VND"]]
    fresh = [46338, "124", "B", 10, 20, 1, 0, "VND", DEFAULT_ACCOUNT]
    with pytest.raises(SyncError, match="capacity exceeded"):
        plan_upserts(raw, [fresh], DEFAULT_ACCOUNT, 2)


def test_group_changes_nonadjacent():
    planned = [(2, [1]), (3,[2]), (7,[3])]
    assert group_changes(planned, "META_RAW") == [
        ("'META_RAW'!A2:I3", [[1],[2]]),
        ("'META_RAW'!A7:I7", [[3]])
    ]


def test_new_campaign_keeps_campaign_id_as_text():
    now = [[46337, "120253361557590202", "Pegatron campaign", 10, 20, 1, 0, "VND", DEFAULT_ACCOUNT],
           [46337, "120253111111111111", "Unknown factory", 10, 20, 1, 0, "VND", DEFAULT_ACCOUNT]]
    changed = campaign_updates([], now, 180)
    assert len(changed) == 1
    a1, rows = changed[0]
    assert a1 == "'CHIEN_DICH_META'!A2:G3"
    for r in rows:
        assert str(r[0]).startswith("'120253")  # preserved text via USER_ENTERED
    assert any(r[2] == "CHƯA GÁN" for r in rows)
    assert any(r[2] == "Pegatron" for r in rows)
    assert all(len(row) == 7 for row in rows)  # Google Sheets owns columns H:J
    assert all("SUMIFS(" in row[3] and "TODAY()-29" in row[3] for row in rows)
    assert all("SUMIFS(" in row[4] and "TODAY()-29" in row[4] for row in rows)
    assert all("META_RAW!$A$2:$A$6000" in row[3] for row in rows)


class FakeMeta:
    def currency(self, account):
        return "VND"
    def insights(self, account, begin, end, currency):
        return [[google_serial(end),"123456789012345678","Pegatron",100.0,10,3,1,"VND",account]]

class FakeSheets:
    def __init__(self):
        self.changes = []
        self.health = [HEALTH_COLS]
    def capacity(self, name):
        return {"META_RAW":(1600,9),"META_ADS_NGAY":(1700,12),
                "CHIEN_DICH_META":(180,7),"META_SYNC_HEALTH":(1200,9)}[name]
    def read(self, tab, a1):
        return {
            "META_RAW": [["date", "campaign_id", "campaign", "spend", "impressions", "clicks", "actions_lead", "account_currency", "ad_account_id"]],
            "CHIEN_DICH_META": [],
            "META_SYNC_HEALTH": self.health,
        }[tab]
    def write_ranges(self, changes, mode="RAW"):
        self.changes.append((mode, changes))


def make_settings(dry_run):
    return Settings("test-token","{}","test-sheet",[DEFAULT_ACCOUNT],"v27.0",8,dry_run)


def test_dry_run_is_read_only():
    sheet=FakeSheets()
    result=sync(make_settings(True),FakeMeta(),sheet)
    assert result["fetched"] == 1
    assert result["appended"] == 1
    assert result["new_campaigns"] == 1
    assert sheet.changes == []


def test_actual_upsert_stays_scoped_to_raw_and_mapping_only():
    sheet=FakeSheets()
    result=sync(make_settings(False),FakeMeta(),sheet)
    assert result["appended"] == 1
    assert len(sheet.changes) == 3
    assert sheet.changes[0][0] == "RAW"
    assert sheet.changes[0][1][0][0] == "'META_RAW'!I1"
    assert sheet.changes[1][0] == "USER_ENTERED"
    assert sheet.changes[1][1][0][0] == "'CHIEN_DICH_META'!A2:G2"
    assert sheet.changes[2][0] == "RAW"
    assert sheet.changes[2][1][0][0] == "'META_SYNC_HEALTH'!A2:I2"
    assert sheet.changes[2][1][0][1][0][3] == "SUCCESS"


def test_api_error_never_includes_secret():
    class Response:
        status_code = 403
        def json(self):
            return {"error":{"code":200,"message":"bad token secretly-your-token"}}
    class HTTP:
        def get(self, *args, **kw): return Response()
    api=MetaClient("secret-token-123","v27.0",session=HTTP())
    with pytest.raises(SyncError) as exc:
        api._request("act_123/insights",{})
    assert "secret-token-123" not in str(exc.value)
    assert "secretly-your-token" not in str(exc.value)


def test_google_sheets_read_uses_valid_encoded_range():
    class Response:
        status_code=200
        def json(self): return {"values": [["date", "campaign_id"]]}
    class Session:
        def __init__(self):self.calls=[]
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return Response()
    h=Session(); sheet=GoogleSheets("{}","test-id",session=h)
    assert sheet.read("META_RAW","A1:I6000") == [["date","campaign_id"]]
    assert h.calls[0][0] == "GET"
    assert "values/%27META_RAW%27%21A1%3AI6000" in h.calls[0][1]
    assert "UNFORMATTED_VALUE" in h.calls[0][2]["params"].values()


def test_no_meta_data_does_not_mutate_sheet():
    class EmptyMeta(FakeMeta):
        def insights(self,*args): return []
    sheet=FakeSheets()
    with pytest.raises(SyncError,match="No Meta insights"):
        sync(make_settings(False),EmptyMeta(),sheet)
    assert sheet.changes == []


def test_view_capacity_guard():
    class LimitedView(FakeSheets):
        def capacity(self,name):
            if name=="META_ADS_NGAY":return (1600,12)
            return super().capacity(name)
    sheet=LimitedView()
    with pytest.raises(SyncError, match="view cannot fit"):
        sync(make_settings(False),FakeMeta(),sheet)
    assert sheet.changes == []


def test_meta_token_only_in_authorization_header():
    class Response:
        status_code = 200
        def json(self): return {"currency": "VND"}
    class HTTP:
        def __init__(self): self.calls = []
        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()
    h = HTTP()
    assert MetaClient("secret-token-123", "v27.0", session=h).currency("123") == "VND"
    url, args = h.calls[0]
    assert "secret-token-123" not in url
    assert "secret-token-123" not in str(args["params"])
    assert args["headers"]["Authorization"] == "Bearer secret-token-123"



def test_account_signature_stable_for_retry_scope():
    assert account_signature(["456", "123", "456"]) == "123,456"


def test_health_success_detected_for_same_accounts_only():
    today = date(2026, 11, 11)
    rows = [HEALTH_COLS,
            [today.isoformat(), "123,456", "2026-11-11 07:15:00", "SUCCESS", 3, 2, 1, 0, "daily"],
            [today.isoformat(), "999", "2026-11-11 07:15:00", "FAILED", 0, 0, 0, 0, "retry"]]
    assert successful_dates(rows, ["456", "123"]) == [today]
    assert successful_dates(rows, ["999"]) == []


def test_health_row_upsert_and_safe_capacity():
    today = date(2026, 11, 11)
    rows = [HEALTH_COLS, [today.isoformat(), "999001", "stamp", "SUCCESS"]]
    assert health_target_row(rows, today, ["999001"], 1200) == 2
    assert health_target_row(rows, today, ["123"], 1200) == 3
    with pytest.raises(SyncError, match="capacity exceeded"):
        health_target_row(rows, today, ["123"], 2)


def test_duplicate_checkpoint_fails_closed():
    today = date(2026, 11, 11)
    rows = [HEALTH_COLS, [today.isoformat(), "999001", "stamp", "SUCCESS"],
            [today.isoformat(), "999001", "stamp", "SUCCESS"]]
    with pytest.raises(SyncError, match="Duplicate"):
        health_target_row(rows, today, ["999001"], 1200)


def test_backfill_expands_for_outage_and_refuses_unbounded_gap():
    today = date(2026, 11, 11)
    assert lookback_days(today, 8, today - timedelta(days=1)) == 8
    assert lookback_days(today, 8, today - timedelta(days=20)) == 21
    assert lookback_days(today, 8, None) == 8
    with pytest.raises(SyncError, match="exceeds 90 days"):
        lookback_days(today, 8, today - timedelta(days=92))


def test_retry_skips_when_today_successful():
    sheet = FakeSheets()
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    sheet.health.append([today.isoformat(), DEFAULT_ACCOUNT, "stamp", "SUCCESS"])
    result = sync(replace(make_settings(False), skip_if_synced=True), FakeMeta(), sheet)
    assert result["skipped"] is True
    assert result["changed"] == 0
    assert sheet.changes == []


def test_gap_backfill_expands_actual_meta_query():
    sheet = FakeSheets()
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    sheet.health.append([(today - timedelta(days=15)).isoformat(), DEFAULT_ACCOUNT, "stamp", "SUCCESS"])
    class TrackingMeta(FakeMeta):
        def insights(self, account, begin, end, currency):
            assert begin == today - timedelta(days=15)
            return super().insights(account, begin, end, currency)
    result = sync(make_settings(True), TrackingMeta(), sheet)
    assert result["fetched"] == 1
    assert sheet.changes == []


def test_failed_meta_does_not_write_checkpoint():
    sheet = FakeSheets()
    class FailedMeta(FakeMeta):
        def insights(self, *args):
            raise SyncError("Temporary Meta failure")
    with pytest.raises(SyncError, match="Temporary"):
        sync(make_settings(False), FailedMeta(), sheet)
    assert sheet.changes == []


def test_health_checkpoint_is_last_write():
    sheet = FakeSheets()
    sync(replace(make_settings(False), run_kind="watchdog"), FakeMeta(), sheet)
    assert len(sheet.changes) == 3
    final = sheet.changes[-1][1][0]
    assert final[0] == "'META_SYNC_HEALTH'!A2:I2"
    assert final[1][0][3] == "SUCCESS"
    assert final[1][0][8] == "watchdog"


def test_bad_health_header_blocks_sheet_writes():
    sheet = FakeSheets()
    sheet.health = [["bad-header"]]
    with pytest.raises(SyncError, match="Unexpected META_SYNC_HEALTH"):
        sync(make_settings(False), FakeMeta(), sheet)
    assert sheet.changes == []


def test_health_capacity_guard_before_data_mutation():
    class FullHealth(FakeSheets):
        def capacity(self, name):
            if name == "META_SYNC_HEALTH":
                return (1, 9)
            return super().capacity(name)
    sheet = FullHealth()
    with pytest.raises(SyncError, match="capacity exceeded"):
        sync(make_settings(False), FakeMeta(), sheet)
    assert sheet.changes == []
