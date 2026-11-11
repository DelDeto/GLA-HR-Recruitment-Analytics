# GLA HR – Meta Ads Direct Sync (GitHub Actions)

Automated campaign-level Meta Marketing API → Google Sheets sync. Uses standard GitHub-hosted `ubuntu-latest` runners, which are free in public GitHub repositories under GitHub's current Actions billing policy.

**Public repository:** This repository intentionally contains only application code, tests, and non-sensitive instructions. Account IDs, spreadsheet ID, token, and Google credentials are deliberately excluded. Do not commit PII, resumes, lead forms, exported sheets, API tokens, or service-account keys.

## One-time configuration (maintainer only)

1. Create a Google Cloud **service account**, enable the **Google Sheets API**, and share the destination Google Sheet with its `client_email` as an **Editor**. Give it access only to the required spreadsheet.
2. Add the following **Actions repository secrets** via `Settings → Secrets and variables → Actions → New repository secret`:
   - `META_ACCESS_TOKEN` — Meta System User token with `ads_read`, limited to intended advertising accounts.
   - `META_AD_ACCOUNT_IDS` — comma-separated numeric Meta Ads account IDs, no `act_` prefix necessary.
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — entire Google service-account JSON key, stored ONLY in GitHub Secrets. Rotate when compromised.
   - `GOOGLE_SHEET_ID` — spreadsheet ID for the existing dashboard workbook.
3. Open `Actions → GLA HR — Meta Ads daily sync → Run workflow`. First choose `dry_run=true`, review logs. Only then use `dry_run=false`. **Scheduled sync will attempt a production run daily at roughly 07:15 Vietnam time**, once secrets are present.

**Security:** Public contributors cannot access these secrets through fork PR workflows. However, any code merged to the protected default branch can access them via scheduled jobs. Limit push access and review changes to `src/` and `.github/workflows/` carefully. Avoid `pull_request_target` and log requests/responses without redacting credentials. For higher security consider Google Workload Identity Federation instead of a long-lived JSON key.

## Data contract and controls

- Only aggregates: spend, impressions, clicks, Meta-reported lead actions per campaign/day. Does NOT retrieve personal lead identities.
- `META_RAW!A:I`: `date, campaign_id, campaign, spend, impressions, clicks, actions_lead, account_currency, ad_account_id`. Date is a Google serial; IDs must be text; currency must be VND.
- Upsert/dedupe key: `(ad_account_id, date, campaign_id)`; rolling 8-day re-fetch. Historical rows kept.
- `CHIEN_DICH_META`: add new campaign IDs with explicit mapping review; never guess factory except clear Pegatron name.
- Read/write restricted to the two designated tabs. Does not touch applicant personal information or bonus records.
- Refuses write on duplicate keys, insufficient capacity, unexpected missing data, wrong currency, or malformed schema.
- Source changes trigger separate unit tests; tests never read production secrets.

To test locally (no Meta credentials necessary):

```bash
python -m pip install -r requirements.txt
pytest -q
```

See `docs/GOOGLE_SHEET_INTEGRATION.md` for schema and `docs/INSTALLATION_STATUS.md` for deployment status.