# 数据库表结构

## dunhill_pdt_group_by_skc

SKC 维度的商品信息汇总表。新增记录使用 `season_by_code` 列为空作为标记。

| 列名 | 类型 | 说明 |
|------|------|------|
| skc | varchar | SKC 编码 |
| category | varchar | 品类 |
| season_by_arrival | varchar | 到店季节 |
| season_by_code | varchar | 编码季节（新增标记用，为空表示本次新增） |
| commercial_line | varchar | 产品线 |
| main_category | varchar | 主品类 |
| division | varchar | 部门 |

## dunhill_pdt_line_by_sku

SKU 维度的 OMS 商品信息表。

| 列名 | 类型 | 说明 |
|------|------|------|
| 货号 | varchar(100) | SPU 编码 |
| 平台对接码 | varchar(100) | OMS SKU 编码 (UNIQUE KEY) |
| 商品名称 | text | 商品名称 |
| 吊牌价 | int | 当前吊牌价 |
| 商品条码 | text | 商品条码 |
| OMS品类 | text | 品类（来自 OMS 开票名称） |
