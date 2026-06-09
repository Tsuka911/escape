"""
静的サイト用のカタログJSON（docs/data/catalog.json）を生成するビルドスクリプト。

GitHub Actions から週1回（＋手動）実行される。やることは1つだけ：

  ブラウザから直接は取れない「演目メタ情報」（種別・最大人数・随時スタート判定）を
  公式サイト realdgame.jp からスクレイプして、演目シード一覧とともにJSONへ焼き出す。

空き状況そのものは静的サイト側がブラウザから公式APIを直接ライブ取得するため、
このスクリプトでは取得しない（だからCIの負荷はごく軽い）。
"""

import json
import os
from datetime import datetime, timezone, timedelta

from scraper import fetch_event_meta, list_events

JST = timezone(timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE_DIR, "docs", "data", "catalog.json")


def build() -> dict:
    """カタログJSONの中身を組み立てて返す。"""
    # force=True で必ず最新を取りに行く（CIにはキャッシュが無いが、ローカル実行でも確実に更新する）
    meta = fetch_event_meta(force=True)
    events = list_events(force=True)

    return {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "events": events,                 # 演目ピッカーの即時表示用シード一覧
        "meta_by_url": meta["by_url"],    # ライブ取得した演目にメタを突合するための索引
        "meta_by_title": meta["by_title"],
    }


def main() -> None:
    data = build()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"書き出し完了: {OUT_PATH}")
    print(f"  演目数: {len(data['events'])}")
    print(f"  メタ(URL索引): {len(data['meta_by_url'])} 件")
    print(f"  更新時刻: {data['updated_at']}")


if __name__ == "__main__":
    main()
