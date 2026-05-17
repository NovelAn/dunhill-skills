# OMS 自动化原理与关键实现

## 核心方案: agent-browser + CDP

使用 `agent-browser --cdp 9222` 通过 Chrome DevTools Protocol 直接连接本机已打开的 Chrome，继承已有登录状态。

### 为什么选 CDP 而非其他方案

| 方案 | 问题 |
|------|------|
| `agent-browser --profile Default` | Chrome 运行中会锁定 cookie 数据库，导致无法继承 session |
| `agent-browser --profile xxx` 隔离配置 | Cookie 同步需要用户手动操作，仍然会遇到锁定问题 |
| Playwright MCP | 无法稳定继承本机 Chrome 登录状态 |
| **agent-browser --cdp 9222** | 直接连接已有 Chrome 实例，完美继承 cookies |

### CDP Profile 持久化机制

使用独立的 Chrome 用户数据目录 `cdp-profile`，与日常使用的 Chrome 默认 profile（`Default`）完全隔离：

```
C:\Users\jm024027\AppData\Local\Google\Chrome\User Data\
├── Default\                    # 日常 Chrome（不受影响）
└── cdp-profile\                # OMS 自动化专用
    └── Default\
        └── Network\
            └── Cookies         # SQLite 数据库，存储所有域名的 cookies
```

**工作原理**：
- 首次登录时输入验证码 → 服务端下发认证 token → 写入 `cdp-profile` 的 Cookies 数据库
- 后续启动 Chrome 时加载同一 profile → 自动携带认证 cookies → 无需重新登录
- Session 过期周期：通常几周甚至更久，取决于宝尊服务端策略
- **日常运行（cookies 有效）**：全自动，零人工干预
- **Session 过期时**：自动填账号密码+选企业，仅在需要验证码时暂停等待用户输入

### 为什么不能用默认 Chrome Profile

默认 Chrome Profile 在 Chrome 运行时会锁定 cookie 数据库（SQLite 锁），导致 `agent-browser` 无法读取。此外默认 profile 的 `--remote-debugging-port` 经常不生效（Chrome 静默忽略）。使用独立 `cdp-profile` 完全避免这些问题。

### 前提条件

1. `agent-browser` CLI 已安装并在 PATH 中
2. 首次使用需在 CDP profile 中手动登录一次 OMS（或由 `auto_login()` 自动完成）

### Chrome 启动逻辑

```python
def _ensure_chrome_running():
    # 通过 HTTP 请求检查 CDP 是否可用（比 netstat 更可靠）
    if _is_chrome_listening():  # urllib.request.urlopen('http://127.0.0.1:9222/json/version')
        return  # 直接用，登录状态已保留在 cdp-profile 中

    # 否则启动新的 Chrome 实例，使用 cdp-profile
    subprocess.Popen([
        r'C:\Users\jm024027\AppData\Local\Google\Chrome\Application\chrome.exe',
        '--remote-debugging-port=9222',
        '--user-data-dir=<cdp-profile-path>',
    ])
```

**注意**: 检测 CDP 使用 HTTP 请求（`urllib.request.urlopen`）而非 `netstat`，因为 `netstat` 在某些 Windows 环境下输出格式不稳定。

## 页面交互策略: JS 优先

agent-browser 的 `open`、`wait`、`find` 命令在 SPA 页面上不可靠（等页面 load complete 永远不触发、命令超时）。因此所有页面交互改用 JS eval：

| 操作 | 旧方案（agent-browser 命令） | 新方案（JS eval） |
|------|-----|------|
| 导航 | `run_ab('open URL')` | `_eval_js("location.href='URL'")` |
| 等待 | `run_ab('wait 3000')` | `time.sleep(3)` |
| 点击按钮 | `run_ab('find role button click --name "重置"')` | `_eval_js("btns[i].click()")` |

只保留 `agent-browser eval` 用于执行 JS，其余全部用 Python + JS 替代。

### 智能页面状态检测

`search_oms()` 启动后**先检测当前页面状态**，根据状态决定下一步，而非盲目导航再等待：

```
_detect_page_state() 返回值:
├── 'ready'        → OMS 商品管理页已就绪 → 直接开始搜索
├── 'login_page'   → 登录页 → 调用 auto_login() → 导航到 OMS
├── 'oms_loading'  → OMS URL 但表单未加载 → 渐进式轮询等待
└── 'other:URL'    → 其他页面（空白页/首页）→ 导航到 OMS → 再次检测
```

