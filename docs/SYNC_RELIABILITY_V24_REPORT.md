# V2.4 release verification — 17 November 2026

**Release decision: BLOCKED for both A and B. No production sync SUCCESS.**

PR #3 remains draft/open/unmerged. No `--apply`, Sheets mutation, new tab,
workflow, trigger or scheduler activation was performed. Existing Meta workflow
files and Meta writer code are unchanged. Private personnel inputs, financial
exports, credentials, deployment programs and the real-ID manifest remain
outside this public repository.

## Implemented and tested

- **115 repository tests PASS**, including 16 added in this continuation.
- Concrete protocol bindings now call the current Lead/PV/OB collector, exact
  attendance/fee normalizer, installed forecast V2.2 and four-program V19 reward
  bundle. Each private program must match its file SHA **and** live deployment
  anchor; collector/normalizer also match their declared SHA cells.
- Verified SHA prefixes: collector `ec8f5c56eab2`, normalizer `3dd93fd06816`,
  XML reader `245a936e90b4`, reward engine `f465aa672644`, sheet adapter
  `6c3af3f046df`, operations report `ede2de6d0d5b`. Full SHAs are pinned in the
  private dependency manifest. No fallback to the stale archived normalizer SHA.
- Adapter options are passed by the runner. Original XLSX bytes are retained
  0600; native attendance can be materialized locally and deterministically.
  Newly discovered files are included; unreviewed tabs/schemas remain PARTIAL.
- Both Google credential environment forms are supported. Mandatory private
  preflight checks the actual runtime identity's read access and target canEdit
  capabilities, without issuing a write probe.
- Direct Meta snapshot capture is separate from the existing writer. The
  adapter validates content SHA, freshness, account/date/currency scope, totals
  and stable keys before comparing native active API facts. An unverified
  empty account remains unknown/review-required.
- **Corrected a real ownership error:** master `OPS_THUONG!A4` is a native
  LET/VSTACK output. The writable V19 cache is existing
  `OPS_KIEM_THU!A2001:V5000`. The live array, program archive and cache headers
  are now protected. B retains TH_THUONG and its O:R human fields.
- Independent calendar projection checks a common period without filter edits
  and must first match every native per-person baseline. Missing values remain
  distinct from numeric zero. Existing fact parity is a separate check.

Synthetic tests additionally cover changed deployment anchors, private immutable
XLSX blobs, newly discovered native attendance, literal formula-looking input
strings, incomplete schema coverage, target access, Meta staleness/duplicate
keys, calendar caps and baseline mismatch. The exact private V19 engine also
passed the existing synthetic tier, fractional-unit, cap, incomplete-history,
draft, exit, overlap, six-month, cumulative-milestone and opening-balance
scenarios. These are not live award approvals.

## Live reads, private diagnostics and replay

The user-connected Drive/Sheets identity read 11 recruitment workbooks and six
attendance XLSX files: **17 files, 184 tabs**, including hidden tabs. The folder
was listed again and still contained the same six attendance files. All source
data and the private manifest are stored outside the public worktree.

The full private snapshot replay invoked the runner's collect/stage/execute/audit
path with a transport that forbids writes. Each of the 17 sources was requested
once. The CRM source was rejected because its duplicate-CV audit tab contains
**287 formula errors**. Consequently the runner retained 16 parsed files / 173
tabs and marked every branch PARTIAL, preserving last-good state. No error was
converted to numeric zero. This replay is **not** a service-account E2E run.

Independent engine diagnostics used collected private inputs without granting
the failed full-source gate: attendance emitted 11,543 daily and 74 period
records; both roles' forecast continuity decisions agreed; V19 emitted no
approved entitlement because no active confirmed policy exists. Diagnostics
are not release PASS or production updates.

| Production audit | A — master | B — September |
|---|---|---|
| Existing UI retained | PASS | PASS |
| Full cached export formula-error scan | PASS: 0 | PASS: 0 |
| Protected authored-cell hashes in replay | PASS: unchanged | PASS: unchanged |
| Fresh bounded native filter/note/price/confirmation reread | PASS: unchanged | PASS: unchanged |
| Authored-cell count before/after replay | PASS: unchanged | PASS: unchanged |
| Master V2.3 KPI/cache/archive/draft protections | PASS: enforced in plans | N/A: separate UI retained |
| Source-to-target service-account E2E | BLOCKED | BLOCKED |
| Production write/native post-write readback | NOT RUN | NOT RUN |

