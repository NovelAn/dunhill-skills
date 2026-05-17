"""
Execute step2 and continuously monitor background task output
This script provides automatic real-time output display in CC terminal
"""
import subprocess
import sys
import time
from pathlib import Path

def main():
    """Run step2 in background and monitor output"""
    script_dir = Path(__file__).parent.parent
    step2_script = script_dir / "scripts" / "step2_run_import.py"

    print("\n" + "="*70)
    print("  Execute Step 2: Data Import (Real-time Monitor)")
    print("  Starting background process and monitoring output...")
    print("="*70 + "\n")

    # Start the process
    process = subprocess.Popen(
        [sys.executable, '-u', str(step2_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
        encoding='utf-8',
        errors='replace'
    )

    # Monitor output line by line
    last_output_length = 0
    check_interval = 0.5  # Check every 0.5 seconds

    try:
        while True:
            line = process.stdout.readline()

            if not line:
                # No new line, check if process ended
                if process.poll() is not None:
                    break
                time.sleep(check_interval)
                continue

            # Print the line immediately
            try:
                print(line, end='', flush=True)
            except UnicodeEncodeError:
                # Handle encoding issues
                safe_line = line.encode('gbk', errors='replace').decode('gbk')
                print(safe_line, end='', flush=True)

    except KeyboardInterrupt:
        print("\n\n[WARN] Script interrupted by user")
        process.terminate()
        return 1

    # Get final return code
    return_code = process.wait()

    # Print summary
    if return_code == 0:
        print("\n" + "="*70)
        print("[OK] Step 2 completed successfully!")
        print("="*70 + "\n")
    else:
        print("\n" + "="*70)
        print(f"[FAIL] Step 2 failed (return code: {return_code})")
        print("="*70 + "\n")

    return return_code

if __name__ == "__main__":
    sys.exit(main())
