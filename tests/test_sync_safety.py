import pytest

from src.sync_safety import (
    UnsafeSyncPlan,
    validate_installed_preflight,
    validate_plan_writes,
)


def config():
    return {
        "installed": True,
        "workbook_role": "MASTER_V23",
        "source_scan_complete": True,
        "source_coverage": {
            "listed_files": 6, "parsed_files": 6,
            "listed_tabs": 34, "parsed_tabs": 34,
            "errors": [], "whitelist_loaded": True,
        },
        "confirmations": {"Pegatron|2026-09-01": {"state": "COMPLETE"}},
        "original_calendar_formula": "=1",
        "original_coverage_formula": "=1",
        "sources": [{
            "factory": "Pegatron", "month": "2026-09-01",
            "imported": True, "fingerprint": "a" * 64,
            "evidence": "source", "state": "COMPLETE",
        }],
        "existing_registry_keys": ["Pegatron|2026-09"],
    }


def write(sheet, row, col, width=1):
    return {"updateCells": {
        "start": {"sheetId": sheet, "rowIndex": row - 1, "columnIndex": col - 1},
        "rows": [{"values": [{} for _ in range(width)]}],
        "fields": "userEnteredValue",
    }}


def test_complete_sources_and_preserved_registry():
    validate_installed_preflight(config())


@pytest.mark.parametrize("name, value", [
    ("source_scan_complete", False),
    ("workbook_role", None),
    ("existing_registry_keys", ["USI|2026-09"]),
])
def test_preflight_fails_closed(name, value):
    data = config()
    data[name] = value
    with pytest.raises(UnsafeSyncPlan):
        validate_installed_preflight(data)


def test_missing_tab_or_whitelist_cannot_report_success():
    for key, val in [("parsed_tabs", 33), ("whitelist_loaded", False)]:
        data = config()
        data["source_coverage"][key] = val
        with pytest.raises(UnsafeSyncPlan):
            validate_installed_preflight(data)


def test_approvals_do_not_move_with_sources():
    data = config()
    data["sources"].insert(0, {
        "factory": "FEVC", "month": "2026-09-01",
        "imported": False, "fingerprint": "", "state": "MISSING",
    })
    with pytest.raises(UnsafeSyncPlan):
        validate_installed_preflight(data)


@pytest.mark.parametrize("sheet,row,col", [
    (7002, 5, 2), (7002, 7, 2), (7002, 15, 14),
    (7002, 1004, 6), (7950, 4, 49),
    (7950, 1200, 49), (7903, 16, 1), (7902, 3501, 1),
])
def test_master_protected_ranges_are_never_written(sheet, row, col):
    with pytest.raises(UnsafeSyncPlan):
        validate_plan_writes([write(sheet, row, col)], config())


def test_targeted_technical_writes_are_allowed():
    validate_plan_writes([
        write(7950, 4, 1), write(7950, 4, 17),
        write(7002, 1004, 1, 5), write(7002, 1004, 11, 2),
        write(7503, 4, 7),
    ], config())


def test_september_file_keeps_its_own_v22_trace():
    data = config()
    data["workbook_role"] = "SEPTEMBER_V22"
    validate_plan_writes([write(7950, 4, 49)], data)


def test_no_tab_recreation_during_refresh():
    with pytest.raises(UnsafeSyncPlan):
        validate_plan_writes([{"addSheet": {"properties": {"sheetId": 7950}}}], config())