对应的 `_wait_for_oms_ready()` 使用渐进式等待：前 3 轮 1s、中间 3 轮 2s、之后 3s。避免固定 3s 导致已就绪时多等。

### agent-browser eval 返回值注意

`agent-browser eval` 返回的字符串值会带引号（如 `"ready"` 而非 `ready`）。比较前必须 `.strip('"')`：

```python
result = _eval_js(js, timeout=8).strip('"').strip("'")
if result == 'ready':  # 不 strip 会是 '"ready"' != 'ready'
    break
```

## agent-browser 命令序列

当前实际执行的命令序列（全部通过 `_eval_js` / Python）：

```python
# 1. 检测当前页面状态
state = _detect_page_state()  # JS eval: 检查 URL + 表单元素

# 2. 根据状态: 导航/登录/等待
_navigate_to(url)              # JS: location.href = url
time.sleep(...)                # Python: 渐进式等待

# 3. JS 点击重置
_eval_js("btns[i].textContent==='重置'? btns[i].click()")

# 4. JS 填入货号 (React setter + dispatchEvent)
_eval_js("setter.call(inp, search_text); inp.dispatchEvent(...)")

# 5. JS 点击搜索
_eval_js("btns[i].textContent==='搜索'? btns[i].click()")

# 6. JS 检查结果数
_eval_js("document.body.innerText.match(/共\\s*(\\d+)\\s*条/)")
```

## JS 执行: base64 + bash -c

### 为什么不能直接传 JS 字符串

OMS 自动化需要向 `agent-browser eval` 传递包含以下内容的 JS：
- 双引号 `"..."`
- 单引号 `'...'`
- 换行符
- 中文（如 `\u5e73\u53f0\u5bf9\u63a5\u7801`）

直接用 `agent-browser eval "..."` 会遇到：
1. Windows `cmd.exe` 不支持 `$()` 命令替换
2. 嵌套引号解析冲突
3. 中文编码问题

### 最终方案: bash -c + base64

```python
import base64

def run_ab(args, timeout=30):
    if args.startswith('eval "'):
        js_code = extract_js_from(args)
        encoded = base64.b64encode(js_code.encode('utf-8')).decode('ascii')
        # bash -c: 确保使用 bash 而非 cmd.exe
        # base64: 避免所有引号和特殊字符问题
        cmd = (
            f'bash -c \'{config.AB_BASE_CMD} eval "$('
            f'python -c "import sys,base64; sys.stdout.buffer.write(base64.b64decode(sys.argv[1]))" '
            f'{encoded}'
            f')"\''
        )
    else:
        cmd = f'bash -c \'{config.AB_BASE_CMD} {args}\''

    result = subprocess.run(cmd, shell=True, ...)
    return result.stdout
```

**原理拆解**:
1. Python 将 JS 编码为 base64 字符串（纯 ASCII）
2. `bash -c '...'` 启动 bash shell（Git Bash 可用）
3. `$(python -c "...")` 在 bash 中执行 Python，解码 base64 得到原始 JS
4. `agent-browser eval "..."` 接收纯净的 JS 字符串

## 表单填写: React 兼容方式

OMS 使用 Ant Design（React），直接设置 `input.value` 不会触发 React 状态更新。需要使用 `dispatchEvent`:

```javascript
(function(){
    var inp = document.querySelectorAll('.ant-form-item')[7].querySelector('textarea,input');
    inp.value = 'SPU1,SPU2';
    inp.dispatchEvent(new Event('input', {bubbles: true}));
    inp.dispatchEvent(new Event('change', {bubbles: true}));
    return inp.value;
})()
```

**注意**: Python f-string 中 `{bubbles:true}` 需要处理为普通字符串变量：
```python
bubbles_obj = "{bubbles:true}"
js_fill = (
    f"inp.value='{search_text}';"
    f"inp.dispatchEvent(new Event('input',{bubbles_obj}));"
)
```

## 数据提取: DevExtreme dx-datagrid

OMS 使用 **DevExtreme DataGrid** 组件（非普通 HTML table），DOM 结构如下：

```
tables[0]  = 操作列（1行，含"操作"按钮）
tables[1]  = 表头行（37列：序号、系统SKU编码、商品名称、货号、商品条码、平台对接码...）
tables[2]  = 数据行（搜索结果）
tables[3]  = 底部行（"更多"按钮）
```

