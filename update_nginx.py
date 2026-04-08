import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('45.138.158.217', username='root', password='aE1wM2vH7fvJ')

nginx_config = """server {
    listen 80;
    server_name islomcrm.uz www.islomcrm.uz 45.138.158.217;

    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/islomcrm/islomcrm.sock;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
        add_header Expires "0";
    }

    location /static {
        alias /var/www/islomcrm/static;
    }
}

server {
    listen 443 ssl;
    server_name islomcrm.uz www.islomcrm.uz;

    ssl_certificate /etc/letsencrypt/live/islomcrm.uz-0001/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/islomcrm.uz-0001/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/islomcrm/islomcrm.sock;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
        add_header Expires "0";
    }

    location /static {
        alias /var/www/islomcrm/static;
    }
}
"""

# SFTP to write the file directly
sftp = ssh.open_sftp()
with sftp.file('/etc/nginx/sites-available/islomcrm', 'w') as f:
    f.write(nginx_config)
sftp.close()

# Symbolic link and restart
ssh.exec_command('ln -sf /etc/nginx/sites-available/islomcrm /etc/nginx/sites-enabled/islomcrm')
ssh.exec_command('systemctl restart nginx')
ssh.exec_command('systemctl restart islomcrm')

print("Nginx configuration updated and services restarted successfully.")
ssh.close()
