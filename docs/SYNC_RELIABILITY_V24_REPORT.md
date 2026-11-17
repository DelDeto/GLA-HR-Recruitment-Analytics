# V2.4 release report — 17 November 2026

**A: BLOCKED. B: BLOCKED. READY_FOR_PRODUCTION_DRY_RUN is not achieved.**

Code continuation: `63f83f4cb7fab5723f982ebc2691a2784d9c7419`, PR #3,
branch `fix/sync-reliability-v24-20261117`. PR remains draft/open/unmerged.
No production apply, Sheets mutation, tab/UI change, scheduler activation or
new workflow/trigger occurred. Existing workflow files remain unchanged.
No personnel data, credential, source URL or private financial export is
committed to this public repository.

## Verification and limits

- **136 repository tests PASS locally and both existing CI unit jobs PASS** on
  code commit `63f83f4`. Runs: `44116035996` and `44116019758`. These jobs did not
  use repository Secrets or run the credentialed canary; unit success is not
  production acceptance.
- The six private deployment-program SHAs remain pinned and matched the current
  collector/normalizer declared SHA cells. Collector `ec8f5c56eab2`, normalizer
  `3dd93fd06816`, XML reader `245a936e90b4`, reward engine `f465aa672644`,
  sheet adapter `6c3af3f046df`, operations report `ede2de6d0d5b`.
- Full private replay read 17 source files / 184 tabs exactly once per file.
  Formula errors are retained and audited by the consuming parser, not treated
  as transport failures or numeric zero. All original source records remain.
- Replay production mutations: **0**. Last-good checkpoints are unchanged.
- Protected authored-cell hashes in the replay are unchanged for A/B. Fresh
  bounded native filters, formula notes, confirmations, fee inputs, master draft
  policies and selected cache/archive controls also match before/after.
- Full cached target export scans show zero formula errors. These are cached
  export checks, not a substitute for a complete credentialed native scan.
- Independent common-period forecast projection remains PASS for 36
  month/factory rows (1 September–17 November, LĐPT/all factories), after matching
  each target's current native per-person baseline. Production filters are not
  changed. The selected presentation caches still fail detailed native parity
  because their eligibility windows differ; zero is not coerced to blank.

## Source formula errors: actual impact

The original cached export showed 287 errors in the CRM duplicate-CV audit.
Fresh native reads also found **287 mirrored errors in Applicants IDs**. This
is 287 affected records across two locations, not 574 different applicants.

- Audit-only mirrored cells: 287 excluded from the collector's input scope.
- Applicants rows with an independent usable phone: 277.
- Applicants rows with an independent usable CV link: 8.
- Applicants rows without either alternative: **2, still critical**.

All exclusions have explicit consumer/header/content evidence. An error in a
required date, hours or identity field remains blocking. Numeric phone values
are normalized consistently with the verified collector, including a dropped
leading zero; source cells are not edited. Exact affected rows/links are in
private `CAN_DOI_SOAT.md` and `crm-critical-cases.json`. No source formula was
repaired and no applicant ID was fabricated.

## Additional Sales intake confirmed by the user

The user confirmed that cold/hot/follow-up tabs are new Lead sources, with LĐPT
default; TTS/IDL SV, IDL Fresher and IDL retain their own groups. The adapter
now normalizes and deduplicates these sources before aggregation.

The private staging diagnostic contains 3,891 date/phone-qualified additional
rows and 3,457 duplicate intake records under the documented management key.
These are source-row/duplicate counts, not a claim of that many new people.
There remain **1,657 rows without a usable intake date** and **25 dated rows
requiring identity review**. They are retained privately and not allocated to
an invented day. The resulting staged totals are not complete or deployed.

## Ownership, event aliases and actual-fee reconciliation

- **Lead ownership fixed:** 1,022 native QL_LEADS references are checked against
  their LEADS_LDPT date/factory cells. Owned input cells are updated in the plan;
  formula outputs and the Total LĐPT column are preserved. Direct/history
  provenance is retained. A decrease from a known historical count is blocked
  for review rather than silently clearing or lowering history.
- **PV/OB ID preservation:** the adapter recognizes verified legacy event keys,
  checks source/episode evidence, retains identical physical roster duplicates
  and preserves native group formulas. **Six alias-review groups per target**
  remain unresolved; these are the same six groups in the shared source, not
  twelve different cases. No new duplicate event is appended for those cases.
- **Actual fees:** 270 private differences are separated into 135 provenance
  differences and **135 fee/eligibility proposals for three Quanta applicants**.
  The latter would promote held/unknown revenue to a number; no approved amount
  is silently changed and no unknown is called zero. Old/proposed hashes,
  source links and values are retained privately. No correction was applied.
