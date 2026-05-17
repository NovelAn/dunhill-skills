---
name: dunhill-regular-report
description: "Interactive e-commerce data analysis for Dunhill Tmall flagship store. Reads Excel data source (weekly sales data with transformed dashboards and raw SKU/order data), performs automated scan for anomalies and highlights across sales performance, product structure, customer analysis (with customer x product cross-analysis), and refund analysis. Supports interactive deep-dive with user. Generates structured Markdown report and syncs to Feishu cloud document. Trigger when user invokes /dunhill-regular-report, asks to analyze Dunhill Tmall weekly/monthly sales data, provides an Excel file matching the Dunhill weekly data source structure (12 sheets - 9 transformed + 3 raw), or wants to generate a Dunhill data analysis report for WTD, MTD, or custom period."
---

# Dunhill Regular Report

Interactive e-commerce data analysis skill for Dunhill Tmall flagship store. Four-phase workflow: Data Ingestion → Auto Scan → Interactive Deep Dive → Report Generation.

## Core Rules

1. **Metric priority:** NET > GMV > RRC > CVR > ATV > AUR > UPT — always follow this order
2. **Data-driven, no fabrication** — all conclusions must trace to specific data cells; mark uncertain items [待确认]
3. **Separate facts from inferences** — "数据显示..." (fact) vs "可能原因是..." (inference); tag inference confidence: [高置信] [中置信] [低置信] [待确认]
4. **When uncertain, ask user** — data contradictions, unclear caliber, or insufficient sample → stop and ask
5. **Customer analysis must include customer × product cross-analysis** (category, price band, discount)
6. **Deep dimensions:** sales performance, product structure, customer×product cross, refund; **Light dimensions:** traffic trends, competitor overview

## Workflow

### Phase 1: Data Ingestion

1. Determine period: default MTD, or parse from user args (--period WTD/MTD/date:date)
2. Locate Excel file: user-specified via --file, or ask user for path
3. **Read [references/data-caliber-notes.md](references/data-caliber-notes.md) first** — contains known data interpretation pitfalls that must be avoided
4. Run `scripts/load_excel.py <path> --summary` to get sheet inventory
4. Read [references/data-schema.md](references/data-schema.md) for sheet mapping
5. Load transformed data sheets first (fast, aggregated metrics)
6. Load raw data sheets on-demand during deep dive (slow, SKU/order level)
7. Confirm data loaded and present key date range to user

### Phase 2: Auto Scan

Read [references/scan-framework.md](references/scan-framework.md) for detailed scan instructions.

Scan all 6 dimensions and produce a Findings Checklist:
- Deep scan: sales performance, product structure, customer analysis (with cross), refund
- Light scan: traffic trends, competitor overview

Output format:
```
🔴 [风险] description + data evidence
🟡 [关注] description + data evidence
🟢 [亮点] description + data evidence
```

Present checklist to user, then ask which findings to deep-dive.

### Phase 3: Interactive Deep Dive

Read [references/deep-dive-rules.md](references/deep-dive-rules.md) for interaction rules.

Support 4 interaction modes:
1. User selects finding numbers
2. User asks free-form questions
3. Follow-up chain (drill into segment, period, or granularity)
4. Dimension switch (user changes focus)

For each analysis: data facts → possible causes → recommendations → confidence level.

Exit when user says "差不多了", "可以出报告了", or similar.

### Phase 4: Report Generation

Read [references/report-spec.md](references/report-spec.md) for report structure.

1. Use `assets/report-template.md` as the report skeleton
2. Fill in all sections with analysis results from Phase 2-3
3. Save locally: `reports/YYYY-MM-DD-dunhill-[周期类型]-分析报告.md`
4. Sync to Feishu: `bash scripts/sync_feishu.sh <report_file> "<title>"`
5. Return both local path and Feishu document URL

## Resources

- `references/metric-definitions.md` — indicator definitions, formulas, priority chain
- `references/data-schema.md` — Excel sheet structure, field mapping, loading strategy
- `references/scan-framework.md` — scan instructions, thresholds, checklist format
- `references/deep-dive-rules.md` — interaction modes, AI behavior rules, exit signals
- `references/report-spec.md` — report structure, naming, Feishu sync flow
- `references/data-caliber-notes.md` — known data interpretation pitfalls, must-read before analysis
- `scripts/load_excel.py` — Excel parser (run to load data)
- `scripts/sync_feishu.sh` — Feishu CLI document sync
- `assets/report-template.md` — report output template
