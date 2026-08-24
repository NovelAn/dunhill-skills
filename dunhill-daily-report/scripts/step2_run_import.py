"""
Step 2: Run Data Import Scripts (Improved Version with Auto-Retry)
Executes the data import Python scripts, verifies required files, and auto-retries failed downloads.
"""

import os
import sys
import locale

# ====== 加载 .env 跨平台路径配置 ======
from pathlib import Path as _P

# 尝试从 skill 符号链接路径加载，再尝试 dunhill-skills 原始路径
_env_candidates = [
    _P.home() / ".claude" / "skills" / ".env",
    _P.home() / ".claude" / "skills" / "dunhill-skills" / ".env",
]
_env_file = None
for _p in _env_candidates:
    if _p.exists():
        _env_file = _p
        break

if _env_file:
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
                # 路径类配置展开 ~ ：不展开的话 Path("~/Downloads") 是相对路径，glob 永远为空
                if _v.startswith("~") and (_k.endswith("_DIR") or _k.endswith("_PATH")):
                    _v = os.path.expanduser(_v)
                if _k and _k not in os.environ:
                    os.environ[_k] = _v

# ====== 自动检测并切换到项目 venv Python（仅在需要时）======
# 注意：此功能已暂时禁用，等待进一步调试
# _etl_dir = os.path.expanduser(os.environ.get("ETL_PIPELINES_DIR", "~/projects/data-import"))
# _venv_python = os.path.join(_etl_dir, ".venv", "bin", "python")
# if os.path.exists(_venv_python) and sys.executable != _venv_python:
#     os.execv(_venv_python, [_venv_python, "-u", __file__] + sys.argv[1:])

# ====== Windows 中文编码修复 ======
if sys.platform == 'win32':
    # 1. 设置环境变量强制UTF-8
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'

    # 2. 设置控制台代码页为 UTF-8 (65001)
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except:
        pass

    # 3. 重新包装 stdout/stderr 为 UTF-8
    try:
        if hasattr(sys.stdout, 'buffer'):
            import codecs
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, errors='replace')
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, errors='replace')
    except:
        pass

# Force unbuffered output for real-time progress display
try:
    sys.stdout.reconfigure(line_buffering=True)
except:
    pass

import subprocess
from pathlib import Path
import yaml
import time
import re
import glob
import filecmp
from datetime import date


class TaskTracker:
    """Track and display task progress in real-time with simple status messages."""

    def __init__(self):
        self.tasks = {
            'quickbi': {'status': 'pending', 'name': 'QuickBI订单源下载'},
            'sycm': {'status': 'pending', 'name': '生意参谋数据爬取'},
            'jycm': {'status': 'pending', 'name': '经营参谋数据下载'},
            'file_upload': {'status': 'pending', 'name': '文件上传处理'},
            'fq_crawler': {'status': 'pending', 'name': '分期购数据爬取'},
            'nick_crawler': {'status': 'pending', 'name': '买家昵称爬取'},
            'pfs_buyer_update': {'status': 'pending', 'name': 'PFS买家类型更新'},
            'dtc_buyer_update': {'status': 'pending', 'name': 'DTC买家类型更新'},
            'alimama': {'status': 'pending', 'name': '阿里妈妈数据爬取'},
            'file_verification': {'status': 'pending', 'name': '文件完整性验证'},
            'jycm_retry': {'status': 'pending', 'name': '经营参谋补下载'},
        }
        self.start_time = time.time()
        self.quickbi_tables = []
        self.jycm_reports = []
        self.completed_tasks = []

    def update_status(self, task, status, detail=None):
        """Update task status and display progress message."""
        if task not in self.tasks:
            return

        old_status = self.tasks[task]['status']
        self.tasks[task]['status'] = status

        # Print progress message when status changes to important states
        if status == 'running' and old_status not in ['running', 'completed']:
            print(f"  [>>] 开始执行: {self.tasks[task]['name']}")
            if detail:
                print(f"      - {detail}")

        elif status == 'completed' and old_status != 'completed':
            task_name = self.tasks[task]['name']
            if task_name not in self.completed_tasks:
                self.completed_tasks.append(task_name)
            print(f"  [OK] {task_name}完成")
            if detail:
                print(f"      - {detail}")

        elif status == 'failed':
            print(f"  [FAIL] {self.tasks[task]['name']}失败")
            if detail:
                print(f"      - {detail}")

        elif status == 'warning':
            print(f"  [WARN] {self.tasks[task]['name']}有警告")
            if detail:
                print(f"      - {detail}")

        elif status == 'skipped':
            print(f"  [SKIP] {self.tasks[task]['name']}已跳过")
            if detail:
                print(f"      - {detail}")

    def print_summary(self):
        """Print final summary of all tasks."""
        elapsed = time.time() - self.start_time
        mins, secs = divmod(int(elapsed), 60)

        print("\n" + "=" * 70)
        print(f"  步骤2执行完成 - 总耗时: {mins:02d}:{secs:02d}")
        print("=" * 70)

        completed = sum(1 for t in self.tasks.values() if t['status'] == 'completed')
        failed = sum(1 for t in self.tasks.values() if t['status'] == 'failed')
        total = len(self.tasks)

        print(f"\n  任务完成情况: {completed}/{total}")

        if self.completed_tasks:
            print(f"\n  已完成的任务:")
            for task_name in self.completed_tasks:
                print(f"    [OK] {task_name}")

        if self.quickbi_tables:
            print(f"\n  QuickBI表格详情:")
            for table in self.quickbi_tables:
                status_icon = '[OK]' if table['success'] else '[FAIL]'
                print(f"    {status_icon} {table['name']}: {table['rows']} 行")

        if self.jycm_reports:
            print(f"\n  经营参谋报告详情:")
            for report in self.jycm_reports:
                status_icon = '[OK]' if report['success'] else '[FAIL]'
                print(f"    {status_icon} {report['name']}")

        print("\n" + "=" * 70 + "\n")

    def add_quickbi_table(self, name, rows, success):
        """Add QuickBI table result."""
        self.quickbi_tables.append({
            'name': name,
            'rows': rows,
            'success': success
        })

    def add_jycm_report(self, name, success):
        """Add JYCM report result."""
        self.jycm_reports.append({
            'name': name,
            'success': success
        })


def load_config(config_path="config/dunhill-config.yaml"):
    """Load configuration from YAML file."""
    script_dir = Path(__file__).parent.parent
    config_file = script_dir / config_path

    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Resolve ${ENV_VAR} placeholders in string values
    config = _resolve_env_vars(config)

    return config


