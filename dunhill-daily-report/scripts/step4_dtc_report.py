"""
Step 4: DTC Daily Report Generation
Automates DTC Excel report generation with data refresh, snapshot creation, and screenshots.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import win32com.client
import yaml
import pythoncom


def load_config(config_path="config/dunhill-config.yaml"):
    """Load configuration from YAML file."""
    script_dir = Path(__file__).parent.parent
    config_file = script_dir / config_path

    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Expand environment variables in credentials
    if '${TAOBAO_PASSWORD}' in config['credentials']['taobao_password']:
        import os
        config['credentials']['taobao_password'] = os.environ.get('TAOBAO_PASSWORD', '')

    return config


def get_yesterday_date():
    """Get yesterday's date formatted as YYYY-MM-DD."""
    yesterday = datetime.now() - timedelta(days=1)
    return yesterday.strftime('%Y-%m-%d')


def copy_range_as_picture(sheet, range_addr, image_path, scale_percent=70):
    """Copy Excel range as picture and save to file with specified scale.

    IMPORTANT: The sheet must be activated before calling this function.
    Use sheet.Activate() and time.sleep(1) before calling.

    Args:
        sheet: Excel sheet object
        range_addr: Range address (e.g., "A1:T49")
        image_path: Output image file path
        scale_percent: Scale percentage (default: 30 for 30% size)
    """
    import time
    try:
        # Get the range
        range_obj = sheet.Range(range_addr)

        # Calculate target size
        target_width = int(range_obj.Width * (scale_percent / 100))
        target_height = int(range_obj.Height * (scale_percent / 100))

        # Add a temporary chart object to a remote location (off-screen)
        # Position it at very high coordinates so it won't be visible
        chart_obj = sheet.ChartObjects().Add(10000, 10000, target_width, target_height)

        # Access the chart
        chart = chart_obj.Chart

        # Select and copy the range
        range_obj.Select()
        time.sleep(0.5)

        # Copy as picture
        range_obj.CopyPicture(Appearance=1, Format=1)
        time.sleep(0.5)

        # Paste into the off-screen chart
        chart.ChartArea.Select()
        chart.Paste()
        time.sleep(0.5)

        # Export the chart as image
        chart.Export(image_path)

        # Delete the temporary chart object (not the sheet)
        chart_obj.Delete()

        # Reselect the original range to clear selection
        range_obj.Select()

        # Verify file was created
        import os
        if os.path.exists(image_path):
            size = os.path.getsize(image_path)
            print(f"  Screenshot saved: {image_path} ({size} bytes)")
            return True
        else:
            print(f"  Error: Screenshot file was not created")
            return False

    except Exception as e:
        print(f"  Screenshot failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def generate_dtc_report(config):
    """Generate DTC daily report with Excel automation."""
    print("Starting DTC Daily Report generation...")

    # Get paths and settings from config
    excel_file = config['paths']['dtc_excel']
    snapfile_dir = config['paths']['dtc_snapfile_dir']
    snapshot_dir = config['paths']['dtc_snapshot_dir']
    wait_timeout = config['settings']['excel_wait_timeout']
    excel_visible = config['settings']['excel_visible']

    yesterday = get_yesterday_date()

    # Ensure output directories exist
    Path(snapfile_dir).mkdir(parents=True, exist_ok=True)
    Path(snapshot_dir).mkdir(parents=True, exist_ok=True)

    # Initialize COM for this thread
    pythoncom.CoInitialize()

    try:
        print(f"Opening Excel file: {excel_file}")
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = excel_visible
        excel.DisplayAlerts = False

        # Open workbook
        wb = excel.Workbooks.Open(excel_file)

        try:
            # Step 1: Refresh all data connections
            print("Refreshing all data connections...")
            wb.RefreshAll()

            # Wait for refresh to complete
            print("Waiting for refresh to complete (this may take 2-3 minutes)...")
            import time

            # Wait for calculation state
            waited = 0
            while excel.CalculationState != 0 and waited < wait_timeout:  # xlDone=0
                time.sleep(5)
                waited += 5
                print(f"Waiting for calculations... ({waited}s)")

            # IMPORTANT: Also wait for data connections to finish refreshing
            # Check each connection's refresh state
            print("Checking data connection refresh status...")
            connection_waited = 0
            max_connection_wait = 120  # Additional 2 minutes for connections

            while connection_waited < max_connection_wait:
                all_done = True
                try:
                    for connection in wb.Connections:
                        # Check if connection is still refreshing
                        if hasattr(connection, 'Refreshing') and connection.Refreshing:
                            all_done = False
                            break
                except:
                    pass  # If we can't check connections, just use timeout

                if all_done:
                    print("  All data connections refreshed!")
                    break

                time.sleep(5)
                connection_waited += 5
                print(f"  Waiting for connections... ({connection_waited}s)")

            if waited >= wait_timeout:
                print("Warning: Refresh timeout reached, proceeding anyway")

            print("Refresh complete!")

            # CRITICAL: Force Excel to fully render the updated data
            print("Forcing screen update and data rendering...")
            excel.Calculate()  # Force calculation
            time.sleep(3)  # Wait for calculation to complete

            # Save the original workbook with refreshed data
            print("Saving original workbook with refreshed data...")
            wb.Save()
            print("  [OK] Original workbook saved")
            time.sleep(2)

            # CRITICAL FIX: Close and reopen to avoid Power Query CopyPicture bug
            print("Closing workbook to fix CopyPicture issue...")
            wb.Close(SaveChanges=False)
            time.sleep(2)
            print("  [OK] Workbook closed")

            print("Reopening workbook...")
            wb = excel.Workbooks.Open(excel_file)
            time.sleep(2)
            print("  [OK] Workbook reopened")

            # IMPORTANT: Take screenshot AFTER reopening
            # Step 2: Take screenshot of Daily Sales Trend sheet (A4:T49)
            print("Taking screenshot of Daily Sales Trend sheet...")

            # Get sheet reference from reopened workbook
            print("  Getting Daily Sales Trend sheet...")
            daily_sheet = wb.Sheets("Daily Sales Trend")
            wb.Activate()
            time.sleep(1)
            daily_sheet.Activate()
            time.sleep(2)
            print(f"  [OK] Activated: {daily_sheet.Name}")

            # Prepare for screenshot
            print("  Preparing for screenshot...")
            excel.ScreenUpdating = True
            time.sleep(1)

            screenshot_name = f"dunhill OFS&WBTQ daily sales report_{yesterday}.jpg"
            screenshot_path = os.path.join(snapshot_dir, screenshot_name)

            print("  Taking screenshot...")
            copy_range_as_picture(daily_sheet, "A4:T49", screenshot_path, scale_percent=100)
            print(f"Screenshot saved: {screenshot_path}")

            # Step 3: Save entire workbook as new file, then convert Daily Sales Trend to values
            print("Creating values-only snapshot...")

            # Step 3.1: Save entire workbook to new file
            print("  Step 3.1: Save entire workbook to new file...")
            snapfile_name = f"dunhill OFS&WBTQ daily sales report_{yesterday}.xlsx"
            snapfile_path = os.path.join(snapfile_dir, snapfile_name)
            print(f"  Saving to: {snapfile_path}")

            # Use SaveAs to save the entire workbook with all sheets
            wb.SaveAs(snapfile_path)
            print(f"  [OK] Entire workbook saved")

            # Step 3.2: Open the newly saved workbook
            print("  Step 3.2: Open new workbook...")
            wb_new = excel.Workbooks.Open(snapfile_path)
            print(f"  [OK] Opened: {snapfile_name}")

            # Step 3.3: Activate Daily Sales Trend sheet in new workbook
            print("  Step 3.3: Activate Daily Sales Trend sheet in new workbook...")
            daily_sheet_new = wb_new.Sheets("Daily Sales Trend")
            daily_sheet_new.Activate()
            time.sleep(0.5)
            print(f"  [OK] Activated: {daily_sheet_new.Name}")

            # Step 3.4: Convert entire sheet to values
            print("  Step 3.4: Convert Daily Sales Trend to values...")
            used_range = daily_sheet_new.UsedRange
            print(f"  Used range: {used_range.Address}")

            # Copy all and paste as values
            used_range.Copy()
            used_range.PasteSpecial(-4163)  # xlPasteValues
            excel.CutCopyMode = False  # Clear clipboard
            print(f"  [OK] Converted to values")

            # Step 3.5: Save and close new workbook
            print("  Step 3.5: Save and close new workbook...")
            wb_new.Save()
            wb_new.Close()
            print(f"  [OK] Snapshot saved")

            print("Snapshot saved!")
            print("DTC Daily Report generation completed successfully!")
            return True

        finally:
            # Close workbook without saving (if still open)
            # NOTE: wb may already be closed due to SaveAs operation
            try:
                if wb is not None:
                    wb.Close(SaveChanges=False)
                    print("   [OK] Original workbook closed")
            except:
                pass  # Workbook may already be closed

            try:
                if excel is not None:
                    excel.Quit()
                    print("   [OK] Excel closed")
            except:
                pass

    except Exception as e:
        print(f"Error during DTC report generation: {str(e)}")
        return False

    finally:
        # Uninitialize COM
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    config = load_config()
    success = generate_dtc_report(config)
    sys.exit(0 if success else 1)
