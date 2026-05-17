# SKC 提取规则

基于 `dunhill_pdt_info_by_sku` 视图中 17,957 条记录分析，100% 一致。

## 规则优先级

1. PIPES 品类：SKU == SKC（始终精确匹配）
2. 品类特定规则（优先检查）
3. 通用规则（按 SKU 长度）

## 品类特定规则

| SKU 长度 | 品类 | 提取 N 值 |
|----------|------|-----------|
| 14 | TIES, TIES | 13 |
| 15 | JERSEY | 12 |
| 13 | FOOTWEAR | 9 |
| 16 | LUCKYBAG | 16 (精确匹配) |
| 11 | BELTS | 9 |

## 通用规则

| SKU 长度 | 提取 N 值 | 说明 |
|----------|-----------|------|
| 17 | 14 | 主流情况，约 80% 的记录 |
| 16 | 14 | |
| 15 | 14 | |
| 14 | 11 | 旧式服装 SKU |
| 13 | 13 | EYEWEAR 精确匹配 |
| 12 | 12 | GIFTING 精确匹配 |
| 11 | 11 | |
| 10 | 10 | EYEWEAR, FRAGRANCE, JEWELLERY 等 |
| 9 | 9 | LARGE LEATHER, SMALL LEATHER 等 |
| 8 | 8 | OTHER SMOKERS, SMOKERS CONSUMABLES |

## SPU 提取规则（反向：从 SKC 提取 SPU）

SPU 是 SKC 的前缀，SKC = SPU + 颜色编码。颜色编码长度因品类而异。

### 数据来源

基于 `dunhill_pdt_group_by_skc` 与 `dunhill_pdt_line_by_sku` 的 JOIN 匹配数据分析。

### 规则

| 品类 | SKC 长度 | SPU 提取方式 | 颜色码位数 |
|------|----------|-------------|-----------|
| PIPES | 任意 | SPU = SKC（精确匹配） | 0 |
| FRAGRANCE | 10 | SPU = SKC（精确匹配） | 0 |
| OTHER SMOKERS | 8 | SPU = SKC（精确匹配） | 0 |
| SMOKERS CONSUMABLES | 8 | SPU = SKC（精确匹配） | 0 |
| LUCKYBAG | 16 | SPU = SKC[:15] | 1 |
| EYEWEAR | 13 | SPU = SKC[:10] | 3 |
| FOOTWEAR | 9 | SPU = SKC[:8] | 1 |
| **其他所有品类** | **14** | **SPU = SKC[:11]** | **3** |

### 默认 fallback

如果 SKC 长度不在上述规则中，SPU = SKC（原样保留，不做截取）。

### 使用场景

- 找出 SKC 表中有但 SKU 表中缺失的记录时，需要提取 SPU 去 OMS 搜索补录
- OMS 搜索使用的是 SPU（货号），不是 SKC

## 实现代码

规则定义在 `db_helper.py` 的 `_SKC_N_RULES` 列表中，提取函数为 `sku_to_skc_by_rule(sku, category)`。

优先级：遍历规则表，先匹配品类特定规则，再匹配通用规则，最后 fallback 为精确匹配。
