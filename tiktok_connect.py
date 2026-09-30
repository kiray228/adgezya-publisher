"""Обмен одноразового кода TikTok на постоянный ключ. Запускается из .github/workflows/tiktok-connect.yml."""
import os
import sys

import tiktok

code = os.environ.get("TIKTOK_CODE", "").strip()
if not code:
    sys.exit("Нет кода: вставьте код со страницы подключения в поле code")
try:
    res = tiktok.exchange_code(code)
    print(f"✓ TikTok подключён. Разрешения: {res.get('scope')}. Ключ сохранён в секрет TIKTOK_REFRESH_TOKEN.")
    user, scope, _ = tiktok.whoami()
    print(f"✓ Аккаунт: {user.get('display_name')}")
except tiktok.TikTokError as e:
    sys.exit(f"✗ {e}")