**关键**: DevExtreme DataGrid 的表头使用 `<td>` 而非 `<th>`！用 `querySelectorAll('th')` 会返回空数组，导致提取 0 条记录。

JS 提取逻辑：
1. `tables[1].querySelectorAll('td')` 获取表头（**不是 `th`**）
2. 建立列名→索引映射（基于 `OMS_COLUMN_MAP`）
3. 遍历 `tables[2]` 数据行，按映射提取字段
4. 过滤无 `平台对接码` 的行（无效数据）
5. 返回 JSON 数组

## 自动登录流程

当 OMS session 过期时，`auto_login()` 自动完成以下步骤：

### 登录页 (https://account-dop.baozun.com/login)

| 元素 | DOM | 填充方式 |
|------|-----|---------|
| 账号 | `input[name=loginName]` | React setter + dispatchEvent |
| 密码 | `input[name=password]` | React setter + dispatchEvent |
| 登录按钮 | `button` text="立即登录" | agent-browser click |

**React 兼容填充**（Ant Design 组件必须用 setter 而非直接赋值）：
```javascript
var s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
s.call(inp, 'value');
inp.dispatchEvent(new Event('input', {bubbles:true}));
inp.dispatchEvent(new Event('change', {bubbles:true}));
```

### 企业选择页 (https://account-dop.baozun.com/selectTenant)

页面结构：`<ul>` 下两个 `<li>`，分别是"宝尊"和"Dunhill"。

```javascript
// 点击 Dunhill 租户
var lis = document.querySelectorAll('li');
for(var i=0; i<lis.length; i++) {
    if(lis[i].textContent.trim() === 'Dunhill') { lis[i].click(); }
}
```

### 验证码页面（仅偶尔触发）

如果登录后出现手机验证码页面，`auto_login()` 会：
1. 检测到验证码输入框（placeholder 包含"验证"或 name 包含"code"）
2. 暂停并在终端提示用户输入验证码
3. 用户输入后自动填入并提交
4. 登录成功后自动跳转到商品信息管理页

### 登录后落地页

无论登录过程经过哪些页面，最终都会自动跳转到：
`https://oms4.baozun.com/basic-info/product?target=tail`（商品信息管理页）

## 导出方案（推荐，替代 JS 提取）

JS 提取 DevExtreme DataGrid 存在不可靠问题（虚拟滚动/延迟渲染导致某些列值为空，`平台对接码` 过滤后返回 0 条）。推荐改用 OMS 导出按钮。

### 流程

```
1. 搜索 SPU（与 JS 提取方案相同）
2. JS 点击导出按钮: document.querySelectorAll('button,.ant-btn') 中找 text==='导出'
3. 从 DownloadMetadata 提取 OSS URL
4. Python urllib.request.urlretrieve 直接下载
5. openpyxl 解析 Excel，映射列名，INSERT IGNORE 到 DB
```

### 从 DownloadMetadata 提取 OSS URL

CDP Chrome 的下载记录存储在 `<cdp-profile>/Default/DownloadMetadata`（二进制文件，非纯文本），内含 OSS URL：

```
路径: C:\Users\jm024027\AppData\Local\Google\Chrome\User Data\cdp-profile\Default\DownloadMetadata
URL格式: https://bztic-gs-files-prod.oss-cn-shanghai.aliyuncs.com/prod/ecs-oms4-baseinfo-service_pro/YYYYMMDD/.../*.xlsx
```

**提取方法**：读取文件内容，用正则提取 `https://bztic-gs-files-prod\.oss-cn-shanghai\.aliyuncs\.com[^\s"']+\.xlsx`。

**直接下载**：OSS URL 通常是公开可访问的，直接用 `urllib.request.urlretrieve` 即可，无需 cookies。

### 导出 Excel 列结构

OMS 导出的 Excel 包含 42 列，关键字段：

| 列名 | 对应 DB 字段 | 说明 |
|------|-------------|------|
| 货号 | 货号 | SPU |
| 平台对接码 | 平台对接码 | SKU（UNIQUE KEY） |
| 商品名称 | 商品名称 | |
| 吊牌价 | 吊牌价 | 需转 float |
| 商品条码 | 商品条码 | |
| 开票名称 | OMS品类 | |

