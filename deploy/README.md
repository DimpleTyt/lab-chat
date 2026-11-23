# Три сценария публикации

Сервер без публичного IP: `127.0.0.1:8000` слушает только локально,
наружу выставляем одним из способов ниже.

## A. Cloudflare Tunnel (рекомендуется)

Не нужны входящие порты и белый IP. Нужен домен, привязанный к Cloudflare.

```bash
# на сервере
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

cloudflared tunnel login                 # ссылка, открыть в браузере
cloudflared tunnel create lab-chat
cloudflared tunnel route dns lab-chat chat.example.com
```

`/etc/cloudflared/config.yml`:

```yaml
tunnel: lab-chat
credentials-file: /root/.cloudflared/<UUID>.json
ingress:
  - hostname: chat.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

```bash
cloudflared service install
systemctl enable --now cloudflared
```

## B. Проброс порта 443/8443

Caddy с DNS-01 (сертификат без входящего 80):

```
{
	email admin@example.com
}

chat.example.com:8443 {
	tls {
		dns cloudflare {env.CF_API_TOKEN}
	}
	reverse_proxy 127.0.0.1:8000
}
```

Либо без домена: `https://IP:8443` с самоподписанным сертификатом
(`tls internal`), браузер покажет предупреждение.

## C. Обычные 80 + 443 и домен

```bash
apt-get install -y caddy
cp deploy/Caddyfile /etc/caddy/Caddyfile
echo 'DOMAIN=chat.example.com' >> /etc/caddy/environment   # или Environment= в unit
systemctl reload caddy
```

Caddy сам выпустит Let's Encrypt.

## После любого варианта

```bash
sudo bash deploy/install.sh /path/to/lab-chat
sudo -u labchat /opt/lab-chat/.venv/bin/python /opt/lab-chat/tools/create_user.py aks1
```

Проверка: открыть адрес, войти, отправить задание, подтвердить карточку.
