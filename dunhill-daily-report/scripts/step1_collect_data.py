"""
Step 1: Data Collection from Taobao Platforms
Automates data collection from Taobao seller platform and Live Platform using Playwright.
"""

import os
import sys
import asyncio
import time
from pathlib import Path
import re
import yaml
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ====== 加载 .env 跨平台路径配置 ======
_env_file = Path.home() / ".claude" / "skills" / ".env"
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _k, _v = _k.strip(), _v.strip()
                if _k and _k not in os.environ:
                    os.environ[_k] = _v


def load_config(config_path="config/dunhill-config.yaml"):
    """Load configuration from YAML file."""
    script_dir = Path(__file__).parent.parent
    config_file = script_dir / config_path

    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Resolve ${ENV_VAR} placeholders in all string values
    config = _resolve_env_vars(config)

    # Expand password environment variable
    if '${TAOBAO_PASSWORD}' in str(config.get('credentials', {}).get('taobao_password', '')):
        config['credentials']['taobao_password'] = os.environ.get('TAOBAO_PASSWORD', '')

    return config


def _resolve_env_vars(obj):
    """Recursively resolve ${ENV_VAR} placeholders in config values."""
    if isinstance(obj, str):
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


async def taobao_refund_export(page, config):
    """Export refund list from Taobao seller platform."""
    print("\n=== Taobao Refund Data Export ===")
    refund_url = config['paths']['refund_list_url']
    username = config['credentials']['taobao_username']
    password = config['credentials']['taobao_password']

    print(f"Navigating to: {refund_url}")
    try:
        # Try with longer timeout and domcontentloaded instead of networkidle
        await page.goto(refund_url, wait_until="domcontentloaded", timeout=120000)
        print("Page loaded (domcontentloaded)")
        await asyncio.sleep(3)  # Additional wait for dynamic content
    except Exception as e:
        print(f"Navigation timeout: {str(e)}")
        print("Page may have loaded partially, continuing...")

    # Check if login is required
    await asyncio.sleep(2)
    current_url = page.url

    if 'login' in current_url.lower():
        print("=" * 60)
        print("LOGIN REQUIRED")
        print("=" * 60)
        print("\n[INFO] Please use your mobile phone to scan QR code:")
        print("   1. Open QianNiu (千牛) app on your phone")
        print("   2. Tap the scan icon in the app")
        print("   3. Scan the QR code on the screen")
        print("\n[WAIT] Waiting for QR code scan and login...")

        # Wait for user to scan QR code and login (up to 2 minutes)
        max_wait_time = 120  # 2 minutes
        waited = 0
        check_interval = 3

        while waited < max_wait_time:
            await asyncio.sleep(check_interval)
            waited += check_interval

            # Check if URL changed (login successful)
            current_url = page.url
            if 'login' not in current_url.lower():
                print(f"\n[OK] Login successful! (waited {waited}s)")
                print("=" * 60)
                break

            # Print progress every 15 seconds
            if waited % 15 == 0:
                print(f"   Still waiting... ({waited}s / {max_wait_time}s)")

        else:
            # Timeout reached
            print(f"\n[WARNING] Login timeout after {max_wait_time}s")
            print("   Please check if QR code scan was successful")
            print("   The script will attempt to continue, but may fail if not logged in")
            print("=" * 60)

        # Additional wait after login
        await asyncio.sleep(3)
    else:
        print("[OK] Already logged in (session restored from saved profile)")

    # Select "全部" from refund status dropdown
    print("Selecting '全部' from refund status dropdown...")
    try:
        await page.select_option('select[name*="refundStatus"], select[aria-label*="退款"]', '全部')
        await asyncio.sleep(3)
        print("Status selected")
    except:
        print("Could not find status dropdown, continuing...")

    # Wait for page to load
    await page.wait_for_load_state("networkidle", timeout=30000)
    await asyncio.sleep(2)

    # Click export button
    print("Looking for export button...")
    try:
        export_button = page.get_by_role("button", name="导出Excel").or_(
            page.get_by_text("导出Excel")
        ).or_(
            page.locator("button:has-text('导出')")
        ).first

        # Wait for download to start
        async with page.expect_download(timeout=30000) as download_info:
            await export_button.click(timeout=10000)

        download = await download_info.value
        download_path = await download.path()
        print(f"Export button clicked")
        print(f"Downloaded: {download_path}")
        print("Refund data export completed!")
        return True

    except Exception as e:
        print(f"Export failed: {str(e)}")
        print("Waiting 10 seconds before continuing...")
        await asyncio.sleep(10)
        return True


async def live_core_indicators(page, config):
    """Download core indicators from Live Platform."""
    print("\n=== Live Platform Core Indicators ===")
    overview_url = config['paths']['live_overview_url']

    print(f"Navigating to: {overview_url}")
    try:
        await page.goto(overview_url, wait_until="domcontentloaded", timeout=120000)
        print("Page loaded")
        await asyncio.sleep(3)
    except Exception as e:
        print(f"Navigation error: {str(e)}")
        return False

    # Click download button for core indicators
    print("Looking for core indicators download button...")
    try:
        # Try multiple selectors for download button
        download_button = page.locator("button:has-text('下载')").first

        async with page.expect_download(timeout=30000) as download_info:
            await download_button.click(timeout=10000)

        download = await download_info.value
        download_path = await download.path()
        print(f"Downloaded: {download_path}")
        print("Core indicators download completed!")
        return True

    except Exception as e:
        print(f"Download failed: {str(e)}")
        print("Trying alternative selector...")
        try:
            # Alternative: try to find any button containing "download"
            download_button = page.get_by_role("button", name="下载").first
            async with page.expect_download(timeout=30000) as download_info:
                await download_button.click(timeout=10000)

            download = await download_info.value
            download_path = await download.path()
            print(f"Downloaded: {download_path}")
            print("Core indicators download completed!")
            return True
        except Exception as e2:
            print(f"Alternative selector also failed: {str(e2)}")
            print("Waiting 10 seconds before continuing...")
            await asyncio.sleep(10)
            return True


