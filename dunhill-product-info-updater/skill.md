---
name: dunhill-product-info-updater
description: "Dunhill商品信息配置表自动更新工具。包含三个子任务：(1) SKC更新 - 从CND8 Daily stock提取新SKC，对比DB和目标Excel并更新；(2) SKU更新 - 将新SPU去重后在OMS系统搜索，导出SKU信息录入DB，跟踪OMS未建档的SPU；(3) tm_id↔SKC映射更新 - 从天猫导出同步tm_id与SKC对照关系到DB和目标Excel。调用方式: /dunhill-product-info-updater [skc|sku|tm-skc|all]"
---

# Dunhill 商品信息配置表自动更新

从 CND8 Daily stock 和 OMS 系统自动同步商品信息到数据库和目标 Excel。

## Quick Start

```
/dunhill-product-info-updater          # 执行完整流程 (SKC + SKU)
/dunhill-product-info-updater skc      # 仅执行 SKC 更新
/dunhill-product-info-updater sku      # 仅执行 SKU 更新 (需先完成 SKC 更新)
/dunhill-product-info-updater tm-skc   # 天猫 tm_id ↔ SKC 映射表更新 (独立流程)
```

## Task 1: SKC 更新

### 流程

1. **获取 CND8 数据**: 从 Outlook 邮箱获取最新的 `CND8 Daily stock YYYY_MMDD.xlsx`
2. **规则提取 SKC**: 对所有 CND8 SKU 使用确定性规则提取 SKC
3. **对比 DB**: 与 `dunhill_pdt_group_by_skc` 对比，找出 DB 没有的新 SKC
4. **写入 DB**: 新 SKC 使用 INSERT IGNORE 写入 `dunhill_pdt_group_by_skc`
5. **对比目标文件**: 与 `商品信息配置表.xlsx` 对比，找出目标文件没有的记录
6. **更新目标 Excel**: 将新记录追加到目标文件

### 执行脚本

> **IMPORTANT**: 必须使用 `python -u`（无缓冲模式）运行，否则通过子进程管道执行时 stdout 全缓冲会导致输出不显示，看起来像卡住。

```bash
cd ${AI_PROJECTS_DIR}/dunhill-product-info-updater/info-updater
python -u scripts/main.py
```

### CND8 邮件信息

- **发件人**: `hamish.huang@dunhill.com`
- **邮件标题**: `CND8`
- **附件名**: `CND8 Daily stock YYYY_MMDD.xlsx`
- **搜索策略**: Outlook `Items.Restrict()` 按 `[SenderEmailAddress]` + 最近 30 天过滤，避免遍历整个收件箱
- **过滤语法**: 必须使用 Jet 语法 (`[SenderEmailAddress] = '...'`)，**不要用** `@SQL=urn:schemas:httpmail:...`（中文版 Outlook 不兼容）

### 关键参考

- SKU→SKC 提取规则: 见 [references/skc-rules.md](references/skc-rules.md)
- CND8→DB 品类映射 + Season 归一化: 见 [references/data-mappings.md](references/data-mappings.md)

## Task 2: SKU 更新

### 前置条件

Task 1 (SKC 更新) 必须先完成。Task 2 **始终执行**，因为即使没有新 SKC，`oms_unmatched_spu.xlsx` 中可能有待建档的 SPU 需要重试（之前 OMS 未建档的 SPU 可能现在已经上架）。

### 流程

1. **加载未匹配 SPU**: 从 `oms_unmatched_spu.xlsx` 加载 status='待建档' 且今天未检查的 SPU
2. **合并搜索列表**: 合并历史未匹配 SPU + Task 1 新 SPU，去重
3. **OMS 搜索**: 通过 `agent-browser --cdp 9222` 连接本机 Chrome，继承已有登录状态
4. **导出 Excel**: 点击 OMS 页面导出按钮，从 Chrome `DownloadMetadata` 提取 OSS URL 直接下载（JS 提取不可靠，详见 references）
5. **解析并录入 DB**: 解析导出的 Excel，INSERT IGNORE 到 `dunhill_pdt_line_by_sku`
6. **跟踪未建档 SPU**: 找到的从文件删除，未找到的保留"待建档"，更新 `oms_unmatched_spu.xlsx`

### OMS 登录机制

使用 `agent-browser --cdp 9222` 通过 Chrome DevTools Protocol 连接本机 Chrome。
- **日常运行**: CDP profile（`cdp-profile`）持久化 cookies，直接继承登录状态，全自动零人工
- **Session 过期时**: `auto_login()` 自动填账号密码+选择 Dunhill 企业，仅在需要手机验证码时暂停等待输入
- **无需手动启动**: `_ensure_chrome_running()` 自动检测并启动带 CDP 的 Chrome 实例

详细说明见 [references/oms-automation.md](references/oms-automation.md)。

### 关键参考

- OMS 自动化原理与关键实现: 见 [references/oms-automation.md](references/oms-automation.md)
- OMS→DB 数据映射: 见 [references/data-mappings.md](references/data-mappings.md)
- DB 表结构: 见 [references/db-schema.md](references/db-schema.md)
- 常见问题: 见 [references/troubleshooting.md](references/troubleshooting.md)

## Task 3: tm_id ↔ SKC 映射更新

### 触发条件

收到新的天猫商品导出 Excel（`export_XXXX_YYYYMMDD_HHMMSS_XXXXXXX.xlsx`），需同步 tm_id ↔ SKC 对照关系。

