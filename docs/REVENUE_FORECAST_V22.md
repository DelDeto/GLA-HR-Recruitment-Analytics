# Revenue Forecast V2.2

This is a forecast-only addition to both existing production workbooks. The
calendar, fee-window, rate, special factory policies and actual-fee pipelines
remain authoritative. Do not publish private run inputs, worker rows, source
links or reconciliation exports in this public repository.

## Modules

- `attendance_presence.py`: full-roster presence, independent of hours and fees.
- `revenue_forecast.py`: pure continuity decisions and native calendar cap.
- `forecast_sheets.py`: trace, revision-bound source confirmation and existing
  revenue-screen integration.
- `forecast_sync.py`: identical native batchUpdate plan for each workbook.

## Source confirmation

`DOANH_THU!A1001:L1200` contains the source registry. The normalizer owns A:E
and K:L; F:J are confirmation inputs. COMPLETE becomes effective only when
the full roster imported successfully, the approver and timestamp are present,
and the approved fingerprint equals the currently imported fingerprint. Read
success, positive hours, a filename or a new tab never imply completeness.

A zero-hour or blank-hour employee row is still present. Missing source months
stay unknown. Missing IDs without a unique evidenced name/join match, conflicting
IDs, homonyms and duplicate employment keys block inference. A later return
after a COMPLETE absence remains stopped and requests employment-episode review.

Stop dates are exclusive. Official source dates are not overwritten; an
inclusive fee expiry is represented as expiry + 1. The forecast cap begins no
earlier than September 2026. Original data-quality gates remain in force; this
change does not fill previously unsupported forecasts or revise actual fees.

## Recurring synchronization

Extend the existing dual-file synchronization task; do not create another
scheduled job or change the existing Ads schedules. For each run:

1. Read both production IDs explicitly; audit metadata and read the original
   uncapped calendar formula from the note at `FORECAST_V22!AM4`, and the
   original coverage formula from the note at `FORECAST_V22!A2`.
2. Read current employee episodes, source registry confirmations and all current
   attendance files/tabs. Use `read_sources` and `match_presence` on full rosters,
   including zero/blank hours. Do not derive absence from fee-qualified rows.
3. Build Factory × YearMonth source states, combining sorted file/tab content
   fingerprints. Successful parsing is PENDING_CONFIRMATION until confirmed.
   Keep errors as ERROR and missing months as MISSING. Revalidate approval
   fingerprints after any file change. Never silently reuse an old approval.
4. Preserve all current confirmation inputs. Propagate a confirmation between
   the two files only when it refers to exactly the same source fingerprint;
   conflicting confirmations require review. Do not clear source data on error.
5. Build a private JSON config for **each** workbook with `people`, `sources`,
   `confirmations`, `evaluated_at`, `original_calendar_formula`,
   `original_coverage_formula`, `coverage_existing`, `ui_ground`, and
   `installed`. Employee rows must correspond to native physical rows.
6. Run `python -m src.forecast_sync --input PRIVATE.json --output PLAN.json`.
   Apply only to that explicitly selected production ID using native Sheets
   batchUpdate. With `installed=true`, existing tabs, protections and UI modes
   are retained. Keep the original snapshot and current user filter selection.
7. Reread both outputs; compare inferred stops and monthly/factory totals with
   the pure engine. Compare equal date/factory/group scopes. Recheck actual
   fee/attendance/policy fingerprints and January–August history before marking
   either file SUCCESS. Metadata-only reads are PARTIAL, not a sync.

The task must refresh the registry and presence materialization whenever source
files change. Native formulas immediately recalculate after a valid confirmation
edit. The visible revenue screen has a monthly/factory before/after view and an
employee trace view. `FORECAST_V22` remains hidden; no extra user dashboard is
created.

No Apps Script project or trigger is deployed by this Python implementation.
An existing external script can still overwrite formulas; the recurring task
must verify the V2.2 cap after its source import and reapply the shared plan if
needed. Do not claim an Apps Script deployment without project/trigger access.

## Validation and recovery

`pytest -q` includes continued presence, confirmed absence, missing/partial
source, zero hours, official dates, ambiguous identity, rejoining, idempotence,
fee expiry and revision-bound confirmation. Production checks additionally
compare real before/after actual-fee and policy snapshots, native results with
an independent calendar calculation, monthly sums and equal-scope workbooks.

Before deployment, create and verify a full backup of each native workbook and
export its cached/formula snapshot privately. Restore original G and X anchors
and their existing native fills from the archived uncapped formula notes to
disable this forecast change. Restore the revenue portal formulas/validation
from the corresponding backup if a complete UI rollback is needed. Do not
replace a production URL, overwrite current actual-fee data or delete history.
