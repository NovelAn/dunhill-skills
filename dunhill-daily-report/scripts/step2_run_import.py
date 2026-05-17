"""
Step 2: Run Data Import Scripts (Improved Version with Auto-Retry)
Executes the data import Python scripts, verifies required files, and auto-retries failed downloads.
"""

import os
import sys
import locale

# ====== 加载 .env 跨平台路径配置 ======
from pathlib import Path as _P
_env_file = _P.home() / ".claude" / "skills" / ".env"
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _k, _v = _k.strip(), _v.strip()
                if _k and _k not in os.environ:
                    os.environ[_k] = _v

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
from datetime import date, timedelta


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
            return value
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


def get_download_path():
    """Get the Downloads folder path."""
    custom_download_path = os.getenv("DOWNLOAD_DIR")
    if custom_download_path and os.path.exists(custom_download_path):
        return custom_download_path
    return os.path.join(os.path.expanduser("~"), "Downloads")


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
        save_path = os.path.join(os.getenv("DUNHILL_DATA_DIR", ""), "文件下载")

    # 支持两种日期格式：20260310 和 2026-03-10
    today_str_hyphen = today_str[:4] + '-' + today_str[4:6] + '-' + today_str[6:8]

    for report_id, file_prefix in REQUIRED_JYCM_DAILY_REPORTS:
        # 跳过客户源文件检查
        if any(ignore in file_prefix for ignore in ignored_prefixes):
            continue

        # Pattern: prefix + YYYY-MM-DD.xlsx or prefix + today.xlsx
        pattern2 = os.path.join(download_path, f"{file_prefix}*.xlsx")

        # Check if file exists in Downloads (支持两种日期格式)
        files = glob.glob(pattern2)
        today_files = [f for f in files if today_str in f or today_str_hyphen in f]

        if not today_files:
            # 检查文件是否已移动到SavePath (支持两种日期格式)
            save_pattern = os.path.join(save_path, "**", f"{file_prefix}*{today_str}*.xlsx")
            saved_files = glob.glob(save_pattern, recursive=True)

            # 也检查带连字符的日期格式
            if not saved_files:
                save_pattern_hyphen = os.path.join(save_path, "**", f"{file_prefix}*{today_str_hyphen}*.xlsx")
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
        save_path = os.path.join(os.getenv("DUNHILL_DATA_DIR", ""), "文件下载")

    # 支持两种日期格式：20260310 和 2026-03-10
    today_str_hyphen = today_str[:4] + '-' + today_str[4:6] + '-' + today_str[6:8]

    for file_prefix in REQUIRED_QUICKBI_FILES:
        pattern = os.path.join(download_path, f"{file_prefix}*.xlsx")
        files = glob.glob(pattern)
        today_files = [f for f in files if today_str in f or today_str_hyphen in f]

        if not today_files:
            # 检查文件是否已移动到SavePath (支持两种日期格式)
            save_pattern = os.path.join(save_path, "**", f"{file_prefix}*{today_str}*.xlsx")
            saved_files = glob.glob(save_pattern, recursive=True)

            # 也检查带连字符的日期格式
            if not saved_files:
                save_pattern_hyphen = os.path.join(save_path, "**", f"{file_prefix}*{today_str_hyphen}*.xlsx")
                saved_files = glob.glob(save_pattern_hyphen, recursive=True)

            if not saved_files:
                # 文件既不在Downloads也不在SavePath，才是真正缺失
                missing.append(file_prefix)

    return len(missing) == 0, missing


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


def run_file_uploader(data_import_dir):
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
            timeout=300,
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
        print(f"       [WARN] 文件上传超时")
        return False
    except Exception as e:
        print(f"       [ERROR] 文件上传失败: {e}")
        return False


