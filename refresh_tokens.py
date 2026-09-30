"""Продление ключей Instagram и Threads (живут 60 дней) и запись новых значений в секреты GitHub.

Запускается раз в неделю из .github/workflows/refresh.yml. Нужны переменные: IG_TOKEN, THREADS_TOKEN,
GH_TOKEN (личный токен GitHub с правом менять секреты этого репозитория), GITHUB_REPOSITORY.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

TARGETS = [
    ("IG_TOKEN", "https://graph.instagram.com/refresh_access_token", "ig_refresh_token"),
    ("THREADS_TOKEN", "https://graph.threads.net/refresh_access_token", "th_refresh_token"),
]

failed = False
for name, url, grant in TARGETS:
    token = os.environ.get(name)
    if not token:
        print(f"· {name}: не задан, пропускаю")
        continue
    try:
        q = urllib.parse.urlencode({"grant_type": grant, "access_token": token})
        with urllib.request.urlopen(f"{url}?{q}", timeout=60) as r:
            data = json.loads(r.read().decode())
        new = data["access_token"]
        days = int(data.get("expires_in", 0)) // 86400
        subprocess.run(["gh", "secret", "set", name, "--repo", os.environ["GITHUB_REPOSITORY"], "--body", new],
                       check=True, capture_output=True)
        print(f"✓ {name}: продлён, действует ещё {days} дн.")
    except urllib.error.HTTPError as e:
        print(f"✗ {name}: HTTP {e.code} {e.read().decode(errors='replace')[:300]}")
        failed = True
    except Exception as e:  # noqa: BLE001
        print(f"✗ {name}: {e}")
        failed = True

sys.exit(1 if failed else 0)
