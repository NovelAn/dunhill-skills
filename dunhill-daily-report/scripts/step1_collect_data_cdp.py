"""
Step 1: Data Collection from Taobao Platforms (Chrome CDP Version)
Connects to an existing Chrome browser with remote debugging enabled.
This allows reusing the logged-in session from your daily Chrome browser.

Prerequisites:
1. Start Chrome with: chrome.exe --remote-debugging-port=9222
2. Log in to Taobao/QianNiu manually
3. Run this script
"""

import os
import sys
import asyncio
import time
from pathlib import Path
import yaml
from playwright.async_api import async_playwright


def load_config(config_path="config/dunhill-config.yaml"):
    """Load configuration from YAML file."""
    script_dir = Path(__file__).parent.parent
    config_file = script_dir / config_path

    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config


async def smart_find_and_click_download(page, button_text="下载"):
    """Smart download button finder with multiple strategies."""

    print(f"Looking for download button containing '{button_text}'...")

    # Strategy 1: Text-based selectors
    text_selectors = [
        f'button:has-text("{button_text}")',
        f'a:has-text("{button_text}")',
        f'[role="button"]:has-text("{button_text}")',
        f'span:has-text("{button_text}")',
        f'div:has-text("{button_text}")',
    ]

    # Strategy 2: Class-based selectors
    class_selectors = [
        '.download-btn',
        '.export-btn',
        '.btn-download',
        '.btn-export',
        '[class*="download"]',
        '[class*="export"]',
        '[class*="Download"]',
        '[class*="Export"]',
    ]

    # Strategy 3: ID and attribute selectors
    attr_selectors = [
        '[id*="download"]',
        '[id*="export"]',
        '[aria-label*="下载"]',
        '[aria-label*="导出"]',
        '[title*="下载"]',
        '[title*="导出"]',
    ]

    all_selectors = text_selectors + class_selectors + attr_selectors

    for selector in all_selectors:
        try:
            elements = page.locator(selector)
            count = await elements.count()

            if count > 0:
                print(f"  Found {count} element(s) with: {selector}")

                # Try clicking each element
                for i in range(min(count, 3)):  # Try max 3 elements
                    try:
                        element = elements.nth(i)

                        # Get element info for debugging
                        text_content = await element.inner_text() if count < 10 else ""
                        class_name = await element.get_attribute('class') or ""
                        print(f"    Trying element {i+1}: text='{text_content[:30]}', class='{class_name[:50]}'")

                        # Try to click and wait for download
                        async with page.expect_download(timeout=10000) as download_info:
                            await element.click(timeout=5000)

                        download = await download_info.value
                        download_path = await download.path()
                        print(f"    [OK] Downloaded: {download_path}")
                        return True

                    except Exception as e:
                        print(f"    [SKIP] Element {i+1} failed: {str(e)[:100]}")
                        continue

        except Exception as e:
            continue

    print(f"  [FAIL] Could not find or click download button")
    return False


