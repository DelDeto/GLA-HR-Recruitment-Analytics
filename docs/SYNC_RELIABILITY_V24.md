# GLA HR sync reliability V2.4 — safe integration contract

Status: **draft implementation**. This repository currently contains Meta Ads sync
and the V2.2 forecast planner; it does **not** contain a verified end-to-end
collector/normalizer/bonus runner. The patch below must not be represented as a
complete dual-workbook production synchronization.

## 1. One scheduler and one writer per owned range

- Preserve the existing 08:00 / 13:00 / 18:00 Vietnam-time task and its current
  enabled/paused state. Do not create new concurrent triggers or change Meta
  GitHub Actions schedules. Never dispatch the Meta workflow twice.
- During migration, keep the old data-writing scheduler **disabled** until a
  single authoritative runner is verified. A diagnostic task must not also write.
- Use a run ID, a per-run lock with expiry, and one idempotency key per
  source/version/target. A retry must resume from the last verified checkpoint,
  not repeat previously applied writes.

## 2. Read -> normalize -> validate -> stage -> write -> readback

1. **Read** both target metadata and their different sheet capacities, live
   filters, source-confirmation inputs, official rates, bonuses and ledgers.
   Enumerate all source files and all tabs, including hidden tabs and zero-hour
   rows. Download XLSX bytes privately and verify content SHA256, not only
   modifiedTime. A file listing or metadata read does not constitute import.
2. **Normalize** sources by stable keys: Lead day/group/phone (+ factory only
   for LĐPT); PV/OB actual event/episode; attendance file ID + sheet + episode +
   period; Meta account + date + campaign. Do not use row positions or names
   alone to identify employees. Never infer confirmed workdays from hours / 8.
3. **Validate** dates, headers, file coverage, conflicts, fingerprint-bound
   COMPLETE approvals, bonus policy version, source-state and price policy.
   Distinguish MISSING, PARTIAL, ERROR and PENDING_CONFIRMATION. Unknown is
   not zero. An error in one source must not erase its last-good snapshot.
4. **Stage privately** an immutable source manifest, normalized facts,
   per-workbook write plan, counts, hash of immutable/user-owned fields, and
   expected readback. Stage only in a private runner; never commit employee
   data, private URLs, credentials or cached spreadsheets to this public repo.
5. **Write** bounded native Sheets operations, exact target ID and sheet IDs.
   Existing input owners and spill/formula ranges are strictly protected.
   Never bulk-replace whole sheets or overwrite an original Google Sheet with
   an XLSX file. Use monotonic per-source checkpoints.
6. **Read back** every changed bounded range and key totals, assert formula
   errors absent, source/fee/ledger hashes unchanged, and date/filter semantics
   correct. Mark SUCCESS **per branch and per workbook** only after readback;
   otherwise PARTIAL/FAILED with accurate source IDs/reasons.

## 3. File ownership and V2.3 compatibility

- File A (master): calendar-forecast KPI only from QL_BAO_CAO!I4. Preserve
  actual-fee J4, unreconciled S4, current B5 modes, N15:Y13000 cache,
  A15:L16 presentation, and the page selector B7. Never restore deprecated
  R4 KPI or before/after menu.
- File A FORECAST_V22: **do not write** archived AM4:AU2000 or
  AW4:BD51; **do not overwrite** the active AW1200:BB1343 monthly-factory
  presentation. Existing formulas should recalculate from validated input.
- File B retains its own V2.2 presentation and September-scoped filters.
  Do not copy file A's V2.3 UI, tabs, charts, or formulas into B.
- On both files, DOANH_THU A1004:E1200 and K:L are computed source registry
  columns. F:J are **human-owned** confirmations and must not be rewritten.
  Existing source rows are keyed physically by Factory|YYYY-MM; any insertion
  or reordering requires key-based migration of confirmations *before* writes.
- CHINH_SACH_THUONG!A12:M111, A131:L230, A251:L650 and
  THUONG_UNG_VIEN!A3501:L4500 have separate ownership. MAU_* rows and
  12 NHÁP policies are never activated; only L=ĐÃ CHỐT, M=Hợp lệ and
  verified engine PASS may accrue benefits. Preserve historical reward IDs,
  versions and the execution ledger.
- Forecast inferred stop date is NOT verified termination for reward
  eligibility. No confirmation of employee receipt or payment is invented.

## 4. Preflight for existing forecast plan (implemented in this PR)

A refresh with installed=true must supply:
- workbook_role: MASTER_V23 or SEPTEMBER_V22
- source_scan_complete: true **only after** full XLSX/native file and tab reads
- source_coverage: listed_files, parsed_files, listed_tabs, parsed_tabs,
  errors=[], whitelist_loaded=true
- existing_registry_keys: actual per-row Factory|YYYY-MM from current workbook
- confirmations: keyed approvals as read from that same workbook
- original_calendar_formula and original_coverage_formula from archived notes
- source records including canonical factory, YYYY-MM-01, imported flag, and
  SHA256 fingerprint on imported files
- existing plan inputs: people, sources, evaluated_at, UI grounding, etc.

If any input is missing, or source row identity changed, the planner raises
UnsafeSyncPlan and **produces no write requests**. Never bypass this exception
to report a successful synchronization. The installed planner now emits only
registry A:E and K:L, not user confirmation F:J, and preserves the V2.3 master
archive/summary/cache. Existing source registry alignment must be verified
before the batchUpdate is applied.

## 5. Remaining production integration (NOT implemented by this patch)

- Port/call the verified current lead/PV/OB collectors, attendance normalizer
  and V19 bonus engine in a private execution environment. Current GitHub
  forecast_sync module only builds plans and does not apply them.
- Build robust one-run orchestration across both files with source-specific
  checkpoints, retry/backoff for transient 429/503, pagination, row capacity
  checks, and accurate PARTIAL when a branch is incomplete.
- Implement staged batch writes plus bounded readback and two-workbook
  reconciliation. Do not mark both SUCCESS if only A succeeded; retry B
  idempotently against the same immutable snapshot.
- Recompute bonus engine on actual policy changes, rather than updating only
  a watermark. Do not touch human reward transactions or use hours/8 as
  confirmed work units.
- Test staging against an isolated **private** copy or read-only dry-run first,
  confirm the seven current A visible tabs and three B visible tabs, then
  explicitly authorize production deployment. No cron added by this PR.

## 6. Acceptance tests

Run pytest -q and inspect live A/B with approved private source snapshots.
At least test: no-source, partial-tab, 429 recovery, roster with zero hours,
same-name/different-ID, changed fingerprint after COMPLETE, source-month
reordering, prior-month join, inferred stop and rejoin, stale Meta history,
12 draft policies, a fully approved award, false paid claim, and A-success/
B-fail retry. Test unchanged monthly T9/T10 Ads decisions, FEVC hour caps,
Quanta 8h fee cap, Amtran confirmed workday tiers, date-window filters and
immutability of actual fees and human-owned records.