- **Schema contracts:** every collected tab has a contract or explicit review
  result. Known parser templates can handle matching new files/tabs; ambiguous
  and unreviewed layouts remain blocked. Successful download never grants
  COMPLETE source approval or permission to overwrite F:J.

## Latest branch/file result

PASS below means the stated diagnostic or plan check only. Overall execution
readiness remains BLOCKED where its sources, history or dependencies fail.

| Branch | Source/normalization diagnostic | A plan | B plan | Release limitation |
|---|---|---|---|---|
| Lead | PARTIAL | BLOCKED | BLOCKED | Two critical CRM identities, missing intake dates/phones and historical count-decrease review. |
| PV/OB | PASS | BLOCKED | BLOCKED | Six legacy alias groups; IDs/history preserved, no duplicate append. |
| Attendance/fees | PASS | BLOCKED | BLOCKED | Immutable Quanta eligibility/revenue proposals require source reconciliation. |
| Forecast V2.2 | PASS | PASS | PASS | Execution BLOCKED by upstream plans; no production refresh claimed. |
| Bonus V19 | PASS, drafts stay inactive | PASS | PASS | Upstream execution BLOCKED; confirmed real policy/award acceptance case is also BLOCKED. |
| Meta snapshot | BLOCKED in this runtime | BLOCKED | BLOCKED | Fresh direct API snapshot and actual target reconciliation unavailable here. |

The current native master Meta health contains successful existing-writer
checkpoints, latest observed 17 November at 14:54:01 ICT. The locked September
monthly total matches the existing approved checkpoint. These are narrow
read-only observations: they do not certify new API scope, B freshness or a
credentialed V2.4 run. Meta writer/watchdog/connection-check workflows and all
closed Ads decisions remain untouched.

## Run IDs and credential boundary

- Source-aware private replay: `35a773353d201c16b507fb0c613b587a51bf394b914bd49d803349dc0d25f5f3`.
  Evidence mode: CONNECTOR_SNAPSHOT_REPLAY_NOT_CREDENTIALED_E2E.
  A/B execution states: PARTIAL. Files/tabs: 17/184. Writes: 0.
- Real service-account CLI attempt: `7e0fdfb4589b422eb652ef01b2521de7`.
  Exit 2, GOOGLE_SERVICE_ACCOUNT_JSON_MISSING. This failed before a full stage
  ID or permission result could be created. Do not call it E2E success.
- Earlier private replay retained for comparison:
  `d7b87a06b1f7bb81d6b116cd4c89efe8a25afeadfa3ad02a1c253fca7a7cdaa3`.
  That older run rejected the entire CRM workbook; the source-aware continuation
  removes that blanket rejection without exempting critical consumed fields.
- Earlier existing connection-check run `43358332159`, attempt 2, job
  `133986685338` found required repository Secrets but failed on an empty Meta
  response. It does not test this dual-target runner or all source permissions.

Repository Secrets are not injected into this workspace. The read-only
`sync_access_check` CLI now offers bounded, hash-authorized discovery, actual
service-account capability/source reads and direct Meta capture in a private
credential-bearing environment. It blocks Google writes, prints only counts/
status/hashes and cannot claim full V2.4 readiness even if its own checks pass.

A concrete patch to run that canary inside the existing test job for internal
PR #3 was prepared. **Automatic approval review rejected the workflow
modification because prior approval is required.** The patch remains private,
unapplied and has not run. No workaround was used to read repository Secrets,
no workflow was changed and no credentialed canary run ID exists for it.

## Manual actions still needed

1. Resolve the two CRM identities and supply actual received dates/identities
   for retained additional-intake rows where available. Do not infer dates from
   file modification time or manufacture applicant IDs.
2. Review historical Lead count decreases and the six event-alias groups using
   the private before/proposed/source evidence. Do not discard confirmed IDs.
3. Reconcile the three Quanta applicants' factory/OB termination evidence before
   promoting the 135 held fee rows. Provenance-only changes are separate.
4. Either approve the exact private read-only CI patch or supply an existing
   private runner with the credential variables/manifest. Then verify actual
   service-account read access to every source and edit capabilities on A/B,
   and capture/validate a fresh direct Meta snapshot.
5. Provide an actually confirmed reward policy/case for live acceptance. All
   12 NHÁP policies remain inactive; no approval or award execution is invented.
6. Run the credentialed full V2.4 DRY RUN after the relevant gates are resolved;
   inspect per-target planning, source coverage, native formula errors,
   protected hashes, filters and equivalent-period A/B values.

Private review files, role/source IDs, employee rows and financial proposals are
outside the public repository. No --apply, merge, scheduler change or new
workflow/trigger is authorized by this report. Both targets remain BLOCKED.
