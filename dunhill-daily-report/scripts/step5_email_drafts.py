"""
Step 5: Create Email Drafts
Creates Outlook email drafts for PFS and DTC reports with screenshots attached.
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

    return config


def get_yesterday_date():
    """Get yesterday's date formatted as YYYY-MM-DD."""
    yesterday = datetime.now() - timedelta(days=1)
    return yesterday.strftime('%Y-%m-%d')


def create_pfs_email_draft_only(config):
    """Create Outlook email draft for PFS report only (testing)."""
    print("=" * 60)
    print("Creating PFS Email Draft (Testing)")
    print("=" * 60)

    # Get paths and settings from config
    pfs_snapshot_dir = config['paths']['pfs_snapshot_dir']
    date_placeholder = config['email']['date_placeholder']
    skill_dir = Path(__file__).parent.parent

    # Get recipients from config
    pfs_to = config['email'].get('pfs_to', [])
    pfs_cc = config['email'].get('pfs_cc', [])

    # Get font settings from config
    font_family = config['email'].get('font_family', 'Arial')
    font_size = config['email'].get('font_size', '11pt')

    yesterday = get_yesterday_date()

    # Initialize COM for this thread
    pythoncom.CoInitialize()

    try:
        # Create Outlook application
        print("\n1. Creating Outlook application...")
        outlook = win32com.client.Dispatch("Outlook.Application")
        print("   [OK] Outlook created")

        # Always create new email (template is just for reference)
        print(f"\n2. Creating new PFS email draft...")
        pfs_snapfile_dir = config['paths']['pfs_snapfile_dir']
        create_new_pfs_email(
            outlook,
            pfs_snapshot_dir,
            pfs_snapfile_dir,
            yesterday,
            pfs_to,
            pfs_cc,
            font_family,
            font_size
        )

        print("\n" + "=" * 60)
        print("PFS Email draft created successfully!")
        print("=" * 60)
        print("\nPlease check Outlook Drafts folder for the email.")
        print("Do NOT send - this is a test run.")
        return True

    except Exception as e:
        print(f"\n[ERROR] Error creating email drafts: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Uninitialize COM
        pythoncom.CoUninitialize()


def attach_inline_image(mail_item, image_path):
    """Attach an image as inline and return its Content ID (CID)."""
    import uuid

    # Generate unique Content ID
    cid = str(uuid.uuid4())

    # Attach the file at position 0 (inline)
    attachment = mail_item.Attachments.Add(image_path, 0)

    # Set the PR_ATTACH_CONTENT_ID property using PropertyAccessor
    # This is the MAPI property tag for Content-ID
    schema = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"
    attachment.PropertyAccessor.SetProperty(schema, cid)

    return cid


def create_new_pfs_email(outlook, snapshot_dir, snapfile_dir, date, to_recipients, cc_recipients, font_family, font_size):
    """Create a new PFS email with embedded images and Excel attachment."""
    try:
        print("   Step 2.1: Creating new mail item...")
        mail_item = outlook.CreateItem(0)  # 0 = MailItem

        # Set subject
        mail_item.Subject = f"Dunhill PFS Daily Report - {date}"
        print(f"   Subject: {mail_item.Subject}")

        # Set recipients
        print("   Step 2.2: Setting recipients...")
        if to_recipients:
            for recipient in to_recipients:
                mail_item.To = mail_item.To + ";" + recipient if mail_item.To else recipient
            print(f"   To: {', '.join(to_recipients)}")
        else:
            print(f"   [INFO] No 'To' recipients configured")

        if cc_recipients:
            for recipient in cc_recipients:
                mail_item.CC = mail_item.CC + ";" + recipient if mail_item.CC else recipient
            print(f"   CC: {', '.join(cc_recipients)}")
        else:
            print(f"   [INFO] No 'CC' recipients configured")

        # Build HTML body with configured font
        print("   Step 2.3: Building HTML body...")
        html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <style>
        body {{ font-family: {font_family}; font-size: {font_size}; line-height: 1.5; }}
        p {{ margin: 10px 0; }}
    </style>
</head>
<body>
<p>Dear all,</p>
<p>Please see the updated annex, updated to {date}.</p>
"""

        # Find screenshots
        print("   Step 2.4: Finding screenshot files...")
        snapshot_files = list(Path(snapshot_dir).glob(f"*{date}.jpg"))

        if not snapshot_files:
            print(f"   [WARNING] No screenshot files found matching *{date}.jpg")
            print(f"   Snapshot directory: {snapshot_dir}")
            # List all files for debugging
            all_files = list(Path(snapshot_dir).glob("*.jpg"))
            print(f"   All .jpg files in directory:")
            for f in all_files:
                print(f"     - {f.name}")
            html_body += "<p><i>No screenshots available for this date.</i></p>"
        else:
            # Find Daily screenshot and Highlights screenshot
            daily_img = None
            highlights_img = None

            for img_file in snapshot_files:
                if "daily report" in img_file.name.lower():
                    daily_img = img_file
                elif "highlights" in img_file.name.lower():
                    highlights_img = img_file

            # Embed Daily screenshot
            if daily_img:
                cid = attach_inline_image(mail_item, str(daily_img))
                html_body += f'<p><img src="cid:{cid}" border="0"></p>'
                print(f"   Embedded: {daily_img.name}")
            else:
                print(f"   [INFO] Daily report screenshot not found")

            # Embed Highlights screenshot (only if exists)
            if highlights_img:
                cid = attach_inline_image(mail_item, str(highlights_img))
                html_body += f'<p><img src="cid:{cid}" border="0"></p>'
                print(f"   Embedded: {highlights_img.name}")
            else:
                print(f"   [INFO] Daily Highlights screenshot not found, skipping")

        # Close HTML body
        html_body += """
<p>&nbsp;</p>
<p>Best Regards,</p>
<p>Novel An</p>
</body>
</html>
"""

        # Set HTML body
        mail_item.HTMLBody = html_body
        print(f"   Step 2.5: HTML body created")

        # Attach Excel snapshot file
        print("   Step 2.6: Attaching Excel snapshot file...")
        snapfile_name = f"dunhill pfs daily report_{date}.xlsx"
        snapfile_path = os.path.join(snapfile_dir, snapfile_name)

        if os.path.exists(snapfile_path):
            mail_item.Attachments.Add(snapfile_path)
            print(f"   [OK] Attached: {snapfile_name}")
        else:
            print(f"   [WARNING] Excel snapshot not found: {snapfile_path}")

        # Save as draft
        print("   Step 2.7: Saving to drafts...")
        mail_item.Save()
        print(f"   [OK] Saved to Outlook Drafts")

    except Exception as e:
        print(f"   [ERROR] Error creating new PFS email: {str(e)}")
        raise


def create_dtc_email_draft_only(config):
    """Create Outlook email draft for DTC report only (testing)."""
    print("=" * 60)
    print("Creating DTC Email Draft (Testing)")
    print("=" * 60)

    # Get paths and settings from config
    dtc_snapshot_dir = config['paths']['dtc_snapshot_dir']
    date_placeholder = config['email']['date_placeholder']

    # Get recipients from config
    dtc_to = config['email'].get('dtc_to', [])
    dtc_cc = config['email'].get('dtc_cc', [])

    # Get font settings from config
    font_family = config['email'].get('font_family', 'Arial')
    font_size = config['email'].get('font_size', '11pt')

    yesterday = get_yesterday_date()

    # Initialize COM for this thread
    pythoncom.CoInitialize()

    try:
        # Create Outlook application
        print("\n1. Creating Outlook application...")
        outlook = win32com.client.Dispatch("Outlook.Application")
        print("   [OK] Outlook created")

        # Always create new email (template is just for reference)
        print(f"\n2. Creating new DTC email draft...")
        dtc_snapfile_dir = config['paths']['dtc_snapfile_dir']
        create_new_dtc_email(
            outlook,
            dtc_snapshot_dir,
            dtc_snapfile_dir,
            yesterday,
            dtc_to,
            dtc_cc,
            font_family,
            font_size
        )

        print("\n" + "=" * 60)
        print("DTC Email draft created successfully!")
        print("=" * 60)
        print("\nPlease check Outlook Drafts folder for the email.")
        print("Do NOT send - this is a test run.")
        return True

    except Exception as e:
        print(f"\n[ERROR] Error creating email drafts: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Uninitialize COM
        pythoncom.CoUninitialize()


def create_new_dtc_email(outlook, snapshot_dir, snapfile_dir, date, to_recipients, cc_recipients, font_family, font_size):
    """Create a new DTC email with embedded images and Excel attachment."""
    try:
        print("   Step 2.1: Creating new mail item...")
        mail_item = outlook.CreateItem(0)  # 0 = MailItem

        # Set subject
        mail_item.Subject = f"dunhill OFS&WBQ daily sales report - {date}"
        print(f"   Subject: {mail_item.Subject}")

        # Set recipients
        print("   Step 2.2: Setting recipients...")
        if to_recipients:
            for recipient in to_recipients:
                mail_item.To = mail_item.To + ";" + recipient if mail_item.To else recipient
            print(f"   To: {', '.join(to_recipients)}")
        else:
            print(f"   [INFO] No 'To' recipients configured")

        if cc_recipients:
            for recipient in cc_recipients:
                mail_item.CC = mail_item.CC + ";" + recipient if mail_item.CC else recipient
            print(f"   CC: {', '.join(cc_recipients)}")
        else:
            print(f"   [INFO] No 'CC' recipients configured")

        # Build HTML body with configured font
        print("   Step 2.3: Building HTML body...")
        html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <style>
        body {{ font-family: {font_family}; font-size: {font_size}; line-height: 1.5; }}
        p {{ margin: 10px 0; }}
    </style>
</head>
<body>
<p>Dear all,</p>
<p>Please kindly find OFS &amp; WBTQ - {date} and YTD sales report as below and attached.</p>
"""

        # Find DTC screenshot (prioritize .jpg, fallback to .png)
        print("   Step 2.4: Finding screenshot files...")
        snapshot_files = list(Path(snapshot_dir).glob(f"*{date}.jpg"))
        if not snapshot_files:
            # Fallback to .png if .jpg not found
            snapshot_files = list(Path(snapshot_dir).glob(f"*{date}.png"))

        if not snapshot_files:
            print(f"   [WARNING] No screenshot files found matching *{date}.jpg or *{date}.png")
            print(f"   Snapshot directory: {snapshot_dir}")
            # List all files for debugging
            all_files = list(Path(snapshot_dir).glob("*.jpg"))
            print(f"   All .jpg files in directory:")
            for f in all_files:
                print(f"     - {f.name}")
            html_body += "<p><i>No screenshots available for this date.</i></p>"
        else:
            # DTC has only one screenshot file
            for img_file in snapshot_files:
                if "daily sales report" in img_file.name.lower():
                    cid = attach_inline_image(mail_item, str(img_file))
                    html_body += f'<p><img src="cid:{cid}" border="0"></p>'
                    print(f"   Embedded: {img_file.name}")
                    break

        # Close HTML body
        html_body += """
<p>&nbsp;</p>
<p>Best Regards,</p>
<p>Novel An</p>
</body>
</html>
"""

        # Set HTML body
        mail_item.HTMLBody = html_body
        print(f"   Step 2.5: HTML body created")

        # Attach Excel snapshot file
        print("   Step 2.6: Attaching Excel snapshot file...")
        snapfile_name = f"dunhill OFS&WBTQ daily sales report_{date}.xlsx"
        snapfile_path = os.path.join(snapfile_dir, snapfile_name)

        if os.path.exists(snapfile_path):
            mail_item.Attachments.Add(snapfile_path)
            print(f"   [OK] Attached: {snapfile_name}")
        else:
            print(f"   [WARNING] Excel snapshot not found: {snapfile_path}")

        # Save as draft
        print("   Step 2.7: Saving to drafts...")
        mail_item.Save()
        print(f"   [OK] Saved to Outlook Drafts")

    except Exception as e:
        print(f"   [ERROR] Error creating new DTC email: {str(e)}")
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Create email drafts for Dunhill reports')
    parser.add_argument('--report-type', choices=['pfs', 'dtc', 'all'], default='all',
                        help='Type of report to create email for: pfs, dtc, or all (default: all)')
    args = parser.parse_args()

    config = load_config()

    success = True

    if args.report_type in ['pfs', 'all']:
        print("\n")
        pfs_success = create_pfs_email_draft_only(config)
        success = success and pfs_success

    if args.report_type in ['dtc', 'all']:
        print("\n")
        dtc_success = create_dtc_email_draft_only(config)
        success = success and dtc_success

    sys.exit(0 if success else 1)
