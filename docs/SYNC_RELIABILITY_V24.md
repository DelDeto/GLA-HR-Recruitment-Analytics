# GLA HR sync reliability V2.4 — safe integration contract

Status: **runner infrastructure implemented; production end-to-end BLOCKED**.
The branch now has native Google/Drive I/O, recursive source collection,
private staging, pinned adapter execution, stable-key upserts, bounded native
readback, retry/resume, single-writer locking and cross-file audits. Concrete business bindings and a disabled private manifest now exist. Data
reconciliation and a credentialed full acceptance run remain blocked. Credentials
are unavailable in the workspace. The user approved the exact read-only
canary patch in the existing PR test job; that scoped path uses GitHub Secrets
inside Actions only. Do not represent passing
infrastructure tests as completed production synchronization.

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

## 5. Remaining production integration (release blockers; see latest report)

- Port/call the verified current lead/PV/OB collectors, attendance normalizer
  and V19 bonus engine in a private execution environment. Current GitHub
  forecast_sync module only builds plans and does not apply them.
- Bind and review the private business adapters with their complete dependency
  SHA manifests; `src.sync_runner` executes them through the protocol below.
  Current workspace legacy scripts are **not** silently treated as approved
  current adapters. Missing adapters yield PARTIAL and preserve last-good state.
- Recompute bonus engine on actual policy changes, rather than updating only
  a watermark. Do not touch human reward transactions or use hours/8 as
  confirmed work units.
- Test staging against an isolated **private** copy or read-only dry-run first,
  confirm the seven current A visible tabs and three B visible tabs, then
  explicitly authorize production deployment. No cron added by this PR.

## 7. Implemented runner and operating procedure

New modules: `sync_runtime` (0700/0600 atomic private state, OS lock, backoff),
`sync_sources` (Google auth, paginated recursive Drive listing, full XLSX/native
tab reads with source-version stability check), `sync_identity`, `sync_plan`
(keyed upserts and ownership), `sync_runner` (dependency graph, immutable stage,
per-target resume/readback), `sync_audit` (same-definition native comparison),
and `sync_export_audit` (read-only export audit, never a write source).

The installed forecast guard now also rejects `updateCells.range`, wildcard
field-mask, `autoFill` and cosmetic writes into protected cells. Unsupported
mutation types, including tab recreation/copy/delete, fail closed. The installed
forecast plan no longer formats or resizes existing targets. Source overrides
in TT_NGUON M:O and the computed Ads filter flag are protected too.

The runner never creates a tab/trigger, uploads an XLSX over production, calls
the Meta Actions dispatcher or changes a scheduler. Meta's existing writer owns
META_RAW. The V2.4 Meta adapter must reconcile its verified API snapshot into
the computed Ads facts without replacing locked monthly/bill decisions. If the
snapshot is stale or access is missing, return PARTIAL; do not invent daily
spend. No automatic Meta API call is hidden inside this runner. `sync_meta_snapshot`
captures a direct API snapshot privately in the credential-bearing environment.
The pinned Meta adapter validates freshness/scope and compares active native API
facts read-only; it never overwrites formula-derived QL_ADS or locked bill/month
decisions. A proven no-op requires per-target row count and fact hash proofs.

### Private configuration (not committed)

Supply these keys in a private JSON file:

- `targets.A/B`: explicit IDs, roles MASTER_V23 / SEPTEMBER_V22, and `ownership`
  per branch. Each ownership rectangle is `[sheetId,r0,r1,c0,c1]` with zero-based,
  end-exclusive bounds. Read actual capacities from **each** workbook; never
  copy master capacities or UI into B.
- `source_folders`, `source_files`: all external roots and Lead/PV/OB files.
  Roots are traversed once, files deduplicated by ID, all tabs including hidden
  tabs read. Successful download is not semantic parsing or COMPLETE approval.
