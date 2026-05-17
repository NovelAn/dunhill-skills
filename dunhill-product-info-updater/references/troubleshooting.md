# Troubleshooting

## SKC 更新

### CND8 邮件搜索很慢（几分钟无输出）

- **症状**: Task 1 在 `[Step 1] 获取CND8库存表...` 之后卡住很久才输出
- **原因**: Outlook COM 搜索使用了错误的过滤语法，或未过滤日期导致遍历整个收件箱
- **解决**: 使用 Jet 过滤语法 + 日期范围限制：
  ```python
  filter_sender = f"[SenderEmailAddress] = '{sender}' AND [ReceivedTime] >= '{cutoff}'"
  items = inbox.Items.Restrict(filter_sender)
  ```
- **禁止使用**: `@SQL=urn:schemas:httpmail:...` 语法（中文版 Outlook 不兼容）
- **日期格式**: `MM/DD/YYYY`，建议过滤最近 30 天

### CND8 数据获取失败

- **症状**: "未获取到CND8数据"
- **原因**: Outlook 邮箱中未找到匹配附件
- **解决**: 检查邮箱中是否有来自 `hamish.huang@dunhill.com` 的邮件，附件名匹配 `CND8 Daily stock YYYY_MMDD.xlsx`

### 目标文件被占用

- **症状**: `PermissionError` 打开目标 Excel
- **原因**: Excel 正在打开该文件
- **解决**: 关闭 Excel 后重试

### SKU 长度不在规则表中

- **症状**: 部分 SKU 无法提取 SKC
- **原因**: SKU 长度或品类组合不在已有规则中
- **解决**: 检查 `db_helper.py` 中的 `_SKC_N_RULES` 表，可能需要新增规则

## SKU 更新 (OMS)

### OMS 页面报错或空白

- **症状**: `agent-browser eval` 返回错误
- **原因**: CDP 连接断开或页面未完全加载
- **解决**: 确保 Chrome 在 9222 端口监听；增加 `wait` 时间

### agent-browser 命令报 SyntaxError

- **症状**: `SyntaxError: missing ) after argument list`
- **原因**: Windows cmd.exe 不支持 `$()` bash 语法
- **解决**: `run_ab()` 函数已使用 `bash -c` 解决；如遇新问题，检查 JS 字符串中是否有未转义的特殊字符

### subprocess UnicodeEncodeError (GBK)

- **症状**: `'gbk' codec can't encode character` 在打印错误时
- **原因**: Windows 终端默认 GBK 编码，无法输出 Unicode 字符
- **解决**: 已在 `run_ab()` 中指定 `encoding='utf-8', errors='replace'`；此错误通常不影响功能

### SPU 在 OMS 中搜索不到

- **原因**: 商品尚未在电商线上建档，但品牌仓库已有库存
- **解决**: 记录到 `oms_unmatched_spu.xlsx`，后续每次执行时重新检查；长期未找到的 SPU 可能是真实缺失

### OMS JS 提取返回 0 条记录（页面显示有结果）

- **症状**: 浏览器中可见 57 条搜索结果，但 `_parse_oms_results` 报告 0 条
- **原因**: `_EXTRACTION_JS` 通过 `tables[2].querySelectorAll('tr td')` 提取数据行，但 `平台对接码` 列的值在提取后为空（可能是 DevExtreme 虚拟滚动或延迟渲染导致 DOM 中该列未填充），`_parse_oms_results` 第 474 行 `if not r.get('平台对接码'): continue` 过滤掉了所有记录
- **解决**: **不要用 JS 提取**，改用 OMS 页面的导出按钮下载 Excel，然后解析文件。详见 [oms-automation.md](oms-automation.md) 的"导出方案"

### CDP Chrome 下载文件不在 ~/Downloads

