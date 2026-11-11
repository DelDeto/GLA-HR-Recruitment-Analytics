# Campaign naming → recruitment cost segmentation

Google Sheet V5.0 contains two independent dimensions:
- **Factory**: `CHIEN_DICH_META!C` (must be confirmed; ambiguous abbreviations are left `CHƯA GÁN`)
- **Recruitment group**: `CHIEN_DICH_META!H` (automatically inferred from the campaign name, with optional override in column I)

## Classification priority (case-insensitive)
1. `LĐPT - ...` → **Lao động phổ thông**
2. `IDL - SV - ...` or `IDL SV ...` → **Thực tập sinh**
3. `IDL - ... - Fresher` → **Cán bộ nguồn** (graduated students)
4. Other `IDL - ...` → **Kỹ sư**
5. Other names → **CHƯA PHÂN LOẠI**, review required

The priority matters: `IDL - SV` and `IDL - Fresher` must never be grouped into generic engineers. A new campaign automatically inherits the type calculation from the Sheet's `ARRAYFORMULA` in `CHIEN_DICH_META!H2`. Manual correction is available in column I, while column J shows how the label was assigned.

**Meta campaign mapping is by Meta Campaign ID**, not fuzzy name matching. Different campaigns with similar names remain distinct.

## Reporting
- `META_RAW!A:I`: campaign/day/account Meta data from GitHub Actions (unchanged).
- `META_ADS_NGAY!M`: looked-up recruitment group; its previous columns A:L remain intact.
- `CHI_PHI_ADS_NHOM`: live **30-calendar-day rolling** aggregation by factory × recruitment group, with spend, Meta-reported leads and CPL. Its totals should reconcile with a 30-day filtered sum of `META_RAW`.
- `CHIEN_DICH_META!D:E`: matching **rolling 30-day** spend and Meta lead totals for each individual campaign; Python appends these formulas to newly discovered campaigns.
- `DASHBOARD_360`: overall 30-day Meta spend and lead metrics now use 30-day conditions.

## Data quality rules
- Do **not** guess what abbreviations such as `EV QN`, `FK`, `GTK`, `HSI`, `LG`, `FECV`, or `CCTY` mean. Existing mapping for these stays `CHƯA GÁN` until confirmed by GLA.
- `CHƯA GÁN` still contributes spend and leads to the totals. It is a data-quality bucket, not a zero cost.
- `Meta Leads` are the figures reported by the ads API, not identifiable candidates, and **CPL Meta** is spend per reported lead. Do not present it as recruitment cost per actual hire unless worker-level lead/campaign IDs and hiring outcomes have been reconciled.
- Do not publish business account IDs, spreadsheet links, credentials, candidate names or lead contact data in this public repository.

## One-time Sheet changes (already applied)
- Additional formula-driven H/J columns and manual override I in `CHIEN_DICH_META`.
- New M column in `META_ADS_NGAY`.
- New `CHI_PHI_ADS_NHOM` live report.
- Existing 32 campaign mappings classified without modifying factory-mapping column C.

## Weekly accounting rule (approved by GLA HR on 2026-11-11)

- **One reporting week is Sunday 00:00 through Saturday 23:59:59, Asia/Ho_Chi_Minh (UTC+7); 7 calendar days inclusive.**
- The private native Google Sheet tab `BAO_CAO_ADS_TUAN` uses `=TODAY()-WEEKDAY(TODAY(),1)-6` for the Sunday of the **most recently completed** week, and adds 6 days for Saturday. This is an automatically moving weekly report, not a Monday→Sunday report.
- Current (incomplete) week is displayed separately and explicitly labeled as incomplete.
- For completed weeks, report **LĐPT by factory** and the three **IDL recruitment types** (Engineers, Students/Interns, Fresh Graduates/Talent Pipeline). Unmapped factories remain flagged without discarding or reassigning spend.
- `DASHBOARD_360` includes a compact last-completed-week summary and links to the weekly report. `CHI_PHI_ADS_NHOM` remains a **separate rolling 30-day view**, clearly labeled. No underlying daily Meta API schedule or source data was altered by this reporting change.
- `BAO_CAO_ADS_TUAN` retains a 12-week trend and marks earlier dates falling outside the source-data coverage as incomplete. Only fully covered weeks are appropriate for week-over-week comparisons.
- Last-completed-week report on 11 Nov 2026: **01–07 Nov 2026**, 14,597,362 VND and 156 Meta-reported leads; spending by group sums to the same total, zero unreconciled cost.
- A one-time independent Windsor.ai comparison on 11 Nov 2026 matched all **98 campaign/day** keys on spend, leads, impressions, and clicks for 01–07 Nov. This is **not** an automatically recurring Windsor comparison; daily scanner still reads Meta directly.
