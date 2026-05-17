"""
Wrapper script to run step2 with real-time output monitoring
This script monitors the background task and displays output in real-time
"""
import subprocess
import sys
import time
from pathlib import Path

def run_with_realtime_output():
    """Run step2 and display output in real-time"""
    script_dir = Path(__file__).parent.parent
    step2_script = script_dir / "scripts" / "step2_run_import.py"

    print("\n" + "="*70)
    print("  开始执行步骤2：数据导入程序")
    print("  (实时输出模式)")
    print("="*70 + "\n")

    # Run the script with real-time output
    process = subprocess.Popen(
        [sys.executable, '-u', str(step2_script)],
        stdout=None,  # Direct output to parent stdout
        stderr=None,
        text=True,
        bufsize=1,
        universal_newlines=True
    )

    # Wait for completion
    return_code = process.wait()

    if return_code == 0:
        print("\n" + "="*70)
        print("[OK] 步骤2执行成功！")
        print("="*70 + "\n")
    else:
        print("\n" + "="*70)
        print(f"[FAIL] 步骤2执行失败，返回码: {return_code}")
        print("="*70 + "\n")

    return return_code

if __name__ == "__main__":
    sys.exit(run_with_realtime_output())