async def taobao_refund_export(page, config):
    """Export refund list from Taobao seller platform."""
    print("\n=== Taobao Refund Data Export ===")
    refund_url = config['paths']['refund_list_url']

    print(f"Navigating to: {refund_url}")
    try:
        await page.goto(refund_url, wait_until="domcontentloaded", timeout=120000)
        print("Page loaded")
        await asyncio.sleep(3)
    except Exception as e:
        print(f"Navigation error: {str(e)}")
        return False

    # Check if login is required
    current_url = page.url
    if 'login' in current_url.lower():
        print("\n" + "=" * 60)
        print("[ERROR] NOT LOGGED IN")
        print("=" * 60)
        print("\nPlease follow these steps:")
        print("  1. In the Chrome browser, make sure you are logged into Taobao/QianNiu")
        print("  2. Navigate to the seller platform manually")
        print("  3. Run this script again")
        print("\nOr press Enter to try manual download...")
        print("=" * 60)

        input("Press Enter to continue or Ctrl+C to exit...")

    # Try automatic download
    try:
        print("\nAttempting automatic download...")

        # Wait for page to stabilize
        await page.wait_for_load_state("networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Try smart download button finder
        success = await smart_find_and_click_download(page, "导出")

        if success:
            print("[OK] Refund data export completed!")
            return True
        else:
            raise Exception("Automatic download failed")

    except Exception as e:
        print(f"\n[WARN] Automatic download failed: {str(e)}")
        print("\n" + "=" * 60)
        print("[MANUAL ACTION REQUIRED]")
        print("=" * 60)
        print("\nPlease complete the following steps:")
        print("  1. In the Chrome browser window, find the 'Export Excel' button")
        print("  2. Click the button to download the refund data")
        print("  3. Wait for the download to complete")
        print("\nThen press Enter in this terminal to continue...")
        print("=" * 60)

        input("\nPress Enter when download is complete...")
        print("[OK] Continuing...")
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

    try:
        print("\nAttempting automatic download...")

        # Wait for page to stabilize
        await page.wait_for_load_state("networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Try smart download button finder
        success = await smart_find_and_click_download(page, "下载")

        if success:
            print("[OK] Core indicators download completed!")
            return True
        else:
            raise Exception("Automatic download failed")

    except Exception as e:
        print(f"\n[WARN] Automatic download failed: {str(e)}")
        print("\n" + "=" * 60)
        print("[MANUAL ACTION REQUIRED]")
        print("=" * 60)
        print("\nPlease complete the following steps:")
        print("  1. In the Chrome browser, click the 'Download' button for core indicators")
        print("  2. Wait for the download to complete")
        print("\nThen press Enter in this terminal to continue...")
        print("=" * 60)

        input("\nPress Enter when download is complete...")
        print("[OK] Continuing...")
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
            # Try to find and interact with time type selector
            print(f"  Looking for time type selector...")

            # Try multiple selector strategies
            time_type_selected = False

            # Check all select elements
            select_elements = await page.locator('select').all()
            print(f"  Found {len(select_elements)} select elements")

            for idx, select_elem in enumerate(select_elements):
                try:
                    options = await select_elem.locator('option').all_text_contents()
                    print(f"  Select {idx}: options = {options[:5]}")  # Show first 5

                    if time_type in options:
                        await select_elem.select_option(time_type)
                        print(f"  [OK] Selected {time_type}")
                        time_type_selected = True
                        await asyncio.sleep(2)
                        break
                except:
                    continue

            if not time_type_selected:
                print(f"  [WARNING] Could not select time type automatically")
                print(f"  [INFO] Make sure '{time_type}' is selected in the browser")

            # Click query button if exists
            try:
                query_button = page.locator("button:has-text('查询')").first
                if await query_button.count() > 0:
                    await query_button.click(timeout=5000)
                    print("  Query button clicked")
                    await page.wait_for_load_state("networkidle", timeout=30000)
                    await asyncio.sleep(3)
            except:
                print("  [INFO] No query button found or failed to click")

            # Try to download
            success = await smart_find_and_click_download(page, "下载")

            if success:
                print(f"  [OK] Downloaded orders by {time_type}")
            else:
                raise Exception("Download failed")

        except Exception as e:
            print(f"\n  [WARN] Automatic download failed: {str(e)}")
            print(f"\n  " + "=" * 60)
            print(f"  [MANUAL ACTION REQUIRED]")
            print(f"  " + "=" * 60)
            print(f"\n  Please complete the following steps:")
            print(f"    1. In the Chrome browser, make sure '{time_type}' is selected")
            print(f"    2. Click the 'Query' button if needed")
            print(f"    3. Click the 'Download' button")
            print(f"    4. Wait for the download to complete")
            print(f"\n  Then press Enter in this terminal to continue...")
            print(f"  " + "=" * 60)

            input(f"\n  Press Enter when download is complete...")
            print(f"  [OK] Continuing...")

    print("\n[OK] Transaction details download completed!")
    return True


async def collect_data(config):
    """Main data collection workflow using Chrome CDP."""
    print("=" * 70)
    print("DUNHILL DAILY REPORT - DATA COLLECTION (Chrome CDP Version)")
    print("=" * 70)

    print("\n[PREREQUISITES]")
    print("1. Chrome must be running with: --remote-debugging-port=9222")
    print("2. You must be logged into Taobao/QianNiu in that Chrome browser")
    print("\nIf not ready, please:")
    print("  a. Start Chrome with: chrome.exe --remote-debugging-port=9222")
    print("  b. Log in to Taobao/QianNiu")
    print("  c. Run this script again")
    print("\n" + "=" * 70)

    input("\nPress Enter to start (or Ctrl+C to cancel)...")

    print("\n[START] Connecting to Chrome browser...")

    async with async_playwright() as p:
        try:
            # Connect to Chrome via CDP
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            print("[OK] Connected to Chrome!")

            # Get the default browser context
            contexts = browser.contexts
            if not contexts:
                print("[ERROR] No browser contexts found. Please make sure Chrome is running.")
                return False

            context = contexts[0]
            print(f"[INFO] Using context: {context}")

            # Get or create a page
            pages = context.pages
            if pages:
                page = pages[0]
                print(f"[INFO] Using existing page: {page.title()}")
            else:
                page = await context.new_page()
                print("[INFO] Created new page")

            try:
                # Step 1: Export Taobao refund data
                await taobao_refund_export(page, config)

                # Step 2: Download Live Platform core indicators
                await live_core_indicators(page, config)

                # Step 3: Download Live Platform transaction details
                await live_transaction_details(page, config)

                print("\n" + "=" * 70)
                print("[SUCCESS] All data collection completed successfully!")
                print("=" * 70)
                return True

            except Exception as e:
                print(f"\n[ERROR] Error during data collection: {str(e)}")
                import traceback
                traceback.print_exc()
                return False

            finally:
                # Don't close the browser - keep it open for future use
                print("\n[INFO] Browser is kept open for next run.")

        except Exception as e:
            print(f"\n[ERROR] Failed to connect to Chrome: {str(e)}")
            print("\n[TROUBLESHOOTING]")
            print("1. Make sure Chrome is running with: --remote-debugging-port=9222")
            print("2. Check if port 9222 is already in use")
            print("3. Try restarting Chrome with the debug flag")
            print("\nCommand to start Chrome:")
            print('  chrome.exe --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\\Google\\Chrome\\User Data"')
            return False


if __name__ == "__main__":
    try:
        config = load_config()
        success = asyncio.run(collect_data(config))

        if success:
            print("\n[DONE] Script completed successfully!")
            sys.exit(0)
        else:
            print("\n[FAILED] Script encountered errors. Please check the messages above.")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n[CANCELLED] Script interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
