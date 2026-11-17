# V2.4 branch verification — 17 November 2026

**Release decision: BLOCKED. No production synchronization claimed.**
PR #3 remains open and unmerged. The ChatGPT data-writing schedule was observed
disabled; its state was not changed. No Meta Action/workflow or trigger was
added, changed or dispatched. No production Sheets mutation was sent.

## Code and automated checks

- 99 repository tests PASS (71 at branch start).
- Real Google/Drive transport and unscheduled runner CLI are implemented;
  private business adapter deployment bindings remain incomplete.
- Tests cover fixed-cell idempotent retry, 429/503 backoff, private lock/stage,
  A-success/B-failure resume, native readback mismatch, stale checkpoints,
  no-op dry-run, source failures, full tab coverage, zero hours, identity
  classification, different workbook roles and protected mutation shapes.
- Existing forecast tests cover COMPLETE/PARTIAL/MISSING, changed-fingerprint
  approvals, rejoining, fee expiry and ambiguous identity. New runner guards
  cannot activate policies, claim payment or replace historical actual facts.
- Workflow files and existing Meta code are unchanged by this continuation.

## Private live read-only audit

| Check | A — master | B — September |
|---|---|---|
| Existing visible UI | PASS: 7 tabs | PASS: 3 tabs |
| Cached formula-error scan, all exported tabs | PASS: 0 | PASS: 0 |
| Protected authored-cell hashes, before/after | PASS | PASS |
| Bounded native controls/confirmations reread | PASS: unchanged | PASS: unchanged |
| Current master forecast KPI I4 | PASS | N/A: own UI retained |
| Draft policy preservation | PASS: 12 NHÁP, untouched | N/A: no master editor copied |
| Production write requests | 0 | 0 |
| Service-account runner dry-run | BLOCKED | BLOCKED |
| Full business pipeline/native write readback | NOT RUN | NOT RUN |

The cached full-workbook audit used fresh native exports; the selected control,
formula-note and approval inputs were also read through native CellData. This
is evidence of a non-writing audit, not proof that a service-account write or
Google-only UI/table metadata is working. Full private snapshots and financial
figures were not committed or uploaded as public artifacts.

The six current attendance XLSX files were downloaded privately. All 34 tabs
were enumerated/read; the presence parser returned 32 current-year tab scopes
and excluded two prior-year scopes. The current fee normalizer code matched
the SHA in TT_PIPELINE A3. The separate old pipeline log still contains a stale
SHA and must not be used to select executable code. Seven synthetic FEVC,
Quanta and Amtran fee cases passed against that exact private normalizer.
This does not certify a full factory import, a fresh onboard whitelist or V19
award calculation. None of the private program/data bytes were published.

## Cross-file result

**FAIL / BLOCKED for acceptance.** The live reports currently select different
date ranges: A includes the current reporting day; B selects September only.
The full requested common current-day scope cannot be verified from B's
currently filtered native caches without changing its filter or running a
private equivalent-scope recomputation. No production filter was changed.

For the overlapping closed month, total forecast and actual amounts agree.
The detailed comparison still correctly fails: one factory has a numeric zero
forecast in A versus an unknown/blank forecast in B. The broader master window
includes later employment episodes that the September filter excludes. This
must be resolved by explicit equivalent-scope validation; the runner does not
coerce blank to zero or manufacture agreement.

## Remaining blockers and required deployment work

1. No GOOGLE_SERVICE_ACCOUNT_JSON is available in this runner environment;
   the actual CLI dry-run exits 2 with GOOGLE_SERVICE_ACCOUNT_JSON_MISSING.
   A connector read under the user's identity does not prove the service
   account can access both production files and all source folders.
2. A complete private source/schema/ownership manifest and reviewed protocol
   bindings for the current Lead/PV/OB collector, exact fee normalizer,
   forecast inputs and V19 bonus program are not provided. Archived scripts
   and old prompts are evidence, not a verified executable release. All
   dependencies and versions must be pinned. No fallback to obsolete code.
3. Meta API credentials/scope and a current verified read-only API snapshot
   are unavailable to this runner. Keep the existing Meta writer unchanged;
   the Meta adapter must prove freshness and deduplicate API/month/bill scope.
4. Both roles need verified table mappings. In particular B has no master
   OPS_THUONG tab: its reviewed adapter must bind existing legacy computed
   award fields append-only while preserving approval/payment fields.
5. Full end-to-end private dry-run, a fully approved V19 award case, production
   native writes/readback and same-current-period cross-file acceptance remain
   NOT RUN. Do not merge, deploy or restart the ChatGPT writer based on unit
   tests or these read-only checks.

Use SYNC_RELIABILITY_V24.md for the private stdin/stdout adapter protocol,
credentials/permission requirements, configuration, CLI, immutable resume and
transaction limitations. Keep legacy writing schedules disabled until a
separately authorized private deployment passes every branch on both files.
