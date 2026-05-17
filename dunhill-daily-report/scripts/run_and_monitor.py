"""
Run step2 script with real-time output monitoring in CC terminal
"""
import subprocess
import sys
import time
import os
from pathlib import Path

def safe_print(text):
    """Print text safely, handling encoding errors"""
    try:
        print(text, end='', flush=True)
    except UnicodeEncodeError:
        # Fallback: encode with error handling
        safe_text = text.encode('gbk', errors='replace').decode('gbk')
        print(safe_text, end='', flush=True)

def main():
    script_dir = Path(__file__).parent.parent
    step2_script = script_dir / "scripts" / "step2_run_import.py"

    print("\n" + "="*70)
    print("  Execute Step 2: Data Import (Real-time Monitor)")
    print("="*70 + "\n")

    # Run step2 and capture output line by line
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

    # Read and display output in real-time
    try:
        for line in process.stdout:
            # Immediately print each line
            safe_print(line)
    except KeyboardInterrupt:
        print("\n\n[WARN] Script interrupted by user")
        process.terminate()
        return 1

    # Wait for process to complete
    return_code = process.wait()

    if return_code == 0:
        print("\n" + "="*70)
        print("[OK] Step 2 completed successfully! Ready for next steps.")
        print("="*70 + "\n")
    else:
        print("\n" + "="*70)
        print(f"[FAIL] Step 2 failed with return code: {return_code}")
        print("="*70 + "\n")

    return return_code

if __name__ == "__main__":
    sys.exit(main())
