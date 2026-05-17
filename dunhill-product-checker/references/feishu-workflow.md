# 飞书多维表格操作规范

## lark-cli 基础

lark-cli 已全局安装: `npm install -g @larksuite/cli@1.0.2`

命令路径: `%APPDATA%\npm\lark-cli.cmd`

所有命令格式:
```bash
lark-cli base <子命令> [参数] --as bot
```

## 多维表格常量

| 常量 | 值 |
|------|-----|
| BASE_TOKEN | `JUTVbArs7aE8g2sckz0cGuMdnDa` |
| TABLE_ID | `tblF64WEO4E1oYM0` |
| 认证方式 | `--as bot` |

## 字段定义

### 文本字段

商品ID, 标题, CSV材质, 页面材质, 差异说明, 极限词, 核查人, OCR识别文字, 核查时间, 原问题备注

### 附件字段

产品信息图1, 产品信息图2, 产品信息图3

## 常用操作

### 获取记录列表 (分页)

```bash
lark-cli base +record-list \
  --base-token JUTVbArs7aE8g2sckz0cGuMdnDa \
  --table-id tblF64WEO4E1oYM0 \
  --limit 200 --offset 0 \
  --as bot
```

返回: `{ ok: true, data: { data: [[...], ...], record_id_list: [...], fields: [...], has_more: bool } }`

### 创建/更新记录 (upsert)

```bash
lark-cli base +record-upsert \
  --base-token JUTVbArs7aE8g2sckz0cGuMdnDa \
  --table-id tblF64WEO4E1oYM0 \
  --json '{"商品ID":"862632821077","标题":"测试","CSV材质":"羊绒"}' \
  --as bot
```

返回: `{ ok: true, data: { record: { record_id: "recXXXXX", fields: {...} } } }`

### 上传附件

```bash
lark-cli base +record-upload-attachment \
  --base-token JUTVbArs7aE8g2sckz0cGuMdnDa \
  --table-id tblF64WEO4E1oYM0 \
  --record-id recXXXXX \
  --field-id 产品信息图1 \
  --file "D:/path/to/image.png" \
  --as bot
```

注意: `--file` 路径支持绝对路径。脚本中可用 `cwd` 参数设置工作目录。

### 删除记录

```bash
lark-cli base +record-delete \
  --base-token JUTVbArs7aE8g2sckz0cGuMdnDa \
  --table-id tblF64WEO4E1oYM0 \
  --record-id recXXXXX \
  --yes \
  --as bot
```

**重要**: `--yes` 参数是必须的，不加会返回 `unsafe_operation_blocked`。

## 坑点

### JSON 中的特殊字符

lark-cli 的 `--json` 通过 shell 传递，以下字符需要处理:
- `&` → 替换为全角 `＆` (否则 shell 会解释为后台运行)
- 其他特殊字符一般没问题 (引号由 JSON 自身的转义处理)

### Windows 编码

Windows 默认 GBK 编码，subprocess 输出可能乱码:
```python
import io, sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
```

### 分页

`+record-list` 默认一页 200 条，用 `has_more` 判断是否还有下一页，`offset` 递增。

### upsert 重复

`+record-upsert` 不会去重 — 如果对同一商品ID多次调用，会产生多条记录。需要在上传前检查已有记录，或上传后清理重复。

## Python 封装

项目中已有两个上传脚本:

1. **upload_to_bitable.py** — 读取xlsx，批量 upsert 文本数据 + 上传附件
2. **upload_attachments.py** — 对已有 bitable 记录补充上传图片附件

两个脚本都通过 `run_lark_cli()` 函数封装 lark-cli 调用，处理 JSON 解析和错误。
