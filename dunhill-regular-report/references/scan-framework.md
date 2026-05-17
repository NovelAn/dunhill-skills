# Scan Framework

## Overview
Auto Scan is Phase 2 of the workflow. It performs a rapid scan across all dimensions to produce a Findings Checklist. It does NOT produce a complete analysis — only flags items worth investigating.

## Priority
All metrics follow: NET > GMV > RRC > CVR > ATV > AUR > UPT

## Deep Scan Dimensions (深度扫描)

### 1. 销售表现
Checks:
- Current NET/GMV vs target → achievement rate
- WoW (vs prior week) and YoY (vs same period last year) change
- Daily sales trend → flag days with >20% spike or drop
- PayWeek comparison → identify which weeks over/under-performed

Thresholds:
- Achievement rate < 90% → 🔴 risk
- Achievement rate 90-100% → 🟡 attention
- Achievement rate > 100% → 🟢 highlight
- Daily fluctuation > ±20% → flag as anomaly

### 2. 商品结构
Checks:
- Category NET/GMV contribution share and change vs prior period
- Top 10 / Bottom 10 SKU by NET/GMV, note discount rate
- Average discount rate trend → flag consecutive deepening (>2 weeks)
- UPT change

Thresholds:
- Discount rate drop > 5pp vs prior period → 🟡 attention
- Category share shift > 3pp → flag
- SKU falling out of Top 10 or entering Bottom 10 → flag

### 3. 客户分析（含交叉）
Checks:
- New vs returning customer ratio and NET contribution
- ATV by segment and change
- Repurchase rate trend
- Member penetration rate
- Customer × Category cross: new vs returning spend distribution by category
- Customer × Price band cross: segment price preference shifts
- Customer × Discount cross: discount dependency by segment

Thresholds:
- New customer ratio shift > 5pp → flag
- Repurchase rate drop > 3pp → 🟡 attention
- Member penetration new high → 🟢 highlight

### 4. 退款售后
Checks:
- Overall RRC and trend
- Refund reason distribution (top 3 reasons)
- RRC by category → identify worst-performing categories
- NET erosion ratio: Refund Amount / NET Sales

Thresholds:
- RRC > 10% → 🔴 risk
- RRC increase > 2pp vs prior period → 🟡 attention
- Single category RRC > 15% → 🔴 risk

## Light Scan Dimensions (轻量扫描)

### 5. 流量趋势
Checks:
- Total UV trend
- Paid vs free traffic ratio change
- Flag obvious spike/drop days (no deep attribution)

Note: Alibaba platform traffic attribution algorithm changes frequently; do NOT make deep comparisons across periods.

### 6. 竞品概况
Checks:
- Competitor GMV ranking changes
- Our store share position
- No deep attribution (competitor data is incomplete)

## Findings Checklist Output Format
```
🔴 [风险] description + data evidence
🟡 [关注] description + data evidence
🟢 [亮点] description + data evidence
```
Each finding must include:
- Severity emoji + tag
- One-sentence summary
- Specific data reference (sheet, field, value)