# 数据映射

## CND8 → DB 品类映射

CND8 列 `Unnamed: 13`（合并单元格导致表头为空）的值大部分直接匹配 DB 品类。

### 需要映射的品类

| CND8 品类 | DB 品类 |
|-------------|---------|
| OTHER SOFTS | OTHER SOFT ACCESSORIES |
| REFILLS | SMOKERS CONSUMABLES |

### 前缀处理

带 `DUNHILL ` 前缀的品类去除前缀：
- `DUNHILL PIPES` → `PIPES`
- `DUNHILL OTHER SMOKERS` → `OTHER SMOKERS`
- `DUNHILL SMOKERS CONSUMABLES` → `SMOKERS CONSUMABLES`

### 实现代码

在 `data_source_cnd8.py` 中处理：
1. `.str.removeprefix('DUNHILL ')`
2. `config.CND8_TO_DB_CATEGORY` 字典映射

## Season 归一化

对 CND8 的 `F&A Current Collection` 列值处理：

| 原始值 | 处理规则 | 结果 |
|--------|---------|------|
| `DU SS26` | 去除 `DU ` 前缀 | `SS26` |
| `DU 00 0` | 去除前缀 → 无效值替换 | `CO` |
| `Not assigned` | 无效值替换 | `CO` |
| `FW26` | `FW` → `AW` | `AW26` |

### PIPES 特殊规则

PIPES 品类的 season 统一为 `CO`（在去除前缀和无效值替换之后应用）。

## OMS → DB 数据映射

OMS 商品管理页面导出的 SKU 维度数据录入 `dunhill_pdt_line_by_sku`。

| DB 列 | OMS 导出列 | 备注 |
|-------|------------|------|
| 货号 | 货号 | SPU 编码 |
| 平台对接码 (PK) | 平台对接码 | OMS SKU 编码 |
| 商品名称 | 商品名称 | |
| 吊牌价 | 吊牌价 | 转为 int |
| 商品条码 | 商品条码 | |
| OMS品类 | 开票名称 | OMS"商品品类"列常为空，改用"开票名称" |

### OMS 注意事项

- OMS SKU 编码比 CND8 SKU 多一个 `R` 后缀（如 `DU26RPTW0GE256` → `DU26RPTW0GE256R`）
- 导出文件通过 Playwright 网络请求获取 OSS 下载链接，再用 Python 下载
- 登录需要手机验证码二次验证
