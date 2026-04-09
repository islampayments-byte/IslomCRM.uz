import subprocess
import sys

def run_cmd(cmd):
    print(f"Running: {cmd}")
    try:
        res = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with {e.returncode}")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)

if __name__ == "__main__":
    run_cmd("git add .")
    run_cmd('git commit -m "Fix VPS dashboard"')
    run_cmd("git push origin main")
    print("Done")
