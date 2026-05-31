import re
import json
import os
from datetime import datetime, date, timedelta, timezone

JST = timezone(timedelta(hours=9))
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "data", "cache.json")
CACHE_HOURS_META = 24
CACHE_HOURS_TICKETS = 2

NAGOYA_EVENTS_URL = "https://realdgame.jp/shop/nagoya/events/"
TICKETS_API = "https://api.scrapmagazine.com/public/api/1/tickets"
PLACE_NAME = "リアル脱出ゲーム名古屋店"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ── キャッシュ操作 ──────────────────────────────────────────


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(data: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clear_cache() -> None:
    """スクレイピング・APIのキャッシュファイルを削除して、次回取得を強制する。
    「データを今すぐ更新」ボタンから呼ばれる。"""
    try:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
    except Exception:
        pass


def _is_valid(cache: dict, key: str, hours: float) -> bool:
    ts = cache.get(f"{key}_updated_at")
    if not ts:
        return False
    try:
        return (datetime.now(JST) - datetime.fromisoformat(ts)).total_seconds() < hours * 3600
    except TypeError:
        return False


# ── 演目メタ情報（一覧ページHTMLから）───────────────────────


def normalize_title(title: str) -> str:
    """突合用にタイトルを正規化（【...】除去・記号統一・空白除去）"""
    t = re.sub(r"^【[^】]*】", "", title)
    t = t.replace("『", "「").replace("』", "」")
    t = re.sub(r"[\s　]+", "", t)
    return t.strip()


def fetch_event_meta(force: bool = False) -> dict:
    """
    一覧ページHTMLから演目メタ情報を取得。
    戻り値: {
        "by_url": {event_url: meta},
        "by_title": {normalized_title: meta},
    }
    meta = {title, type, start_type, max_team_size, is_anytime}
    """
    cache = load_cache()
    if not force and _is_valid(cache, "meta", CACHE_HOURS_META):
        return cache["meta"]

    resp = _get(NAGOYA_EVENTS_URL)
    soup = BeautifulSoup(resp.text, "html.parser")

    by_url = {}
    by_title = {}

    for ul in soup.find_all("ul", class_=["list02", "list04"]):
        for li in ul.find_all("li"):
            a = li.find("a", href=True)
            if not a:
                continue
            href = a["href"]

            tit_el = a.find("p", class_="tit")
            title_raw = tit_el.get_text(strip=True) if tit_el else ""
            if not title_raw:
                img = a.find("img")
                title_raw = img["alt"].strip() if img and img.get("alt") else ""
            if not title_raw:
                continue

            # 種別（icon_period内の<strong>）
            event_type = None
            period = a.find("p", class_="icon_period")
            if period:
                strong = period.find("strong")
                if strong:
                    s = strong.get_text(strip=True)
                    if "ホール" in s:
                        event_type = "ホール型"
                    elif "ルーム" in s:
                        event_type = "ルーム型"

            # スタート方式
            start_el = a.find("p", class_="icon_start")
            start_text = start_el.get_text(strip=True) if start_el else ""
            is_anytime = "随時" in start_text

            # チーム人数（最大値）
            max_team_size = None
            people_el = a.find("p", class_="icon_people")
            if people_el:
                nums = re.findall(r"\d+", people_el.get_text(strip=True))
                if nums:
                    max_team_size = int(nums[-1])

            meta = {
                "title": re.sub(r"^【[^】]*】\s*", "", title_raw).strip(),
                "type": event_type,
                "start_type": start_text,
                "max_team_size": max_team_size,
                "is_anytime": is_anytime,
            }
            by_url[href] = meta
            by_title[normalize_title(title_raw)] = meta

    result = {"by_url": by_url, "by_title": by_title}
    cache["meta"] = result
    cache["meta_updated_at"] = datetime.now(JST).isoformat()
    save_cache(cache)
    return result


# 検索対象から外す演目（タイトルに含まれていたら除外するキーワード）
EXCLUDE_TITLE_KEYWORDS = ("街歩き",)


def is_excluded_title(event_name: str) -> bool:
    """演目名に除外キーワード（街歩き 等）が含まれていればTrue"""
    return any(kw in (event_name or "") for kw in EXCLUDE_TITLE_KEYWORDS)


def _lookup_meta(meta_index: dict, event_url: str, event_name: str) -> Optional[dict]:
    """APIの演目を一覧メタと突合（URL優先、タイトルでフォールバック）"""
    if event_url in meta_index["by_url"]:
        return meta_index["by_url"][event_url]
    norm = normalize_title(event_name)
    if norm in meta_index["by_title"]:
        return meta_index["by_title"][norm]
    return None


# ── チケット情報（公式API）──────────────────────────────────


def fetch_tickets_for_date(date_str: str, force: bool = False) -> list:
    """
    指定日(YYYY-MM-DD)の全演目チケット情報をAPIから取得。
    結果は2時間キャッシュ（日付単位）。
    戻り値: APIの events 配列（各演目に tickets リスト付き）
    """
    cache = load_cache()
    key = f"tickets_{date_str}"
    if not force and _is_valid(cache, key, CACHE_HOURS_TICKETS):
        return cache.get(key, [])

    events = []
    page = 1
    while True:
        params = {
            "date": date_str,
            "per": 30,
            "page": page,
            "place_name": PLACE_NAME,
            "lang": "ja",
        }
        try:
            resp = requests.get(TICKETS_API, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        events.extend(data.get("events", []))
        last_page = data.get("last_page", 1)
        if page >= last_page:
            break
        page += 1

    cache[key] = events
    cache[f"{key}_updated_at"] = datetime.now(JST).isoformat()
    save_cache(cache)
    return events


# ── 期間スケジュールの取得（メタ統合済み）──────────────────


def iter_target_dates(start: date, end: date, weekend_only: bool):
    cur = start
    while cur <= end:
        if not weekend_only or cur.weekday() >= 5:
            yield cur
        cur += timedelta(days=1)


def fetch_schedule(
    start: date,
    end: date,
    weekend_only: bool,
    exclude_anytime: bool = True,
    force: bool = False,
    progress_callback=None,
) -> list:
    """
    期間内の対象日について全演目のチケット情報を取得し、メタ情報とマージ。
    随時スタートは exclude_anytime=True のとき除外。

    戻り値: [
        {
            "date": "2026-06-07", "weekday": "土",
            "event_name": str, "event_url": str, "tickets_url": str,
            "type": "ホール型"/"ルーム型"/None,
            "max_team_size": int/None,
            "order_unit": "人"/"組",
            "slots": [{"time": "14:00", "stock": int, "status": "○",
                       "ticket_url": str}, ...],
        }, ...
    ]
    """
    meta_index = fetch_event_meta(force=force)
    target_dates = list(iter_target_dates(start, end, weekend_only))

    rows = []
    for i, d in enumerate(target_dates):
        if progress_callback:
            progress_callback(i, len(target_dates), d.isoformat())

        date_str = d.isoformat()
        events = fetch_tickets_for_date(date_str, force=force)
        weekday = "月火水木金土日"[d.weekday()]

        for ev in events:
            # タイトルに除外キーワード（街歩き 等）を含む演目はスキップ
            if is_excluded_title(ev.get("event_name", "")):
                continue

            meta = _lookup_meta(meta_index, ev.get("event_url", ""), ev.get("event_name", ""))

            # 随時スタートの除外（メタで判定できた場合のみ）
            if exclude_anytime and meta and meta.get("is_anytime"):
                continue

            # その日のスロットを整形
            slots = []
            for t in ev.get("tickets", []):
                starts_at = t.get("starts_at", "")
                # ISO形式 "2026-06-07T14:00:00..." から日付・時刻を取り出す
                if not starts_at.startswith(date_str):
                    continue
                time_str = starts_at[11:16]  # HH:MM
                slots.append(
                    {
                        "time": time_str,
                        "stock": t.get("stock"),
                        "status": t.get("status"),
                        "ticket_url": t.get("ticket_url"),
                    }
                )

            if not slots:
                continue

            slots.sort(key=lambda s: s["time"])

            rows.append(
                {
                    "date": date_str,
                    "weekday": weekday,
                    "event_name": re.sub(r"^【[^】]*】\s*", "", ev.get("event_name", "")).strip(),
                    "event_url": ev.get("event_url"),
                    "tickets_url": ev.get("tickets_url"),
                    "type": meta.get("type") if meta else None,
                    "max_team_size": meta.get("max_team_size") if meta else None,
                    "order_unit": ev.get("order_unit", "組"),
                    "slots": slots,
                }
            )

    return rows


def list_events(exclude_anytime: bool = True, force: bool = False) -> list:
    """
    演目選択用の一覧を返す。直近1ヶ月のAPIから演目名を集め、メタとマージ。
    戻り値: [{event_name, event_url, type, max_team_size, order_unit}]
    """
    meta_index = fetch_event_meta(force=force)
    today = date.today()

    # 直近の数日分のAPIを叩いて出現する全演目を収集
    seen = {}
    for offset in (0, 7, 14, 30, 45):
        d = today + timedelta(days=offset)
        events = fetch_tickets_for_date(d.isoformat(), force=force)
        for ev in events:
            name = ev.get("event_name", "")
            if name in seen:
                continue
            # タイトルに除外キーワード（街歩き 等）を含む演目はスキップ
            if is_excluded_title(name):
                continue
            meta = _lookup_meta(meta_index, ev.get("event_url", ""), name)
            if exclude_anytime and meta and meta.get("is_anytime"):
                continue
            seen[name] = {
                "event_name": re.sub(r"^【[^】]*】\s*", "", name).strip(),
                "raw_name": name,
                "event_url": ev.get("event_url"),
                "tickets_url": ev.get("tickets_url"),
                "type": meta.get("type") if meta else None,
                "max_team_size": meta.get("max_team_size") if meta else None,
                "order_unit": ev.get("order_unit", "組"),
            }

    return sorted(seen.values(), key=lambda e: e["event_name"])


# ── 最終更新時刻 ────────────────────────────────────────────


def get_meta_updated_at() -> Optional[str]:
    cache = load_cache()
    ts = cache.get("meta_updated_at")
    if ts:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
    return None


# ── HTTP ヘルパー ───────────────────────────────────────────


def _get(url: str) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp
