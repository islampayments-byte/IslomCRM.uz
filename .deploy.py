import os
import subprocess
import paramiko

# 1. Delete unnecessary files locally and from git
files_to_remove = ["run_git.py", "run_vps.py"]
for f in files_to_remove:
    if os.path.exists(f):
        try:
            # We don't want git rm to fail if file isn't tracked
            subprocess.run(f"git rm -f {f}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception:
            pass
        try:
            os.remove(f)
        except Exception:
            pass

# 2. Push awesome new UI to github
def run_cmd(cmd):
    print(">", cmd)
    subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

run_cmd("git add .")
run_cmd('git commit -m "Enhance VPS Management UI & Clean up temp files"')
run_cmd("git push origin main")

# 3. Pull on VPS using ssh
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
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    if out:
        print(f"OUT: {out}")

ssh.close()
print("Done!")