- `as_of`: explicit business date in Vietnam time.
- `adapters`: six entries `lead`, `pv_ob`, `attendance`, `forecast`, `bonus`,
  `meta`. Each has `entrypoint` (private local absolute path), `version`,
  `sha256`, `files` (every dependency filename and SHA256), optional timeout and `options` (private business bindings, passed in the input).
  No program is fetched or executed from a Sheet cell automatically. Review
  the current program and verify its SHA before creating this manifest.
- `reconciliation`: `scope` with from/to/group/factory; layouts A/B with
  sheet_id, row_start/end, month_col, factory_col, and metric column mappings.
  For existing V2.3 A use FORECAST_V22 AW1200:BB1343; B uses AW4:BD51. The
  forecast/actual columns differ. Closed months may be compared inside broader
  report windows; partial months require the same exact ending date. Unknown
  actual fees remain unknown, not zero. Filters are never changed by dry-run.
- `deployment_approved` and `single_writer_private_volume` must both be true
  to use `--apply`, following a separately approved production deployment.

Do not put any real IDs/worker rows/credentials in public example configs or
GitHub inputs. The service account needs Sheets access to **both** target IDs
and Drive read access to every external source/folder. Secrets existing only
in GitHub Actions are not automatically available to this private runner.

### Adapter protocol (private stdin/stdout JSON)

Input contains branch, as_of, the one shared source bundle, the current staged
target snapshots and earlier normalized branch results. A/B data is passed
privately. Stdout must be one JSON object; diagnostics, candidate names or
credentials must never be printed. The parent captures stdout/stderr privately,
does not forward exception bodies, and removes Google/Meta credentials from
the normalization subprocess environment.

Return `version`, `complete:true`, `validation:"PASS"`, `normalized`, `coverage`
and either `tables:{A:[...],B:[...]}` or `forecast:{A:config,B:config}`. Coverage
must name **every collected file**, its exact fingerprint, and every tab with
PARSED or VERIFIED_OUT_OF_SCOPE plus a reason code. Count-only assertions are
insufficient. Unknown/new schemas cannot be silently skipped. `complete` is a
statement about semantic coverage, never a request to approve source F:J.

Each fact table has `sheet_id`, `start_row`, `end_row`, sorted `columns`,
`key_columns`, `expected_headers`, `identity_basis`, `rows`, and optionally
`immutable_existing`. The key basis must be one of the documented business
identities. Rows have exactly one value per column; null preserves the old
value. An empty, verified table may have rows=[], but omitting either target
or providing no verifiable table is not successful processing. Conflicting
duplicate keys or changed headers block the branch; retries never append the
same key again. Existing actual-fee facts **must** use immutable_existing=true;
corrections need a separately reviewed reconciliation/override, not a quiet
change by this migration. The bonus output cannot claim approval/payment.

The bonus output layout is role-specific: master writes only the existing
OPS_KIEM_THU!A2001:V5000 cache. OPS_THUONG!A4 is a native LET/VSTACK array
reading that cache and must remain protected;
B has no OPS tab and uses existing TH_THUONG computed columns, append-only via
immutable_existing=true. Never create OPS_THUONG in B. Legacy approval/payment
columns O:R and all existing award records remain protected. A private adapter
must validate this actual legacy schema before it can emit a B table; a missing
or incompatible binding remains a deployment blocker.

Forecast configs must pass the original V2.4 preflight, use notes read from the
same target, retain physical source-registry key alignment and onboard
whitelist evidence, and installed=true. Its native autofill is materialized
into exact formulas for capacity checks and complete native readback. No UI
or approval input is rewritten.

### Run, resume and audit

```sh
umask 077
python -m src.sync_runner --config /private/gla-sync.json --state-dir /private/gla-state
# Only after private deployment review/authorization:
python -m src.sync_runner --config /private/gla-sync.json --state-dir /private/gla-state --apply
python -m src.sync_runner --config /private/gla-sync.json --state-dir /private/gla-state --apply --resume RUN_ID
```

