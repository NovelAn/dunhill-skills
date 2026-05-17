# Metric Definitions

## Priority Chain

All analysis dimensions follow this indicator priority: **NET > GMV > RRC > CVR > ATV > AUR > UPT**

## Indicators

### NET Sales (净销售额)
- Priority: 1 (highest)
- Definition: Revenue after deducting returns and refunds
- Formula: GMV - Refund Amount
- Notes: The most important metric — reflects actual revenue retained

### GMV (Gross Merchandise Value)
- Priority: 2
- Definition: Total transaction value including all orders
- Notes: Gross figure before returns; always pair with RRC to understand NET gap

### RRC (Return & Refund Rate)
- Priority: 3
- Definition: Proportion of GMV returned/refunded
- Formula: Refund Amount / GMV × 100%
- Notes: Bridge between GMV and NET; rising RRC directly erodes NET

### CVR (Conversion Rate)
- Priority: 4
- Definition: Proportion of visitors who complete a purchase
- Formula: Orders / UV × 100%
- Notes: Efficiency indicator; sensitive to traffic quality and landing page experience

### ATV (Average Transaction Value)
- Priority: 5
- Definition: Average revenue per order
- Formula: GMV / Orders
- Notes: Reflects basket size and cross-sell effectiveness

### AUR (Average Unit Retail)
- Priority: 6
- Definition: Average price per unit sold
- Formula: GMV / Units Sold
- Notes: Reflects product mix and discount depth

### UPT (Units Per Transaction)
- Priority: 7
- Definition: Average number of units per order
- Formula: Units Sold / Orders
- Notes: Cross-sell and attachment rate indicator

## Dimension-Specific Metrics

### Sales Performance
- Daily NET/GMV trend
- Target achievement rate: Actual / Target × 100%
- WoW (Week-over-Week) change
- YoY (Year-over-Year) change
- PayWeek comparison

### Product Structure
- Category NET/GMV contribution share
- SKU-level NET/GMV ranking
- Average discount rate: Actual Price / Tag Price × 100%
- Discount depth trend

### Customer Analysis
- New vs returning customer ratio (by count and by NET)
- Average order value by customer segment
- Repurchase rate
- Member penetration rate
- Cross-analysis: customer × category, customer × price band, customer × discount

### Refund & After-sales
- Overall RRC
- RRC by category
- RRC by channel
- Refund reason distribution
- NET erosion ratio: Refund Amount / NET Sales