async def live_transaction_details(page, config):
    """Download transaction order details from Live Platform."""
    print("\n=== Live Platform Transaction Details ===")
    transaction_url = config['paths']['live_transaction_url']

    print(f"Navigating to: {transaction_url}")
    try:
        await page.goto(transaction_url, wait_until="domcontentloaded", timeout=120000)
        print("Page loaded")
        await asyncio.sleep(3)
    except Exception as e:
        print(f"Navigation error: {str(e)}")
        return False

    # Need to download twice: payment time and confirmation time
    for time_type in ["支付时间", "确认收货时间"]:
        print(f"\nDownloading orders by {time_type}...")

        try:
            # Select time type dropdown - try multiple selectors
            time_type_selected = False
            for selector in [
                'select:has-text("时间类型")',
                'select[name*="timeType"]',
                'select[name*="time"]',
                'select'
            ]:
                try:
                    select_element = page.locator(selector).first
                    if await select_element.count() > 0:
                        options = await select_element.locator('option').all_text_contents()
                        print(f"  Found select with options: {options[:5]}")  # Show first 5 options

                        if time_type in options:
                            await select_element.select_option(time_type)
                            print(f"  Selected {time_type}")
                            time_type_selected = True
                            await asyncio.sleep(2)
                            break
                except:
                    continue

            if not time_type_selected:
                print(f"  [WARNING] Could not select time type: {time_type}")
                print(f"  [INFO] Continuing anyway...")

            # Select last 3 days (excluding today)
            # Note: Adjust selector based on actual page structure
            date_range_selector = page.locator('select:has-text("时间范围"), input[name*="date"]')
            if await date_range_selector.count() > 0:
                try:
                    await page.select_option('select:has-text("时间范围")', '近3天')
                    print("  Selected date range: 近3天")
                except:
                    pass
            await asyncio.sleep(2)

            # Click query button
            try:
                query_button = page.locator("button:has-text('查询')").first
                await query_button.click(timeout=10000)
                print("  Query button clicked")
                await page.wait_for_load_state("networkidle", timeout=30000)
                await asyncio.sleep(3)
            except Exception as e:
                print(f"  [WARNING] Query button failed: {str(e)}")
                print(f"  [INFO] Continuing anyway...")

            # Click download button
            download_button = page.locator("button:has-text('下载')").first

            async with page.expect_download(timeout=30000) as download_info:
                await download_button.click(timeout=10000)

            download = await download_info.value
            download_path = await download.path()
            print(f"  Downloaded: {download_path}")

        except Exception as e:
            print(f"  Download failed: {str(e)}")
            print(f"  Waiting 10 seconds before continuing...")
            await asyncio.sleep(10)

    print("Transaction details download completed!")
    return True


async def collect_data(config):
    """Main data collection workflow."""
    print("Starting data collection from Taobao platforms...")

    headless = config['settings']['browser_headless']
    slow_mo = config['settings']['browser_slow_mo']
    user_data_dir = config['settings']['browser_user_data_dir']

    # Use persistent context to save login session
    print(f"Using persistent browser profile: {user_data_dir}")
    print("If this is your first time, please scan QR code to login.")
    print("The session will be saved for future runs (7-30 days).\n")

    async with async_playwright() as p:
        # Launch persistent browser context (saves cookies, localStorage, etc.)
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=headless,
            slow_mo=slow_mo,
            accept_downloads=True,
            viewport={'width': 1280, 'height': 720}
        )

        # Get or create page
        if len(context.pages) > 0:
            page = context.pages[0]
        else:
            page = await context.new_page()

        try:
            # Step 1: Export Taobao refund data
            await taobao_refund_export(page, config)

            # Step 2: Download Live Platform core indicators
            await live_core_indicators(page, config)

            # Step 3: Download Live Platform transaction details
            await live_transaction_details(page, config)

            print("\n" + "=" * 60)
            print("All data collection completed successfully!")
            print("=" * 60)
            print("\nBrowser session has been saved for next run.")
            return True

        except Exception as e:
            print(f"\nError during data collection: {str(e)}")
            print("Please complete remaining steps manually")
            return False

        finally:
            # Keep context open to preserve session
            # Uncomment the next line to close browser after script completes
            # await context.close()
            print("\n[INFO] Browser context is kept open to preserve login session.")
            print("[INFO] You can close the browser window manually when done.")


if __name__ == "__main__":
    config = load_config()

    # Check for credentials
    if not config['credentials']['taobao_password']:
        print("Error: Taobao password not set!")
        print("Please set environment variable: TAOBAO_PASSWORD")
        print("Or edit config/dunhill-config.yaml")
        sys.exit(1)

    # Run async data collection
    success = asyncio.run(collect_data(config))
    sys.exit(0 if success else 1)
