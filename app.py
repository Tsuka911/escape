from datetime import date, timedelta

import pandas as pd
import streamlit as st

from scraper import (
    list_events,
    fetch_schedule,
    get_meta_updated_at,
)

st.set_page_config(
    page_title="リアル脱出ゲーム 名古屋 検索",
    page_icon="🔍",
    layout="wide",
)


# ── 容量チェック ─────────────────────────────────────────────


def capacity_label(stock, unit: str, group_size: int) -> str:
    """在庫と参加人数から判定ラベルを返す"""
    if stock is None:
        return "？ 不明"
    if stock == 0:
        return "❌ 満員"
    if unit == "人":
        if stock >= group_size:
            return f"✅ 残り{stock}人"
        else:
            return f"⚠️ 残り{stock}人（{group_size}人には不足）"
    else:
        # 「組」単位: 1組として予約するため1以上あればOK
        return f"✅ 残り{stock}組"


def capacity_rank(label: str) -> int:
    if label.startswith("✅"):
        return 0
    if label.startswith("⚠️"):
        return 1
    if label.startswith("❌"):
        return 2
    return 3


def best_slot_label(slots, unit, group_size):
    """その演目のスロット群から最良の状況ラベルを返す"""
    best = max(slots, key=lambda s: (s["stock"] or 0))
    return capacity_label(best["stock"], unit, group_size)


def weekday_jp(d: date) -> str:
    return "月火水木金土日"[d.weekday()]


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
    st.title("🎮 リアル脱出ゲーム 名古屋 チケット検索")

    with st.sidebar:
        st.header("設定")
        group_size = st.number_input(
            "参加予定人数", min_value=1, max_value=20, value=4, step=1
        )
        hide_full = st.checkbox("満員の枠を非表示", value=True)

        st.markdown("---")
        updated = get_meta_updated_at()
        if updated:
            st.caption(f"演目情報の最終更新: {updated}")
        st.caption("空き状況は2時間キャッシュされます")
        if st.button("🔄 データを今すぐ更新"):
            st.cache_data.clear()
            st.rerun()

    tab1, tab2 = st.tabs(["🎭 演目から探す", "📅 日付から探す"])

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
            label = capacity_label(s["stock"], unit, group_size)
            table_rows.append(
                {
                    "日付": f"{d.month}/{d.day}({r['weekday']})",
                    "時刻": s["time"],
                    "空き状況": label,
                    "予約": s.get("ticket_url") or "",
                    "_d": d,
                }
            )

    if not table_rows:
        st.info("指定期間内に表示できる空き枠が見つかりませんでした。期間を広げるか「土日のみ」を外してみてください。")
        return

    table_rows.sort(key=lambda x: (x["_d"], x["時刻"]))
    df = pd.DataFrame(table_rows)[["日付", "時刻", "空き状況", "予約"]]
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "予約": st.column_config.LinkColumn("予約リンク", display_text="予約ページ"),
        },
    )
    st.caption(f"{len(df)} 件表示")


def render_tab_date(group_size, hide_full):
    today = date.today()
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        start_d = st.date_input("期間（開始）", value=today, key="t2_s")
    with c2:
        end_d = st.date_input("期間（終了）", value=today + timedelta(days=30), key="t2_e")
    with c3:
        weekend_only = st.checkbox("土日のみ表示", value=True, key="t2_we")

    q1, q2, q3 = st.columns(3)
    with q1:
        if st.button("今週末"):
            sat = today + timedelta(days=(5 - today.weekday()) % 7)
            st.session_state["t2_s"] = sat
            st.session_state["t2_e"] = sat + timedelta(days=1)
            st.rerun()
    with q2:
        if st.button("来週末"):
            sat = today + timedelta(days=(5 - today.weekday()) % 7 + 7)
            st.session_state["t2_s"] = sat
            st.session_state["t2_e"] = sat + timedelta(days=1)
            st.rerun()
    with q3:
        if st.button("今月の土日"):
            first = today.replace(day=1)
            if today.month == 12:
                last = date(today.year + 1, 1, 1) - timedelta(days=1)
            else:
                last = date(today.year, today.month + 1, 1) - timedelta(days=1)
            st.session_state["t2_s"] = first
            st.session_state["t2_e"] = last
            st.rerun()

    if start_d > end_d:
        st.warning("開始日が終了日より後になっています。")
        return

    st.markdown("---")
    st.caption(
        "各演目の空いている時間帯をすべて表示します。"
        "✅=参加人数OK / ⚠️=人数に対し残席不足の可能性 / ❌=満員"
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
            slot_labels = []
            for s in r["slots"]:
                if hide_full and (s["stock"] == 0):
                    continue
                label = capacity_label(s["stock"], unit, group_size)
                # 時刻 + 状況（簡潔に）
                if label.startswith("✅"):
                    mark = "✅"
                elif label.startswith("⚠️"):
                    mark = "⚠️"
                elif label.startswith("❌"):
                    mark = "❌"
                else:
                    mark = "？"
                stock_str = "満" if s["stock"] == 0 else f"{s['stock']}{unit}"
                slot_labels.append(f"{mark}{s['time']}({stock_str})")

            if not slot_labels:
                continue

            best_rank = min(
                capacity_rank(capacity_label(s["stock"], unit, group_size))
                for s in r["slots"]
            )
            type_str = r["type"] or "－"
            size_str = f"{r['max_team_size']}人" if r["max_team_size"] else "－"
            rendered.append(
                {
                    "演目": r["event_name"],
                    "種別": type_str,
                    "最大人数": size_str,
                    "空き時間帯": "　".join(slot_labels),
                    "予約": r.get("tickets_url") or "",
                    "_rank": best_rank,
                }
            )

        if not rendered:
            continue

        rendered.sort(key=lambda x: x["_rank"])
        st.subheader(f"{d.month}/{d.day}（{weekday_jp(d)}）")
        df = pd.DataFrame(rendered)[["演目", "種別", "最大人数", "空き時間帯", "予約"]]
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "予約": st.column_config.LinkColumn("予約", display_text="一覧"),
            },
        )


if __name__ == "__main__":
    main()