The default is dry-run. It still performs live reads, normalization, validation
and immutable staging, but never calls a Sheets mutation or advances last-good
watermarks. Exit 2 means BLOCKED/PARTIAL, never success. Reports contain reason
codes/hashes/counts, not source URLs or worker facts. Full artifacts stay 0600
under the 0700 state directory; do not upload them as public Actions artifacts.

Apply checks human-owned hashes and row-key/owned-cell preimages. HTTP 429/503
uses bounded backoff and fixed-cell idempotent retries, never append requests.
Every changed cell is read natively; a final full native scan checks formula
errors and all protected fields. Only after final audit/reconciliation are
verified branch last-good checkpoints advanced. A failure of B does not claim
B success or blindly reapply A. Resume reuses the same immutable snapshot,
checks its config hash and expiry, and refuses rollback over a newer checkpoint.

The file lock protects one host/shared private state volume. Expiry is recorded
for diagnostics but does not steal an active OS lock. **Multi-host operation
requires a distributed fencing lease before deployment.** Sheets does not
offer cross-workbook transactions or per-cell compare-and-swap. A network
failure between bounded batches can leave partially applied computed facts;
the run stays PARTIAL and retries the exact staged cells. The prior last-good
snapshot remains private and is not erased. No blind whole-sheet rollback is
performed. Keep all legacy data-writing schedulers paused during migration.

## 8. Verification boundary

Repository tests use synthetic names/IDs and fake transports to exercise real
write planning, retry, locks, readback mismatch and resume behavior. Live export
audits inspect cached formula errors and authored-cell hashes but do **not**
certify a production write, service-account access, Google-only table/chip
metadata, private adapter completeness or future scheduled execution. These
remain separate PASS/FAIL/BLOCKED checks in the release report. Historical
installation notes in other documents are not evidence of a current full sync.

## 6. Acceptance tests

Run pytest -q and inspect live A/B with approved private source snapshots.
At least test: no-source, partial-tab, 429 recovery, roster with zero hours,
same-name/different-ID, changed fingerprint after COMPLETE, source-month
reordering, prior-month join, inferred stop and rejoin, stale Meta history,
12 draft policies, a fully approved award, false paid claim, and A-success/
B-fail retry. Test unchanged monthly T9/T10 Ads decisions, FEVC hour caps,
Quanta 8h fee cap, Amtran confirmed workday tiers, date-window filters and
immutability of actual fees and human-owned records.


## 9. Concrete business bindings and current release boundary

`sync_business` binds the current private collector and attendance normalizer,
V2.2 presence/forecast planner, and the four-program V19 reward bundle. Programs
must match both their local SHA256 and explicitly configured live deployment
anchors (and declared SHA cells where present). The public repository contains
protocol code and synthetic tests, not the private deployment programs/data.

A private adapter bundle entrypoint calls `src.sync_business.main`. Its `files`
manifest must hash the entrypoint and every bundled public Python module.
`options.programs` supplies each private program's path, SHA and zero-based
`anchor` (`sheet_id`, `row`, `column`, optional `hash_row`). Missing or changed
anchors stop execution. `options.source_roles` names the external recruitment
sources. Original XLSX bytes are retained 0600 in the private state directory;
normalization never substitutes an export over the original source. Newly
listed attendance files are included. Native attendance files are converted
locally with deterministic ZIP metadata and literal strings; incompatible tab
names/schemas remain blocked rather than silently renamed or skipped.

`options.tab_contracts[file_id][tab_id]` must identify an actual parser and
verify its header row/column values, or explicitly document a verified excluded
scope. New tabs and unreviewed layouts remain PARTIAL. Downloading every tab
alone is insufficient. The current production manifest is deliberately disabled
and its outstanding schema reviews are recorded privately.

