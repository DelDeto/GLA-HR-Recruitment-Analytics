"""Explicit Meta API historical capture into a hidden, private Sheets staging tab.

Uses existing repository secrets. Does not change META_RAW, mapping, checkpoints,
report inputs, schedules, campaign configuration or payment/bonus records.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import re
from datetime import date, datetime, timedelta
import logging
import math
import os
from zoneinfo import ZoneInfo

from src.meta_sync import (GoogleSheets, MetaClient, RAW_COLS, Settings, SyncError,
                           google_serial, iso_date, normalize_id, parse_accounts,
                           plan_upserts)

TAB = "META_API_HISTORY"
HEADERS = RAW_COLS + ["account_name", "fetched_at_ict"]
SCOPE_HEADERS = ["account_id", "account_name", "from_date", "to_date", "rows",
                 "spend", "currency", "timezone_name", "fetched_at_ict",
                 "source", "status"]
LOGGER = logging.getLogger("gla_meta_history")


def month_windows(begin: date, end: date):
    if begin > end or (end - begin).days > 366:
        raise SyncError("Historical range must be ordered and no longer than 367 days")
    current = begin
    while current <= end:
        last = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
        stop = min(last, end)
        yield current, stop
        current = stop + timedelta(days=1)


def collect(meta, accounts, begin, end, fetched_at):
    """A successful empty month is not a permission error or a fabricated row."""
    windows = list(month_windows(begin, end))
    all_rows, summaries, names, seen = [], [], {}, set()
    for account in accounts:
        info = meta._request(f"act_{account}", {"fields": "id,name,currency,timezone_name"})
        if normalize_id(info.get("id")) != account or not info.get("name"):
            raise SyncError("Meta account metadata did not match requested account")
        if info.get("currency") != "VND":
            raise SyncError("Historical report requires VND; no implicit conversion")
        names[account] = str(info["name"])
        account_rows = []
        for lo, hi in windows:
            rows = meta.insights(account, lo, hi, "VND")
            for row in rows:
                day = date.fromisoformat(iso_date(row[0]))
                if len(row) != 9 or row[8] != account or not lo <= day <= hi:
                    raise SyncError("Historical API row outside requested account/window")
                if any(not math.isfinite(float(row[c])) or float(row[c]) < 0 for c in (3, 4, 5, 6)):
                    raise SyncError("Invalid historical Meta metric")
                key = (row[8], row[0], row[1])
                if key in seen:
                    raise SyncError("Duplicate historical Meta account/date/campaign")
                seen.add(key)
                account_rows.append(row)
        all_rows.extend(account_rows)
        summaries.append([account, names[account], google_serial(begin), google_serial(end),
                          len(account_rows), sum(float(r[3]) for r in account_rows), "VND",
                          str(info.get("timezone_name", "")), fetched_at,
                          "META_MARKETING_API_DIRECT", "COMPLETE" if account_rows else "VERIFIED_NO_ROWS"])
    return sorted(all_rows, key=lambda r: (r[8], r[0], r[1])), summaries, names


def capture(settings, begin, end, expected_sheet, meta=None, sheets=None):
    if settings.spreadsheet_id != expected_sheet:
        raise SyncError("Configured spreadsheet does not match explicitly requested target")
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    if end > today:
        raise SyncError("Historical end date cannot be in the future")
    api = meta or MetaClient(settings.access_token, settings.api_version)
    sheet = sheets or GoogleSheets(settings.google_json, settings.spreadsheet_id)
    props = sheet._request("GET", "", params={"fields": "sheets.properties"})
    existing_sheet = next((s["properties"] for s in props.get("sheets", [])
                           if s["properties"].get("title") == TAB), None)
    stored = []
    scopes = []
    if existing_sheet:
        capacity = existing_sheet["gridProperties"]["rowCount"]
        data = sheet.read(TAB, f"A1:K{capacity}")
        if not data or data[0] != HEADERS:
            raise SyncError("Historical staging headers differ; no writes")
        stored = data[1:]
        scope_data = sheet.read(TAB, "M1:W100")
        if not scope_data or scope_data[0] != SCOPE_HEADERS:
            raise SyncError("Historical coverage headers differ; no writes")
        scopes = scope_data[1:]
    now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M:%S")
    rows, summaries, names = collect(api, settings.accounts, begin, end, now)
    capacity = max(12000, len(stored) + len(rows) + 1000,
                   existing_sheet["gridProperties"]["rowCount"] if existing_sheet else 0)
    proposed, appended = plan_upserts(stored, rows, "", capacity)
    scopes_by_key = {(str(r[0]), iso_date(r[2]), iso_date(r[3])): i + 2
                     for i, r in enumerate(scopes) if len(r) >= 4 and r[0]}
    scope_changes = []
    tail = max(scopes_by_key.values(), default=1)
    for summary in summaries:
        key = (summary[0], begin.isoformat(), end.isoformat())
        physical = scopes_by_key.get(key)
        if physical is None:
            tail += 1
            physical = tail
        if physical > 100:
            raise SyncError("Historical coverage log is full; no writes")
        scope_changes.append((f"'{TAB}'!M{physical}:W{physical}", [summary]))
    result = {"dry_run": settings.dry_run, "accounts": len(settings.accounts),
              "fetched": len(rows), "changed": len(proposed), "appended": appended,
              "required_capacity": capacity, "verified_empty_accounts": sum(s[-1] == "VERIFIED_NO_ROWS" for s in summaries)}
    if settings.dry_run:
        LOGGER.info("Historical preview completed: %s", result)
        return result
    requests = []
    if existing_sheet is None:
        requests.append({"addSheet": {"properties": {"title": TAB, "hidden": True,
                          "gridProperties": {"rowCount": capacity, "columnCount": 23, "frozenRowCount": 1}}}})
    else:
        requests.append({"updateSheetProperties": {"properties": {"sheetId": existing_sheet["sheetId"], "hidden": True,
                          "gridProperties": {"rowCount": capacity, "columnCount": max(23, existing_sheet["gridProperties"]["columnCount"]) }},
                          "fields": "hidden,gridProperties.rowCount,gridProperties.columnCount"}})
    sheet._request("POST", ":batchUpdate", json={"requests": requests})
    sheet.write_ranges([(f"'{TAB}'!A1:K1", [HEADERS]), (f"'{TAB}'!M1:W1", [SCOPE_HEADERS])])
    for offset in range(0, len(proposed), 250):
        chunk = proposed[offset:offset + 250]
        # Bounded batches; raw data committed first, scope marker only at the end.
        changes = [(f"'{TAB}'!A{physical}:K{physical}", [row + [names[str(row[8])], now]])
                   for physical, row in chunk]
        sheet.write_ranges(changes)
    sheet.write_ranges(scope_changes)
    LOGGER.info("Historical capture completed: %s", result)
    return result


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Direct Meta historical capture; existing secrets, private staging only")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--account-hashes", required=True)
    parser.add_argument("--expected-sheet-hash", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.days = 8
    try:
        from dataclasses import replace
        settings = Settings.from_env(args)
        hashes = set(args.account_hashes.split(","))
        if not hashes or any(not re.fullmatch(r"[a-f0-9]{64}", h) for h in hashes):
            raise SyncError("Account selection hashes are invalid")
        accounts = [a for a in settings.accounts if hashlib.sha256(a.encode()).hexdigest() in hashes]
        if len(accounts) != len(hashes):
            raise SyncError("Requested accounts are not all configured in the existing secret")
        if hashlib.sha256(settings.spreadsheet_id.encode()).hexdigest() != args.expected_sheet_hash:
            raise SyncError("Target spreadsheet hash mismatch")
        settings = replace(settings, accounts=accounts)
        capture(settings, date.fromisoformat(args.start_date), date.fromisoformat(args.end_date), settings.spreadsheet_id)
        return 0
    except (SyncError, ValueError):
        # Errors can originate in remote metadata; never echo token-bearing values.
        LOGGER.error("Historical capture failed; check account access, dates, target sheet and staging schema")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
