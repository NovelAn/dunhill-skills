"""
Check Outlook Drafts folder to help locate email drafts
"""
import win32com.client
import pythoncom

def check_outlook_drafts():
    """Check Outlook Drafts folder and list all draft emails."""
    pythoncom.CoInitialize()

    try:
        print("Connecting to Outlook...")
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")

        # Try to get the default Inbox folder first
        print("\nChecking default account...")
        try:
            inbox = namespace.GetDefaultFolder(6)  # 6 = olFolderInbox
            account_name = inbox.Parent.Name
            print(f"Default account: {account_name}")
        except:
            print("Could not determine default account")

        # Get Drafts folder
        print("\nAccessing Drafts folder...")
        drafts = namespace.GetDefaultFolder(16)  # 16 = olFolderDrafts

        # Get all items in Drafts folder
        items = drafts.Items
        count = items.Count
        print(f"\nTotal drafts in folder: {count}")

        if count > 0:
            print("\nRecent drafts (last 10):")
            print("-" * 80)

            # Sort by CreationTime (descending)
            items.Sort("[CreationTime]", True)

            # Show last 10 drafts
            for i in range(min(10, count)):
                item = items.Item(i + 1)
                subject = getattr(item, 'Subject', '(No Subject)')
                created = getattr(item, 'CreationTime', '(Unknown)')
                to_addr = getattr(item, 'To', '(No To)')

                print(f"\n{i+1}. Subject: {subject}")
                print(f"   Created: {created}")
                print(f"   To: {to_addr[:80]}...")  # Truncate long recipient lists
                print(f"   Has Attachments: {getattr(item, 'Attachments', {}).Count > 0}")

                # Check if this is one of our Dunhill reports
                if 'Dunhill' in subject or 'dunhill' in subject or 'OFS' in subject:
                    print("   *** THIS IS A DUNHILL REPORT ***")

        else:
            print("\n[WARNING] No drafts found in the default Drafts folder!")
            print("\nPossible reasons:")
            print("1. You have multiple Outlook accounts - check other accounts' Drafts folders")
            print("2. The email was saved to a different folder")
            print("3. Outlook needs to be refreshed (press F5 in Outlook)")
            print("4. The email creation actually failed (though no error was shown)")

        # Check all accounts if there are multiple
        print("\n\nChecking all Outlook accounts...")
        try:
            for store in namespace.Stores:
                print(f"\nAccount: {store.DisplayName}")
                try:
                    # Try to get Drafts folder for this store
                    drafts_folder = store.GetDefaultFolder(16)  # olFolderDrafts
                    drafts_count = drafts_folder.Items.Count
                    print(f"  Drafts count: {drafts_count}")

                    if drafts_count > 0:
                        # Show last draft
                        last_draft = drafts_folder.Items(1)
                        print(f"  Last draft: {getattr(last_draft, 'Subject', '(No Subject)')}")
                except Exception as e:
                    print(f"  Error accessing drafts: {str(e)}")
        except:
            print("Could not enumerate all accounts")

        print("\n" + "=" * 80)
        print("If you still don't see the drafts, please:")
        print("1. Close and reopen Outlook")
        print("2. Press F5 to refresh the Drafts folder")
        print("3. Check if you have multiple email accounts in Outlook")
        print("4. Look in the 'Outbox' folder (might be stuck there)")

    except Exception as e:
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    check_outlook_drafts()