def run_order_crawlers(data_import_dir):
    """
    Run order crawlers (fq and nick) and buyer type updates.

    执行顺序（重要）:
    1. file_uploader 必须先完成
    2. nick_crawler 和 fq_crawler 串行执行（都是千牛后台，并发有风险）
    3. 买家类型更新（PFS/DTC）可以与爬虫并发执行（纯SQL操作）

    并发策略:
    - 买家类型更新在后台线程执行
    - 爬虫任务串行执行（先nick后fq，或反过来）
    - 最后等待买家类型更新完成
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    print(f"\n  {'='*60}")
    print(f"  执行后续任务: 爬虫和买家类型更新...")
    print(f"  {'='*60}")
    print(f"  执行策略: 爬虫串行(千牛后台) + 买家类型更新并发(SQL)")

    # Add project paths for imports
    sys.path.insert(0, data_import_dir)
    sys.path.insert(0, os.path.join(data_import_dir, 'src'))

    results = {
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
            print(f"       [OK] 存储过程执行成功")
        except Exception as e:
            print(f"       [WARN] 存储过程执行失败: {str(e)[:80]}")

        # 使用线程池并发执行买家类型更新
        with ThreadPoolExecutor(max_workers=2) as buyer_type_pool:
            # 提交买家类型更新任务到后台
            pfs_future = buyer_type_pool.submit(run_pfs_buyer_update, user_info)
            dtc_future = buyer_type_pool.submit(run_dtc_buyer_update, user_info)

            print(f"\n  [INFO] 买家类型更新已在后台启动，开始串行执行爬虫任务...")

            # ===== 串行执行爬虫任务（千牛后台，不能并发）=====

            # 1. 买家昵称爬虫
            print(f"\n  [>>] 执行买家昵称爬虫（千牛后台）...")
            try:
                user_info.nick_spider_execute("dunhill_bi订单源")
                update_result('nick_crawler', True)
                print(f"       [OK] 买家昵称爬虫完成")
            except Exception as e:
                print(f"       [WARN] 买家昵称爬虫执行失败: {str(e)[:50]}")

            # 2. 分期购爬虫（等待昵称爬虫完成后执行）
            print(f"\n  [>>] 执行分期购爬虫（千牛后台）...")
            try:
                user_info.fq_spider_execute("dunhill_tm订单分期购")
                update_result('fq_crawler', True)
                print(f"       [OK] 分期购爬虫完成")
            except Exception as e:
                print(f"       [WARN] 分期购爬虫执行失败: {str(e)[:50]}")

            # 等待买家类型更新完成
            print(f"\n  [>>] 等待买家类型更新完成...")
            pfs_future.result()  # 等待PFS完成
            dtc_future.result()  # 等待DTC完成

    except ImportError as e:
        print(f"       [ERROR] 无法导入所需模块: {e}")
        return results
    except Exception as e:
        print(f"       [ERROR] 后续任务执行错误: {e}")

    # Summary
    success_count = sum(1 for v in results.values() if v)
    print(f"\n  后续任务完成: {success_count}/4")

    return results


def run_import_script(config, skip_upload=False, auto_retry=True):
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

            if jycm_ok and quickbi_ok:
                tracker.update_status('file_verification', 'completed', '所有必需文件已存在')
                print(f"       [OK] 所有必需文件已存在")
            else:
                if missing_jycm:
                    print(f"       [WARN] 缺失 {len(missing_jycm)} 个经营参谋文件:")
                    for report_id, prefix in missing_jycm:
                        print(f"              - {prefix}")
                    tracker.update_status('file_verification', 'warning', f'缺失{len(missing_jycm)}个文件')

                if missing_quickbi:
                    print(f"       [WARN] 缺失 {len(missing_quickbi)} 个QuickBI文件:")
                    for prefix in missing_quickbi:
                        print(f"              - {prefix}")

                # Auto-retry missing JYCM files
                if missing_jycm:
                    tracker.update_status('jycm_retry', 'running', f'补充下载{len(missing_jycm)}个文件')
                    still_missing = download_missing_jycm_files(missing_jycm, download_path, today_str)

                    if not still_missing:
                        tracker.update_status('jycm_retry', 'completed', '所有文件补充下载成功')
                    else:
                        tracker.update_status('jycm_retry', 'warning', f'{len(still_missing)}个文件仍缺失')

                    # Re-run file uploader after retrying downloads
                    print("\n  重新执行文件上传...")
                    upload_success = run_file_uploader(data_import_dir)

                    # Run follow-up tasks: crawlers and buyer type updates
                    if upload_success:
                        print("\n  执行后续任务...")
                        run_order_crawlers(data_import_dir)

        elif auto_retry and return_code == 0:
            # run.py 已经完整执行了所有任务（下载→上传→爬虫→买家类型更新）
            # 但需要检查是否有残留文件未被上传
            print("\n" + "=" * 70)
            print("  run.py 执行成功，检查是否有残留文件...")
            print("=" * 70)

            download_path = get_download_path()
            today = date.today()
            today_str = today.strftime("%Y-%m-%d")

            # 检查是否有今天的数据源文件残留（未被上传）
            jycm_ok, missing_jycm = check_required_jycm_files(download_path, today_str)
            quickbi_ok, missing_quickbi = check_required_quickbi_files(download_path, today_str)

            # 如果文件存在但没有被上传（文件存在于Downloads但应该已被移动）
            # 检查是否有符合今天日期的数据文件残留
            has_residual_files = not jycm_ok or not quickbi_ok

            if has_residual_files:
                print("\n  [WARN] 发现残留的数据源文件，执行额外的文件上传...")

                # 额外执行一次 file_uploader
                time.sleep(3)  # 等待文件系统同步
                extra_upload_success = run_file_uploader(data_import_dir)

                if extra_upload_success:
                    print("       [OK] 额外文件上传完成")
                    # 重新执行后续任务（爬虫和买家类型更新）
                    print("\n  [>>] 执行后续任务（确保数据完整性）...")
                    run_order_crawlers(data_import_dir)
                else:
                    print("       [WARN] 额外文件上传有警告")
            else:
                print("\n  [OK] 所有文件已正确上传，无需额外处理")

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

        # Print final summary again
        tracker.print_summary()

        return return_code == 0

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
    args = parser.parse_args()

    config = load_config()
    success = run_import_script(
        config,
        skip_upload=args.skip_upload,
        auto_retry=not args.no_auto_retry
    )

    if success:
        print("\n[OK] 步骤2执行成功！可以继续执行后续步骤。\n")
    else:
        print("\n[FAIL] 步骤2执行失败！请检查错误信息后重试。\n")

    sys.exit(0 if success else 1)