Set `require_service_account_preflight:true`. The real runtime identity must
read both targets and all source metadata; both targets must report canEdit.
The subsequent data scan verifies actual content access, not metadata alone.
Use GOOGLE_SERVICE_ACCOUNT_JSON **or** GOOGLE_APPLICATION_CREDENTIALS in that
same environment. A GitHub Secrets settings URL cannot reveal secret values to
this workspace. Do not change an existing Meta workflow or add a trigger to
work around that boundary. Capture Meta separately, for example:

```sh
python -m src.sync_meta_snapshot --from-date 2026-01-01 --to-date YYYY-MM-DD --state-dir /private/gla-state
```

Configure the resulting private snapshot path/SHA, accounts, from date and
freshness limit as `options.meta_snapshot`. An empty account response remains
EMPTY_REQUIRES_REVIEW; no unverified numeric zero is manufactured. Snapshot
validation cannot authorize replacing source facts or bypass bill/month rules.

`sync_scope.check_common` can independently recompute a private common date
scope after matching every row against each target's current native calendar
baseline. `compare_facts` checks existing native Lead/PV/OB/actual-fee parity
without presentation filter edits. This evidence is reported separately from
native post-write reconciliation and never turns a blocked service-account
run into SUCCESS. Existing fact parity alone does not certify source completeness.

The live audit found unresolved fact-region/legacy-key/history conflicts. The
bindings are release candidates, not an approved migration. Do not enable apply,
schedules, policy activation or a new workflow based on synthetic tests or a
connector snapshot replay. See SYNC_RELIABILITY_V24_REPORT.md for exact gates.


## 10. Source-aware reconciliation and confirmed additional intake

Native source formula errors are retained with tab/row/column/type and included
in source fingerprints. Reading an error cell does not reject an entire workbook
or replace the value with zero. `sync_source_audit` validates each consumer's
contract and classifies errors by actual use. CRM applicant-ID errors can be
excluded only when that row has an independent usable phone/CV identity;
missing identity remains critical. Excluding an audit tab never exempts errors
in its primary-data consumers. In the live diagnostic, 287 audit errors mirror
287 Applicants ID errors; only two Applicants rows lack an alternative identity.

The user confirmed that cold/hot/follow-up Sales tabs are new intake, with
LĐPT default and TTS/IDL SV, IDL Fresher and IDL retained separately.
`sync_legacy_leads` reads those reviewed layouts, normalizes the phone/date,
and merges using date/group/identity, with factory in the LĐPT key. Student
classification retains precedence. Missing dates/phones stay in private
quarantine and keep the Lead branch PARTIAL; no date is invented. This source
policy is explicit in private options, not an automatic assumption for an
unreviewed source. Newly matching tabs can reuse a reviewed parser template;
unknown or ambiguous layouts fail closed. Exclusion decisions never propagate
to new tabs by filename alone.

The Lead adapter validates native =N(LEADS_LDPT!...) references against their
source date/factory headers, writes only the corresponding owned input matrix
cells and preserves QL_LEADS formulas. The Total LĐPT column is excluded from
ownership. Direct/historical tables retain provenance and allow verified
count increases; a count decrease requires reconciliation. Do not bypass that
guard to replace missing source history with zero.

PV/OB reconciliation preserves installed event IDs, evidenced legacy aliases
and identical physical roster duplicates. A source row URL alone is never an
identity. Ambiguous alias groups generate private review artifacts and target
plan blockers, rather than appending a second event. Existing formula-derived
group columns are verified against their effective values and never replaced.

`sync_fact_audit` produces private per-row old/proposed values, hashes and
classification. Provenance-only differences are separate from fee/eligibility
changes. Existing actual-fee amounts, including unknown-to-number proposals,
remain immutable until the corresponding review is resolved. No review file
constitutes an approval or authorizes applying a correction.

The runner retains a fully source-validated normalization for downstream
read-only diagnostic planning when a target plan fails. Every target still gets
its own plan result. Execution, including a dry-run readiness claim, retains
the dependency gates: a blocked PV/OB/attendance plan cannot become a verified
forecast or reward refresh. Last-good checkpoints never advance in dry-run.
Only allowlisted counts appear in public diagnostics; source URLs, candidates,
raw discrepancies and credentials remain in private artifacts.

