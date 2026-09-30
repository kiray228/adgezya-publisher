"""TikTok Content Posting API: вход по refresh-ключу, загрузка видео файлом (FILE_UPLOAD).

Режимы (переменная TIKTOK_MODE):
  inbox  — видео приходит черновиком во «Входящие» TikTok, владелец публикует его в приложении (работает до проверки TikTok);
  direct — сразу публикация (после проверки приложения TikTok; до проверки — только SELF_ONLY, видно лишь владельцу).
Ключи: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN. Access-ключ живёт сутки — берём новый при каждом запуске.
TikTok может выдать новый refresh-ключ: тогда перезаписываем секрет через gh (нужен GH_TOKEN с правом на секреты).
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://open.tiktokapis.com/v2"
REDIRECT_URI = "https://kiray228.github.io/adgezya-publisher/site/tiktok-callback.html"


class TikTokError(Exception):
    pass


def _req(method, url, *, token=None, form=None, body=None, data=None, headers=None):
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    payload = None
    if form is not None:
        payload = urllib.parse.urlencode(form).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        payload = json.dumps(body).encode()
        h["Content-Type"] = "application/json; charset=UTF-8"
    elif data is not None:
        payload = data
    req = urllib.request.Request(url, data=payload, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        raise TikTokError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}") from None
    res = json.loads(raw) if raw.strip().startswith("{") else {}
    err = res.get("error")
    if isinstance(err, dict) and err.get("code") not in (None, "ok"):
        raise TikTokError(f"{err.get('code')}: {err.get('message')}")
    if isinstance(err, str) and err:
        raise TikTokError(f"{err}: {res.get('error_description')}")
    return res


def _save_secret(name, value):
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not (repo and os.environ.get("GH_TOKEN")):
        print(f"! {name}: нечем сохранить новый ключ (нет GH_TOKEN) — обновите секрет вручную")
        return
    subprocess.run(["gh", "secret", "set", name, "--repo", repo, "--body", value], check=True, capture_output=True)


def exchange_code(code):
    """Одноразовый код со страницы tiktok-callback → refresh-ключ (живёт 365 дней)."""
    res = _req("POST", f"{API}/oauth/token/", form={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"], "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "code": code.strip(), "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI})
    _save_secret("TIKTOK_REFRESH_TOKEN", res["refresh_token"])
    return res


def access_token():
    refresh = os.environ.get("TIKTOK_REFRESH_TOKEN", "").strip()
    if not refresh:
        raise TikTokError("TikTok не подключён: нет TIKTOK_REFRESH_TOKEN")
    res = _req("POST", f"{API}/oauth/token/", form={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"], "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token", "refresh_token": refresh})
    if res.get("refresh_token") and res["refresh_token"] != refresh:
        _save_secret("TIKTOK_REFRESH_TOKEN", res["refresh_token"])
        os.environ["TIKTOK_REFRESH_TOKEN"] = res["refresh_token"]
    return res["access_token"], res.get("scope", "")


def whoami():
    token, scope = access_token()
    me = _req("GET", f"{API}/user/info/?fields=open_id,display_name", token=token)
    return me.get("data", {}).get("user", {}), scope, token


def creator_info(token):
    return _req("POST", f"{API}/post/publish/creator_info/query/", token=token, body={}).get("data", {})


def publish_video(path, caption, mode=None):
    mode = (mode or os.environ.get("TIKTOK_MODE") or "inbox").lower()
    token, _ = access_token()
    size = os.path.getsize(path)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}
    if mode == "direct":
        info = creator_info(token)
        options = info.get("privacy_level_options") or ["SELF_ONLY"]
        privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in options else options[0]
        init = _req("POST", f"{API}/post/publish/video/init/", token=token, body={
            "post_info": {"title": caption[:2200], "privacy_level": privacy,
                          "disable_duet": False, "disable_comment": False, "disable_stitch": False},
            "source_info": source})
    else:
        init = _req("POST", f"{API}/post/publish/inbox/video/init/", token=token, body={"source_info": source})
    data = init["data"]
    with open(path, "rb") as f:
        blob = f.read()
    _req("PUT", data["upload_url"], data=blob,
         headers={"Content-Type": "video/mp4", "Content-Length": str(size), "Content-Range": f"bytes 0-{size - 1}/{size}"})
    pid = data["publish_id"]
    # ждём, пока TikTok примет видео
    t0 = time.time()
    while time.time() - t0 < 600:
        st = _req("POST", f"{API}/post/publish/status/fetch/", token=token, body={"publish_id": pid}).get("data", {})
        status = st.get("status")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            ids = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id") or []
            link = f"https://www.tiktok.com/@{os.environ.get('TIKTOK_USERNAME', 'adgezyakz')}/video/{ids[0]}" if ids else None
            return pid, link or ("черновик во «Входящих» TikTok — откройте и опубликуйте" if status == "SEND_TO_USER_INBOX"
                                  else "опубликовано (ссылка появится после модерации)")
        if status == "FAILED":
            raise TikTokError(f"TikTok отклонил видео: {st.get('fail_reason')}")
        time.sleep(5)
    raise TikTokError("TikTok не подтвердил приём видео за 10 минут")
