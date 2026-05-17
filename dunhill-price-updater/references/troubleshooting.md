# Dunhill价格更新故障排除指南

## 常见错误及解决方案

### 1. 价格文件未找到

**错误信息:**
```
FileNotFoundError: 未找到价格文件: D:\Work\dunhill\product\调价清单\PRICE_*.xlsx
```

**解决方案:**
- 确认价格文件目录存在
- 检查文件名是否符合 `PRICE_YYYYMMDD.xlsx` 格式
- 确认文件扩展名是 `.xlsx` 而非 `.xls`

### 2. 数据库配置未找到

**错误信息:**
```
FileNotFoundError: 数据库配置文件不存在: C:\Users\jm024027\database_config.json
```

**解决方案:**
- 创建数据库配置文件
- 确保配置文件格式正确:

```json
{
  "databases": [
    {
      "name": "Aliyun DB",
      "host": "your-host",
      "user": "your-user",
      "password": "your-password",
      "database": "dunhill",
      "port": 3306,
      "charset": "utf8mb4"
    }
  ]
}
```

### 3. 数据库连接失败

**错误信息:**
```
pymysql.err.OperationalError: (2003, "Can't connect to MySQL server...")
```

**解决方案:**
- 检查网络连接
- 确认数据库服务器地址和端口正确
- 检查防火墙设置
- 验证用户名和密码

### 4. 复合唯一键冲突

**错误信息:**
```
pymysql.err.IntegrityError: (1062, "Duplicate entry 'DU0DRADUN091F-2023-02-01-2025-04-30' for key 'dunhill_价格源_UN'")
```

**原因:**
- 数据库已存在相同 的记录
- 可能是之前导入失败留下的重复记录

**解决方案:**
- 脚本已使用 `INSERT IGNORE` 自动跳过重复记录
- 如需强制更新，先删除旧记录再重新导入

### 5. 日期类型转换错误

**问题现象:**
- 插入后 `validTo` 字段变为 `NULL`
- 或出现 `Incorrect date value` 错误

**原因:**
- Python `datetime` 对象直接插入 MySQL `date` 字段失败
- Excel 中的日期已经是 `datetime` 类型

**解决方案:**
脚本已内置 `to_date()` 函数处理转换：
```python
def to_date(self, dt):
    if pd.isna(dt) or dt is None:
        return date(9999, 12, 31)  # 空值转为最大日期
    if hasattr(dt, 'date'):
        return dt.date()  # datetime -> date
    return dt
```

### 6. validTo 为 NULL 问题

**问题现象:**
```
数据库中 validTo 为 NULL 的记录: 12655
```

**原因:**
- Excel 中 `validTo` 为空/NaT
- 日期转换时未正确处理空值

**解决方案:**
脚本已自动处理：
- Excel 中 `validTo` 为空时，自动转为 `9999-12-31`
- 表示该价格长期有效

### 7. Excel 缺少 SPU 记录（只有 SKC/SKU）

**问题现象:**
- 某些 SPU 在数据库中存在，但执行更新后显示 0 条新增/更新
- Excel 中只有长编码（SKC/SKU），没有对应的短编码（SPU）

**示例:**
```
数据库 SPU: DU1DBFB52 | RSP: ¥6,750
Excel 只有: DU1DBFB5211, DU1DBFB5216 (SKC 编码)
```

**原因:**
- Excel 源文件在记录时确实掉了 SPU 级别的调价记录
- 只保留了 SKC（颜色编码）或 SKU（颜色+尺码编码）记录
- 脚本无法匹配，因为 SPU 编码不一致

**编码规则:**
- SPU（短编码）: `DU1DBFB52`
- SKC（颜色编码）: `DU1DBFB5211`、`DU1DBFB5216`
- SKU（颜色+尺码）: `DU1DBFB5211, BLACK, 39, .0`

**临时解决方案:**
手动更新数据库中缺失的 SPU 记录：
```sql
UPDATE dunhill_价格源 SET rsp = 7250
WHERE spu = 'DU1DBFB52' AND validTo = '9999-12-31';
```

**未来改进方向:**
脚本可增加逻辑 - 当 Excel 缺少 SPU 记录但存在对应 SKC/SKU 记录时，自动用 SKC/SKU 的价格更新 SPU。

---

### 8. 日期重叠警告

**错误信息:**
```
============================================================
警告: 发现日期重叠问题!
============================================================
  日期重叠: SPU=DU23R4A11GB, 新记录[2024-12-01~9999-12-31] 与现有记录[2024-12-01~2025-04-30]重叠
```

**原因:**
- 同一 SPU 的两条调价记录在时间段上有交集
- 可能是品牌方调整价格时，旧记录的 validTo 未更新