- **症状**: 通过 CDP Chrome 点击导出按钮后，文件未出现在 `~/Downloads`
- **原因**: CDP profile（`cdp-profile`）是独立的 Chrome 用户数据目录，如果未设置 `download.default_directory`，下载行为可能不一致（被拦截、弹出另存为对话框、或下载到非预期位置）
- **解决**: 不依赖文件系统监听。从 Chrome 的 `DownloadMetadata` 文件中提取 OSS URL，直接用 Python 下载：
  ```
  路径: <cdp-profile>/Default/DownloadMetadata
  格式: 二进制，内含 OSS URL（如 bztic-gs-files-prod.oss-cn-shanghai.aliyuncs.com/.../*.xlsx）
  ```
  用 Python 提取 URL 后 `urllib.request.urlretrieve` 下载即可。详见 [oms-automation.md](oms-automation.md) 的"从 DownloadMetadata 提取 OSS URL"

### OMS 未登录或会话过期

- **症状**: `_detect_page_state()` 返回 `login_page`
- **原因**: CDP profile 中的认证 cookies 已过期（通常几周至数月）
- **解决**: 脚本自动检测登录页并调用 `auto_login()`，自动填账号密码+选企业，仅在需要验证码时暂停等待输入
- **手动处理**: 如自动登录失败，在 CDP Chrome 中手动打开 https://account-dop.baozun.com/login 登录

### agent-browser 命令全部卡住（open/wait/find 都超时）

- **症状**: `run_ab('open ...')`、`run_ab('wait 2000')`、`run_ab('find ...')` 全部 30s 超时
- **原因**: agent-browser 在 SPA 页面重定向/加载期间整体无响应，不限于 `open` 命令
- **解决**: 所有页面交互已改用 JS eval + `time.sleep()` 方案，不再依赖 agent-browser 的 `open`/`wait`/`find` 命令。详见 [oms-automation.md](oms-automation.md) 的"页面交互策略"

### 页面状态检测返回值不匹配

- **症状**: JS eval 返回 `"ready"` 但 `result == 'ready'` 为 False
- **原因**: agent-browser eval 返回 JSON 编码的字符串，带引号 `'"ready"'`
- **解决**: 比较前加 `.strip('"').strip("'")`

### Chrome CDP 端口 9222 未监听

- **症状**: `_is_chrome_listening()` 返回 False
- **原因**: Chrome 未启动或未带 `--remote-debugging-port=9222` 参数
- **解决**: `_ensure_chrome_running()` 会自动启动带 CDP 的 Chrome 实例（使用独立 `cdp-profile`）

### 清除 localStorage 后 OMS 显示 404

- **症状**: 手动清除 localStorage 后，OMS 页面 URL 变为 404
- **原因**: OMS 是 Angular 应用，路由依赖 localStorage 中的状态
- **解决**: 不要手动清除 localStorage；如需重新登录，直接导航到 https://account-dop.baozun.com/login

### 默认 Chrome Profile 无法启用 CDP

- **症状**: 用默认 Profile 启动 Chrome 后 9222 端口不监听
- **原因**: Chrome 在某些情况下会静默忽略 `--remote-debugging-port` 参数
- **解决**: 使用独立的 `cdp-profile` 用户数据目录（`config.CDP_PROFILE_DIR`）

### OMS 品类为空

- **原因**: OMS 表格的"商品品类"列可能为空
- **解决**: 使用"开票名称"列（字段映射为 `OMS品类`）填充

### JS 填充表单不生效

- **症状**: 货号字段填写了但搜索结果为空
- **原因**: Ant Design React 组件需要 `dispatchEvent` 触发状态更新
- **解决**: 确保使用 `inp.dispatchEvent(new Event('input',{bubbles:true}))` 而非仅设置 `value`

### Python f-string 中 `{` 报 SyntaxError

- **症状**: `SyntaxError: invalid syntax` 或 `Unexpected end of input`
- **原因**: f-string 把 JS 中的 `{}` 解析为 Python 插值表达式
- **解决**: 将 `{bubbles:true}` 等对象字面量提取为普通 Python 变量：`bubbles_obj = "{bubbles:true}"`
