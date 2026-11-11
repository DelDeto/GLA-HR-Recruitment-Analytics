# GLA HR – Meta Ads Direct Sync (GitHub Actions)

Automated campaign-level Meta Marketing API → Google Sheets sync. Uses standard GitHub-hosted `ubuntu-latest` runners, which are free in public GitHub repositories under GitHub's current Actions billing policy.

**Public repository:** This repository intentionally contains only application code, tests, and non-sensitive instructions. Account IDs, spreadsheet ID, token, and Google credentials are deliberately excluded. Do not commit PII, resumes, lead forms, exported sheets, API tokens, or service-account keys.

## One-time configuration (maintainer only)

1. Create a Google Cloud **service account**, enable the **Google Sheets API**, and share the destination Google Sheet with its `client_email` as an **Editor**. Give it access only to the required spreadsheet.
2. Add the following **Actions repository secrets** via `Settings → Secrets and variables → Actions → New repository secret`:
   - `META_ACCESS_TOKEN` — Meta System User token with `ads_read`, limited to intended advertising accounts.
   - `META_AD_ACCOUNT_IDS` — comma-separated numeric Meta Ads account IDs, no `act_` prefix necessary.
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — entire Google service-account JSON key, stored ONLY in GitHub Secrets. Rotate when compromised.
   - `GOOGLE_SHEET_ID` — spreadsheet ID for the ads-only cost tracker workbook.
3. Open `Actions → GLA HR — Meta Ads daily sync → Run workflow`. First choose `dry_run=true`, review logs. Only then use `dry_run=false`. **Scheduled sync will attempt a production run daily at roughly 07:15 Vietnam time**, once secrets are present.

**Security:** Public contributors cannot access these secrets through fork PR workflows. However, any code merged to the protected default branch can access them via scheduled jobs. Limit push access and review changes to `src/` and `.github/workflows/` carefully. Avoid `pull_request_target` and log requests/responses without redacting credentials. For higher security consider Google Workload Identity Federation instead of a long-lived JSON key.

## Data contract and controls

- Only aggregates: spend, impressions, clicks, Meta-reported lead actions per campaign/day. Does NOT retrieve personal lead identities.
- `META_RAW!A:I`: `date, campaign_id, campaign, spend, impressions, clicks, actions_lead, account_currency, ad_account_id`. Date is a Google serial; IDs must be text; currency must be VND.
- Upsert/dedupe key: `(ad_account_id, date, campaign_id)`; rolling 8-day re-fetch. Historical rows kept.
- `CHIEN_DICH_META`: add new campaign IDs with explicit mapping review; never guess factory except clear Pegatron name.
- Read/write limited to the ads-related source/mapping/checkpoint tabs; does not touch applicant personal information or bonus records.
- Refuses write on duplicate keys, insufficient capacity, unexpected missing data, wrong currency, or malformed schema.
- Source changes trigger separate unit tests; tests never read production secrets.

To test locally (no Meta credentials necessary):

```bash
python -m pip install -r requirements.txt
pytest -q
```

See `docs/GOOGLE_SHEET_INTEGRATION.md` for schema and `docs/INSTALLATION_STATUS.md` for deployment status.
## V1.1 – automatic recovery and independent watchdog

V1.1 adds the private **`META_SYNC_HEALTH`** tab in the destination Google Sheet (not this public repo), with one SUCCESS checkpoint per Vietnam calendar day and account scope. The checkpoint is written **only after** the ads upsert and campaign-mapping updates succeed. If any earlier step fails, retries may safely execute the same idempotent upsert again.

- **07:15 ICT:** primary daily scan (Meta API already includes up to five HTTP retries on transient failures).
- **07:25, 07:45, 08:15 ICT:** independent scheduled retry opportunities; skip if today's SUCCESS checkpoint already exists.
- **09:10, 12:10 ICT:** separate watchdog workflow verifies the checkpoint and attempts the same safe backfill if missing. An unresolved failure appears as a failed GitHub Actions run.
- Normally refreshes the latest **8 days**. If an earlier SUCCESS checkpoint shows several missed days, catch-up expands to cover the entire gap (up to 90 days). Gaps beyond 90 days fail explicitly rather than silently discarding history.
- **No additional GitHub Secrets required.** Manual `workflow_dispatch` in the daily workflow still supports `dry_run=true` or `false`.

GitHub schedules are **best effort**, not an SLA: delayed/dropped schedules are possible, and public-repo schedules can be disabled after 60 days without activity. Recovery cannot fix revoked tokens, revoked Google permissions, invalid currency, spreadsheet schema errors or quota restrictions. It never assumes the absence of new daily ads rows is itself an API failure when historical Meta data is returned.

## Ads-only workbook reset (2026-11-11)

The connected Google Sheet was reduced **in place** from 19 tabs to 7, with the spreadsheet ID unchanged, so no GitHub Secret changes were necessary. A full backup copy of the 19-tab source is retained privately in the user's Google Drive.

The surviving tabs are:

1. `BAO_CAO_ADS_TUAN` — **main weekly cost report**, Sunday–Saturday, last completed week + current incomplete week + 12-week history.
2. `CHI_PHI_ADS_NHOM` — separate rolling **30-day** cost view.
3. `META_ADS_NGAY` — date/campaign metrics from `META_RAW` + type/factory lookups.
4. `CHIEN_DICH_META` — campaign ID → recruitment category / optional factory mapping.
5. `META_RAW` — the 9-column daily source write target; **schema unchanged**.
6. `META_SYNC_HEALTH` — daily SUCCESS checkpoint for retries and watchdog; **schema unchanged**.
7. `HUONG_DAN_ADS` — ads-only rules and connection documentation (replaces old mixed-purpose `THIET_LAP_API`).

All previous ATS/lead/payout/revenue sheets, including the old mixed `DASHBOARD_360`, were removed from the **working** workbook; data remains in the private backup. No program references those removed tabs. Do not restore old dashboard formulas without reintroducing their dependencies.
