"""Fail-closed checks for a *future* installed dual-workbook forecast refresh.

These checks never access credentials, worker records, or network services.
The caller must collect source evidence privately and verify native readback.
"""
import re
from datetime import date


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
    try:
        date.fromisoformat(month)
    except ValueError:
        raise UnsafeSyncPlan("Invalid source calendar month") from None
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


def protected_rects(role):
    common = [
        (7000, 0, 1000, 0, 12),       # filters, KPI definitions and navigation
        (7002, 0, 1003, 0, 13),       # entire revenue presentation
        (7002, 0, 13000, 13, 25),     # live cache and selectors
        (7002, 1003, 1200, 5, 10),    # human confirmations F:J
        (7903, 0, 6500, 0, 16),       # all policy inputs including drafts
        (7902, 0, 6500, 0, 16),       # award UI and execution ledger
        (6240, 0, 6500, 0, 12),       # rates, overrides, approvals/transactions
        (7401, 0, 3000, 14, 18),      # legacy approval/payment/status columns
        (7507, 0, 6000, 0, 23),
        (7907, 0, 6500, 0, 22),      # live bonus array, never overwrite its spill
        (7908, 0, 2000, 0, 24),      # program archives and cache headers
        (7908, 5000, 6500, 0, 24),   # only A2001:V5000 is computed cache
        (7304, 3, 1000, 12, 15),      # attendance source-period overrides
        (7502, 3, 20000, 8, 9),       # computed Ads filter flag I
    ]
    if role == 'MASTER_V23':
        common += [(7401, 0, 3000, 0, 22), (7950, 3, 2000, 38, 47), (7950, 3, 51, 48, 56),
                   (7950, 1199, 1343, 48, 54)]
    return common


def request_rect(request):
    """Return the ENTIRE mutated rectangle, fail closed for unsupported requests.

    updateCells.range may clear cells not represented in rows. AutoFill extends
    beyond the source by fillLength. Cosmetic requests are writes too.
    """
    if len(request) != 1:
        raise UnsafeSyncPlan('Exactly one native request type required')
    kind, change = next(iter(request.items()))
    if kind == 'updateCells':
        if not change.get('fields'):
            raise UnsafeSyncPlan('Explicit field mask required')
        if 'range' in change:
            rect = change['range']
        elif 'start' in change:
            start = change['start']; rows = change.get('rows', [])
            rect = dict(start, startRowIndex=start.get('rowIndex', 0),
                        startColumnIndex=start.get('columnIndex', 0))
            rect['endRowIndex'] = rect['startRowIndex'] + len(rows)
            rect['endColumnIndex'] = rect['startColumnIndex'] + max(
                (len(row.get('values', [])) for row in rows), default=0)
        else:
            raise UnsafeSyncPlan('Missing updateCells geometry')
    elif kind == 'autoFill':
        spec = change.get('sourceAndDestination', {})
        rect = dict(spec.get('source', {})); length = spec.get('fillLength')
        if type(length) is not int or length < 0:
            raise UnsafeSyncPlan('Unsupported autofill direction')
        if spec.get('dimension') == 'ROWS':
            rect['endRowIndex'] = rect.get('endRowIndex', 0) + length
        elif spec.get('dimension') == 'COLUMNS':
            rect['endColumnIndex'] = rect.get('endColumnIndex', 0) + length
        else:
            raise UnsafeSyncPlan('Invalid autofill dimension')
    elif kind == 'repeatCell':
        rect = change.get('range', {})
    else:
        raise UnsafeSyncPlan('Unsupported installed mutation: ' + kind)
    keys = ('sheetId', 'startRowIndex', 'endRowIndex', 'startColumnIndex', 'endColumnIndex')
    if any(type(rect.get(k)) is not int for k in keys):
        raise UnsafeSyncPlan('Mutation must have finite explicit bounds')
    sid, r0, r1, c0, c1 = (rect[k] for k in keys)
    if min(sid, r0, c0) < 0 or r1 <= r0 or c1 <= c0:
        raise UnsafeSyncPlan('Invalid mutation bounds')
    return sid, r0, r1, c0, c1


def validate_plan_writes(requests, config):
    if not config.get('installed'):
        return
    if config.get('workbook_role') not in ROLES:
        raise UnsafeSyncPlan('Unknown workbook role')
    for request in requests:
        sid, r0, r1, c0, c1 = request_rect(request)
        for psid, pr0, pr1, pc0, pc1 in protected_rects(config['workbook_role']):
            if sid == psid and r0 < pr1 and r1 > pr0 and c0 < pc1 and c1 > pc0:
                raise UnsafeSyncPlan('Attempted write to protected UX/policy/confirmation range')
