---
name: dunhill-product-checker
description: "Dunhill天猫商品详情页材质核查工具。从CSV加载商品列表，用Playwright抓取天猫详情页材质+产品信息图片，写入xlsx，然后上传到飞书多维表格。调用方式: /dunhill-product-checker [scrape|upload|all]"
---

# Dunhill 商品详情页材质核查

从天猫商品详情页抓取材质信息和产品信息图片，写入 xlsx，再上传到飞书多维表格。

## Quick Start

```
/dunhill-product-checker          # 完整流程 (scrape + upload)
/dunhill-product-checker scrape   # 仅执行抓取
/dunhill-product-checker upload   # 仅上传到飞书 (需先有xlsx)
```

## Step 1: 抓取材质+图片

### 常用命令

```bash
cd ${AI_PROJECTS_DIR}/dunhill-product-info-updater/p-info-web-checker

# 基本抓取 (无头模式，自动交互选择过滤条件)
python main.py scrape -i "商详材质&极限词核查-554个商品（有554行数据）.csv"

# 指定核查人 + 空备注 + 3窗口并发
python main.py scrape -i "商详材质&极限词核查-554个商品（有554行数据）.csv" \
  --inspector chris --empty-notes-only --workers 3

# 有头模式 (可处理验证码)
python main.py scrape -i "input.csv" --headed --workers 1

# 追加到已有xlsx (自动跳过已抓取)
python main.py scrape -i "input.csv" --continue-xlsx "output/已有结果.xlsx" \
  --inspector chris --empty-notes-only --workers 3

# 强制重新抓取指定ID
python main.py scrape -i "input.csv" --force-ids "862632821077,862632821078" --headed
```

### 并发模型

- 每个 worker 创建一个 `PageScraper`（一个浏览器），从共享 `queue.Queue` 取产品ID
- 浏览器窗口复用：`page.goto(new_url)` 替换URL，不关窗口
- `queue.get_nowait()` 是原子操作，不会重复分配ID
- 每抓完一个产品 `time.sleep(random.uniform(3, 6))` 防反爬

### 自动跳过机制

- 扫描 `output/images/` 目录，已有 `{pid}_*.png` 的产品自动跳过
- `--continue-xlsx` 也会读取已有xlsx的ID列表跳过
- `--force-ids` 排除自动跳过，删除旧图片后重新抓取

### 输出

- xlsx: `output/{input_basename}_核查结果_{YYYYMMDDHHMM}.xlsx`
- 图片: `output/images/{product_id}_{3|4|5}.png` (产品信息图片)
- xlsx 包含16列: 商品ID, 标题, CSV材质, 页面材质, 差异说明, 极限词, 核查人, OCR识别文字, 核查时间, 原问题备注, img1_path, img2_path, img3_path, img1_token, img2_token, img3_token

### 关键参数

| 参数 | 说明 |
|------|------|
| `--input, -i` | 输入CSV文件路径 |
| `--workers, -w` | 并发窗口数 (默认1, 建议1-5) |
| `--headed` | 有头模式 (验证码时用) |
| `--inspector` | 按核查人过滤 |
| `--empty-notes-only` | 只爬问题备注为空的 |
| `--limit, -l` | 限制本次爬取数量 |
| `--offset, -o` | 跳过前N条 |
| `--continue-xlsx` | 追加到已有xlsx |
| `--force-ids` | 强制重新抓取 (逗号分隔ID) |
| `--match-mode` | 材质比对: exact / fuzzy |

## Step 2: 上传到飞书多维表格

抓取完成后，将 xlsx 数据上传到飞书多维表格，再上传图片附件。

### 前置条件

- 飞书多维表格已存在 (BASE_TOKEN, TABLE_ID)
- lark-cli 已全局安装 (`npm install -g @larksuite/cli@1.0.2`)
- 图片已保存在 `output/images/`

### 上传文本数据

```bash
cd ${AI_PROJECTS_DIR}/dunhill-product-info-updater/p-info-web-checker
python upload_to_bitable.py
```

修改 `upload_to_bitable.py` 中的 `XLSX_PATH` 指向要上传的xlsx文件。

### 上传图片附件

```bash
python upload_attachments.py "output/核查结果_YYYYMMDDHHMM.xlsx"
```

此脚本会：
1. 从飞书多维表格获取所有记录 (record_id + 商品ID)
2. 查找 `output/images/{product_id}_{3|4|5}.png`
3. 上传到对应记录的附件字段

### 增量上传

如果上传中断，用环境变量跳过已上传的行：
```bash
SKIP_ROWS=49 python upload_to_bitable.py
```

### 清理重复记录

如果 `+record-upsert` 产生了重复，手动清理：
1. 用 `+record-list` 获取所有记录
2. 按 商品ID 分组，找出重复的 record_id
3. 用 `+record-delete --yes --record-id <id>` 删除较旧的重复

详细飞书操作规范见 [references/feishu-workflow.md](references/feishu-workflow.md)。

## 关键文件

| 文件 | 路径 |
|------|------|
| 项目目录 | `${AI_PROJECTS_DIR}/dunhill-product-info-updater/p-info-web-checker/` |
| 主入口 | `main.py` |
| 抓取器 | `checker/page_scraper.py` (PageScraper, ScrapResult) |
| 结果写入 | `checker/result_writer.py` (ResultWriter, DiffRecord) |
| CSV加载 | `checker/csv_loader.py` (CSVLoader, ProductRecord) |
| CLI参数 | `checker/cli.py` |
| 配置 | `config.py` |
| 飞书上传(文本) | `upload_to_bitable.py` |
| 飞书上传(附件) | `upload_attachments.py` |
| 图片目录 | `output/images/` |
| 飞书多维表格 | BASE_TOKEN=`JUTVbArs7aE8g2sckz0cGuMdnDa`, TABLE_ID=`tblF64WEO4E1oYM0` |

## 已知坑点

- **虚拟无头**: 真正的 headless 模式下天猫 desc-v8 不渲染，用 `--window-position=-2400,-2400` 模拟无头
- **auth.json**: Playwright 使用 `~/auth.json` 中的 cookies，需先手动登录天猫一次
- **alicdn 防盗链**: 用 canvas 从浏览器内存提取图片，不走 HTTP 下载
- **JSON中的 `&`**: lark-cli 的 `--json` 参数中 `&` 会被 shell 解释，需替换为全角 `＆`
- **`+record-delete`**: 必须加 `--yes` 参数，否则返回 `unsafe_operation_blocked`
- **GBK编码**: Windows 下 subprocess 输出可能 GBK 编码错误，用 `io.TextIOWrapper(encoding='utf-8')` 包裹 stdout/stderr
