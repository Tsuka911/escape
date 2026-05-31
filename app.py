from datetime import date, timedelta
from html import escape

import streamlit as st

from scraper import (
    list_events,
    fetch_schedule,
    get_meta_updated_at,
)

st.set_page_config(
    page_title="リアル脱出ゲーム 名古屋 検索",
    page_icon=":material/vpn_key:",
    layout="wide",
)


# ── 容量チェック ─────────────────────────────────────────────


def capacity_status(stock, unit: str, group_size: int):
    """在庫と参加人数から (状態キー, 表示テキスト) を返す。
    状態キー: ok（余裕あり）/ warn（人数に不足の可能性）/ full（満員）/ unknown（不明）"""
    if stock is None:
        return "unknown", "不明"
    if stock == 0:
        return "full", "満員"
    if unit == "人":
        if stock >= group_size:
            return "ok", f"残り{stock}人"
        return "warn", f"残り{stock}人（{group_size}人には不足）"
    # 「組」単位: 1組として予約するため1以上あればOK
    return "ok", f"残り{stock}組"


# 状態の並び順（良い順）
STATUS_RANK = {"ok": 0, "warn": 1, "full": 2, "unknown": 3}

# タブ2のテーブル内で使う記号（1セルに複数枠が入るため色は付けられない）
STATUS_MARK = {"ok": "○", "warn": "△", "full": "×", "unknown": "－"}

# 空き状況バッジの背景色・文字色
STATUS_STYLE = {
    "ok": "background-color:#DCFCE7; color:#166534;",
    "warn": "background-color:#FEF3C7; color:#92400E;",
    "full": "background-color:#FEE2E2; color:#991B1B;",
    "unknown": "background-color:#F1F5F9; color:#475569;",
}


def weekday_jp(d: date) -> str:
    return "月火水木金土日"[d.weekday()]


# ── 見た目（CSS / ヘッダー）─────────────────────────────────


