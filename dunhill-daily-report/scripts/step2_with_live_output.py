"""
Step 2 Executor with Live Output Display
This version outputs everything immediately to stdout for CC terminal display
"""
import subprocess
import sys
import os
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        # Set output encoding to UTF-8
        os.environ['PYTHONIOENCODING'] = 'utf-8'
    except:
        pass

def main():
    script_dir = Path(__file__).parent.parent
    step2_script = script_dir / "scripts" / "step2_run_import.py"

    # Run step2 script with unbuffered output
    process = subprocess.Popen(
        [sys.executable, '-u', str(step2_script)],
        stdout=None,  # Inherit stdout from parent
        stderr=None,  # Inherit stderr from parent
        stdin=None,
        cwd=str(script_dir),
        env=os.environ
    )

    # Wait for completion
    return_code = process.wait()

    return return_code

if __name__ == "__main__":
    sys.exit(main())
