"""
Step 3: PFS Daily Report Generation
Automates PFS Excel report generation with data refresh, snapshot creation, and screenshots.
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


def get_yesterday_date_file():
    """Get yesterday's date formatted as YYYY-MM-DD for filenames."""
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

    Returns:
        True if screenshot was saved successfully, False otherwise
    """
    import time
    excel = None
    chart_obj = None

    try:
        # Get Excel application from sheet
        excel = sheet.Application
        range_obj = sheet.Range(range_addr)

        # Calculate target size
        target_width = int(range_obj.Width * (scale_percent / 100))
        target_height = int(range_obj.Height * (scale_percent / 100))

        # Ensure screen updating is enabled for CopyPicture to work
        excel.ScreenUpdating = True

        # Select the range first
        range_obj.Select()
        time.sleep(0.3)

        # Add a temporary chart object to a remote location (off-screen)
        chart_obj = sheet.ChartObjects().Add(10000, 10000, target_width, target_height)
        chart = chart_obj.Chart

        # Try CopyPicture with different formats
        # Format=2 (xlBitmap) is often more reliable than Format=1 (xlPicture)
        copy_success = False

        # Method 1: Try xlBitmap format first (more compatible)
        try:
            range_obj.CopyPicture(Appearance=1, Format=2)  # xlScreen=1, xlBitmap=2
            copy_success = True
        except Exception as e1:
            print(f"  Method 1 (xlBitmap) failed: {e1}")
            # Method 2: Try xlPicture format
            try:
                range_obj.CopyPicture(Appearance=1, Format=1)  # xlScreen=1, xlPicture=1
                copy_success = True
            except Exception as e2:
                print(f"  Method 2 (xlPicture) failed: {e2}")
                # Method 3: Use Selection.CopyPicture after reselecting
                try:
                    range_obj.Select()
                    time.sleep(0.2)
                    excel.Selection.CopyPicture(Appearance=1, Format=2)
                    copy_success = True
                except Exception as e3:
                    print(f"  Method 3 (Selection.CopyPicture) failed: {e3}")

        if not copy_success:
            print("  All CopyPicture methods failed")
            return False

        time.sleep(0.3)

        # Paste into the off-screen chart
        chart.ChartArea.Select()
        chart.Paste()
        time.sleep(0.3)

        # Export the chart as image
        chart.Export(image_path)

        # Delete the temporary chart object
        chart_obj.Delete()
        chart_obj = None

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
        # Clean up chart object if it exists
        try:
            if chart_obj is not None:
                chart_obj.Delete()
        except:
            pass
        return False


def calculate_highlights_last_row(sheet):
    """Calculate the last row for Daily Highlights screenshot based on C5:C14 non-empty count."""
    try:
        # Count non-empty cells in C5:C14
        non_empty_count = 0
        for row in range(5, 15):  # Rows 5 to 14 inclusive
            cell_value = sheet.Cells(row, 3).Value  # Column C = 3
            if cell_value and str(cell_value).strip():
                non_empty_count += 1

        # Calculate last row: non_empty_count + 4
        last_row = non_empty_count + 4

        print(f"  Non-empty cells in C5:C14: {non_empty_count}")
        print(f"  Calculated last row: {last_row} ({non_empty_count} + 4)")

        return last_row
    except Exception as e:
        print(f"  Error calculating last row: {str(e)}")
        return 9  # Default fallback (5 + 4)


def generate_pfs_report(config):
    """Generate PFS daily report with Excel automation."""
    print("Starting PFS Daily Report generation...")

    # Get paths and settings from config
    excel_file = config['paths']['pfs_excel']
    snapfile_dir = config['paths']['pfs_snapfile_dir']
    snapshot_dir = config['paths']['pfs_snapshot_dir']
    wait_timeout = config['settings']['excel_wait_timeout']
    excel_visible = config['settings']['excel_visible']

    yesterday = get_yesterday_date()

    # Ensure output directories exist
    Path(snapfile_dir).mkdir(parents=True, exist_ok=True)
    Path(snapshot_dir).mkdir(parents=True, exist_ok=True)

    # Initialize COM for this thread
    pythoncom.CoInitialize()

    excel = None
    wb = None
    new_wb = None

    try:
        print(f"Opening Excel file: {excel_file}")
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = excel_visible
        excel.DisplayAlerts = False

        # Open workbook
        wb = excel.Workbooks.Open(excel_file)

        # Step 1: Refresh all data connections
        print("Refreshing all data connections...")
        wb.RefreshAll()

        # Wait for refresh to complete
        print("Waiting for refresh to complete (this may take 2-3 minutes)...")
        import time

        # Wait for calculation state (with error handling for compatibility)
        waited = 0
        try:
            while excel.CalculationState != 0 and waited < wait_timeout:  # xlDone=0
                time.sleep(5)
                waited += 5
                print(f"Waiting for calculations... ({waited}s)")
        except AttributeError:
            # CalculationState not available in some Excel versions, use simple wait
            print("  CalculationState not available, using timed wait...")
            time.sleep(30)  # Wait 30 seconds for calculations to complete

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
        time.sleep(5)  # Give Excel more time to stabilize after refresh

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

        # Step 2: Copy "Daily" sheet to new workbook with formatting
        print("Creating values-only snapshot...")

        # IMPORTANT: First activate the Daily sheet to ensure we're copying the right one
        print("  Step 2.0: Activate Daily sheet...")
        daily_sheet = wb.Sheets("Daily")
        daily_sheet.Activate()
        import time
        time.sleep(0.5)
        print(f"  Activated sheet: {daily_sheet.Name}")

        # Method: Copy Daily sheet within same workbook
        print("  Step 2.1: Copy Daily sheet to Daily2...")

        # CRITICAL FIX: Use Copy() without parameters, then get the newly created sheet
        # The copy creates a new sheet that becomes the active sheet
        daily_sheet.Copy()
        daily2_sheet = excel.ActiveSheet  # The copied sheet becomes active

        # Rename it
        daily2_sheet.Name = "Daily2"
        print(f"  Created {daily2_sheet.Name}")
        print(f"  Workbook now has {wb.Sheets.Count} sheets")

        # Activate Daily2 sheet
        print("  Step 2.2: Activate Daily2 sheet...")
        daily2_sheet.Activate()
        import time
        time.sleep(0.5)

        # Select all used cells and paste as values
        print("  Step 2.3: Convert all formulas to values...")
        used_range = daily2_sheet.UsedRange
        used_range.Copy()
        used_range.PasteSpecial(-4163)  # xlPasteValues
        excel.CutCopyMode = False  # Clear clipboard
        print(f"  Converted entire sheet to values")

        # Now copy Daily2 to a new workbook
        print("  Step 2.4: Copy Daily2 to new workbook...")
        new_wb = excel.Workbooks.Add()

        # Delete default sheets in new workbook (keep only 1)
        while new_wb.Sheets.Count > 1:
            new_wb.Sheets(2).Delete()

        # Copy Daily2 sheet to new workbook
        # NOTE: This will MOVE Daily2 to new workbook, not copy it
        print("  Moving Daily2 to new workbook...")
        daily2_sheet.Copy(Before=new_wb.Sheets(1))
        new_sheet = new_wb.Sheets(1)
        print(f"  Moved to new workbook: {new_sheet.Name}")

        # NOTE: Daily2 is no longer in original workbook (it was moved)
        # So we don't need to delete it

        print(f"  [OK] Snapshot sheet ready")

        # Save snapshot file
        snapfile_name = f"dunhill pfs daily report_{yesterday}.xlsx"
        snapfile_path = os.path.join(snapfile_dir, snapfile_name)
        print(f"Saving snapshot to: {snapfile_path}")
        new_wb.SaveAs(snapfile_path)
        new_wb.Close(SaveChanges=False)
        new_wb = None  # Release reference

        print("Snapshot saved!")

        # IMPORTANT: Get fresh reference to Daily sheet after creating snapshot
        # The previous daily_sheet reference may be stale after moving Daily2 to new workbook
        print("Getting fresh reference to Daily sheet...")
        daily_sheet = wb.Sheets("Daily")

        # Step 3: Take screenshot of Daily sheet (B8:AH37)
        print("Taking screenshots...")
        screenshot1_name = f"dunhill pfs daily report_{yesterday}.jpg"
        screenshot1_path = os.path.join(snapshot_dir, screenshot1_name)

        # IMPORTANT: Fully activate Daily sheet and workbook before screenshot
        print("  Activating Daily sheet...")
        # First, ensure Excel window is active
        excel.ActivateMicrosoftApp(0)  # Activate Excel window
        time.sleep(0.3)
        # Activate the workbook
        wb.Activate()
        time.sleep(0.3)
        # Activate the sheet
        daily_sheet.Activate()
        time.sleep(1)
        # Scroll to make the range visible
        daily_sheet.Range("B8").Select()
        time.sleep(0.3)

        # Screenshot range B8:AH37 (scaled to 70%)
        success1 = copy_range_as_picture(daily_sheet, "B8:AH37", screenshot1_path, scale_percent=70)
        if success1:
            print(f"Screenshot 1 saved: {screenshot1_path}")
        else:
            print(f"Warning: Screenshot 1 failed to save")

        # Step 4: Take screenshot of Daily Highlights sheet (B3:G?)
        print("Checking Daily Highlights for data...")
        highlights_sheet = wb.Sheets("Daily Highlights")

        # Count non-empty cells in C5:C14
        non_empty_count = 0
        for row in range(5, 15):  # Rows 5 to 14 inclusive
            cell_value = highlights_sheet.Cells(row, 3).Value  # Column C = 3
            if cell_value and str(cell_value).strip():
                non_empty_count += 1

        print(f"  Non-empty cells in C5:C14: {non_empty_count}")

        # Only take screenshot if there is data
        if non_empty_count > 0:
            print("Taking Daily Highlights screenshot...")

            # IMPORTANT: Activate Daily Highlights sheet before screenshot
            print("  Activating Daily Highlights sheet...")
            wb.Activate()  # Ensure workbook is in focus
            highlights_sheet.Activate()
            time.sleep(1)  # Increased wait time to ensure sheet is fully activated

            # Calculate last row based on C5:C14 non-empty cell count
            last_row = calculate_highlights_last_row(highlights_sheet)
            highlights_range = f"B3:G{last_row}"

            screenshot2_name = f"pfs_daily_highlights_{yesterday}.jpg"
            screenshot2_path = os.path.join(snapshot_dir, screenshot2_name)

            success2 = copy_range_as_picture(highlights_sheet, highlights_range, screenshot2_path, scale_percent=70)
            if success2:
                print(f"Screenshot 2 saved: {screenshot2_path}")
            else:
                print(f"Warning: Screenshot 2 failed to save")
        else:
            print("  [INFO] No data in Daily Highlights (C5:C14 is empty)")
            print("  [INFO] Skipping Daily Highlights screenshot")

        print("PFS Daily Report generation completed successfully!")
        return True

    except Exception as e:
        print(f"Error during PFS report generation: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Clean up COM objects
        try:
            if wb is not None:
                wb.Close(SaveChanges=False)
        except:
            pass

        try:
            if new_wb is not None:
                new_wb.Close(SaveChanges=False)
        except:
            pass

        try:
            if excel is not None:
                excel.Quit()
        except:
            pass

        # Uninitialize COM
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    config = load_config()
    success = generate_pfs_report(config)
    sys.exit(0 if success else 1)
