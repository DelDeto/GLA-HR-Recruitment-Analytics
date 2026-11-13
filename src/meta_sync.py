"""GLA HR: read-only Meta Marketing API -> existing GLA Google Sheets V5.0.

API token never written to logs / Sheets / Git. Sheets credentials reside only in
GitHub Actions secrets. The script does not modify ad campaigns or budgets.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

LOGGER = logging.getLogger("gla_meta_sync")
RAW_TAB = "META_RAW"
CAMPAIGN_TAB = "CHIEN_DICH_META"
HEALTH_TAB = "META_SYNC_HEALTH"
HEALTH_COLS = ["run_date_ict","account_ids","finished_at_ict","status","fetched","changed","appended","new_campaigns","run_type"]
RAW_COLS = ["date", "campaign_id", "campaign", "spend", "impressions", "clicks", "actions_lead", "account_currency", "ad_account_id"]
BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"
PERMISSIONS = ["https://www.googleapis.com/auth/spreadsheets"]


class SyncError(RuntimeError):
    """Expected sync failure (no leaked secrets)."""


def google_serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days


def iso_date(raw: object) -> str:
    if raw is None or str(raw) == "":
        raise SyncError("Blank date in META_RAW")
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.replace(".", "", 1).isdigit()):
        return (date(1899, 12, 30) + timedelta(days=int(float(raw)))).isoformat()
    text = str(raw).strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        try:
            return datetime.strptime(text, "%d/%m/%Y").date().isoformat()
        except ValueError as exc:
            raise SyncError("Unsupported date format in META_RAW") from exc


def normalize_id(v: object) -> str:
    val = str(v or "").strip().removeprefix("act_")
    if not re.fullmatch(r"\d+", val):
        raise SyncError("Invalid numeric account/campaign ID")
    return val


def parse_accounts(env: str | None) -> list[str]:
    accounts = [normalize_id(v) for v in (env or "").split(",") if v.strip()]
    if not accounts:
        raise SyncError("No Meta ad account IDs configured")
    return sorted(set(accounts))


def parse_meta_leads(actions: Any) -> int:
    """Prefer Meta's aggregated `lead` action; never sum overlapping action types.

    Other Meta action types can measure different events. A single fallback is
    used only when the aggregate lead action is absent. This is an ad metric,
    not the number of unique contactable candidates.
    """
    if not isinstance(actions, list):
        return 0
    by_type: dict[str, int] = {}
    for entry in actions:
        if not isinstance(entry, dict) or "action_type" not in entry:
            continue
        try:
            by_type[str(entry["action_type"])] = int(float(entry.get("value", 0)))
        except (ValueError, TypeError):
            continue
    for key in ("lead", "onsite_conversion.lead_grouped", "leadgen_grouped", "offsite_conversion.fb_pixel_lead"):
        if key in by_type:
            return max(0, by_type[key])
    return 0


def parse_meta_result(account_id: str, currency: str, r: dict[str, Any]) -> list[object]:
    required = ("date_start", "campaign_id")
    if not all(r.get(k) for k in required):
        raise SyncError("Meta Insights row missing date or campaign ID")
    d = date.fromisoformat(str(r["date_start"])[:10])
    def metric(k: str):
        value = float(r.get(k, 0) or 0)
        if value < 0:
            raise SyncError(f"Unexpected negative {k} from Meta")
        return value if k == "spend" else int(value)
    return [
        google_serial(d), normalize_id(r["campaign_id"]), str(r.get("campaign_name", "")),
        metric("spend"), metric("impressions"), metric("clicks"),
        parse_meta_leads(r.get("actions")), currency, account_id,
    ]


def record_key(row: list[object], default_account: str) -> tuple[str, str, str]:
    if len(row) < 2 or not row[0] or not row[1]:
        raise SyncError("Row missing date or campaign_id")
    account = normalize_id(row[8] if len(row) > 8 and row[8] else default_account)
    return (account, iso_date(row[0]), normalize_id(row[1]))


def plan_upserts(existing: list[list[object]], incoming: list[list[object]], default_account: str,
                 max_row: int) -> tuple[list[tuple[int, list[object]]], int]:
    """Return only the changed physical rows; never clear historical records."""
    index: dict[tuple[str, str, str], int] = {}
    for i, row in enumerate(existing, start=2):
        if not row or not row[0] or not row[1]:
            continue
        key = record_key(row, default_account)
        if key in index:
            raise SyncError(f"Duplicate existing Meta data key at row {i}; manual audit required")
        index[key] = i
    incoming_seen: set[tuple[str, str, str]] = set()
    planned: list[tuple[int, list[object]]] = []
    appended = 0
    tail = max((r for r in index.values()), default=1)
    for row in incoming:
        key = record_key(row, default_account)
        if key in incoming_seen:
            raise SyncError("Duplicate campaign/day/account returned by Meta; refusing to double-count")
        incoming_seen.add(key)
        if key in index:
            physical = index[key]
            old = existing[physical - 2]
            # A:I is the only writable region. Add the original account ID if missing.
            previous = list(old[:9]) + [""] * max(0, 9 - len(old))
            if previous == row:
                continue
        else:
            tail += 1
            physical = tail
            appended += 1
        if physical > max_row:
            raise SyncError(f"META_RAW capacity exceeded at row {physical} (limit {max_row}); no writes made")
        planned.append((physical, row))
    return planned, appended


@dataclass(frozen=True)
class Settings:
    access_token: str
    google_json: str
    spreadsheet_id: str
    accounts: list[str]
    api_version: str
    refresh_days: int
    dry_run: bool
    skip_if_synced: bool = False
    run_kind: str = "manual"

    @classmethod
    def from_env(cls, args: argparse.Namespace) -> "Settings":
        tok = os.environ.get("META_ACCESS_TOKEN", "").strip()
        cred = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if not tok:
            raise SyncError("Missing GitHub secret META_ACCESS_TOKEN")
        if not cred:
            raise SyncError("Missing GitHub secret GOOGLE_SERVICE_ACCOUNT_JSON")
        sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{20,}", sheet_id):
            raise SyncError("Missing or malformed GitHub secret GOOGLE_SHEET_ID")
        api = os.environ.get("META_API_VERSION", "v27.0")
        if not re.fullmatch(r"v\d+\.0", api):
            raise SyncError("Invalid META_API_VERSION")
        days = int(args.days)
        if not 1 <= days <= 90:
            raise SyncError("--days must be between 1 and 90")
        return cls(tok, cred, sheet_id,
                   parse_accounts(os.environ.get("META_AD_ACCOUNT_IDS")), api, days, args.dry_run,
                   getattr(args, "skip_if_synced", False), getattr(args, "run_kind", "manual"))


class MetaClient:
    def __init__(self, token: str, api_version: str, session: requests.Session | None = None):
        self.token = token
        self.api_version = api_version
        self.http = session or requests.Session()

    def _request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"https://graph.facebook.com/{self.api_version}/{endpoint.lstrip('/')}"
        params = dict(params)
        # Keep the access token out of query strings, server URLs and error logs.
        headers = {"Authorization": f"Bearer {self.token}"}
        for attempt in range(5):
            try:
                resp = self.http.get(url, params=params, headers=headers, timeout=60)
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise SyncError(f"Meta API returned invalid JSON (HTTP {resp.status_code})") from exc
                if not isinstance(payload, dict):
                    raise SyncError("Meta returned unexpected response")
                err = payload.get("error")
                if err:
                    code = int(err.get("code", 0))
                    if (resp.status_code in (429, 500, 502, 503, 504) or code in (4, 17, 32, 613)) and attempt < 4:
                        time.sleep(min(2 ** attempt, 12))
                        continue
                    # Do not print request URLs because Meta pagination may embed access token.
                    raise SyncError(f"Meta API error (code {code}, HTTP {resp.status_code}); check token and asset permissions")
                if resp.status_code >= 400:
                    raise SyncError(f"Meta API HTTP {resp.status_code}; check permissions or API availability")
                return payload
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == 4:
                    raise SyncError("Meta API network unavailable after retries") from exc
                time.sleep(min(2 ** attempt, 12))
            except requests.RequestException as exc:
                raise SyncError("Meta API request failed; check connectivity and permissions") from exc
        raise SyncError("Meta API retry limit exceeded")

    def currency(self, account: str) -> str:
        result = self._request(f"act_{account}", {"fields": "currency"})
        currency = str(result.get("currency", ""))
        if currency != "VND":
            raise SyncError(f"Account {account} reports currency {currency!r}; current dashboard expects VND")
        return currency

    def insights(self, account: str, begin: date, end: date, currency: str) -> list[list[object]]:
        endpoint = f"act_{account}/insights"
        params: dict[str, Any] = {
            "fields": "date_start,campaign_id,campaign_name,spend,impressions,clicks,actions",
            "level": "campaign", "time_increment": 1, "limit": 500,
            "time_range": json.dumps({"since": begin.isoformat(), "until": end.isoformat()}),
        }
        collected: list[list[object]] = []
        seen_pages: set[str] = set()
        for _page in range(50):
            result = self._request(endpoint, params)
            if not isinstance(result.get("data"), list):
                raise SyncError("Meta Insights response missing data array; no writes made")
            collected.extend(parse_meta_result(account, currency, r) for r in result.get("data", []))
            paging = result.get("paging") or {}
            cursor = (paging.get("cursors") or {}).get("after")
            if not paging.get("next"):
                return collected
            if not cursor or cursor in seen_pages:
                raise SyncError("Invalid Meta cursor pagination; no writes made")
            seen_pages.add(cursor)
            params["after"] = cursor
        raise SyncError("Meta Insights exceeded 50 pages; no writes made")


class GoogleSheets:
    def __init__(self, credentials_json: str, spreadsheet_id: str, session=None):
        self.id = spreadsheet_id
        if session is not None:
            self.http = session
        else:
            try:
                # Lazy imports keep pure unit tests runnable without Google credentials.
                from google.auth.transport.requests import AuthorizedSession
                from google.oauth2.service_account import Credentials
                info = json.loads(credentials_json)
                credential = Credentials.from_service_account_info(info, scopes=PERMISSIONS)
            except (ValueError, KeyError, TypeError, ImportError) as exc:
                raise SyncError("Invalid or unavailable Google service-account credentials") from exc
            self.http = AuthorizedSession(credential)

    def _request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        suffix = endpoint if endpoint.startswith(":") else f"/{endpoint.lstrip('/')}" if endpoint else ""
        url = f"{BASE_URL}/{self.id}" + suffix
        try:
            response = self.http.request(method, url, timeout=90, **kwargs)
        except requests.RequestException as exc:
            raise SyncError("Google Sheets API request failed; check connectivity and permissions") from exc
        if response.status_code >= 400:
            raise SyncError(f"Google Sheets API HTTP {response.status_code}; check share permission, scopes, tab names and API activation")
        return response.json()

    def read(self, tab: str, a1_range: str) -> list[list[object]]:
        params = {"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"}
        result = self._request("GET", "values/" + quote(f"'{tab}'!{a1_range}", safe=""), params=params)
        return result.get("values", [])

    def write_ranges(self, changes: list[tuple[str, list[list[object]]]], mode: str = "RAW") -> None:
        if not changes:
            return
        data = [{"range": range_, "values": values} for range_, values in changes]
        # One values.batchUpdate call; no clearing, upsert only.
        self._request("POST", "values:batchUpdate", json={"valueInputOption": mode, "data": data})

    def capacity(self, sheet_name: str) -> tuple[int, int]:
        props = self._request("GET", "", params={"fields": "sheets.properties", "includeGridData": "false"})
        for sh in props.get("sheets", []):
            p = sh.get("properties", {})
            if p.get("title") == sheet_name:
                g = p.get("gridProperties", {})
                return int(g.get("rowCount", 0)), int(g.get("columnCount", 0))
        raise SyncError(f"Required tab {sheet_name} not present")


def group_changes(planned: list[tuple[int, list[object]]], tab: str) -> list[tuple[str, list[list[object]]]]:
    """Consecutive physical rows are grouped to minimize API request size."""
    if not planned:
        return []
    changes: list[tuple[str, list[list[object]]]] = []
    ordered = sorted(planned, key=lambda x: x[0])
    start = last = ordered[0][0]
    chunk = [ordered[0][1]]
    for index, row in ordered[1:]:
        if index == last + 1:
            chunk.append(row)
        else:
            changes.append((f"'{tab}'!A{start}:I{last}", chunk))
            start, chunk = index, [row]
        last = index
    changes.append((f"'{tab}'!A{start}:I{last}", chunk))
    return changes


def campaign_updates(existing: list[list[object]], incoming: list[list[object]], max_row: int) -> list[tuple[str, list[list[object]]]]:
    """Only append newly discovered campaigns, with default UNMAPPED status."""
    known = {normalize_id(r[0]) for r in existing if r and r[0] and str(r[0]).strip().isdigit()}
    new: dict[str, str] = {}
    for row in incoming:
        ident = str(row[1])
        if ident not in known:
            new[ident] = str(row[2])
    if not new:
        return []
    last = max((i for i, r in enumerate(existing, start=2) if r and r[0]), default=1)
    if last + len(new) > max_row:
        raise SyncError("CHIEN_DICH_META is full; no writes made")
    # Update A:G only. Columns H:J are controlled by native Google Sheets
    # automatic recruitment-type classification + manual correction.
    batch=[]
    for i,(id_,name) in enumerate(sorted(new.items()), start=last+1):
        # Mapping intentionally does not silently auto-assign an ambiguous factory.
        factory = "Pegatron" if re.search(r"\bpegatron\b", name, re.I) else "CHƯA GÁN"
        batch.append(["'" + id_, name, factory,
                      f'=SUMIFS(META_RAW!$D$2:$D$6000,META_RAW!$B$2:$B$6000,A{i},META_RAW!$A$2:$A$6000,">="&TODAY()-29,META_RAW!$A$2:$A$6000,"<="&TODAY())',
                      f'=SUMIFS(META_RAW!$G$2:$G$6000,META_RAW!$B$2:$B$6000,A{i},META_RAW!$A$2:$A$6000,">="&TODAY()-29,META_RAW!$A$2:$A$6000,"<="&TODAY())',
                      "RÕ" if factory=="Pegatron" else "CẦN XÁC MINH",
                      "Meta API discovered; review factory mapping before attributing cost"])
    return [(f"'{CAMPAIGN_TAB}'!A{last+1}:G{last+len(batch)}",batch)]



def account_signature(accounts: list[str]) -> str:
    """Stable grouping; account identifiers are only stored privately in Sheets."""
    return ",".join(sorted(set(accounts)))


def successful_dates(health_rows: list[list[object]], accounts: list[str]) -> list[date]:
    """Only fully completed writes count as healthy. Missing/invalid dates fail closed."""
    signature = account_signature(accounts)
    found: list[date] = []
    for row in health_rows[1:]:
        if len(row) < 4 or str(row[1]) != signature or str(row[3]) != "SUCCESS":
            continue
        try:
            found.append(date.fromisoformat(str(row[0])[:10]))
        except ValueError as exc:
            raise SyncError("Invalid date in META_SYNC_HEALTH status log") from exc
    return found


def health_target_row(health_rows: list[list[object]], on_date: date,
                      accounts: list[str], max_row: int) -> int:
    """Find today's status row or an unused row; never overwrite a different day/account."""
    signature = account_signature(accounts)
    tail = 1
    matching: list[int] = []
    for physical, row in enumerate(health_rows[1:], start=2):
        if not row or not row[0]:
            continue
        tail = max(tail, physical)
        if str(row[0])[:10] == on_date.isoformat() and len(row) >= 2 and str(row[1]) == signature:
            matching.append(physical)
    if len(matching) > 1:
        raise SyncError("Duplicate META_SYNC_HEALTH status keys; manual audit needed")
    target = matching[0] if matching else tail + 1
    if target > max_row:
        raise SyncError("META_SYNC_HEALTH capacity exceeded; no data writes made")
    return target


