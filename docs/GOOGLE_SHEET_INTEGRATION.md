# Google Sheets integration contract (internal ID intentionally withheld)

Provide the actual spreadsheet ID via GitHub Actions secret `GOOGLE_SHEET_ID`.

Columns of `META_RAW` must remain:

| Column | Field | Data type |
|---|---|---|
| A | date | Google Sheets date serial |
| B | campaign_id | text |
| C | campaign | text |
| D | spend | numeric VND |
| E | impressions | integer |
| F | clicks | integer |
| G | actions_lead | Meta ad-reported lead metric |
| H | account_currency | `VND` |
| I | ad_account_id | text |

Only ads reports (`BAO_CAO_ADS_TUAN` for Sunday–Saturday and `CHI_PHI_ADS_NHOM` for a distinct rolling 30-day view) read through `META_ADS_NGAY`; source data belongs in `META_RAW`. The script does not touch employee/ATS or payment data. It can add new campaign metadata in `CHIEN_DICH_META` but deliberately leaves most factory mapping unresolved.

Destination workbook was prepared 11 November 2026: 410 existing snapshot rows backfilled with their account ID, `META_RAW` expanded to 6000 rows, `META_ADS_NGAY` to 6002, and 202 dependent formulas updated. The capacity guard requires manual expansion once those limits are reached.

**Do not add API tokens or Google credentials to any Sheet cell.**

## V1.1 status tab

`META_SYNC_HEALTH` is a Google Sheet tab reserved for successful sync checkpoints (no candidate data). Header A:I:

`run_date_ict, account_ids, finished_at_ict, status, fetched, changed, appended, new_campaigns, run_type`

Only `SUCCESS` after a complete production upsert qualifies. Watchdog/retries read it to avoid duplicate work. Account scope is a sorted comma-separated list. Workbook capacity is 1,200 rows; if exhausted, sync fails closed and requires range extension.

This tab is part of the **private destination spreadsheet** and does not expose account IDs in the public Git repository.

## Working workbook after 11 Nov 2026 cleanup

Exactly seven tabs remain: `BAO_CAO_ADS_TUAN`, `CHI_PHI_ADS_NHOM`, `META_ADS_NGAY`, `CHIEN_DICH_META`, `META_RAW`, `META_SYNC_HEALTH`, `HUONG_DAN_ADS`.

The native Sheet's spreadsheet ID and existing GitHub Actions secrets were preserved. Ads source data, campaign mappings, formula-driven reports, and health checkpoints were verified after removing 12 non-Ads tabs. The private full pre-cleanup backup preserves every original tab.

**Reporting grain:** last fully completed Sunday–Saturday week for the main report, a clearly separate incomplete current-week view, and an explicitly labeled rolling 30-day view. LĐPT costs are split by factory; IDL costs are classified by Engineers, Interns (SV) and Fresh Graduates (Fresher). Unverified factory abbreviations remain flagged and are never silently assigned.
