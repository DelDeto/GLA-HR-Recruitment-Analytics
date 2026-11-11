# GLA HR Meta Ads → Google Sheets — release V1.1 status

Last verified: **2026-11-11 21:05 ICT**. Public GitHub repository; business data and credentials remain in the private destination Sheet and GitHub Actions Secrets.

## Deployed to `main`
- V1.1 [pull request #1](https://github.com/DelDeto/GLA-HR-Recruitment-Analytics/pull/1) merged successfully.
- **27/27** unit tests passed.
- Existing five-attempt Meta API retry on transient errors remains active.
- Additional scheduled primary/recovery scans at **07:15 / 07:25 / 07:45 / 08:15 ICT**.
- Independent watchdog workflow at **09:10 / 12:10 ICT**; verifies successful private daily checkpoint and attempts controlled recovery only when missing.
- All scheduled workflows share a concurrency group with `queue: max` and `cancel-in-progress: false` to avoid overlapping Google Sheet writes.
- Backfill dynamically expands from 8 days to include the gap since the last success (max 90 days), and fails rather than silently omitting periods longer than 90 days.
- Added private Google Sheets tab `META_SYNC_HEALTH` with header A:I for successful checkpoints. The checkpoint is written only after the raw ads and mapping writes succeed.

## Verified live acceptance
[GitHub Actions production acceptance run 43035037675](https://github.com/DelDeto/GLA-HR-Recruitment-Analytics/actions/runs/43035037675):
- Meta Marketing API fetched **115** campaign/day rows.
- Google Sheets production upsert changed **18** rows, added **0**.
- The private status tab has an entry `2026-11-11 | SUCCESS | 115 fetched | 18 changed | manual` at **21:05:10 ICT**.
- The immediate watchdog-style check read that checkpoint, logged **"Recovery not required"**, and made **no redundant Meta scan**.
- One-time acceptance workflow was removed after successful verification; permanent daily and watchdog workflows remain.

## Caveats and monitoring
- **Automatic scheduled retries and missing-checkpoint recovery have been configured and unit tested; no real scheduled failure/recovery event has yet been observed.**
- GitHub scheduled jobs may run late or be dropped; public-repo schedules may be disabled after 60 days of inactivity.
- Permanent problems (expired/revoked Meta token, removed Google Sheet access, API policy, invalid schema, quota, currency mismatch, outages >90d) will result in failed GitHub Actions runs and require review.
- Manual production run: `Actions → GLA HR — Meta Ads daily sync V1.1 → Run workflow` with `dry_run=false`.
- Manual preview run: same workflow with `dry_run=true`.
- Failure visibility: GitHub Actions run history. **No independent Telegram failure alerts** are configured.

## Security
`META_ACCESS_TOKEN`, `META_AD_ACCOUNT_IDS`, `GOOGLE_SERVICE_ACCOUNT_JSON`, and `GOOGLE_SHEET_ID` remain in GitHub Secrets. Never commit them or lead identities to this public repository. Review default-branch code/workflow edits because a malicious change to a workflow could gain access to secrets.

## Ads-only working Sheet reset — verified 11 Nov 2026

- Made a complete native Google Sheets backup (19 tabs) into the same user's Google Drive folder before any deletion; the backup remains a distinct, private historical copy.
- Working spreadsheet **kept the same file ID and service-account sharing scope** and was renamed to `GLA HR | Theo dõi chi phí Ads – V1.0 (CN–T7)`.
- Deleted 12 non-Ads tabs: `DASHBOARD_360`, `LEAD_PIPELINE`, `NHA_MAY_DON_GIA`, `DOANH_THU_NGAY`, `OVERVIEW_UNG_VIEN`, `TONG_QUAN`, `UNG_VIEN`, `CONG_PEGATRON`, `MOC_THUONG`, `DI_THUONG`, `HUONG_DAN`, `DOI_SOAT_NGUON`.
- Preserved exactly seven ads-related tabs: `BAO_CAO_ADS_TUAN`, `CHI_PHI_ADS_NHOM`, `META_ADS_NGAY`, `CHIEN_DICH_META`, `META_RAW`, `META_SYNC_HEALTH`, and `HUONG_DAN_ADS` (formerly `THIET_LAP_API`, rewritten to ads-only documentation).
- Post-cleanup verified: week 01–07 Nov 2026 = **14,597,362 VND** / **156 leads**, group reconciliation **0 VND**; rolling 30-day = **70,300,139 VND** / **707 leads**; `META_RAW` 9-column schema intact; `META_SYNC_HEALTH` SUCCESS checkpoint intact; no formula errors in sampled report/sync ranges.
- GitHub Actions source code references only its preserved ads data/mapping/checkpoint tabs. **This is structural verification, not proof that a future scheduled GitHub Actions run will succeed**; monitor the next scheduled run to confirm.
