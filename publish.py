"""Публикатор «Адгезии»: берёт из queue.json посты, чьё время подошло, и публикует через официальные API.

Instagram — Instagram API with Instagram Login (graph.instagram.com), Threads — Threads API (graph.threads.net).
Файлы берутся по публичной ссылке MEDIA_BASE + путь (GitHub Pages этого репозитория): оба API сами скачивают медиа по URL.
Итог каждой публикации пишется в state/published.json — повторно не публикуется.

Запуск:  python publish.py              — опубликовать всё, что пора
         python publish.py --dry-run    — только показать план и проверить ссылки на файлы
         python publish.py --only post_3 — опубликовать конкретный пост сейчас, не дожидаясь времени
Переменные окружения: IG_TOKEN, THREADS_TOKEN, MEDIA_BASE.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "queue.json")
STATE = os.path.join(HERE, "state", "published.json")
ALMATY = timezone(timedelta(hours=5))  # Казахстан — единый UTC+5
MEDIA_BASE = os.environ.get("MEDIA_BASE", "https://kiray228.github.io/adgezya-publisher/").rstrip("/") + "/"
MAX_ATTEMPTS = 3

IG_API = "https://graph.instagram.com/v23.0"
TH_API = "https://graph.threads.net/v1.0"


class ApiError(Exception):
    pass


def call(method, url, params=None):
    params = {k: v for k, v in (params or {}).items() if v is not None}
    data = None
    if method == "GET":
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise ApiError(f"HTTP {e.code}: {body[:500]}") from None


def media_url(path):
    return MEDIA_BASE + urllib.parse.quote(path)


def wait_ready(check, timeout, label):
    """Ждём, пока платформа скачает и обработает медиа-контейнер."""
    t0 = time.time()
    while True:
        status = check()
        if status in ("FINISHED", "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise ApiError(f"{label}: контейнер в статусе {status}")
        if time.time() - t0 > timeout:
            raise ApiError(f"{label}: не дождались обработки за {timeout} с (статус {status})")
        time.sleep(5)


# ------------------------------------------------------------------ Instagram

def ig_publish(item, token):
    me = call("GET", f"{IG_API}/me", {"fields": "user_id,username", "access_token": token})
    uid = me.get("user_id") or me["id"]
    kind, media, caption = item["type"], item["media"], item.get("caption", "")

    def container(params):
        return call("POST", f"{IG_API}/{uid}/media", {**params, "access_token": token})["id"]

    def status(cid):
        return call("GET", f"{IG_API}/{cid}", {"fields": "status_code", "access_token": token}).get("status_code")

    if kind == "image":
        cid = container({"image_url": media_url(media[0]), "caption": caption})
        wait_ready(lambda: status(cid), 120, "Instagram фото")
    elif kind == "carousel":
        kids = []
        for m in media:
            is_video = m.lower().endswith(".mp4")
            k = container({"media_type": "VIDEO" if is_video else None,
                           "video_url" if is_video else "image_url": media_url(m), "is_carousel_item": "true"})
            wait_ready(lambda: status(k), 300 if is_video else 120, "Instagram карусель")
            kids.append(k)
        cid = container({"media_type": "CAROUSEL", "children": ",".join(kids), "caption": caption})
        wait_ready(lambda: status(cid), 120, "Instagram карусель")
    elif kind == "reel":
        cid = container({"media_type": "REELS", "video_url": media_url(media[0]), "caption": caption,
                         "share_to_feed": "true", "cover_url": media_url(item["cover"]) if item.get("cover") else None})
        wait_ready(lambda: status(cid), 600, "Instagram Reels")
    else:
        raise ApiError(f"Instagram не умеет тип {kind}")

    mid = call("POST", f"{IG_API}/{uid}/media_publish", {"creation_id": cid, "access_token": token})["id"]
    link = call("GET", f"{IG_API}/{mid}", {"fields": "permalink", "access_token": token}).get("permalink")
    return mid, link


# ------------------------------------------------------------------ Threads

def th_publish(item, token):
    kind, media = item["type"], item.get("media", [])
    text = item.get("threads_text") or item.get("caption", "")

    def container(params):
        return call("POST", f"{TH_API}/me/threads", {**params, "access_token": token})["id"]

    def status(cid):
        return call("GET", f"{TH_API}/{cid}", {"fields": "status", "access_token": token}).get("status")

    if kind == "text" or not media:
        cid = container({"media_type": "TEXT", "text": text})
    elif kind in ("image", "reel") and len(media) == 1:
        is_video = media[0].lower().endswith(".mp4")
        cid = container({"media_type": "VIDEO" if is_video else "IMAGE",
                         "video_url" if is_video else "image_url": media_url(media[0]), "text": text})
        wait_ready(lambda: status(cid), 600 if is_video else 120, "Threads")
    else:
        kids = []
        for m in media:
            is_video = m.lower().endswith(".mp4")
            k = container({"media_type": "VIDEO" if is_video else "IMAGE",
                           "video_url" if is_video else "image_url": media_url(m), "is_carousel_item": "true"})
            wait_ready(lambda: status(k), 600 if is_video else 120, "Threads карусель")
            kids.append(k)
        cid = container({"media_type": "CAROUSEL", "children": ",".join(kids), "text": text})
        wait_ready(lambda: status(cid), 120, "Threads карусель")

    mid = call("POST", f"{TH_API}/me/threads_publish", {"creation_id": cid, "access_token": token})["id"]
    link = call("GET", f"{TH_API}/{mid}", {"fields": "permalink", "access_token": token}).get("permalink")
    return mid, link


# ------------------------------------------------------------------ TikTok

def tt_publish(item, _refresh_token):
    import tiktok
    media = item.get("media", [])
    if not media or not media[0].lower().endswith(".mp4"):
        raise ApiError("TikTok: публикуем только видео (.mp4)")
    text = item.get("tiktok_text") or item.get("caption", "")
    try:
        return tiktok.publish_video(os.path.join(HERE, media[0]), text)
    except tiktok.TikTokError as e:
        raise ApiError(str(e)) from None


PUBLISHERS = {"instagram": ("IG_TOKEN", ig_publish), "threads": ("THREADS_TOKEN", th_publish),
              "tiktok": ("TIKTOK_REFRESH_TOKEN", tt_publish)}


# ------------------------------------------------------------------ main

def parse_when(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=ALMATY)


def check_url(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            return f"{r.status} {r.headers.get('Content-Type')}"
    except Exception as e:  # noqa: BLE001
        return f"НЕДОСТУПЕН ({e})"


def check_login():
    """Проверка ключей: входим в каждую сеть и показываем аккаунт, ничего не публикуя."""
    ok = True
    for platform, url, fields in (("instagram", f"{IG_API}/me", "user_id,username,account_type"),
                                  ("threads", f"{TH_API}/me", "id,username")):
        token = os.environ.get(PUBLISHERS[platform][0])
        if not token:
            print(f"✗ {platform}: ключ не задан")
            ok = False
            continue
        # только тип ключа, без раскрытия: IGAA… — Instagram Login, TH… — Threads, EAA… — Facebook
        junk = [n for n, bad in (("пробелы/переносы", token != token.strip() or " " in token),
                                 ("кавычки", '"' in token or "'" in token)) if bad]
        print(f"· {platform}: ключ начинается с «{token.strip()[:4]}…», длина {len(token.strip())}"
              + (f", есть {', '.join(junk)}" if junk else ""))
        token = token.strip().strip('"').strip("'")
        try:
            me = call("GET", url, {"fields": fields, "access_token": token})
            print(f"✓ {platform}: вход выполнен — @{me.get('username')} ({me.get('account_type', 'аккаунт')})")
            # лимит публикаций отвечает, только если у ключа есть право публиковать
            if platform == "instagram":
                uid = me.get("user_id") or me["id"]
                lim = call("GET", f"{IG_API}/{uid}/content_publishing_limit",
                           {"fields": "quota_usage,config", "access_token": token})
            else:
                lim = call("GET", f"{TH_API}/me/threads_publishing_limit",
                           {"fields": "quota_usage,config", "access_token": token})
            d = (lim.get("data") or [{}])[0]
            print(f"✓ {platform}: право публикации есть — использовано {d.get('quota_usage', 0)} "
                  f"из {(d.get('config') or {}).get('quota_total', '?')} публикаций за сутки")
        except ApiError as e:
            print(f"✗ {platform}: {e}")
            ok = False
    if os.environ.get("TIKTOK_REFRESH_TOKEN"):
        import tiktok
        try:
            user, scope, token = tiktok.whoami()
            mode = os.environ.get("TIKTOK_MODE") or "inbox"
            print(f"✓ tiktok: вход выполнен — {user.get('display_name')}; режим «{mode}»; разрешения: {scope}")
            if mode == "direct":
                info = tiktok.creator_info(token)
                print(f"✓ tiktok: прямая публикация доступна, видимость: {', '.join(info.get('privacy_level_options', []))}")
        except tiktok.TikTokError as e:
            print(f"✗ tiktok: {e}")
            ok = False
    else:
        print("· tiktok: ещё не подключён")
    sys.exit(0 if ok else 1)


def main():
    if "--check" in sys.argv:
        check_login()
    dry = "--dry-run" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    queue = json.load(open(QUEUE, encoding="utf-8"))
    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    now = datetime.now(ALMATY)
    failed = False

    for item in queue:
        iid = item["id"]
        due = parse_when(item["when"]) <= now
        if only and iid != only:
            continue
        for platform in item["platforms"]:
            st = state.setdefault(iid, {}).setdefault(platform, {})
            if st.get("status") == "ok":
                continue
            if not (due or only):
                if dry:
                    print(f"· {iid} → {platform}: ждёт {item['when']}")
                continue
            if st.get("attempts", 0) >= MAX_ATTEMPTS and not only:
                print(f"✗ {iid} → {platform}: {MAX_ATTEMPTS} неудачных попыток, пропускаю (последняя ошибка: {st.get('error')})")
                continue
            if dry:
                links = ", ".join(f"{m} [{check_url(media_url(m))}]" for m in item.get("media", []))
                print(f"▶ {iid} → {platform}: опубликую сейчас; файлы: {links or 'нет'}")
                continue
            env, fn = PUBLISHERS[platform]
            token = os.environ.get(env)
            if not token:
                print(f"✗ {iid} → {platform}: нет ключа {env}")
                failed = True
                continue
            try:
                mid, link = fn(item, token)
                st.update(status="ok", media_id=mid, permalink=link, at=now.isoformat(timespec="minutes"), error=None)
                print(f"✓ {iid} → {platform}: {link}")
            except Exception as e:  # noqa: BLE001
                st.update(status="error", attempts=st.get("attempts", 0) + 1, error=str(e)[:500],
                          at=now.isoformat(timespec="minutes"))
                print(f"✗ {iid} → {platform}: {e}")
                failed = True

    if not dry:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
