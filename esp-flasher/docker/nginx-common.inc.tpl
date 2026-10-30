    root /usr/share/nginx/html;
    index index.html;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;
    add_header Permissions-Policy "serial=(self)" always;

    location = /healthz { return 200 "ok\n"; }

    # Setup, login and settings (docker/api.py). Secrets never leave it except the Wi-Fi for a logged-in browser.
    location /api/ {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Host $host;
        client_max_body_size 32k;
    }

    # Firmware catalog and images; never cached so a new build shows up at once
    location /firmware/ {
        alias @FW@/;
        add_header Cache-Control "no-cache";
        add_header X-Content-Type-Options nosniff always;
    }

    location / {
        add_header Cache-Control "no-cache";
        add_header X-Content-Type-Options nosniff always;
        add_header Referrer-Policy no-referrer always;
        add_header Permissions-Policy "serial=(self)" always;
        try_files $uri $uri/ /index.html;
    }
