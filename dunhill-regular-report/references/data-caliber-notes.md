# Data Caliber Notes

> 本文档记录数据分析过程中的数据解读错误和口径说明，避免重复犯错。
> 每次分析中发现新的口径问题时应追加到此文档。

## 通用规则

### 百分数字段
Excel 中部分百分比字段以小数形式存储（如 0.6415 表示 64.15%），读取时 **必须 × 100** 并以 `%` 呈现。

涉及字段：
- `paydate_rrc` → 0.6415 = **64.15%**（不是 0.64%）
- `cancel_rate` → 0.2432 = **24.32%**（不是 0.24%）
- `paydate_return_rate` → 0.3983 = **39.83%**
- `paydate_rrc_yoy` → 0.1605 = **+16.05pp**（同比变化量，单位是百分点）
- `net_sales%` → 占比，需 × 100（如 0.6559 = 65.59%）

**判断方法：** 如果字段名包含 `rate`、`rrc`、`%` 且值在 0~1 之间，大概率是百分数，需 × 100。

### YoY 字段
- `netsales_yoy` = 同比增长率（如 0.0986 = **同比+9.86%**），不是同比绝对值
- `netunits_yoy` = 同比增长率（如 1.333 = **同比+133.3%**）
- `*_yoy` 后缀字段均为增长率，不是绝对值或占比

## Sheet 间列布局差异

### 客户分析 vs 退款分析
两个 sheet 的列顺序**不同**，不能假设相同列索引对应相同字段。

**退款分析列顺序（R8）：**
| 索引 | 字段 |
|------|------|
| 4 | net_sales |
| 5 | net_sales% (占比) |
| 6 | netsales_yoy (同比) |
| 7 | paydate_rrc |
| 8 | paydate_return_rate |
| 9 | cancel_rate |

**客户分析列顺序（new/old 汇总行）：**
| 索引 | 字段 |
|------|------|
| 5 | net_sales |
| 6 | net_sales% (占比) |
| 7 | netsales_yoy (同比) |
| 8 | net_clients (客户数，不是 net_sales) |
| 9 | net_clients% (客户占比) |
| 10 | net_clients_yoy (客户数同比) |
| 11 | paydate_rrc |
| 12 | paydate_return_rate |
| 13 | cancel_rate |

**错误案例：** 曾将客户分析 col8（net_clients=58）误读为 net_sales，将 net_sales%（占比 65.6%）误读为同比增幅（实际同比仅 +9.86%）。

### 正确的读取方法
每个 sheet 应先读取 header 行，根据字段名确认列映射，**不要跨 sheet 假设列索引一致**。

## Dashboard Sheet 特殊布局

Dashboard 不是标准表格，而是散点布局：
- Gross Sales 在 R18（col6）
- NET Sales 在 R25（col6）
- 各指标分散在不同行，需按行号定位而非列名

## 数据源 Sheet 清单

不需要分析的 sheet：
- `DUN全周期报数` — 不参与任何分析，不是引用源

## PFS_订单源 raw sheet 混合年份问题

PFS_订单源 sheet 同时包含 BU27（当年）和 BU26（去年）对比数据，以及无付款日期的 SKU 主数据（~9600 行）。

**必须用 `付款日期.year == 2026 AND 付款日期.month == 4` 过滤，不能用 `pay_month == 4`。**

- `pay_year` 列有三种值：`BU27`（247 行）、`BU26`（560 行）、`None`（9644 行）
- 仅 `pay_year == 'BU27'` 不能覆盖全部当年数据（部分当年数据 pay_year 为 None）
- **可靠过滤条件：** `isinstance(付款日期, datetime) and 付款日期.year == 2026`

**错误案例：** 曾用 `pay_month == 4` 过滤，混入了去年数据，导致 SHIRTS Cancel Rate 从实际 25% 被高估到 71.4%（混入 10 笔去年 cancel 订单）。
