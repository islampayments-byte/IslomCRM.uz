import subprocess
import sys

try:
    import paramiko
except ImportError:
    print("Installing paramiko...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "cryptography"])
    import paramiko

def run_ssh_commands():
    host = "45.138.158.217"
    user = "root"
    password = "aE1wM2vH7fvJ"

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    print(f"Connecting to {host}...")
    try:
        ssh.connect(host, username=user, password=password, timeout=10)
        print("Connected successfully.")
        
        commands = [
            "cd /var/www/islomcrm && git pull origin main",
            "/var/www/islomcrm/venv/bin/pip install psutil",
            "systemctl restart islomcrm",
            "systemctl status islomcrm | grep Active"
        ]
        
        for cmd in commands:
            print(f">>> {cmd}")
            stdin, stdout, stderr = ssh.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            
            if out:
                print(f"OUT:\n{out}")
            if err:
                print(f"ERR:\n{err}")
                
            print(f"Exit status: {exit_status}\n")

    except Exception as e:
        print(f"Connection failed: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    run_ssh_commands()
