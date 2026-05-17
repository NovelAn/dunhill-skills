# Task 3: 天猫 tm_id ↔ SKC 映射表更新

从天猫导出数据同步 tm_id ↔ SKC 对照关系到 DB 和目标 Excel。

## 触发条件

收到新的天猫商品导出 Excel（通常命名为 `export_XXXX_YYYYMMDD_HHMMSS_XXXXXXX.xlsx`），需要更新 `dunhill_pdt_tm_id_mapping_skc` 表和 `商品信息配置表.xlsx` 的 `skc_mapping_tm_id` sheet。

## 核心概念

### 数据源

| 来源 | 内容 | 列 |
|------|------|----|
| 天猫导出 Excel | tm_id + SKU/SPU 行 | col[0]=商品ID, col[3]=SKU ID, col[6]=商家编码 |
| DB `dunhill_pdt_tm_id_mapping_skc` | 当前映射 | tm_id, skc, st_date, end_date |
| DB `dunhill_pdt_group_by_skc` | 有效 SKC 主表 | skc |
| DB `dunhill_pdt_info_by_sku` | SKU↔SKC 视图 | col[0]=货号(spu), col[1]=平台对接码(oms_sku) |

### INSERT 预处理格式

DB 的 INSERT 方式需要对 `(tm_id, st_date, end_date)` 做 groupby，SKC 逗号拼接：
```sql
-- 等效于: groupby(["tm_id", "st_date", "end_date"]).agg({'skc': ','.join})
```
因此一个 tm_id 可以对应多个 SKC（逗号分隔），但 `(tm_id, st_date, end_date)` 必须唯一。

### SKU → SKC 提取（天猫场景）

天猫导出**没有品类信息**，只能用通用长度规则：

```python
_SKC_LEN_RULES = {17:14, 16:14, 15:14, 14:11, 13:13, 12:12, 11:11, 10:10, 9:9, 8:8}
```

定义在 `tm_skc_compare.py` 和 `tm_skc_mapping_updater.py` 中，独立于 `db_helper.py` 的品类感知规则。

### PIPES 特殊规则

- `DUDP` / `DUDPZ` 前缀 = PIPES 品类
- SKU == SKC（精确匹配，不截取）
- 来源的编码始终可信，直接导入

### 商家编码清洗

```python
def clean_merchant_code(code):
    code = re.sub(r'&amp;|&|nbsp;', '', code)  # HTML 实体
    return code.strip()
```

## 流程（6 个阶段）

### Stage 1: 比对 (tm_skc_compare.py)

**输入**: 天猫导出 Excel
**输出**: `output/tm_skc_compare_result.xlsx`（6 个 sheet）

```bash
cd ${AI_PROJECTS_DIR}/dunhill-product-info-updater/info-updater
python -u scripts/tm_skc_compare.py
```

步骤：
1. 加载源表，分离 SKU 行（SKU ID not NaN）和 SPU 行
2. 连接 DB，读取当前映射 + 有效 SKC + `dunhill_pdt_info_by_sku` 视图
3. 构建 SPU → SKC 反向映射（用于只有 SPU 行的 tm_id）
4. 对每个 tm_id 提取 SKC 集合
5. 与 DB 比对，分类为：已匹配 / SKC 变化 / 新增 / 已移除
6. 生成 groupby 格式

**编码问题**: Windows 下 pymysql 的 SQL 语句中中文列名会乱码。解决方案是用 `SELECT *` + `cursor.description` 按位置引用列。

### Stage 2: 分类 (人工或脚本)

从比对结果中，将 tm_id 分为三类：

| 类别 | 条件 | 处理 |
|------|------|------|
| `ready_to_add` | 新增 tm_id，SKC 在有效列表中 | 直接导入 |
| `hold_invalid` | 新增 tm_id，SKC 不在有效列表 | 需进一步验证 |
| `review_mismatch` | 已有 tm_id，SKC 变化 | 需人工确认 |

**输出**: `output/tm_skc_action_plan.xlsx`

### Stage 3: 验证无效 SKC (tmp_check_invalid.py)

对 `hold_invalid` 中的 SKC 进行验证：

```bash
python -u scripts/tmp_check_invalid.py
```

验证路径：
1. 在 `dunhill_pdt_info_by_sku` 视图中查找匹配
2. 分类结果：
   - **前缀可扩展**: 源 SKC 是完整 SKC 的前缀 → 取完整版本
   - **古老商品**: 条形码/垃圾编码 → 过滤忽略
   - **DUDP PIPES**: 直接导入
   - **新商品未建档**: 需要在 OMS 中搜索确认

**输出**: `output/tm_skc_invalid_check.xlsx`

### Stage 4: 解决不匹配 (tm_skc_resolve_mismatch.py)

对 `review_mismatch` 中的 153 条记录进行 SKC 调和：

```bash
python -u scripts/tm_skc_resolve_mismatch.py
```

**核心原则**: 源表优先（source-first），源 SKC 为准。