def _resolve_env_vars(obj):
    """Recursively resolve ${ENV_VAR} placeholders in config values."""
    if isinstance(obj, str):
        import re
        def _replace(match):
            var_name = match.group(1)
            value = os.environ.get(var_name, match.group(0))
            return os.path.expanduser(value)
        return re.sub(r'\$\{(\w+)\}', _replace, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


# Required JYCM daily reports (report_id, file_prefix)
# Note: 直播取数源 (dunhill_livestream_query_d_recent_1d_) 不是必须的，已从列表中移除
REQUIRED_JYCM_DAILY_REPORTS = [
    ("445603", "dunhill_shop_d_recent_30d_"),        # 取数源(shop源)
    ("225266", "dunhill_traffic_d_recent_1d_"),      # 流量源
    ("446524", "dunhill_client_d_recent_30d_"),      # 客户源
    ("445350", "dunhill_product_d_recent_1d_"),      # 商品源
    ("458866", "dunhill_product_traffic_d_recent_1d_"),    # 商品流量源
]

# Required QuickBI files
REQUIRED_QUICKBI_FILES = [
    "BI_tm_t01_trade_order_line",
    "BI_tm_trade_refund_info_allsuc_filter",
    "BI_tm_trade_refund_info_paydate_filter",
    "BI_dtc_t01_trade_order_line",
    "BI_dtc_t01_trade_refund_info_allsuc_filter",
]
QUICKBI_PREFIX_TO_STEP1_SOURCE = {
    "BI_tm_t01_trade_order_line": "tm_order",
    "BI_tm_trade_refund_info_allsuc_filter": "tm_refund_success",
    "BI_tm_trade_refund_info_paydate_filter": "tm_refund_pending",
    "BI_dtc_t01_trade_order_line": "dtc_order",
    "BI_dtc_t01_trade_refund_info_allsuc_filter": "dtc_refund",
}

STEP1_UPLOAD_PATTERNS = [
    ("退款源", ["[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9].xlsx"]),
    ("直播大盘", ["直播间大盘数据-*.xlsx"]),
    ("直播场次", ["直播分场次效果*.xlsx", "*分场次效果*.xlsx"]),
    ("直播订单", ["直播间成交订单明细*.xlsx"]),
    ("TM订单补充", ["BI_tm_t01_trade_order_line*.xlsx"]),
    ("TM退款成功补充", ["BI_tm_trade_refund_info_allsuc_filter*.xlsx"]),
    ("TM待退款补充", ["BI_tm_trade_refund_info_paydate_filter*.xlsx"]),
    ("DTC订单补充", ["BI_dtc_t01_trade_order_line*.xlsx"]),
    ("DTC退款补充", ["BI_dtc_t01_trade_refund_info_allsuc_filter*.xlsx"]),
    ("经营参谋店铺源", ["dunhill_shop_d_recent_*.xlsx"]),
    ("经营参谋流量源", ["dunhill_traffic_d_recent_*.xlsx"]),
    ("经营参谋商品源", ["dunhill_product_d_recent_*.xlsx"]),
    ("经营参谋商品流量源", ["dunhill_product_traffic_d_recent_*.xlsx"]),
]
STEP1_BACKUP_TARGETS = {
    "直播大盘": "dunhill_直播取数源",
    "直播场次": "dunhill_直播场次实时源",
    "直播订单": "dunhill_直播订单源",
    "TM订单补充": "dunhill_BI订单源",
    "TM退款成功补充": "dunhill_TM退款源_hive",
    "TM待退款补充": "dunhill_TM退款源_hive",
    "DTC订单补充": "dunhill_DTC订单源_hive",
    "DTC退款补充": "dunhill_DTC退款源_hive",
    "经营参谋店铺源": "dunhill_tm取数源_backup",
    "经营参谋流量源": "dunhill_tm流量源_new",
    "经营参谋商品源": "dunhill_tm商品源",
    "经营参谋商品流量源": "dunhill_tm商品流量源",
}
DATED_STEP1_LABELS = {
    "TM订单补充",
    "TM退款成功补充",
    "TM待退款补充",
    "DTC订单补充",
    "DTC退款补充",
    "经营参谋店铺源",
    "经营参谋流量源",
    "经营参谋商品源",
    "经营参谋商品流量源",
}


def get_download_path():
    """Get the Downloads folder path."""
    custom_download_path = os.getenv("DOWNLOAD_DIR")
    if custom_download_path and os.path.exists(custom_download_path):
        return custom_download_path
    return os.path.join(os.path.expanduser("~"), "Downloads")


def get_default_save_path():
    """Get the file_uploader backup path used after files leave Downloads."""
    data_dir = os.getenv("DUNHILL_DATA_DIR")
    if data_dir:
        candidate = os.path.join(data_dir, "文件下载")
        if os.path.exists(candidate):
            return candidate

    data_import_backup = Path.home() / "Projects" / "data-import" / "backup"
    if data_import_backup.exists():
        return str(data_import_backup)

    return os.path.join(os.getenv("DUNHILL_DATA_DIR", ""), "文件下载")


def file_mtime_is_today(path, day=None):
    """Check whether file modification time falls on the local calendar day."""
    if day is None:
        day = date.today()
    modified = date.fromtimestamp(os.path.getmtime(path))
    return modified == day


def is_empty_live_order_file(path):
    """Return True when a live-order export has headers but no data rows."""
    try:
        import pandas as pd

        return pd.read_excel(path).dropna(how="all").empty
    except Exception:
        return False


def backup_has_uploaded_file(label, file_path, save_path):
    """Return True only when the backup has the same name and contents."""
    target = STEP1_BACKUP_TARGETS.get(label)
    backup_dir = Path(save_path) / target if target else Path(save_path)
    filename = os.path.basename(file_path)
    if target:
        candidates = [backup_dir / filename]
    else:
        candidates = backup_dir.rglob(filename)
    return any(
        path.is_file() and filecmp.cmp(file_path, path, shallow=False)
        for path in candidates
    )


def filename_matches_day(path, day):
    compact, hyphen = date_tokens(day.isoformat())
    filename = os.path.basename(path)
    return compact in filename or hyphen in filename


def find_step1_upload_residuals(download_path, day=None, save_path=None):
    """
    Return Step 1 sources that still need upload handling.

    Completion requires the exact current source in data-import backup. An empty
    live-order export in Downloads is a valid no-order day and needs no upload.
    """
    if day is None:
        day = date.today()
    if save_path is None:
        save_path = get_default_save_path()

    residuals = []
    seen = set()
    for label, patterns in STEP1_UPLOAD_PATTERNS:
        for pattern in patterns:
            for file_path in glob.glob(os.path.join(download_path, pattern)):
                if not os.path.isfile(file_path):
                    continue
                if not file_mtime_is_today(file_path, day):
                    continue
                if label in DATED_STEP1_LABELS and not filename_matches_day(file_path, day):
                    continue
                if backup_has_uploaded_file(label, file_path, save_path):
                    continue
                key = os.path.abspath(file_path)
                if key in seen:
                    continue
                if label == "直播订单" and is_empty_live_order_file(file_path):
                    print(f"       [SKIP] 直播订单源为空，按正常无订单处理: {os.path.basename(file_path)}")
                    continue
                seen.add(key)
                residuals.append({
                    "label": label,
                    "path": key,
                    "name": os.path.basename(file_path),
                })
    return residuals


def date_tokens(date_text):
    """Return compact and hyphenated date strings for file-name matching."""
    text = str(date_text)
    compact = text.replace("-", "")
    if len(compact) == 8 and compact.isdigit():
        hyphen = f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
        return compact, hyphen
    return text, text


def check_required_jycm_files(download_path, today_str, save_path=None):
    """
    Check if all required JYCM files exist.
    Returns: (all_exist, missing_files)

    Note: dunhill_client_d_recent_30d_ (客户源) 文件可以残留在Downloads，会被忽略
    """
    missing = []

    # 客户源文件可以残留在Downloads，忽略检查
    ignored_prefixes = ['dunhill_client_d_recent_30d_']

    # 默认SavePath（file_uploader移动文件的目标路径）
    if save_path is None:
        save_path = get_default_save_path()

    # 支持两种日期格式：20260310 和 2026-03-10
    today_compact, today_hyphen = date_tokens(today_str)

    for report_id, file_prefix in REQUIRED_JYCM_DAILY_REPORTS:
        # 跳过客户源文件检查
        if any(ignore in file_prefix for ignore in ignored_prefixes):
            continue

        # Pattern: prefix + YYYY-MM-DD.xlsx or prefix + today.xlsx
        pattern2 = os.path.join(download_path, f"{file_prefix}*.xlsx")

        # Check if file exists in Downloads (支持两种日期格式)
        files = glob.glob(pattern2)
        today_files = [f for f in files if today_compact in f or today_hyphen in f]

        if not today_files:
            # 检查文件是否已移动到SavePath (支持两种日期格式)
            save_pattern = os.path.join(save_path, "**", f"{file_prefix}*{today_compact}*.xlsx")
            saved_files = glob.glob(save_pattern, recursive=True)

            # 也检查带连字符的日期格式
            if not saved_files:
                save_pattern_hyphen = os.path.join(save_path, "**", f"{file_prefix}*{today_hyphen}*.xlsx")
                saved_files = glob.glob(save_pattern_hyphen, recursive=True)

            if not saved_files:
                # 文件既不在Downloads也不在SavePath，才是真正缺失
                missing.append((report_id, file_prefix))

    return len(missing) == 0, missing


def check_required_quickbi_files(download_path, today_str, save_path=None):
    """
    Check if all required QuickBI files exist.
    Returns: (all_exist, missing_files)
    """
    missing = []

    # 默认SavePath（file_uploader移动文件的目标路径）
    if save_path is None:
        save_path = get_default_save_path()

    # 支持两种日期格式：20260310 和 2026-03-10
    today_compact, today_hyphen = date_tokens(today_str)

    for file_prefix in REQUIRED_QUICKBI_FILES:
        pattern = os.path.join(download_path, f"{file_prefix}*.xlsx")
        files = glob.glob(pattern)
        today_files = [f for f in files if today_compact in f or today_hyphen in f]

        if not today_files:
            # 检查文件是否已移动到SavePath (支持两种日期格式)
            save_pattern = os.path.join(save_path, "**", f"{file_prefix}*{today_compact}*.xlsx")
            saved_files = glob.glob(save_pattern, recursive=True)

            # 也检查带连字符的日期格式
            if not saved_files:
                save_pattern_hyphen = os.path.join(save_path, "**", f"{file_prefix}*{today_hyphen}*.xlsx")
                saved_files = glob.glob(save_pattern_hyphen, recursive=True)

            if not saved_files:
                # 文件既不在Downloads也不在SavePath，才是真正缺失
                missing.append(file_prefix)

    return len(missing) == 0, missing


def confirmed_zero_quickbi_sources(logs_dir):
    """Return sources whose Step 1 preview explicitly confirmed zero rows."""
    sources = set()
    pattern = re.compile(r'"prefix"\s*:\s*"([^"]+)".*?"rows"\s*:\s*0(?:\D|$)')
    for log_path in Path(logs_dir).glob("step1*.log"):
        for match in pattern.finditer(log_path.read_text(encoding="utf-8", errors="replace")):
            sources.add(match.group(1))
    return sources


def quickbi_completion_gate(run_succeeded, files_ok, missing_files, confirmed_zero_sources=()):
    """只有子流程成功且当天必需 QuickBI 文件齐全时才允许 Step 2 成功。"""
    unresolved = [source for source in missing_files if source not in confirmed_zero_sources]
    return bool(run_succeeded and (files_ok or not unresolved)), unresolved


def tm_order_import_complete(source_keys, database_keys):
    """Return whether every order line in today's source is present in MySQL."""
    return bool(source_keys) and source_keys <= database_keys


def verify_tm_order_database(data_import_dir, run_day, save_path=None):
    """Reconcile today's Tmall order source keys against the destination table."""
    import pandas as pd
    from sqlalchemy import bindparam, text

    if save_path is None:
        save_path = get_default_save_path()
    compact, hyphen = date_tokens(run_day.isoformat())
    backup_dir = Path(save_path) / STEP1_BACKUP_TARGETS["TM订单补充"]
    source_files = [
        path for path in backup_dir.glob("BI_tm_t01_trade_order_line*.xlsx")
        if compact in path.name or hyphen in path.name
    ]
    source_keys = set()
    for path in source_files:
        frame = pd.read_excel(path, dtype={"订单号": str, "子订单号": str})
        frame.columns = [str(column).split("-")[0].strip() for column in frame.columns]
        if not {"订单号", "子订单号"} <= set(frame.columns):
            raise ValueError(f"天猫订单源缺少订单号/子订单号列: {path.name}")
        source_keys.update(
            (str(order).strip(), str(line).strip())
            for order, line in frame[["订单号", "子订单号"]].dropna().itertuples(index=False, name=None)
        )
    if not source_keys:
        return False, "当天备份中没有可核验的天猫订单行"

    sys.path.insert(0, data_import_dir)
    sys.path.insert(0, os.path.join(data_import_dir, "src"))
    from data_pipeline.core import Engines

    statement = text(
        "SELECT `订单号`, `子订单号` FROM `dunhill_bi订单源` "
        "WHERE `订单号` IN :order_ids"
    ).bindparams(bindparam("order_ids", expanding=True))
    database_keys = set()
    order_ids = sorted({order for order, _ in source_keys})
    with Engines[0].connect() as connection:
        for start in range(0, len(order_ids), 500):
            rows = connection.execute(statement, {"order_ids": order_ids[start:start + 500]})
            database_keys.update((str(order).strip(), str(line).strip()) for order, line in rows)

    missing_count = len(source_keys - database_keys)
    if not tm_order_import_complete(source_keys, database_keys):
        return False, f"数据库缺少当天源中的 {missing_count} 个订单行"
    return True, f"数据库已核验当天源中的 {len(source_keys)} 个订单行"


def run_taobao_login_interactive(data_import_dir):
    """
    Run the Taobao login helper, auto-selecting menu option 1.

    The login helper still needs a human to scan/confirm in Chrome. This wrapper
    keeps that interaction in the current terminal, then returns to Step 2 so it
    can re-check cookies and continue automatically.
    """
    login_script = os.path.join(data_import_dir, "scripts", "login", "taobao_login.py")
    if not os.path.exists(login_script):
        print(f"  [FAIL] 未找到登录脚本: {login_script}")
        return False

    print("\n" + "=" * 70)
    print("  千牛 cookies 已过期，自动启动登录脚本")
    print("=" * 70)
    print("  [AUTO] 将自动选择: 1. 千牛/淘宝")
    print("  [ACTION] 浏览器打开后，请完成扫码/验证；脚本提示时按 Enter 继续。")

    def chrome_has_taobao_session():
        script = '''
tell application "Google Chrome"
  repeat with w in windows
    repeat with t in tabs of w
      set u to URL of t
      if (u contains "myseller.taobao.com" or u contains "trade.taobao.com") and u does not contain "login" then
        return u
      end if
    end repeat
  end repeat
end tell
return ""
'''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        url = result.stdout.strip()
        return url or None

    def wait_for_taobao_session(timeout=300):
        print("  [WAIT] 当前环境无法读取终端 Enter，改为自动等待 Chrome 登录成功...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            url = chrome_has_taobao_session()
            if url:
                print(f"  [OK] 检测到千牛/淘宝登录态: {url}")
                return True
            time.sleep(2)
        print("  [FAIL] 等待 Chrome 登录成功超时")
        return False

    if os.name != "posix":
        print("  [WARN] 当前系统不支持 PTY 自动菜单选择，请手动选择 1。")
        result = subprocess.run([sys.executable, "-u", login_script], cwd=data_import_dir)
        return result.returncode == 0

    import pty
    import select

    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-u", login_script],
        cwd=data_import_dir,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    sent_menu_choice = False
    output_window = ""
    enter_prompt_markers = [
        "按回车继续",
        "按回车键继续",
    ]

    try:
        while process.poll() is None:
            ready, _, _ = select.select([master_fd], [], [], 0.2)
            if not ready:
                continue

            try:
                data = os.read(master_fd, 4096)
            except OSError:
                break
            if not data:
                break

            text = data.decode("utf-8", errors="replace")
            sys.stdout.write(text)
            sys.stdout.flush()
            output_window = (output_window + text)[-4000:]

            if not sent_menu_choice and "请输入选项" in output_window:
                os.write(master_fd, b"1\n")
                sent_menu_choice = True
                output_window = ""
                continue

            if sent_menu_choice and any(marker in output_window for marker in enter_prompt_markers):
                print("\n  [WAIT] 请在浏览器中完成登录/验证后，回到这里按 Enter 继续...", flush=True)
                if sys.stdin.isatty():
                    try:
                        input()
                    except EOFError:
                        print("  [WARN] 当前环境无法读取 Enter 输入，改为自动检测 Chrome 登录态。")
                        if not wait_for_taobao_session():
                            process.terminate()
                            return False
                else:
                    if not wait_for_taobao_session():
                        process.terminate()
                        return False
                os.write(master_fd, b"\n")
                output_window = ""

        while True:
            ready, _, _ = select.select([master_fd], [], [], 0.1)
            if not ready:
                break
            try:
                data = os.read(master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            sys.stdout.write(data.decode("utf-8", errors="replace"))
            sys.stdout.flush()
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass

    return_code = process.wait()
    if return_code == 0:
        print("\n  [OK] 登录脚本执行完成")
        return True
    print(f"\n  [FAIL] 登录脚本返回码: {return_code}")
    return False


def run_taobao_login_mcp(data_import_dir):
    """Run the MCP-based Taobao login updater in the user's normal Chrome."""
    login_script = os.path.join(data_import_dir, "scripts", "login", "taobao_login_mcp.py")
    if not os.path.exists(login_script):
        print(f"  [WARN] 未找到 MCP 登录脚本: {login_script}")
        return False

    print("\n" + "=" * 70)
    print("  千牛 cookies 已过期，优先使用本机 Chrome MCP 登录更新")
    print("=" * 70)
    print("  [ACTION] 如出现二维码，请用手机淘宝/千牛扫码；脚本会自动继续。")

    process = subprocess.Popen(
        [sys.executable, "-u", login_script],
        cwd=data_import_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line.rstrip())
    return_code = process.wait()
    if return_code == 0:
        print("  [OK] MCP 登录脚本执行完成")
        return True
    print(f"  [WARN] MCP 登录脚本失败，返回码: {return_code}")
    return False


def run_alimama_auth_refresh(manage_script, data_import_dir, tracker=None):
    """Refresh Alimama csrfId/cookies through local Chrome MCP before crawling."""
    print("\n" + "=" * 70)
    print("  阿里妈妈认证刷新: Playwright MCP Extension + 本机 Chrome")
    print("=" * 70)

    process = subprocess.Popen(
        [sys.executable, "-u", manage_script, "alimama", "--refresh-auth"],
        cwd=data_import_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line.rstrip())

    return_code = process.wait()
    if return_code == 0:
        print("  [OK] 阿里妈妈认证刷新完成")
        return True

    print(f"  [WARN] 阿里妈妈认证刷新失败，返回码: {return_code}")
    if tracker:
        tracker.update_status('alimama', 'warning', '认证刷新失败，后续爬虫会尝试自动刷新')
    return False


def run_alimama_crawler(manage_script, data_import_dir, tracker):
    """Run the daily Alimama crawler as an independent Step 2 task."""
    tracker.update_status('alimama', 'running', '正在抓取并入库阿里妈妈数据')

    print("\n" + "=" * 70)
    print("  Step 2: 执行阿里妈妈数据爬取")
    print("=" * 70)

    process = subprocess.Popen(
        [sys.executable, "-u", manage_script, "alimama"],
        cwd=data_import_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line.rstrip())

    return_code = process.wait()
    if return_code == 0:
        tracker.update_status('alimama', 'completed', '阿里妈妈数据爬取完成')
        return True

    tracker.update_status('alimama', 'failed', f'阿里妈妈爬虫返回码: {return_code}')
    return False


def download_single_jycm_file(args):
    """
    Download a single JYCM file (worker function for parallel execution).

    Args:
        args: Tuple of (report_id, file_prefix, today_str, download_path, max_retries)

    Returns:
        Tuple of (report_id, file_prefix, success)
    """
    report_id, file_prefix, today_str, download_path, max_retries = args
    save_name = f"{file_prefix}{today_str}"

    # Add project paths for imports (each thread needs its own import)
    data_import_dir = os.getenv("ETL_PIPELINES_DIR", r"D:\Work\DataProject\数据导入程序")
    if data_import_dir not in sys.path:
        sys.path.insert(0, data_import_dir)
    src_dir = os.path.join(data_import_dir, 'src')
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    try:
        from data_pipeline.crawler.tasks.jycm import JycmCrawler
    except ImportError as e:
        print(f"  [ERROR] 无法导入JycmCrawler: {e}")
        return (report_id, file_prefix, False)

    # Each thread creates its own crawler instance
    crawler = JycmCrawler()

    print(f"\n  [>>] 下载: {save_name}")
    print(f"       报告ID: {report_id}")

    # Reduced retry logic with shorter wait times
    retry_count = 0
    success = False

    while retry_count < max_retries and not success:
        retry_count += 1
        wait_time = 3 + retry_count  # 4s, 5s, 6s, 7s, 8s... (faster than before)

        try:
            print(f"       [{save_name}] 尝试 {retry_count}/{max_retries} (等待{wait_time}秒)...")
            crawler.download(report_id=report_id, save_name=save_name, sleep_time=wait_time)

            # Verify file was created
            expected_file = os.path.join(download_path, f"{save_name}.xlsx")
            if os.path.exists(expected_file):
                print(f"       [{save_name}] [OK] 下载成功!")
                success = True
            else:
                print(f"       [{save_name}] [WARN] 文件未创建，重试...")

        except Exception as e:
            print(f"       [{save_name}] [WARN] 下载失败: {str(e)[:50]}")

        if not success and retry_count < max_retries:
            time.sleep(2)  # Shorter wait before next retry

    if not success:
        print(f"       [{save_name}] [FAIL] 超过最大重试次数")

    return (report_id, file_prefix, success)


def download_missing_jycm_files(missing_files, download_path, today_str, max_retries=5):
    """
    Download missing JYCM files in parallel.

    Args:
        missing_files: List of (report_id, file_prefix) tuples
        download_path: Path to Downloads folder
        today_str: Today's date string (YYYY-MM-DD)
        max_retries: Maximum number of retries per file (reduced to 5)

    Returns:
        List of files that still failed to download
    """
    if not missing_files:
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    print(f"\n  {'='*60}")
    print(f"  开始并行补充下载 {len(missing_files)} 个缺失的经营参谋文件...")
    print(f"  {'='*60}")

    # Prepare arguments for parallel execution
    tasks = [
        (report_id, file_prefix, today_str, download_path, max_retries)
        for report_id, file_prefix in missing_files
    ]

    still_missing = []

    # Use ThreadPoolExecutor for parallel downloads
    with ThreadPoolExecutor(max_workers=len(missing_files)) as executor:
        futures = {executor.submit(download_single_jycm_file, task): task for task in tasks}

        for future in as_completed(futures):
            report_id, file_prefix, success = future.result()
            if not success:
                still_missing.append((report_id, file_prefix))

    return still_missing


def download_missing_quickbi_files(missing_files):
    """Download only the missing QuickBI Step 1 sources, skipping refund and live exports."""
    sources = [
        QUICKBI_PREFIX_TO_STEP1_SOURCE[prefix]
        for prefix in missing_files
        if prefix in QUICKBI_PREFIX_TO_STEP1_SOURCE
    ]
    if not sources:
        return list(missing_files)

    root_dir = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-u",
        str(root_dir / "scripts" / "step1_collect_data.py"),
        "--skip-refund",
        "--skip-live",
        "--quickbi-sources",
        *sources,
    ]
    print(f"\n  {'='*60}")
    print(f"  补充下载缺失 QuickBI 源: {', '.join(sources)}")
    print(f"  {'='*60}")
    result = subprocess.run(command, cwd=str(root_dir))
    if result.returncode != 0:
        return list(missing_files)

    today_str = date.today().strftime("%Y-%m-%d")
    _, still_missing = check_required_quickbi_files(get_download_path(), today_str)
    return [prefix for prefix in still_missing if prefix in missing_files]


def run_file_uploader(data_import_dir, timeout=900):
    """Run the file_uploader.py script to upload all files to database."""
    uploader_script = os.path.join(data_import_dir, 'src', 'data_pipeline', 'processors', 'file_uploader.py')

    print(f"\n  {'='*60}")
    print(f"  执行文件上传程序...")
    print(f"  {'='*60}")

    try:
        result = subprocess.run(
            [sys.executable, '-u', uploader_script],
            cwd=data_import_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8',
            errors='replace'
        )

        # Print output
        if result.stdout:
            # Only print key lines to avoid clutter
            for line in result.stdout.split('\n'):
                if any(key in line for key in ['[OK]', '[FAIL]', 'ERROR', '成功', '失败', '写入MySQL', '目标:', '移动', '文件成功']):
                    print(f"       {line.strip()}")

        if result.returncode == 0:
            print(f"\n       [OK] 文件上传完成")
            return True
        else:
            print(f"\n       [WARN] 文件上传返回码: {result.returncode}")
            return False

    except subprocess.TimeoutExpired:
        print(f"       [WARN] 文件上传超时 ({timeout}s)")
        return False
    except Exception as e:
        print(f"       [ERROR] 文件上传失败: {e}")
        return False


def print_upload_residuals(residuals, prefix="       -"):
    for item in residuals:
        print(f"{prefix} {item['label']}: {item['name']}")


def residual_key(residuals):
    return sorted(item["path"] for item in residuals)


def drain_upload_residuals(data_import_dir, download_path, tracker, day=None, max_attempts=3):
    """
    Upload raw source files until Downloads is clean.

    file_uploader logs/return codes are not reliable enough for this workflow:
    success is defined only by all expected raw files moving out of Downloads.
    """
    residuals = find_step1_upload_residuals(download_path, day)
    if not residuals:
        tracker.update_status('file_upload', 'completed', 'backup 已有今天有效源，空直播订单无需上传')
        print("\n  [OK] backup 已有今天有效源；空直播订单按无订单日处理，可视为上传完成")
        return True

    tracker.update_status('file_upload', 'warning', f'发现 {len(residuals)} 个源尚未进入 backup')
    print("\n  [WARN] 发现今天仍有原始数据源未进入 backup，执行文件上传补偿...")
    print_upload_residuals(residuals)

    previous_key = residual_key(residuals)
    for attempt in range(1, max_attempts + 1):
        print(f"\n  [>>] 文件上传补偿尝试 {attempt}/{max_attempts}")
        time.sleep(3)
        run_file_uploader(data_import_dir)

        residuals = find_step1_upload_residuals(download_path, day)
        if not residuals:
            tracker.update_status('file_upload', 'completed', 'backup 已有今天有效源')
            print("       [OK] 文件上传完成，backup 已有今天有效源")
            return True

        current_key = residual_key(residuals)
        tracker.update_status('file_upload', 'warning', f'仍有 {len(residuals)} 个源尚未进入 backup')
        print("       [WARN] 文件上传后仍有源尚未进入 backup:")
        print_upload_residuals(residuals, prefix="              -")
        if current_key == previous_key:
            break
        previous_key = current_key

    tracker.update_status('file_upload', 'failed', '文件上传后仍有源尚未进入 backup')
    print("       [FAIL] 文件上传后仍有源尚未进入 backup，不能继续后置任务")
    print_upload_residuals(residuals, prefix="              -")
    tracker.print_summary()
    return False


def run_order_crawlers(data_import_dir):
    """
    Run order crawlers (fq and nick) and buyer type updates.

    执行顺序（重要）:
    1. file_uploader 必须先完成
    2. UpdateMaskedBuyerNicknames 必须在爬虫前完成
    3. fq_crawler / nick_crawler / PFS买家类型 / DTC买家类型 可并发执行
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    print(f"\n  {'='*60}")
    print(f"  执行后续任务: 爬虫和买家类型更新...")
    print(f"  {'='*60}")
    print(f"  执行策略: mask 完成后，并发执行 fq/nick/PFS/DTC")

    # Add project paths for imports
    sys.path.insert(0, data_import_dir)
    sys.path.insert(0, os.path.join(data_import_dir, 'src'))

    results = {
        'mask_update': False,
        'fq_crawler': False,
        'nick_crawler': False,
        'pfs_buyer_update': False,
        'dtc_buyer_update': False
    }
    results_lock = threading.Lock()

    def update_result(key, value):
        with results_lock:
            results[key] = value

    def run_pfs_buyer_update(user_info):
        """PFS买家类型更新（可并发）"""
        print(f"\n  [>>] 执行PFS买家类型更新...")
        try:
            from scripts.update_pfs_buyer_types import BuyerTypeUpdater
            updater = BuyerTypeUpdater()
            updater.run()
            update_result('pfs_buyer_update', True)
            print(f"       [OK] PFS买家类型更新完成")
        except Exception as e:
            print(f"       [WARN] PFS买家类型更新失败，尝试存储过程: {str(e)[:50]}")
            try:
                user_info.call_buyer_types_update_execute("UpdatePFSBuyerTypes")
                update_result('pfs_buyer_update', True)
                print(f"       [OK] PFS买家类型更新完成(存储过程)")
            except Exception as e2:
                print(f"       [FAIL] PFS买家类型更新失败: {str(e2)[:50]}")

    def run_dtc_buyer_update(user_info):
        """DTC买家类型更新（可并发）"""
        print(f"\n  [>>] 执行DTC买家类型更新...")
        try:
            from scripts.update_dtc_buyer_types import DTCBuyerTypeUpdater
            updater = DTCBuyerTypeUpdater()
            updater.run()
            update_result('dtc_buyer_update', True)
            print(f"       [OK] DTC买家类型更新完成")
        except Exception as e:
            print(f"       [WARN] DTC买家类型更新失败，尝试存储过程: {str(e)[:50]}")
            try:
                user_info.call_buyer_types_update_execute("UpdateDTCBuyerTypes")
                update_result('dtc_buyer_update', True)
                print(f"       [OK] DTC买家类型更新完成(存储过程)")
            except Exception as e2:
                print(f"       [FAIL] DTC买家类型更新失败: {str(e2)[:50]}")

    try:
        from data_pipeline.crawler.tasks.orderinfo import UserInfo
        user_info = UserInfo()

        # 在爬虫解密前，先通过存储过程解密历史老客昵称，减少爬虫请求量
        print(f"\n  [>>] 执行存储过程 UpdateMaskedBuyerNicknames（解密历史老客昵称）...")
        try:
            user_info.call_buyer_types_update_execute("UpdateMaskedBuyerNicknames")
            update_result('mask_update', True)
            print(f"       [OK] 存储过程执行成功")
        except Exception as e:
            print(f"       [WARN] 存储过程执行失败: {str(e)[:80]}")

        def run_nick_crawler():
            if not results.get('mask_update'):
                print(f"\n  [WARN] 跳过买家昵称爬虫：UpdateMaskedBuyerNicknames 未成功完成")
                return

            print(f"\n  [>>] 执行买家昵称爬虫（千牛后台）...")
            try:
                user_info.nick_spider_execute("dunhill_bi订单源")
                update_result('nick_crawler', True)
                print(f"       [OK] 买家昵称爬虫完成")
            except Exception as e:
                print(f"       [WARN] 买家昵称爬虫执行失败: {str(e)[:50]}")

        def run_fq_crawler():
            print(f"\n  [>>] 执行分期购爬虫（千牛后台）...")
            try:
                user_info.fq_spider_execute("dunhill_tm订单分期购")
                update_result('fq_crawler', True)
                print(f"       [OK] 分期购爬虫完成")
            except Exception as e:
                print(f"       [WARN] 分期购爬虫执行失败: {str(e)[:50]}")

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(run_fq_crawler),
                pool.submit(run_nick_crawler),
                pool.submit(run_pfs_buyer_update, user_info),
                pool.submit(run_dtc_buyer_update, user_info),
            ]
            for future in as_completed(futures):
                future.result()

    except ImportError as e:
        print(f"       [ERROR] 无法导入所需模块: {e}")
        return results
    except Exception as e:
        print(f"       [ERROR] 后续任务执行错误: {e}")

    # Summary
    success_count = sum(1 for v in results.values() if v)
    print(f"\n  后续任务完成: {success_count}/5")

    return results


def run_import_script(
    config,
    skip_upload=False,
    auto_retry=True,
    auto_login=True,
    refresh_alimama_auth_first=False,
    run_alimama=True,
):
    """Execute run.py and monitor for QuickBI warnings."""
    print("\n" + "=" * 70)
    print("  步骤2: 执行数据导入程序 (增强版 - 自动验证与重试)")
    print("=" * 70)
    print("\n开始执行数据导入流程...\n")

    tracker = TaskTracker()

    run_script = config['paths']['run_script']
    manage_script = config['paths']['manage_script']
    data_import_dir = config['paths']['data_import_dir']
    check_interval = config['settings']['script_check_interval']
    max_wait = config['settings']['script_max_wait']

    print(f"执行脚本: {run_script}")
    print(f"工作目录: {data_import_dir}\n")

    # Change to data import directory
    original_dir = os.getcwd()
    os.chdir(data_import_dir)

    # 千牛 cookie 健康检查（在 run.py 之前预检，避免浪费时间）
    try:
        sys.path.insert(0, data_import_dir)
        sys.path.insert(0, os.path.join(data_import_dir, 'src'))
        from data_pipeline.crawler.base import check_taobao_cookie_health

        print("  [>>] 检查千牛 cookies 有效性...")
        if not check_taobao_cookie_health():
            if auto_login:
                tracker.update_status('nick_crawler', 'warning', '千牛 cookies 已过期，准备自动更新认证')
                tracker.update_status('fq_crawler', 'warning', '千牛 cookies 已过期，准备自动更新认证')
                login_ok = run_taobao_login_mcp(data_import_dir)
                if not login_ok:
                    print("\n[FAIL] MCP 登录更新失败；按要求不回退到旧 Playwright 登录脚本。")
                if not login_ok:
                    tracker.update_status('nick_crawler', 'failed', '千牛 MCP 登录脚本执行失败')
                    tracker.update_status('fq_crawler', 'failed', '千牛 MCP 登录脚本执行失败')
                    tracker.print_summary()
                    os.chdir(original_dir)
                    return False

                print("\n  [>>] 重新检查千牛 cookies 有效性...")
                if not check_taobao_cookie_health():
                    tracker.update_status('nick_crawler', 'failed', '登录后千牛 cookies 仍无效')
                    tracker.update_status('fq_crawler', 'failed', '登录后千牛 cookies 仍无效')
                    print("\n[FAIL] 登录脚本已执行，但 cookies 仍然无效。请检查浏览器登录是否成功。")
                    tracker.print_summary()
                    os.chdir(original_dir)
                    return False
                print("  [OK] 千牛 cookies 已更新并验证通过")
            else:
                tracker.update_status('nick_crawler', 'failed', '千牛 cookies 已过期')
                tracker.update_status('fq_crawler', 'failed', '千牛 cookies 已过期')
                print("\n[!] 千牛 cookies 已过期！请先运行登录脚本更新认证：")
                print("  python scripts/login/taobao_login.py")
                print("更新完成后重新执行步骤2即可。")
                tracker.print_summary()
                os.chdir(original_dir)
                return False
        print("  [OK] 千牛 cookies 有效")
    except Exception as e:
        print(f"  [WARN] Cookie 健康检查异常: {e}，继续执行...")

    if refresh_alimama_auth_first:
        run_alimama_auth_refresh(manage_script, data_import_dir, tracker)

    try:
        # Execute run.py with unbuffered output
        process = subprocess.Popen(
            [sys.executable, '-u', run_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            encoding='utf-8',
            errors='replace'
        )

        output_lines = []
        quickbi_warning_detected = False

        while True:
            line = process.stdout.readline()

            if not line and process.poll() is not None:
                break

            if line:
                output_lines.append(line)
                line_stripped = line.strip()

                # Track QuickBI progress
                if 'QuickBI' in line or 'quickbi' in line.lower():
                    if '开始执行' in line or '启动' in line:
                        tracker.update_status('quickbi', 'running', '正在抓取数据')
                    elif '成功' in line:
                        tracker.update_status('quickbi', 'completed', '数据抓取完成')
                    elif '异常' in line or '错误' in line:
                        tracker.update_status('quickbi', 'failed', '请检查日志')

                # Track 生意参谋
                if '生意参谋' in line or 'sycm' in line.lower():
                    if '开始执行' in line:
                        tracker.update_status('sycm', 'running', '正在爬取数据')
                    elif '成功' in line:
                        tracker.update_status('sycm', 'completed', '数据爬取完成')
                    elif '异常' in line or '错误' in line:
                        tracker.update_status('sycm', 'failed', '请检查日志')

                # Track 经营参谋
                if '经营参谋' in line or 'jycm' in line.lower():
                    if '开始执行' in line:
                        tracker.update_status('jycm', 'running', '正在下载数据')
                    elif '成功' in line:
                        tracker.update_status('jycm', 'completed', '数据下载完成')
                    elif '异常' in line or '错误' in line:
                        tracker.update_status('jycm', 'failed', '请检查日志')

                # Track JYCM report downloads (specific report names)
                jycm_report_pattern = re.search(r'dunhill_\w+_d_recent_\d+d[_\w]*', line)
                if jycm_report_pattern:
                    report_name = jycm_report_pattern.group()
                    # Clean up the report name for display
                    display_name = report_name.rstrip('_')
                    print(f"      - 正在下载报告: {display_name}")

                # Check for successful JYCM download
                if '保存文件成功' in line or 'download success' in line.lower():
                    # Try to extract report name from context
                    report_match = re.search(r'dunhill_\w+_d_recent_\d+d[_\w]*', line)
                    if report_match:
                        report_name = report_match.group().rstrip('_')
                        tracker.add_jycm_report(report_name, True)
                        print(f"      - [OK] {report_name} 下载成功")

                # Check for failed JYCM download
                if '下载失败' in line or 'download failed' in line.lower():
                    report_match = re.search(r'dunhill_\w+_d_recent_\d+d[_\w]*', line)
                    if report_match:
                        report_name = report_match.group().rstrip('_')
                        tracker.add_jycm_report(report_name, False)
                        print(f"      - [FAIL] {report_name} 下载失败")

                # Track 文件上传
                if '文件上传' in line or '文件导入' in line:
                    if '开始执行' in line:
                        tracker.update_status('file_upload', 'running', '正在处理文件')
                    elif '成功' in line or '完成' in line:
                        tracker.update_status('file_upload', 'completed', '文件处理完成')
                    elif '错误' in line:
                        tracker.update_status('file_upload', 'warning', '有警告但继续')

                # Track 分期购爬虫 (fq)
                if re.search(r'\bfq\b', line, re.IGNORECASE) or '分期购' in line:
                    if '开始执行' in line and '爬虫程序' in line:
                        tracker.update_status('fq_crawler', 'running', '正在爬取分期购数据')
                    elif '执行成功' in line or '爬虫程序执行成功' in line:
                        tracker.update_status('fq_crawler', 'completed', '分期购数据爬取完成')
                    elif '异常' in line:
                        error_match = re.search(r'fq.*?异常[：:]\s*(.+)', line, re.IGNORECASE)
                        error_msg = error_match.group(1) if error_match else '请检查日志'
                        tracker.update_status('fq_crawler', 'warning', f'可能有错误: {error_msg}')

                # Track 买家昵称爬虫 (nick)
                if re.search(r'\bnick\b', line, re.IGNORECASE) and '分期购' not in line or '买家昵称' in line:
                    if '开始执行' in line and '爬虫程序' in line:
                        tracker.update_status('nick_crawler', 'running', '正在爬取买家昵称')
                    elif '执行成功' in line or '爬虫程序执行成功' in line:
                        tracker.update_status('nick_crawler', 'completed', '买家昵称爬取完成')
                    elif '异常' in line:
                        error_match = re.search(r'nick.*?异常[：:]\s*(.+)', line, re.IGNORECASE)
                        error_msg = error_match.group(1) if error_match else '请检查日志'
                        tracker.update_status('nick_crawler', 'warning', f'可能有错误: {error_msg}')

                # Track PFS买家类型更新
                if 'PFS' in line and '新老客' in line:
                    if '开始执行' in line:
                        tracker.update_status('pfs_buyer_update', 'running', '正在更新PFS买家类型')
                    elif '成功' in line:
                        tracker.update_status('pfs_buyer_update', 'completed', 'PFS买家类型更新完成')
                    elif '异常' in line or '错误' in line:
                        tracker.update_status('pfs_buyer_update', 'failed', '请检查日志')

                # Track DTC买家类型更新
                if 'DTC' in line and '新老客' in line:
                    if '开始执行' in line:
                        tracker.update_status('dtc_buyer_update', 'running', '正在更新DTC买家类型')
                    elif '成功' in line:
                        tracker.update_status('dtc_buyer_update', 'completed', 'DTC买家类型更新完成')
                    elif '异常' in line or '错误' in line:
                        tracker.update_status('dtc_buyer_update', 'failed', '请检查日志')

                # Track QuickBI table results
                quickbi_match = re.search(r'开始任务: (BI_\w+)', line)
                if quickbi_match:
                    table_name = quickbi_match.group(1)
                    print(f"      - 正在获取表格: {table_name}")

                # Check for successful QuickBI data extraction
                success_match = re.search(r'\[OK\] 成功保存.*?(\d+) 行', line)
                if success_match:
                    rows = success_match.group(1)
                    table_name = re.search(r'BI_\w+', line)
                    if table_name:
                        tracker.add_quickbi_table(table_name.group(), rows, True)
                        print(f"      - [OK] {table_name.group()}: {rows} 行")

                # Check for failed extraction
                if '超时或未获取到数据' in line:
                    table_match = re.search(r'BI_\w+', line)
                    if table_match:
                        tracker.add_quickbi_table(table_match.group(), 0, False)
                        print(f"      - [FAIL] {table_match.group()}: 超时或无数据")

                # Check for QuickBI table warnings (>50 rows)
                if "50" in line and ("行" in line or "rows" in line or "rows" in line.lower()):
                    if "警告" in line or "warning" in line.lower() or "exceed" in line.lower():
                        quickbi_warning_detected = True

            # Check max wait time periodically (every ~100 lines to avoid overhead)
            if len(output_lines) % 100 == 0:
                elapsed_time = time.time() - tracker.start_time
                if elapsed_time >= max_wait:
                    print(f"\n[WARN] 警告: 脚本执行超过最大等待时间 ({max_wait}s)")
                    process.terminate()
                    break

        # Final status display
        return_code = process.wait()

        # Update final statuses for incomplete tasks
        for task in tracker.tasks:
            current_status = tracker.tasks[task]['status']
            if current_status == 'running':
                if task in ['fq_crawler', 'nick_crawler']:
                    if current_status != 'completed':
                        tracker.update_status(task, 'warning', '可能无数据需要爬取')
                else:
                    tracker.update_status(task, 'failed', '可能超时或未完成')

        tracker.print_summary()
        print(f"脚本返回码: {return_code}\n")
        pipeline_succeeded = return_code == 0

        # ============================================================
        # 智能验证：只在 run.py 失败时才执行验证和补下载
        # ============================================================
        if auto_retry and return_code != 0:
            download_path = get_download_path()
            today = date.today()
            today_str = today.strftime("%Y-%m-%d")

            print("\n" + "=" * 70)
            print("  run.py 执行异常，开始验证文件完整性并尝试补下载...")
            print("=" * 70)

            tracker.update_status('file_verification', 'running', '检查必需文件')

            # Check JYCM files
            jycm_ok, missing_jycm = check_required_jycm_files(download_path, today_str)
            quickbi_ok, missing_quickbi = check_required_quickbi_files(download_path, today_str)

            confirmed_zero_sources = confirmed_zero_quickbi_sources(
                Path(__file__).resolve().parents[1] / "runs" / today_str / "logs"
            )
            unresolved_quickbi = [
                source for source in missing_quickbi if source not in confirmed_zero_sources
            ]

            if jycm_ok and not unresolved_quickbi:
                tracker.update_status('file_verification', 'completed', '所有必需文件已存在')
                print(f"       [OK] 所有必需文件已存在")
            else:
                if missing_jycm:
                    print(f"       [WARN] 缺失 {len(missing_jycm)} 个经营参谋文件:")
                    for report_id, prefix in missing_jycm:
                        print(f"              - {prefix}")
                    tracker.update_status('file_verification', 'warning', f'缺失{len(missing_jycm)}个文件')

                if unresolved_quickbi:
                    print(f"       [WARN] 缺失 {len(unresolved_quickbi)} 个QuickBI文件:")
                    for prefix in unresolved_quickbi:
                        print(f"              - {prefix}")

                # Auto-retry missing JYCM files
                if missing_jycm:
                    tracker.update_status('jycm_retry', 'running', f'补充下载{len(missing_jycm)}个文件')
                    still_missing = download_missing_jycm_files(missing_jycm, download_path, today_str)

                    if not still_missing:
                        tracker.update_status('jycm_retry', 'completed', '所有文件补充下载成功')
                    else:
                        tracker.update_status('jycm_retry', 'warning', f'{len(still_missing)}个文件仍缺失')

                    jycm_ok, _ = check_required_jycm_files(download_path, today_str)

                if unresolved_quickbi:
                    tracker.update_status('quickbi', 'running', f'补充下载{len(unresolved_quickbi)}个缺失源')
                    still_missing_quickbi = download_missing_quickbi_files(unresolved_quickbi)
                    if not still_missing_quickbi:
                        tracker.update_status('quickbi', 'completed', '缺失 QuickBI 源补充下载成功')
                    else:
                        tracker.update_status('quickbi', 'failed', f'{len(still_missing_quickbi)}个 QuickBI 源仍缺失')

                    quickbi_ok, missing_quickbi = check_required_quickbi_files(download_path, today_str)
                    unresolved_quickbi = [
                        source for source in missing_quickbi if source not in confirmed_zero_sources
                    ]

            if jycm_ok and not unresolved_quickbi:
                print("\n  重新执行文件上传...")
                upload_success = drain_upload_residuals(data_import_dir, download_path, tracker, today)
                if upload_success:
                    print("\n  执行后续任务...")
                    followup_results = run_order_crawlers(data_import_dir)
                    for task, success in followup_results.items():
                        tracker.update_status(task, 'completed' if success else 'failed')
                    pipeline_succeeded = all(followup_results.values())

        elif auto_retry and return_code == 0:
            # run.py 已经完整执行了所有任务（下载→上传→爬虫→买家类型更新）
            # 但需要检查是否有残留文件未被上传
            print("\n" + "=" * 70)
            print("  run.py 执行成功，检查原始数据文件是否已迁移出 Downloads...")
            print("=" * 70)

            download_path = get_download_path()
            today_day = date.today()
            upload_success = drain_upload_residuals(data_import_dir, download_path, tracker, today_day)
            if not upload_success:
                return False

            # run.py may have continued after a false upload success. Re-run follow-up
            # tasks after verified upload completion to guarantee ordering.
            print("\n  [>>] 执行后续任务（确保数据完整性）...")
            followup_results = run_order_crawlers(data_import_dir)
            for task, success in followup_results.items():
                tracker.update_status(task, 'completed' if success else 'failed')
            pipeline_succeeded = all(followup_results.values())

        # Check for QuickBI warnings
        if quickbi_warning_detected:
            print("!" * 70)
            print("[WARN] 检测到 QuickBI 表格警告!")
            print("某些表格超过 50 行上限，可能需要手动下载。")
            print("!" * 70)
            print("\nQuickBI URLs:")
            print(f"  TM Order: {config['quickbi']['tm_order_url']}")
            print(f"  DTC Order: {config['quickbi']['dtc_order_url']}")
            print(f"  DTC Refund: {config['quickbi']['dtc_refund_url']}")

            # 检查实际的 QuickBI 文件是否存在
            download_path = get_download_path()
            today = date.today()
            today_str = today.strftime("%Y-%m-%d")
            quickbi_ok, missing_quickbi = check_required_quickbi_files(download_path, today_str)

            if not quickbi_ok:
                print(f"\n  [WARN] 缺失 {len(missing_quickbi)} 个 QuickBI 文件:")
                for prefix in missing_quickbi:
                    print(f"         - {prefix}")
                print("\n  请手动下载缺失的文件后，重新运行步骤2。")
            else:
                print("\n  [OK] 所有 QuickBI 文件已存在，无需手动下载。")

            # 自动跳过交互式提示，避免非交互环境下的 EOF 错误
            # 文件上传已在前面执行，此处无需额外处理
            print("\n  [INFO] 文件上传已在主流程中执行。")

        alimama_ok = True
        if run_alimama:
            alimama_ok = run_alimama_crawler(manage_script, data_import_dir, tracker)
        else:
            tracker.update_status('alimama', 'warning', '已按参数跳过阿里妈妈任务')

        # Final required-file gate: a zero subprocess return code must not hide
        # a missing QuickBI source or stale database import.
        download_path = get_download_path()
        today_str = date.today().strftime("%Y-%m-%d")
        quickbi_files_ok, missing_quickbi = check_required_quickbi_files(
            download_path,
            today_str,
        )
        confirmed_zero_sources = confirmed_zero_quickbi_sources(
            Path(__file__).resolve().parents[1] / "runs" / today_str / "logs"
        )
        tm_order_ok = True
        if "BI_tm_t01_trade_order_line" not in confirmed_zero_sources:
            tm_order_ok, tm_order_detail = verify_tm_order_database(
                data_import_dir,
                date.today(),
            )
            tracker.update_status(
                'file_verification',
                'completed' if tm_order_ok else 'failed',
                tm_order_detail,
            )
            print(f"\n{'[OK]' if tm_order_ok else '[FAIL]'} 天猫订单数据库对账: {tm_order_detail}")
        step_succeeded, missing_quickbi = quickbi_completion_gate(
            run_succeeded=pipeline_succeeded and alimama_ok and tm_order_ok,
            files_ok=quickbi_files_ok,
            missing_files=missing_quickbi,
            confirmed_zero_sources=confirmed_zero_sources,
        )
        if confirmed_zero_sources:
            print(f"\n[OK] Step 1 已确认零行数据源: {', '.join(sorted(confirmed_zero_sources))}")
        if missing_quickbi:
            print("\n[FAIL] 当天必需 QuickBI 文件不完整，Step 2 不得标记成功:")
            for prefix in missing_quickbi:
                print(f"       - {prefix}")
            print("  [ACTION] 重试 QuickBI 抓取；仍失败时检查对应页面登录态和数据接口。")

        # Print final summary again
        tracker.print_summary()

        return step_succeeded

    except Exception as e:
        print(f"[FAIL] 脚本执行错误: {str(e)}")
        return False

    finally:
        os.chdir(original_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Run data import scripts with progress tracking and auto-retry')
    parser.add_argument('--skip-upload', action='store_true',
                        help='Skip file upload prompt even if QuickBI warnings are detected')
    parser.add_argument('--no-auto-retry', action='store_true',
                        help='Disable automatic retry for missing files')
    parser.add_argument('--no-auto-login', action='store_true',
                        help='Do not auto-refresh Taobao/QianNiu cookies when they expire')
    parser.add_argument('--refresh-alimama-auth-first', action='store_true',
                        help='Refresh Alimama csrfId/cookies via local Chrome MCP before running the Alimama crawler')
    parser.add_argument('--skip-alimama', action='store_true',
                        help='Skip the daily Alimama crawler task')
    args = parser.parse_args()

    config = load_config()
    success = run_import_script(
        config,
        skip_upload=args.skip_upload,
        auto_retry=not args.no_auto_retry,
        auto_login=not args.no_auto_login,
        refresh_alimama_auth_first=args.refresh_alimama_auth_first,
        run_alimama=not args.skip_alimama,
    )

    if success:
        print("\n[OK] 步骤2执行成功！可以继续执行后续步骤。\n")
    else:
        print("\n[FAIL] 步骤2执行失败！请检查错误信息后重试。\n")

    sys.exit(0 if success else 1)
