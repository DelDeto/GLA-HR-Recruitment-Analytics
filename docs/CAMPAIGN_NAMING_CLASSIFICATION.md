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