**解决算法** (`resolve_skc` 函数):

```
1. 跳过: TZ- 前缀 / 含下划线 → skip
2. 清洗: 去除尺寸后缀 (XLRZ, XLR, XSR, OLR, OMR, OSR, 2XR, 4XR)
3. 清洗: 去除非 DU/DUDP 前缀
4. 精确匹配: cleaned SKC 在 master 表中 → exact/cleaned
5. DB 前缀匹配: cleaned 是某 DB SKC 的前缀 → db_prefix
6. Master 前缀匹配: cleaned 是某 master SKC 的前缀 → master_prefix
7. 未解决: 以上都不匹配 → unresolved
```

**输出**:
- `output/tm_skc_mismatch_resolved.xlsx`（resolved_detail + groupby_format + unresolved）
- `output/tm_skc_unresolved_13.xlsx`（需人工确认的未解决记录）

### Stage 5: 应用更新 (tm_skc_apply_mismatch.py + tmp_append_*.py)

```bash
# 1. 应用已解决的 mismatch（移除旧记录 + 写入新记录）
python -u scripts/tm_skc_apply_mismatch.py

# 2. 追加验证通过的新记录
python -u scripts/tmp_append_ready.py

# 3. 追加前缀扩展 + 新商品记录
python -u scripts/tmp_append_round2.py

# 4. 追加 DUDPZ PIPES 记录
python -u scripts/tmp_append_dudpz.py
```

**注意事项**:
- 目标 Excel 在网络路径 `\\10.188.9.99\...`，常被锁定 → 保存到本地 `output/`
- 用户需手动复制到网络路径
- 默认日期: st_date=2020-08-07, end_date=9999-12-31

**输出**: `output/skc_mapping_tm_id_updated.xlsx`

### Stage 6: DB 清理 (tm_skc_find_errors.py + tm_skc_find_dup_index.py)

```bash
# 1. 查找错误 SKC（DB 中有但源表无匹配）
python -u scripts/tm_skc_find_errors.py

# 2. 查找重复索引记录（联合索引冲突）
python -u scripts/tm_skc_find_dup_index.py
```

**输出**:
- `output/db_erroneous_skc.xlsx`（delete_candidates sheet → 从 DB 删除）
- `output/db_dup_index_records.xlsx`（需手动调整 st_date/end_date 使其唯一）

## 脚本索引

| 脚本 | 阶段 | 用途 |
|------|------|------|
| `tm_skc_compare.py` | 1 | 源表 vs DB 全量比对 |
| `tm_skc_mapping_updater.py` | - | 旧版一键更新脚本（简单场景可用） |
| `tm_skc_resolve_mismatch.py` | 4 | 不匹配 SKC 调和算法 |
| `tm_skc_apply_mismatch.py` | 5 | 应用调和结果到目标 Excel |
| `tmp_check_invalid.py` | 3 | 无效 SKC 验证 |
| `tmp_append_ready.py` | 5 | 追加验证通过的新记录 |
| `tmp_append_round2.py` | 5 | 追加前缀扩展记录 |
| `tmp_append_dudpz.py` | 5 | 追加 DUDPZ 记录 |
| `tm_skc_find_errors.py` | 6 | 查找 DB 错误 SKC |
| `tm_skc_find_dup_index.py` | 6 | 查找重复索引记录 |

## 常见边界情况

### 历史 tm_id 复用

天猫会复用历史高流量 tm_id 到新商品上。DB 中同一 tm_id 可能映射到完全不同的商品（不同 SKC）。这类情况需要人工确认：
- 如果是 tm_id 换绑了新商品 → 移除旧 SKC，写入新 SKC
- 如果是新 SKC 变体 → 追加新 SKC

### 尺寸后缀

商家编码可能包含尺寸标识，需要去除：
- XLR, XSR, XLRZ（主要）
- OLR, OMR, OSR, 2XR, 4XR（次要）

### 不完整编码

源表商家编码有时是截断的（如 `DUBM004TCB2` 应为 `DUBM004TCB232`）。解决方法：
1. 先查 DB 该 tm_id 下是否有以源编码为前缀的 SKC
2. 再查 master 表前缀匹配
3. 多个匹配时全部纳入（颜色变体）

### Windows 编码问题

- pymysql SQL 中的中文列名在 Windows 下会乱码 → 用 `SELECT *` + `cursor.description`
- Python f-string 中混用中文引号会 SyntaxError → 用 `%` 格式化
- `sys.stdout.reconfigure(encoding='utf-8')` 确保终端输出正常

## DB 表结构

### dunhill_pdt_tm_id_mapping_skc

| 列名 | 类型 | 说明 |
|------|------|------|
| tm_id | varchar | 天猫商品 ID |
| skc | varchar | SKC 编码 |
| st_date | date | 生效日期 |
| end_date | date | 失效日期 |

联合索引: `(tm_id, st_date, end_date)` — 必须唯一，重复记录需手动清理。
