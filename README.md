# Bsky

регистрация аккаунтов bluesky / account registration cli

файлы / files:
- autoreg.py — cli
- bsky/client.py — api
- bsky/captcha.py — hcaptcha via hcaptchasolver.org
- bsky/mail.py — temp mail
- bsky/proxy.py — proxies
- proxies.example.txt — proxy list example
- requirements.txt

запуск / run:
pip install -r requirements.txt
ключ hcaptchasolver.org в captcha_key.txt (или --captcha-key / CAPTCHA_KEY)
python autoreg.py
python autoreg.py --no-prompt --count 10

аккаунты падают в logs/accounts.json

прокси / proxies, один на строку:
host:port
host:port:user:pass
user:pass@host:port
после | ссылка смены ip, без неё прокси считается rotating