Export formulas include Excel adaptation and cached spill cells. They cannot
authorize replacing a native formula with a fact. Native reads verified critical
original formula notes, confirmations and the actual bonus-array anchor. Full
private artifacts were not uploaded as public Actions artifacts.

## Common-period A/B checks

Private equivalent scope: **1 September–17 November 2026, LĐPT, all factories**.
No production filter was changed.

- PASS: independent calendar matches all 552 applicable native physical rows
  in A and 496 in B under their respective current baseline windows.
- PASS: recomputing the same common period matches **36 month/factory rows**
  across A/B, preserving unknown versus zero.
- PASS: existing native Lead/PV/OB/actual-fee facts have equal common-scope
  projections. This proves existing fact parity, not source completeness.
- FAIL for existing presentation-cache acceptance: production windows remain
  different. Closed-month detail includes a factory with zero in A versus blank
  in B due to different eligibility windows. The independent projection explains
  that mismatch; it does not change B's selected month or certify post-write
  native results.

## Branch-by-branch release gates

All six branches remain **PARTIAL in both A and B** in the full runner replay
because the shared source gate failed. Additional diagnostics establish the
following gates, which must not be bypassed to get green CI.

| Branch | A | B | Remaining gate |
|---|---|---|---|
| Lead | BLOCKED | BLOCKED | Installed QL_LEADS includes legacy formula-derived facts; complete the owned-source/table binding and reconcile history without replacing formulas. |
| PV/OB | BLOCKED | BLOCKED | Reconcile legacy event identifiers with evidence. Preserve native keys; do not append duplicate hash IDs. Handle existing roster duplicates without deleting physical history. |
| Attendance/fees | BLOCKED | BLOCKED | Current normalization encounters immutable historical fact conflicts, including status/provenance. Preserve approved prices, source periods, exceptions and last-good facts. |
| Forecast V2.2 | BLOCKED | BLOCKED | Source/whitelist/attendance prerequisites are not release-ready. Pure common-period projection passes; installed refresh still fails the source gate. |
| Bonus V19 | BLOCKED | BLOCKED | Master cache mapping is corrected; diagnostic plans pass for that cache and B's append-only output. All 12 drafts stay inactive. No confirmed real award case exists for live acceptance. |
| Meta snapshot | BLOCKED | BLOCKED | No fresh direct API snapshot is available in this runtime. Cached history is insufficient proof of current account scope. |

The private production manifest was created with six pinned entrypoints,
explicit target roles, source roots and ownership rectangles. **It is disabled**:
deployment_approved=false and single_writer_private_volume=false. Outstanding
tab contracts are recorded as REVIEW_REQUIRED, never silently approved.

## Credential/Actions evidence and exact blockers

The actual CLI dry-run against that manifest exited 2 with
`GOOGLE_SERVICE_ACCOUNT_JSON_MISSING`. Neither that variable nor
GOOGLE_APPLICATION_CREDENTIALS is present here. A GitHub Secrets settings URL
does not expose values to this environment or prove permissions on both targets
and every source. The complete service-account preflight remains **BLOCKED**,
not PASS or an assertion that sharing is absent.

The existing **read-only connection-check** job was rerun once; no workflow was
created/edited and no scheduled writer was enabled. Run `43358332159`, attempt 2,
job `133986685338`, on original commit `c3a5992b2bd0`, found all required Secrets
but **FAILED** on an empty Meta insights response from a configured account.
That limited job does not exercise the dual-target runner, all source permissions
or target edit capabilities. It was not retried repeatedly and its empty result
was not treated as verified zero spend.

Required next steps before release:

1. Supply Google credential and Meta scope/token through an authorized private
   execution environment; never paste them in chat or commit them. Run actual
   capability/content preflight for A, B and every source.
2. Complete semantic schema contracts and resolve the CRM formula-error scope
   without modifying external sources or suppressing consumed-field errors.
3. Reconcile Lead formula ownership, event-key aliases/roster duplicates and
   immutable actual-fee differences with private evidence. Re-run all branches.
4. Obtain a fresh direct API snapshot and a genuinely confirmed live reward
   policy/case. Do not activate drafts or invent approval for testing.
5. Pass a full credentialed E2E DRY RUN and all role-specific/common-scope gates.
   Production apply/readback requires separate subsequent authorization.

Do not merge PR #3, run --apply, enable ChatGPT 08:00/13:00/18:00, change Meta
Actions, or create a new trigger based on this report. See
SYNC_RELIABILITY_V24.md for the private runtime and manifest protocol.