其他列（系统SKU编码、商品状态、品牌对接码等）不需要录入 DB。

### 完整脚本: `oms_export_import.py`

位于 `scripts/oms_export_import.py`，执行流程：

1. `load_unmatched_spus()` + 硬编码 SPU 列表
2. `_ensure_chrome_running()` + `run_ab('open OMS_URL')`
3. 检查登录 → `auto_login()`（如需要）
4. 重置 → 填货号 → 搜索
5. JS 点击导出按钮
6. 等待下载或从 DownloadMetadata 提取 URL
7. `_parse_exported_file()` 解析 xlsx/csv
8. `insert_oms_skus()` INSERT IGNORE 到 DB
9. `update_unmatched_spu_file()` 更新跟踪文件

## 关键坑点汇总

| 坑点 | 原因 | 解决方案 |
|------|------|---------|
| **`agent-browser open` 卡死** | SPA 页面 load complete 永远不触发（异步资源持续加载） | 改用 JS `location.href` 导航（`_navigate_to()`） |
| **`agent-browser wait` 卡死** | 页面重定向期间 agent-browser 整体无响应 | 改用 Python `time.sleep()` |
| **`agent-browser find` 超时** | find 命令在 SPA 页面上慢/不可靠 | 改用 JS `querySelectorAll + click()` |
| **eval 返回值带引号** | agent-browser eval 返回 JSON 编码的字符串 `"ready"` | 比较前 `.strip('"').strip("'")` |
| **session 过期时整体卡住** | 旧逻辑先 open→轮询→才检测登录页，白白等 60s+ | 改为先检测页面状态（`_detect_page_state()`），根据状态决定操作 |
| **表格提取返回 0 条** | DevExtreme DataGrid 表头用 `<td>` 而非 `<th>` | 用 `querySelectorAll('td')` |
| **JS 提取 `平台对接码` 为空** | DevExtreme 虚拟滚动/延迟渲染导致 DOM 中该列未填充 | 改用导出方案（点击导出按钮 + 下载 Excel） |
| **CDP Chrome 下载文件不在 ~/Downloads** | CDP profile 未设置 `download.default_directory` | 从 `DownloadMetadata` 提取 OSS URL 直接下载 |
| Python f-string `{bubbles:true}` 报 SyntaxError | f-string 把 `{}` 解析为 Python 表达式 | 提取到普通变量 |
| `agent-browser eval` 报 `missing ) after argument list` | Windows `cmd.exe` 不支持 `$()` | 用 `bash -c '...'` |
| subprocess 输出乱码/报错 | Windows GBK 编码问题 | `encoding='utf-8', errors='replace'` |
| 默认 Chrome Profile CDP 不生效 | Chrome 静默忽略 `--remote-debugging-port` | 用独立 `cdp-profile` |
| `--profile Default` 继承 cookie 失败 | Chrome 运行中锁定 cookie 数据库 | 用 `--cdp 9222` |
| `netstat` 检测 CDP 不可靠 | 不同 Windows 版本输出格式不同 | 用 HTTP 请求 `urllib.request.urlopen` |
| 登录后不在商品管理页 | 登录落地页是首页或预警页 | 自动 `open` 跳转到 `OMS_URL` |
| 清除 localStorage 后 OMS 404 | Angular 路由依赖 localStorage 状态 | 不要清除 localStorage，只依赖 cookie 过期 |
| Ant Design 表单填充不生效 | React 组件需要 dispatchEvent 触发状态更新 | 用 `HTMLInputElement.prototype.value` setter |

## subprocess 编码问题

Windows Python 默认使用 GBK 编码 subprocess 输出。必须显式指定：

```python
subprocess.run(
    cmd, shell=True, capture_output=True, text=True,
    timeout=timeout, encoding='utf-8', errors='replace',
)
```

## 未匹配 SPU 跟踪机制

`oms_unmatched_spu.xlsx` 结构：
- `status='待建档'`: 尚未在 OMS 中找到对应 SKU
- `status='已建档'`: 已在 OMS 中找到对应 SKU
- `checked_date`: 最后一次检查日期

每次执行 `oms_updater.py`:
1. 跳过 `checked_date == 今天` 的记录（已检查）
2. 搜索结果中找到的 → status 改为 `已建档`
3. 搜索结果中未找到 → 保留 `待建档`
4. 所有搜索过的 SPU → `checked_date` 更新为今天