### Approved credentialed read-only canary

`python -m src.sync_access_check --scan-sources --read-meta` is a separate,
read-only capability/source/Meta canary for a credential-bearing environment.
It authorizes only reviewed resource hashes discovered through bounded native
master references. It blocks Google mutations, stores raw inputs privately,
prints counts/status/hashes only and exposes no apply option. A passing canary
cannot claim READY_FOR_PRODUCTION_DRY_RUN or replace the full V2.4 runner.

A concrete patch was prepared to add this check to the existing test job for
internal PR #3 only, using existing repository Secrets. It adds no workflow,
job, trigger or scheduler and leaves the three Meta workflow files unchanged.
Automatic approval review initially rejected publishing that workflow change
because prior approval was required. The user then explicitly approved the exact
private patch. Commit `83478fab90b956abe648401c1ddd210f0ef936dc` changes only
`tests.yml` (22 additions), leaving all existing triggers and Meta workflow files
unchanged. The credentialed step runs only on internal PR #3, the named branch,
and an explicitly marked `[v24-access]` head commit. Push tests skip it.

The first approved canary ran in Actions run `44118492903`. Direct Meta capture
passed; Google master-reference reads passed but Drive capability/source reads
returned HTTP 403. This is actual runtime evidence, not a successful full runner.
The continuation exposes only allowlisted Google reason enums to distinguish
service configuration from scopes/access, without response messages or project
identifiers. Unread source formula-error counts are unknown, never numeric zero.
The reason-confirming run `44119457932` identifies
`REMOTE_HTTP_403_SERVICE_DISABLED`: enable Google Drive API in the credential's
consumer project, then rerun that existing read-only job. The user subsequently
activated Drive API. Attempt 2 of that run verifies canEdit=true for A/B and
reads 16/17 files (182 tabs); CTECH remains HTTP 404. Resolve the source's
identity/sharing and repeat the same check without dropping it from coverage.
A/B edit capability is verified, while source completeness and full business
acceptance remain blocked. See the latest report for retry IDs.
Do not expand the patch into the full business runner or export private inputs
through public CI. See the report for the remaining data and full-E2E gates.

The alternative is an existing private runner configured with the credential
variables and private manifest. A Secrets settings URL cannot export secret
values into this workspace. Full E2E remains separately BLOCKED until actual
runtime access and all data/case acceptance gates pass. See the latest report
for attempt IDs and private manual-review instructions.


### User-confirmed intake exclusion (18 November)

CTECH is explicitly not used according to the user. `sync_source_scope` binds
that decision to the reviewed resource hash; it is excluded from active source
requirements, never substituted for numeric zero. A changed resource identity
under that role blocks review. The private manifest removes only its explicit
file entry, retains historical scope evidence and pins the revised adapters.
The fixed legacy collector form loop is adapted in memory for this approved
exclusion and restored afterward; its source file/deployed SHA is unchanged.
Other missing sources remain errors. Historical facts and count-decrease
protection remain unchanged; no production migration or source deletion occurs.


HTTP 429 now waits one full 60-second quota window between bounded retries.
The former initial exponential delays could exhaust all attempts within about
31 seconds while Sheets' minute quota was still active. HTTP 5xx keeps its
bounded backoff. Retry does not append, change the request or suppress a failed
source; incomplete scans retain last-good and remain PARTIAL/BLOCKED.


The revised-scope canary run `44219333231` passes all 13 active capability checks,
A/B canEdit, 16/16 full source reads (182 tabs), 148 tests and direct Meta through
18 November. It observes 2,045 native source formula-error cells. The private
consumer-aware validation must reclassify those current cells; transport/canary
PASS cannot certify source semantics, native target parity or full E2E readiness.
