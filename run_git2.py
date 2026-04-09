import os
import subprocess
import paramiko

def run_cmd(cmd):
    print(">", cmd)
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        print("Failed:", e)

# 1. Clean up
files_to_remove = ["run_git.py", "run_vps.py", ".deploy.py"]
for f in files_to_remove:
    run_cmd(f"git rm -f {f}")
    if os.path.exists(f):
        try: os.remove(f)
        except: pass

# 2. Push awesome new UI to github
run_cmd("git add .")
run_cmd('git commit -m "Enhance VPS Management UI to professional design"')
run_cmd("git push origin main")

# 3. Pull on VPS using ssh
try:
    host = "45.138.158.217"
    user = "root"
    password = "aE1wM2vH7fvJ"

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=10)

    commands = [
        "cd /var/www/islomcrm && git pull origin main",
        "systemctl restart islomcrm"
    ]

    for cmd in commands:
        print(f"VPS > {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode().strip()
        if out:
            print(f"OUT: {out}")

    ssh.close()
    print("Done!")
except Exception as e:
    print("SSH Failed:", e)