def inject_css():
    """全体のスタイルとMaterial Symbolsアイコンを読み込む"""
    st.markdown(
        """
        <style>
        html, body, [class*="css"] {
            font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans",
                "Noto Sans JP", sans-serif;
        }
        /* 上部のStreamlitツールバー（Deployメニュー）の帯を背景透明にし、
           その高さ分の余白を確保してタイトルが隠れないようにする */
        [data-testid="stHeader"] {
            background: transparent;
        }
        .block-container {
            padding-top: 4rem;
            padding-bottom: 3rem;
            max-width: 1100px;
        }
        @media (max-width: 640px) {
            .block-container {
                padding-left: 0.8rem;
                padding-right: 0.8rem;
                padding-top: 3.5rem;
            }
        }
        /* カスタムヘッダー */
        .app-header {
            display: flex;
            align-items: center;
            gap: 0.8rem;
            padding: 0.2rem 0 1rem;
            border-bottom: 1px solid #E2E8F0;
            margin-bottom: 1.2rem;
        }
        .app-header .icon {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 48px;
            height: 48px;
            border-radius: 14px;
            background: linear-gradient(135deg, #2563EB, #4F46E5);
            color: #fff;
            flex-shrink: 0;
        }
        .app-header .icon svg { width: 28px; height: 28px; }
        .app-header .title {
            font-size: 1.35rem;
            font-weight: 700;
            color: #0F172A;
            line-height: 1.2;
        }
        .app-header .sub {
            font-size: 0.82rem;
            color: #64748B;
            margin-top: 2px;
        }

        /* ボタンを軽いタグ風に */
        .stButton > button {
            border-radius: 999px;
            padding: 0.2rem 0.85rem;
            font-size: 0.82rem;
            border: 1px solid #CBD5E1;
            background: #fff;
            color: #334155;
        }
        .stButton > button:hover {
            border-color: #2563EB;
            color: #2563EB;
        }

        /* テーブルを少しコンパクトに */
        [data-testid="stDataFrame"] { font-size: 0.9rem; }

        /* ── カード表示 ── */
        .card-grid {
            display: grid;
            gap: 0.8rem;
            margin: 0.4rem 0 1.6rem;
        }
        /* タブ1: 時間枠カード（小さめ） */
        .grid-slots {
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
        }
        /* タブ2: 演目カード（大きめ） */
        .grid-events {
            grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
        }
        .slot-card, .event-card {
            border: 1px solid #E2E8F0;
            border-radius: 14px;
            background: #fff;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
            display: flex;
            flex-direction: column;
            transition: box-shadow 0.15s ease, transform 0.15s ease;
        }
        .slot-card:hover, .event-card:hover {
            box-shadow: 0 6px 16px rgba(15, 23, 42, 0.10);
            transform: translateY(-2px);
        }
        .slot-card {
            padding: 0.85rem 1rem;
            gap: 0.55rem;
        }
        .slot-card .slot-time {
            font-size: 1.2rem;
            font-weight: 700;
            color: #0F172A;
        }
        .event-card {
            padding: 1rem 1.1rem;
            gap: 0.65rem;
        }
        .event-card .event-name {
            font-size: 1.02rem;
            font-weight: 700;
            color: #0F172A;
            line-height: 1.4;
        }
        .event-card .event-meta {
            font-size: 0.8rem;
            color: #64748B;
        }
        /* 空き状況バッジ（カード内） */
        .badge {
            display: inline-block;
            width: fit-content;
            padding: 0.25rem 0.65rem;
            border-radius: 999px;
            font-size: 0.83rem;
            font-weight: 600;
        }
        /* 時間帯チップ群（タブ2） */
        .slot-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
        }
        .chip {
            display: inline-block;
            padding: 0.22rem 0.55rem;
            border-radius: 8px;
            font-size: 0.79rem;
            font-weight: 600;
        }
        /* 予約ボタン（カード内リンク） */
        .book-btn {
            display: block;
            text-align: center;
            margin-top: auto;
            padding: 0.5rem 0.8rem;
            border-radius: 10px;
            background: linear-gradient(135deg, #2563EB, #4F46E5);
            color: #fff !important;
            font-size: 0.85rem;
            font-weight: 600;
            text-decoration: none;
        }
        .book-btn:hover { opacity: 0.92; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header():
    """アプリ上部のタイトルヘッダー"""
    st.markdown(
        """
        <div class="app-header">
          <div class="icon"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12.65 10C11.83 7.67 9.61 6 7 6c-3.31 0-6 2.69-6 6s2.69 6 6 6c2.61 0 4.83-1.67 5.65-4H17v4h4v-4h2v-4H12.65zM7 14c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg></div>
          <div>
            <div class="title">リアル脱出ゲーム 名古屋</div>
            <div class="sub">チケット空き状況チェッカー</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── キャッシュラッパー ───────────────────────────────────────


@st.cache_data(ttl=7200, show_spinner=False)
def get_event_list():
    return list_events()


@st.cache_data(ttl=7200, show_spinner=False)
def get_schedule(start_iso, end_iso, weekend_only):
    return fetch_schedule(
        date.fromisoformat(start_iso),
        date.fromisoformat(end_iso),
        weekend_only,
    )


# ── UI ──────────────────────────────────────────────────────


def main():
    inject_css()
    render_header()

    with st.sidebar:
        st.subheader(":material/tune: 設定")
        group_size = st.number_input(
            "参加予定人数", min_value=1, max_value=20, value=4, step=1
        )
        hide_full = st.checkbox("満員の枠を非表示", value=True)

        st.markdown("---")
        updated = get_meta_updated_at()
        if updated:
            st.caption(f"演目情報の最終更新: {updated}")
        st.caption("空き状況は2時間キャッシュされます")
        if st.button("データを今すぐ更新", icon=":material/refresh:"):
            st.cache_data.clear()
            st.rerun()

    tab1, tab2 = st.tabs(
        [":material/theater_comedy: 演目から探す", ":material/calendar_month: 日付から探す"]
    )

    # ── タブ1: 演目から探す ──────────────────────────────────
    with tab1:
        render_tab_event(group_size, hide_full)

    # ── タブ2: 日付から探す ──────────────────────────────────
    with tab2:
        render_tab_date(group_size, hide_full)


def render_tab_event(group_size, hide_full):
    with st.spinner("演目一覧を読み込み中..."):
        try:
            events = get_event_list()
        except Exception as e:
            st.error(f"演目一覧の取得に失敗しました: {e}")
            return

    if not events:
        st.warning("演目が見つかりませんでした。")
        return

    def fmt(e):
        parts = [e["event_name"]]
        extra = []
        if e.get("type"):
            extra.append(e["type"])
        if e.get("max_team_size"):
            extra.append(f"最大{e['max_team_size']}人")
        if extra:
            parts.append("（" + " / ".join(extra) + "）")
        return "".join(parts)

    idx = st.selectbox(
        "演目を選ぶ", range(len(events)), format_func=lambda i: fmt(events[i]), key="ev_sel"
    )
    ev = events[idx]
    unit = ev["order_unit"]

    today = date.today()
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        start_d = st.date_input("期間（開始）", value=today, key="t1_s")
    with c2:
        end_d = st.date_input("期間（終了）", value=today + timedelta(days=60), key="t1_e")
    with c3:
        weekend_only = st.checkbox("土日のみ表示", value=True, key="t1_we")

    if start_d > end_d:
        st.warning("開始日が終了日より後になっています。")
        return

    info = []
    if ev.get("type"):
        info.append(f"種別: **{ev['type']}**")
    if ev.get("max_team_size"):
        info.append(f"1チーム最大: **{ev['max_team_size']}人**")
    info.append(f"残数単位: **{unit}**")
    st.caption("　".join(info))

    with st.spinner(f"「{ev['event_name']}」の空き状況を確認中..."):
        try:
            rows = get_schedule(start_d.isoformat(), end_d.isoformat(), weekend_only)
        except Exception as e:
            st.error(f"データ取得に失敗しました: {e}")
            return

    # 選択した演目の行だけ抽出
    target = [r for r in rows if r["event_name"] == ev["event_name"]]

    table_rows = []
    for r in target:
        d = date.fromisoformat(r["date"])
        for s in r["slots"]:
            if hide_full and (s["stock"] == 0):
                continue
            status, text = capacity_status(s["stock"], unit, group_size)
            table_rows.append(
                {
                    "日付": f"{d.month}/{d.day}({r['weekday']})",
                    "時刻": s["time"],
                    "空き状況": text,
                    "予約": s.get("ticket_url") or "",
                    "_d": d,
                    "_status": status,
                }
            )

    if not table_rows:
        st.info("指定期間内に表示できる空き枠が見つかりませんでした。期間を広げるか「土日のみ」を外してみてください。")
        return

    table_rows.sort(key=lambda x: (x["_d"], x["時刻"]))

    # 日付ごとにグループ化し、時間枠をカードで表示
    by_day = {}
    for row in table_rows:
        by_day.setdefault(row["日付"], []).append(row)

    for day_label, items in by_day.items():
        st.markdown(f"#### {day_label}")
        cards = []
        for it in items:
            badge_style = STATUS_STYLE.get(it["_status"], "")
            url = it["予約"]
            btn = (
                f'<a class="book-btn" href="{escape(url)}" target="_blank">予約ページ</a>'
                if url
                else ""
            )
            cards.append(
                '<div class="slot-card">'
                f'<div class="slot-time">{escape(it["時刻"])}</div>'
                f'<span class="badge" style="{badge_style}">{escape(it["空き状況"])}</span>'
                f"{btn}"
                "</div>"
            )
        st.markdown(
            f'<div class="card-grid grid-slots">{"".join(cards)}</div>',
            unsafe_allow_html=True,
        )
    st.caption(f"{len(table_rows)} 件表示")


def render_tab_date(group_size, hide_full):
    today = date.today()

    def next_sat(offset_weeks: int = 0) -> date:
        days = (5 - today.weekday()) % 7
        return today + timedelta(days=days + offset_weeks * 7)

    # containerで表示位置を先に確保し、日付欄が上・クイック選択が下になるよう制御
    date_row = st.container()
    quick_row = st.container()

    # ボタン処理はwidget生成より前に実行する必要があるため quick_row を先に書く
    with quick_row:
        st.caption("クイック選択（土曜日をセット）")
        lb_s, b_s1, b_s2, b_s3, _sp, lb_e, b_e1, b_e2, b_e3 = st.columns(
            [0.8, 1, 1, 1.1, 0.4, 0.8, 1, 1, 1.1]
        )
        with lb_s:
            st.caption("開始日")
        with b_s1:
            if st.button("今週土", key="qs_s1"):
                st.session_state["t2_s"] = next_sat(0)
        with b_s2:
            if st.button("来週土", key="qs_s2"):
                st.session_state["t2_s"] = next_sat(1)
        with b_s3:
            if st.button("再来週土", key="qs_s3"):
                st.session_state["t2_s"] = next_sat(2)
        with lb_e:
            st.caption("終了日")
        with b_e1:
            if st.button("今週土", key="qs_e1"):
                st.session_state["t2_e"] = next_sat(0)
        with b_e2:
            if st.button("来週土", key="qs_e2"):
                st.session_state["t2_e"] = next_sat(1)
        with b_e3:
            if st.button("再来週土", key="qs_e3"):
                st.session_state["t2_e"] = next_sat(2)

    with date_row:
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            start_d = st.date_input("期間（開始）", value=today, key="t2_s")
        with c2:
            end_d = st.date_input("期間（終了）", value=today + timedelta(days=30), key="t2_e")
        with c3:
            weekend_only = st.checkbox("土日のみ表示", value=True, key="t2_we")

    if start_d > end_d:
        st.warning("開始日が終了日より後になっています。")
        return

    st.markdown("---")
    st.caption(
        "各演目の空いている時間帯をすべて表示します。"
        "○=参加人数OK / △=人数に対し残席不足の可能性 / ×=満員"
    )

    with st.spinner("空き状況を確認中..."):
        try:
            rows = get_schedule(start_d.isoformat(), end_d.isoformat(), weekend_only)
        except Exception as e:
            st.error(f"データ取得に失敗しました: {e}")
            return

    # 日付ごとにグループ化
    by_date = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)

    if not by_date:
        st.info("指定期間内に空き枠のある演目が見つかりませんでした。")
        return

    for date_str in sorted(by_date.keys()):
        day_rows = by_date[date_str]
        d = date.fromisoformat(date_str)

        # 演目ごとに、表示するスロットを整形
        rendered = []
        for r in day_rows:
            unit = r["order_unit"]
            slots_info = []
            ranks = []
            for s in r["slots"]:
                status, _text = capacity_status(s["stock"], unit, group_size)
                ranks.append(STATUS_RANK[status])
                if hide_full and (s["stock"] == 0):
                    continue
                # 記号 + 時刻 + 残数（○=余裕 △=不足の可能性 ×=満員）
                mark = STATUS_MARK[status]
                stock_str = "満" if s["stock"] == 0 else f"{s['stock']}{unit}"
                slots_info.append(
                    {"label": f"{mark} {s['time']}（{stock_str}）", "status": status}
                )

            if not slots_info:
                continue

            best_rank = min(ranks) if ranks else 3
            meta_parts = []
            if r["type"]:
                meta_parts.append(r["type"])
            if r["max_team_size"]:
                meta_parts.append(f"最大{r['max_team_size']}人")
            rendered.append(
                {
                    "event_name": r["event_name"],
                    "meta": " ・ ".join(meta_parts),
                    "slots": slots_info,
                    "url": r.get("tickets_url") or "",
                    "_rank": best_rank,
                }
            )

        if not rendered:
            continue

        rendered.sort(key=lambda x: x["_rank"])
        st.subheader(f"{d.month}/{d.day}（{weekday_jp(d)}）")
        cards = []
        for it in rendered:
            chips = "".join(
                f'<span class="chip" style="{STATUS_STYLE.get(si["status"], "")}">'
                f'{escape(si["label"])}</span>'
                for si in it["slots"]
            )
            meta_html = (
                f'<div class="event-meta">{escape(it["meta"])}</div>'
                if it["meta"]
                else ""
            )
            btn = (
                f'<a class="book-btn" href="{escape(it["url"])}" target="_blank">'
                "予約ページ</a>"
                if it["url"]
                else ""
            )
            cards.append(
                '<div class="event-card">'
                f'<div class="event-name">{escape(it["event_name"])}</div>'
                f"{meta_html}"
                f'<div class="slot-chips">{chips}</div>'
                f"{btn}"
                "</div>"
            )
        st.markdown(
            f'<div class="card-grid grid-events">{"".join(cards)}</div>',
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    main()
