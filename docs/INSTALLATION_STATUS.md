# GLA HR Meta Ads → Google Sheets — installation status

Last verified: **2026-11-11**. Public GitHub repository. Never commit credentials or candidate data.

## Completed and verified
- Source code, unit tests, and daily-sync workflow committed to `main`.
- `META_RAW` prepared with columns A:I, historic rows labeled with source ad account, 6,000-row capacity; dependent formulas expanded.
- Four GitHub Actions repository Secrets have been **validated by successful workflow execution**. Secret values are not readable from this repository.
- Added the dedicated **read-only** workflow `.github/workflows/connection-check.yml`.
- [Live dry-run success — run 43011673424](https://github.com/DelDeto/GLA-HR-Recruitment-Analytics/actions/runs/43011673424):
  - `fetched=115` Meta campaign/day rows
  - `changed=19` Google Sheet rows **would** be updated
  - `appended=0`
  - `new_campaigns=0`
  - **NO production writes** were made (dry-run mode).

## Next step: first production run (not yet performed)
Go to **Actions → GLA HR — Meta Ads daily sync → Run workflow**, set `days=8` and uncheck `dry_run` (set to **false**). The workflow is configured to sync only `META_RAW` and campaign-mapping data. Verify results in the Sheet and check run logs after completion.

## Automatic schedule
The production workflow in `.github/workflows/meta-ads-sync.yml` is configured with `cron: '15 0 * * *'`, i.e. **07:15 Asia/Ho_Chi_Minh** daily. GitHub scheduled start times may be delayed. First scheduled production execution has **not** been verified yet.

## Secrets and security
- `META_ACCESS_TOKEN` and `META_AD_ACCOUNT_IDS` — read-only Meta Ads access
- `GOOGLE_SERVICE_ACCOUNT_JSON` — credentials for a narrowly scoped Google service account
- `GOOGLE_SHEET_ID` — target workbook
- Do not paste credentials into issues, pull requests, logs, code, Google Sheets, or chat.
- Public repositories still require vigilant code review: changes merged to the default branch can influence workflow behavior and credential access.

## Scope
Only aggregated campaign/day Meta metrics are synchronized. No personal lead/worker records, instant-form submissions, invoices, or payout status are transmitted through this pipeline.