### 核心原则

- **源表优先**: 天猫导出的 SKC 为准
- **直接写 DB**: new_insert 记录直接 INSERT，输出 Excel 备份
- **白名单/忽略规则**: 自动过滤 tm_id 复用引流、垃圾编码等，减少人工判断
- **DUDP 烟斗**: 以编码更长的为准，不替换为短编码

### 执行脚本

> **IMPORTANT**: 必须使用 `python -u`（无缓冲模式）运行。

```bash
cd ${AI_PROJECTS_DIR}/dunhill-product-info-updater/info-updater

# 执行更新
python -u scripts/tm_skc_updater.py data/export_XXXX_YYYYMMDD_HHMMSS_XXXXXXX.xlsx

# 维护白名单
python -u scripts/tm_skc_updater.py --add-reuse <tm_id>
python -u scripts/tm_skc_updater.py --add-ignore <tm_id>
```

### 流程

```
tm_skc_updater.py (单脚本一键)
  ├─ 1. 加载配置 (tm_skc_config.json)
  ├─ 2. 读取源表 + DB
  ├─ 3. 比对 → 4 类:
  │   ├─ new_insert:   tm_id 不在 DB，SKC 有效 → 直接 INSERT DB
  │   ├─ new_invalid:  tm_id 不在 DB，SKC 无效 → 输出待确认
  │   ├─ auto_skip:    命中白名单/忽略规则 → 静默跳过
  │   └─ mismatch:     SKC 变化且不在白名单 → 输出待确认
  ├─ 4. INSERT new_insert → DB
  └─ 5. 输出报告 → tm_skc_update_report.xlsx
      ├─ summary
      ├─ inserted
      ├─ needs_review (new_invalid + mismatch)
      └─ skipped (含跳过原因)
```

### 配置文件

`scripts/tm_skc_config.json` 包含：
- `reuse_whitelist`: tm_id 复用引流白名单（14 个）
- `ignored_tm_ids`: 忽略的 tm_id（空链接、赠品等）
- `skip_rules`: 自动跳过规则（TZ- 前缀、条形码、废弃、垃圾值、DUDP 保留更长）
- `defaults`: 默认 st_date / end_date

### 关键参考

- 完整流程、边界情况: 见 [references/tm-skc-mapping.md](references/tm-skc-mapping.md)
- SKU→SKC 通用规则（无品类信息时）: 同样定义在 tm_skc_updater.py 的 `_SKC_LEN_RULES`

## 文件路径

| 文件 | 路径 |
|------|------|
| 项目目录 | `${AI_PROJECTS_DIR}/dunhill-product-info-updater/info-updater/` |
| 目标 Excel | `\\10.188.9.99\Dunhill项目\6 数据\product_info_config\商品信息配置表.xlsx` |
| DB/OMS 配置 | `~/database_config.json` |
| OMS 未建档跟踪 | `info-updater\output\oms_unmatched_spu.xlsx` |
| 更新报告 | `info-updater\output\商品信息更新表_YYYY_MMDD.xlsx` |
| OMS 导出 | `info-updater\output\OMS商品信息_YYYY_MMDD.xlsx` |

## 核心脚本

| 脚本 | 用途 |
|------|------|
| `scripts/main.py` | Task 1: SKC 更新（规则提取 + 对比 + 写入 DB + 写入目标 Excel） |
| `scripts/data_source_cnd8.py` | Task 1: CND8 数据获取和解析 |
| `scripts/db_helper.py` | DB 连接、SKC 提取规则 |
| `scripts/target_updater.py` | Task 1: 目标文件读写操作 |
| `scripts/oms_updater.py` | Task 2: OMS 自动化（浏览器操控、JS 提取、未匹配 SPU 跟踪） |
| `scripts/oms_export_import.py` | Task 2: OMS 导出方案（点击导出按钮 + OSS 下载 + Excel 解析，推荐） |
| `scripts/config.py` | 配置常量 |
| `scripts/tm_skc_updater.py` | **Task 3: tm_id↔SKC 一键更新（比对 + 自动过滤 + INSERT DB + 报告）** |
| `scripts/tm_skc_config.json` | **Task 3: 白名单、忽略规则配置文件** |
| `scripts/tm_skc_compare.py` | Task 3 legacy: 天猫导出 vs DB 全量比对 |
| `scripts/tm_skc_resolve_mismatch.py` | Task 3 legacy: 不匹配 SKC 调和 |
| `scripts/tm_skc_apply_mismatch.py` | Task 3 legacy: 应用调和结果到目标 Excel |

## 参考文件索引

| 文件 | 何时读取 |
|------|---------|
| [references/skc-rules.md](references/skc-rules.md) | Task 1 提取 SKC 时，需要了解 SKU→SKC 规则 |
| [references/data-mappings.md](references/data-mappings.md) | Task 1 品类映射/Season 处理，Task 2 OMS 数据映射 |
| [references/db-schema.md](references/db-schema.md) | 写入 DB 时需要确认表结构或字段类型 |
| [references/oms-automation.md](references/oms-automation.md) | Task 2 OMS 自动化原理、agent-browser + CDP、JS 执行机制、关键坑点 |
| [references/troubleshooting.md](references/troubleshooting.md) | 遇到问题时查阅 |
| [references/tm-skc-mapping.md](references/tm-skc-mapping.md) | Task 3 天猫 tm_id↔SKC 映射更新完整流程 |
