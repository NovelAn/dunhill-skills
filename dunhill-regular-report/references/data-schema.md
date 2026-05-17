# Data Schema

## Excel Structure Overview
12 sheets total: 9 transformed + 3 raw data

## Sheet Inventory
| # | Sheet Name | Rows | Cols | Type | Description |
|---|------------|------|------|------|-------------|
| 1 | DUN全品牌表 / Dashboard | 118 | 17 | Transformed | Brand-level dashboard |
| 2 | Calc_Engine | 29 | 12 | Transformed | Calculation engine |
| 3 | Dashboard (PFS Sales Driver Tree) | 57 | 24 | Transformed | PFS sales driver tree |
| 4 | 品牌tracking | 163 | 94 | Transformed | Brand tracking |
| 5 | 退款明细 | 276 | 57 | Transformed | Refund details |
| 6 | 流量渠道 | 83 | 17 | Transformed | Traffic channels |
| 7 | 客户细分 | 54 | 57 | Transformed | Customer segmentation |
| 8 | channelMapping | 23 | 2 | Reference | Channel mapping reference |
| 9 | 竞品分析 | 56 | 39 | Transformed | Competitor analysis |
| 10 | 全店铺数据 | 842 | 141 | Raw Data | Full store data |
| 11 | PFS_数据源 | 10452 | 75 | Raw Data | PFS data source (SKU/order level) |
| 12 | 竞品数据 | 9407 | 11 | Raw Data | Competitor data |

## Dimension → Sheet Mapping
| Analysis Dimension | Data Source Sheets | Key Fields |
|-------------------|-------------------|------------|
| 销售表现 | 全店铺数据, Dashboard | daily NET/GMV, targets, PayWeek |
| 商品结构 | PFS_数据源, 全店铺数据 | SKU, category, division, netsales, disc |
| 客户分析 | 客户细分, PFS_数据源 | 新老客, RFM, category×customer |
| 退款售后 | PFS_数据源(筛选退款订单), 退款明细 | 退款率, 退款原因, 品类维度 |
| 流量概览 | 流量渠道, 全店铺数据 | UV, paid/free traffic |
| 竞品概况 | 竞品分析, 竞品数据 | 竞品GMV, 份额 |

## Key Fields
Common key fields found across sheets:
- stat_date (YYYY-MM-DD format)
- all_suc_ns (NET Sales)
- gmv (GMV)
- uv
- buyers
- netsales
- disc (discount rate)
- category, division
- PayYear, PaySeason, PayMonth, PayWeek

## Data Loading Strategy
1. User specifies Excel path
2. Auto-detect sheet names and structure
3. Read transformed data aggregated metrics first (fast)
4. Load raw data on-demand during deep dive (slow, SKU/order level)
5. Cache parsed results within session