**解决方案:**
1. **确认是否预期行为**：如果是品牌方正常调价，使用 `--skip-overlap` 跳过检查
2. **手动修复**：先更新旧记录的 validTo，再导入新记录
3. **检查数据**：确认 Excel 中的日期段是否正确

### 8. Excel读取错误

**错误信息:**
```
ValueError: Worksheet is corrupted or unsupported format
```

**解决方案:**
- 用Excel打开文件并另存为新文件
- 检查文件是否损坏
- 确认文件格式为 `.xlsx`

### 9. 依赖包缺失

**错误信息:**
```
ModuleNotFoundError: No module named 'pymysql' / 'yaml' / 'pandas'
```

**解决方案:**
```bash
pip install pymysql pyyaml pandas openpyxl
```

---

## 历史问题案例

### 案例1: validTo=9999-12-31 记录被误删

**问题描述:**
修复日期重叠问题时，批量删除了所有 Excel 中没有的 validTo=9999-12-31 记录，导致部分有效记录丢失。

**根因分析:**
- 判断逻辑错误：只保留 Excel 中有的记录
- 但有些记录是数据库原有且仍然有效的（Excel 中没有是因为价格没变化）

**修复方案:**
```sql
-- 找出缺少有效记录的SPU，恢复最后一条记录的validTo
UPDATE dunhill_价格源
SET validTo = '9999-12-31'
WHERE (spu, validFrom) IN (
    SELECT spu, MAX(validFrom)
    FROM dunhill_价格源
    WHERE spu NOT IN (SELECT spu FROM dunhill_价格源 WHERE validTo = '9999-12-31')
    GROUP BY spu
);
```

**预防措施:**
- 脚本只执行 INSERT 和 UPDATE，不执行 DELETE
- 保留数据库中已有但 Excel 中没有的记录

### 案例2: SPU 录入成 SKU

**问题描述:**
某些 SPU 在数据库中找不到，但存在带后缀的变体（如 DU0DWADUN200A、DU0DWADUN200B）。

**原因:**
- 品牌方眼镜/配饰产品通常用后缀字母区分颜色变体
- 录入时误将 SKU 变体当作 SPU

**解决方案:**
- 确认正确的 SPU 编码格式
- 手动在数据库中修正 SPU 编码

---

## SPU/SKU判断说明

### 判断逻辑
- **SPU**: 商品名称不含逗号，如 `COLLEGE PENNY LOAFER LTR`
- **SKU**: 商品名称含逗号分隔的颜色尺码，如 `COLLEGE PENNY LOAFER LTR, BLACK, 39, .0`

### 验证SPU筛选是否正确

运行脚本后检查输出:
```
原始数据总行数: 210260
筛选SPU记录后: 65069 行     <- 应该约为原始行数的1/3
筛选有零售价记录后: 62913 行
去重后(SPU+ValidFrom+ValidTo): 62913 行
```

如果SPU记录数过多，可能是Excel格式有变化，需要检查列名是否匹配。

---

## 预览模式验证

在执行实际更新前，建议先使用 `--dry-run` 预览:

```bash
python scripts/update_prices.py --dry-run
```

检查:
1. SPU总数是否合理
2. 新增和更新记录数是否符合预期
3. 是否有日期重叠警告
4. 确认无误后再执行实际更新

---

## 数据验证SQL

### 检查更新后的记录数
```sql
SELECT COUNT(*) FROM dunhill_价格源;
```

### 检查 validTo 为 NULL 的记录
```sql
SELECT COUNT(*) FROM dunhill_价格源 WHERE validTo IS NULL;
```

### 检查有效记录数
```sql
SELECT COUNT(*) FROM dunhill_价格源 WHERE validTo = '9999-12-31';
```

### 检查特定SPU的所有调价记录
```sql
SELECT spu, validFrom, validTo, rsp
FROM dunhill_价格源
WHERE spu = 'DU23R4A11GB'
ORDER BY validFrom;
```

### 检查日期重叠的记录
```sql
SELECT a.spu, a.validFrom as from1, a.validTo as to1,
       b.validFrom as from2, b.validTo as to2
FROM dunhill_价格源 a
JOIN dunhill_价格源 b ON a.spu = b.spu
WHERE a.validFrom < b.validTo
  AND b.validFrom < a.validTo
  AND a.validFrom != b.validFrom;
```

### 检查最近更新的记录
```sql
SELECT * FROM dunhill_价格源
ORDER BY updated_at DESC
LIMIT 20;
```

---

## 日志与调试

如需更详细的调试信息，可以在脚本中添加:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## 联系支持

如果以上方案无法解决问题，请提供:
1. 完整的错误信息
2. 价格文件名和日期
3. 数据库配置(隐藏密码)
4. 相关SPU编码
