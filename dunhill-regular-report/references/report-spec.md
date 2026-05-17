# Report Specification

## File Naming
Pattern: `YYYY-MM-DD-dunhill-[周期类型]-分析报告.md`
Examples:
- `2026-04-20-dunhill-周报-分析报告.md`
- `2026-04-20-dunhill-月报-分析报告.md`
- `2026-04-20-dunhill-专项-分析报告.md`

## Period Labels
| Mode | Title Example | Analysis Range |
|------|--------------|----------------|
| MTD (default) | [Dunhill 月报] 2026-04 MTD | Month start to today |
| WTD | [Dunhill 周报] 2026-W03 04-14 ~ 04-19 | Week start to today |
| Custom | [Dunhill 专项] D11 预售期分析 | User-specified range |

## Report Structure
See `assets/report-template.md` for the full template. Key sections:

1. **Header** — Period, data cutoff, generation time
2. **Executive Summary** — 3-5 sentences, top 1-2 action items
3. **核心指标概览** — KPI table (NET, GMV, RRC, CVR, ATV, AUR, UPT) with target, achievement, WoW, YoY
4. **一、销售表现** — NET/GMV priority, target achievement, trends
5. **二、商品结构** — Category contribution, SKU ranking, discount trends
6. **三、客户分析** — New/returning, ATV, repurchase, member, customer×product cross-analysis
7. **四、退款售后** — RRC trends, reasons, category differences
8. **五、流量概览** — UV trend, channel mix, anomaly flags (lightweight)
9. **六、竞品概况** — Share, ranking changes (lightweight)
10. **深挖分析** — Content from interactive deep dive phase
11. **建议与行动项** — Prioritized actionable recommendations, tagged [数据支撑] or [待确认]
12. **附录** — Data caliber notes, uncovered areas

## Content Rules
- All numbers must reference actual data — no fabrication
- Tag uncertain items with [待确认]
- Distinguish facts ("数据显示...") from inferences ("可能原因是...")
- Inference confidence levels: [高置信], [中置信], [低置信], [待确认]

## Output Locations

### Local
Save to project directory: `reports/YYYY-MM-DD-dunhill-[周期类型]-分析报告.md`

### Feishu (飞书)
After local save, sync to Feishu via CLI:
1. Create/update cloud document in target knowledge base folder
2. Document title: `[Dunhill 月报] 2026-04 MTD` (auto-formatted by period)
3. Convert Markdown to Feishu rich text format
4. If same-period report exists → update (preserve comments/annotations)
5. Return document URL for sharing

## Feishu Sync Script
Use `scripts/sync_feishu.sh` for the actual sync operation.