def lookback_days(today: date, base_days: int, latest_success: date | None) -> int:
    """Catch up after downtime, but never silently truncate a >90-day gap."""
    required = base_days if latest_success is None else max(base_days, (today - latest_success).days + 1)
    if required > 90:
        raise SyncError("Synchronization gap exceeds 90 days; guided historical backfill required")
    return required


def sync(settings: Settings, meta: MetaClient | None = None, sheets: GoogleSheets | None = None) -> dict[str, Any]:
    api = meta or MetaClient(settings.access_token, settings.api_version)
    sheet = sheets or GoogleSheets(settings.google_json, settings.spreadsheet_id)
    rows_max, cols = sheet.capacity(RAW_TAB)
    if cols < 9:
        raise SyncError("META_RAW must have column I = ad_account_id; see bootstrap steps")
    view_max,_ = sheet.capacity("META_ADS_NGAY")
    if view_max < rows_max + 2:
        raise SyncError("META_ADS_NGAY view cannot fit all META_RAW rows; sync blocked")
    raw = sheet.read(RAW_TAB, f"A1:I{rows_max}")
    if not raw or raw[0][:9] != RAW_COLS:
        raise SyncError("Unexpected META_RAW headers; refusing overwrite")
    stored = raw[1:]
    if len(settings.accounts) > 1 and any(r and r[0] and r[1] and (len(r) < 9 or not r[8]) for r in stored):
        raise SyncError("Legacy META_RAW rows without account_id; multi-account sync blocked")
    campaigns_max, _ = sheet.capacity(CAMPAIGN_TAB)
    mapped = sheet.read(CAMPAIGN_TAB, f"A2:G{campaigns_max}")
    health_max, health_cols = sheet.capacity(HEALTH_TAB)
    if health_cols < len(HEALTH_COLS):
        raise SyncError("META_SYNC_HEALTH needs 9 columns")
    health = sheet.read(HEALTH_TAB, f"A1:I{health_max}")
    if not health or health[0][:len(HEALTH_COLS)] != HEALTH_COLS:
        raise SyncError("Unexpected META_SYNC_HEALTH headers; refusing to write")
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    successes = successful_dates(health, settings.accounts)
    if settings.skip_if_synced and today in successes:
        result = {"dry_run": settings.dry_run, "skipped": True, "fetched": 0, "changed": 0,
                  "appended": 0, "new_campaigns": 0, "reason": "Already synced today"}
        LOGGER.info("Recovery not required; today's successful checkpoint exists")
        return result
    previous = max((d for d in successes if d < today), default=None)
    effective_days = lookback_days(today, settings.refresh_days, previous)
    begin = today - timedelta(days=effective_days - 1)
    status_target = health_target_row(health, today, settings.accounts, health_max)
    LOGGER.info("Meta scan window: %d days (rolling backfill enabled)", effective_days)
    fresh: list[list[object]] = []
    for account in settings.accounts:
        currency = api.currency(account)
        downloaded = api.insights(account, begin, today, currency)
        if not downloaded:
            # An inactive account must not stop other configured accounts. A
            # disappearing previously stored positive window still fails closed.
            if any(r and len(r) >= 9 and str(r[8]) == account
                   and begin.isoformat() <= iso_date(r[0]) <= today.isoformat()
                   and float(r[3] or 0) > 0 for r in stored):
                raise SyncError("Meta returned no insights for a previously positive account window")
            LOGGER.info("Configured account has a verified empty scan window; continuing")
            continue
        fresh.extend(downloaded)
    if not fresh:
        raise SyncError("No Meta insights across configured accounts; no writes made")
    # Legacy rows without account_id can be resolved only when one account is configured.
    default_account = settings.accounts[0] if len(settings.accounts) == 1 else ""
    proposed, appended = plan_upserts(stored, fresh, default_account, rows_max)
    camp_changes = campaign_updates(mapped, fresh, campaigns_max)
    if settings.dry_run:
        result = {"dry_run": True, "fetched": len(fresh), "changed": len(proposed),
                  "appended": appended, "new_campaigns": sum(len(rows) for _, rows in camp_changes)}
        LOGGER.info("Dry-run completed: %s", result)
        return result
    changes = group_changes(proposed, RAW_TAB)
    # Header I and changes to two tabs in the same values.batchUpdate call.
    changes.insert(0, (f"'{RAW_TAB}'!I1", [[RAW_COLS[8]]]))
    # RAW writes use RAW valueInputOption; campaign formulas must use USER_ENTERED
    # and therefore are submitted separately after the raw data.
    sheet.write_ranges(changes)
    if camp_changes:
        sheet.write_ranges(camp_changes, mode="USER_ENTERED")
    # This is the commit marker. If any write above fails, no SUCCESS is recorded;
    # the independent retry/watchdog will safely upsert again on a later run.
    finished_at = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M:%S")
    health_record = [today.isoformat(), account_signature(settings.accounts), finished_at,
                     "SUCCESS", len(fresh), len(proposed), appended,
                     sum(len(rows) for _, rows in camp_changes), settings.run_kind]
    sheet.write_ranges([(f"'{HEALTH_TAB}'!A{status_target}:I{status_target}", [health_record])])
    result = {"dry_run": False, "fetched": len(fresh), "changed": len(proposed),
              "appended": appended, "new_campaigns": sum(len(rows) for _, rows in camp_changes)}
    LOGGER.info("Meta sync completed: %s", result)
    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="GLA HR Meta Ads API -> Sheets V5.0")
    parser.add_argument("--days", type=int, default=int(os.environ.get("META_SYNC_DAYS", "8")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-if-synced", action="store_true")
    parser.add_argument("--run-kind", choices=("manual", "daily", "retry", "watchdog"), default="manual")
    args = parser.parse_args()
    try:
        settings = Settings.from_env(args)
        result = sync(settings)
        LOGGER.info("Success: fetched=%s changed=%s", result["fetched"], result["changed"])
        return 0
    except (SyncError, ValueError) as exc:
        LOGGER.error("Sync failed: %s", exc)
        return 1
    except requests.RequestException:
        LOGGER.error("Sync failed: unexpected network error (details suppressed to protect credentials)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
