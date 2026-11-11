# Deployment status

## Completed
- Prepared public-safe GitHub Actions source and CI tests.
- Destination Sheet bootstrap already performed: nine-column `META_RAW`, 410 historical rows labeled with source account, 6000-row capacity, 202 dependent formulas updated.
- Prior dashboard KPI values verified unchanged.

## Still required (do not claim production live)
1. Push project source to the existing public repository.
2. Add four Actions Secrets: `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_IDS`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID`.
3. Ensure Google Cloud service account has Editor permission on the intended spreadsheet and the Sheets API is enabled.
4. Run manual dry-run to verify live Meta/Google access, then actual run with `dry_run=false`.
5. Scheduled production starts after all configuration is valid.

No personal candidate data or secret values may be committed or printed in logs.
