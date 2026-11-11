# GLA HR Meta Ads → Google Sheets — production status

Last verified: **2026-11-11**. Public GitHub repository. No credentials or candidate PII are committed.

## Production running
- Daily-sync workflow: [`.github/workflows/meta-ads-sync.yml`](../.github/workflows/meta-ads-sync.yml); schedule `15 0 * * *` (approximately **07:15 Vietnam time**, scheduler may delay).
- Four GitHub Actions Secrets tested successfully by read-only connection check.
- Google Sheets V5.0: `META_RAW` A:I, 6,000-row grid, 410 historical rows (source account tagged), dependent dashboard formulas extended.
- **Initial production sync succeeded**: [GitHub Actions run 43012260436](https://github.com/DelDeto/GLA-HR-Recruitment-Analytics/actions/runs/43012260436).
  - 16 unit tests passed
  - 115 campaign/day rows fetched from Meta Marketing API
  - 19 existing rows updated
  - 0 appended, 0 newly mapped campaigns
  - `dry_run=False`; writes to Google Sheets succeeded
- Post-run sheet verified: dashboard total Meta spend and reported lead count refreshed; lead and candidate source data preserved.
- One-time bootstrap production workflow was removed after its successful run to prevent redundant execution.

## Verification records
- Read-only dry run: [43011673424](https://github.com/DelDeto/GLA-HR-Recruitment-Analytics/actions/runs/43011673424), success, fetched 115 / would update 19 / appended 0.
- Initial production: [43012260436](https://github.com/DelDeto/GLA-HR-Recruitment-Analytics/actions/runs/43012260436), success, fetched 115 / actually updated 19 / appended 0.

## Automated schedule status
GitHub workflow is configured for the next scheduled run, but **the first scheduled execution itself has not yet occurred/been verified**. Review GitHub Actions after the next scheduled window. A failed run must be investigated; do not assume it self-healed.

## Maintenance
- Manual re-run: **Actions → GLA HR — Meta Ads daily sync → Run workflow → days=8, dry_run=false**.
- Safe preview: use the same menu with `dry_run=true`.
- Monitoring: watch workflow status and compare latest Meta day on `DASHBOARD_360`; the workflow does not independently notify Telegram.
- No personal lead/worker records, instant form contacts, invoices, or payout-status data flow through this pipeline.

## Security
Secrets must only remain in GitHub repository Secrets: `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_IDS`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID`. This repository is **public**. Review code and workflow modifications before merging; users with default-branch write access can potentially access secrets through altered workflows.
