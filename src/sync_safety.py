"""Fail-closed checks for a *future* installed dual-workbook forecast refresh.

These checks never access credentials, worker records, or network services.
The caller must collect source evidence privately and verify native readback.
"""
import re


class UnsafeSyncPlan(ValueError):
    """The planned write could modify unchecked data or user-owned cells."""


ROLES = {"MASTER_V23", "SEPTEMBER_V22"}


def _source_key(source):
    factory = source.get("factory")
    month = source.get("month")
    if not isinstance(factory, str) or not factory.strip():
        raise UnsafeSyncPlan("Source is missing a canonical factory")
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}-01", month):
        raise UnsafeSyncPlan("Source month must be a YYYY-MM-01 date")
    return factory.strip() + "|" + month[:7]


def validate_installed_preflight(config):
    """Refuse installed writes after incomplete reads or registry reordering.

    existing_registry_keys must come from native DOANH_THU A:B readback,
    in physical row order starting at row 1004, as 'Factory|YYYY-MM'.
    source_coverage must come from the full file AND tab enumeration.
    """
    if not config.get("installed"):
        return
    if config.get("workbook_role") not in ROLES:
        raise UnsafeSyncPlan("Explicit MASTER_V23 or SEPTEMBER_V22 role required")
    if config.get("source_scan_complete") is not True:
        raise UnsafeSyncPlan("Full source scan not verified; keep last good snapshot")
    coverage = config.get("source_coverage")
    if not isinstance(coverage, dict):
        raise UnsafeSyncPlan("Missing independently verified source coverage")
    for kind in ("files", "tabs"):
        listed = coverage.get("listed_" + kind)
        parsed = coverage.get("parsed_" + kind)
        if type(listed) is not int or type(parsed) is not int or listed < 1 or parsed != listed:
            raise UnsafeSyncPlan("Incomplete source " + kind + " coverage")
    if coverage.get("errors") != [] or coverage.get("whitelist_loaded") is not True:
        raise UnsafeSyncPlan("A source error or unverified onboard whitelist blocks refresh")
    if not isinstance(config.get("confirmations"), dict):
        raise UnsafeSyncPlan("Current user confirmations must be read from target")
    if not config.get("original_calendar_formula") or not config.get("original_coverage_formula"):
        raise UnsafeSyncPlan("Archived original formula notes were not read")
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise UnsafeSyncPlan("No source registry provided")
    keys = [_source_key(source) for source in sources]
    if len(keys) != len(set(keys)):
        raise UnsafeSyncPlan("Duplicate factory-month source key")
    for source in sources:
        if source.get("imported") is True and not re.fullmatch(
            r"[0-9a-fA-F]{64}", str(source.get("fingerprint", ""))
        ):
            raise UnsafeSyncPlan("Imported source is missing its SHA256 fingerprint")
    existing = config.get("existing_registry_keys")
    if not isinstance(existing, list) or not existing:
        raise UnsafeSyncPlan("Current physical source registry was not read")
    # An inserted/reordered source would silently attach approvals to the wrong row.
    if len(existing) > len(keys) and any(existing[len(keys):]):
        raise UnsafeSyncPlan("Existing source registry has unaccounted rows")
    for index, key in enumerate(keys):
        old = existing[index] if index < len(existing) else ""
        if old not in ("", key):
            raise UnsafeSyncPlan("Factory-month rows moved; reconcile approvals by key first")


def validate_plan_writes(requests, config):
    """Guard the V2.3 UI, historic trace and F:J confirmation controls."""
    if not config.get("installed"):
        return
    protected = [
        (7002, 4, 5, 1, 2),           # DOANH_THU B5 selector
        (7002, 6, 7, 1, 2),           # DOANH_THU B7 page
        (7002, 14, 16, 0, 12),        # A15:L16 headers and display
        (7002, 14, 13000, 13, 25),   # N15:Y13000 cache
        (7002, 1003, 1200, 5, 10),   # F:J user approvals
        (7903, 0, 2900, 0, 13),      # bonus policy editor
        (7902, 3500, 4500, 0, 12),  # execution ledger
    ]
    if config["workbook_role"] == "MASTER_V23":
        protected += [
            (7950, 3, 51, 48, 56),       # archived AW4:BD51
            (7950, 1199, 1343, 48, 54), # live AW1200:BB1343
        ]
    for request in requests:
        if "addSheet" in request:
            raise UnsafeSyncPlan("Installed refresh must not recreate sheets")
        change = request.get("updateCells", {})
        start = change.get("start")
        if not start or change.get("fields") != "userEnteredValue":
            continue
        sid = start.get("sheetId")
        r0 = start.get("rowIndex", 0)
        c0 = start.get("columnIndex", 0)
        rows = change.get("rows", [])
        r1 = r0 + len(rows)
        c1 = c0 + max((len(row.get("values", [])) for row in rows), default=0)
        for psid, pr0, pr1, pc0, pc1 in protected:
            if sid == psid and r0 < pr1 and r1 > pr0 and c0 < pc1 and c1 > pc0:
                raise UnsafeSyncPlan("Attempted write to protected UX/policy/confirmation range")
