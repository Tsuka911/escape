import json
from datetime import date, timedelta
from html import escape
from pathlib import Path

from PIL import Image as PILImage
import streamlit as st

from scraper import (
    list_events,
    fetch_schedule,
    get_meta_updated_at,
    clear_cache,
)

# ユーザー設定（除外演目など）の保存先
SETTINGS_PATH = Path(__file__).parent / "data" / "user_settings.json"


def load_excluded_events() -> list:
    """除外する演目名のリストをファイルから読み込む（無ければ空リスト）"""
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return list(data.get("excluded_events", []))
    except Exception:
        return []


def save_excluded_events(names: list) -> None:
    """除外する演目名のリストをファイルに保存する"""
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps({"excluded_events": names}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        st.warning(f"除外設定の保存に失敗しました: {e}")

_icon = PILImage.open(Path(__file__).parent / "icon.png")
st.set_page_config(
    page_title="リアル脱出ゲーム 名古屋 検索",
    page_icon=_icon,
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
        return "warn", f"残り{stock}人"
    # 「組」単位: 1組として予約するため1以上あればOK
    return "ok", f"残り{stock}組"


# 状態の並び順（良い順）
STATUS_RANK = {"ok": 0, "warn": 1, "full": 2, "unknown": 3}

# タブ2のテーブル内で使う記号（1セルに複数枠が入るため色は付けられない）
STATUS_MARK = {"ok": "○", "warn": "△", "full": "×", "unknown": "－"}

# 空き状況バッジの背景色・文字色（A:クリーン トーン）
STATUS_STYLE = {
    "ok": "background-color:#E6F6EC; color:#1D8A4E;",
    "warn": "background-color:#FDF1DE; color:#B9740F;",
    "full": "background-color:#FDEAEA; color:#CC3B3B;",
    "unknown": "background-color:#EEF2F7; color:#8A94A3;",
}

# 予約ボタン内の外部リンク矢印（絵文字不使用・SVGで統一）
BOOK_ARROW = (
    '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" '
    'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
    'stroke-linejoin="round" style="margin-left:5px">'
    '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7'
    'a1 1 0 0 1 1-1h5"/></svg>'
)


def weekday_jp(d: date) -> str:
    return "月火水木金土日"[d.weekday()]


def day_head_html(d: date, right_text: str) -> str:
    """日付見出し（曜日カラー + 罫線 + 右側ヒント）。タブ1/2共通。"""
    wd = weekday_jp(d)
    color = "#2F6FED" if wd == "土" else "#D8453D" if wd == "日" else "#1A2230"
    return (
        '<div class="day-head">'
        f'<span class="day-date">{d.month}/{d.day}'
        f'<span style="color:{color};font-weight:700">（{wd}）</span></span>'
        '<span class="day-rule"></span>'
        f'<span class="day-count">{escape(right_text)}</span>'
        "</div>"
    )


# ── 見た目（CSS / ヘッダー）─────────────────────────────────


def inject_css():
    """全体のスタイルとMaterial Symbolsアイコンを読み込む（A:クリーン トーン）"""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@400;500;700;900&display=swap');
        :root {
            --accent: #2F6FED;
            --accent-strong: #2862D8;
            --text: #1A2230;
            --text-sub: #5A6678;
            --text-faint: #909AAB;
            --border: #E7EBF1;
            --border-soft: #E3E8EF;
            --chip: #EEF2F7;
            --card-shadow: 0 1px 2px rgba(20,40,80,0.05), 0 4px 14px rgba(20,40,80,0.04);
            --app-font: "Zen Kaku Gothic New", -apple-system, BlinkMacSystemFont,
                "Hiragino Sans", "Noto Sans JP", sans-serif;
        }
        /* アプリ全体に Zen Kaku Gothic New を適用（Streamlit生成要素も対象） */
        html, body, [class*="css"],
        [data-testid="stSidebar"], [data-testid="stAppViewContainer"],
        button, input, select, textarea {
            font-family: var(--app-font);
        }
        /* st.markdown で描いたカスタムHTML（日付見出し・時刻・演目名・チップ等）にだけ
           明示指定。Streamlit既定フォント(Source Sans)を上書きする。
           ※ 全要素(*)には当てない。Material Symbolsアイコン用フォントまで
              上書きしてしまい、アイコンが文字名で表示されるのを防ぐため。 */
        .app-header, .app-header .title, .app-header .sub,
        .day-head, .day-date, .day-count,
        .slot-card, .slot-time, .event-card, .event-name, .event-meta,
        .badge, .chip, .meta-row, .meta-chip,
        .excl-banner, .excl-banner-label, .excl-chip, .book-btn {
            font-family: var(--app-font) !important;
        }
        /* 上部のStreamlitツールバー（Deployメニュー）の帯を背景透明にし、
           その高さ分の余白を確保してタイトルが隠れないようにする */
        [data-testid="stHeader"] {
            background: transparent;
        }
        /* ── メイン背景色（A:クリーン の page=#F5F7FA / サイドバー=#FBFCFE）── */
        [data-testid="stAppViewContainer"], .stApp, [data-testid="stMain"] {
            background: #F5F7FA;
        }
        [data-testid="stSidebar"] {
            background: #FBFCFE;
            border-right: 1px solid var(--border);
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
            gap: 0.85rem;
            padding: 0.2rem 0 1rem;
            border-bottom: 1px solid var(--border);
            margin-bottom: 1.3rem;
        }
        .app-header .icon {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 46px;
            height: 46px;
            border-radius: 12px;
            background: linear-gradient(150deg, #3B7BF4, #2F6FED);
            color: #fff;
            flex-shrink: 0;
            box-shadow: 0 1px 2px rgba(47,111,237,0.25);
        }
        .app-header .icon svg { width: 26px; height: 26px; }
        .app-header .title {
            font-size: 1.38rem;
            font-weight: 800;
            color: var(--text);
            line-height: 1.18;
            letter-spacing: -0.01em;
            white-space: nowrap;
        }
        .app-header .sub {
            font-size: 0.83rem;
            color: var(--text-sub);
            font-weight: 600;
            margin-top: 3px;
        }

        /* ── サイドバーをモック（A:クリーン）風に寄せる ── */
        /* 見出し「設定」 */
        [data-testid="stSidebar"] [data-testid="stSubheader"],
        [data-testid="stSidebar"] h3 {
            font-weight: 800;
            color: var(--text);
            letter-spacing: -0.01em;
        }
        /* 入力ラベル */
        [data-testid="stSidebar"] label p {
            font-weight: 600;
            color: var(--text-sub);
            font-size: 0.8rem;
        }
        /* 数値入力（参加人数）— 枠とステッパーをカード風に */
        [data-testid="stSidebar"] [data-testid="stNumberInput"] > div > div {
            border-radius: 9px;
            border: 1px solid var(--border-soft);
            background: #fff;
            overflow: hidden;
        }
        [data-testid="stSidebar"] [data-testid="stNumberInput"] input {
            font-weight: 800;
            font-size: 1.05rem;
            color: var(--text);
        }
        /* ＋／− ステッパーボタンをアクセント寄りに */
        [data-testid="stSidebar"] [data-testid="stNumberInputStepUp"],
        [data-testid="stSidebar"] [data-testid="stNumberInputStepDown"] {
            color: var(--accent);
        }
        [data-testid="stSidebar"] [data-testid="stNumberInputStepUp"]:hover,
        [data-testid="stSidebar"] [data-testid="stNumberInputStepDown"]:hover {
            background: var(--chip);
        }
        /* チェックボックス（満員の枠を非表示）チェック時アクセント */
        [data-testid="stSidebar"] [data-baseweb="checkbox"] [data-checked="true"] {
            background-color: var(--accent) !important;
            border-color: var(--accent) !important;
        }
        /* ポップオーバー起動ボタン（演目を選ぶ）をフィールド風の白枠に */
        [data-testid="stSidebar"] [data-testid="stPopover"] > div > button {
            width: 100%;
            justify-content: space-between;
            border-radius: 9px;
            border: 1px solid var(--border-soft);
            background: #fff;
            color: var(--text);
            font-weight: 600;
            padding: 0.55rem 0.8rem;
        }
        [data-testid="stSidebar"] [data-testid="stPopover"] > div > button:hover {
            border-color: var(--accent);
            color: var(--accent);
        }
        /* 「データを今すぐ更新」ボタン — サイドバー内はアクセント塗りに */
        [data-testid="stSidebar"] .stButton > button {
            width: 100%;
            border-radius: 9px;
            background: var(--chip);
            border: 1px solid var(--border-soft);
            color: var(--text);
            font-weight: 700;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            border-color: var(--accent);
            color: var(--accent);
            background: #fff;
        }
        /* キャプション（最終更新など） */
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            color: var(--text-faint);
        }

        /* メイン側のボタンを軽いタグ風に（タブ2のクイック選択など） */
        .stButton > button {
            border-radius: 999px;
            padding: 0.2rem 0.9rem;
            font-size: 0.82rem;
            font-weight: 600;
            border: 1px solid var(--border-soft);
            background: #fff;
            color: var(--text-sub);
        }
        .stButton > button:hover {
            border-color: var(--accent);
            color: var(--accent);
        }

        /* タブの見出し */
        [data-baseweb="tab"] { font-weight: 600; }
        [data-baseweb="tab-highlight"] { background-color: var(--accent) !important; }

        /* テーブルを少しコンパクトに */
        [data-testid="stDataFrame"] { font-size: 0.9rem; }

        /* 演目メタ情報チップ（タブ1） */
        .meta-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin: 0.5rem 0 0.2rem;
        }
        .meta-chip {
            font-size: 0.76rem;
            color: var(--text-sub);
            background: var(--chip);
            border-radius: 999px;
            padding: 0.28rem 0.7rem;
            font-weight: 600;
        }
        .meta-chip b { color: var(--text); font-weight: 800; margin-left: 2px; }

        /* 日付見出し（曜日カラー + 罫線 + 右ヒント） */
        .day-head {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            margin: 0.8rem 0 0.7rem;
        }
        .day-date {
            font-size: 1.32rem;
            font-weight: 800;
            color: var(--text);
            letter-spacing: -0.01em;
        }
        .day-rule { flex: 1; height: 1px; background: var(--border); }
        .day-count {
            font-size: 0.76rem;
            color: var(--text-faint);
            font-weight: 600;
            white-space: nowrap;
        }

        /* ── カード表示 ── */
        .card-grid {
            display: grid;
            gap: 0.85rem;
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
            border: 1px solid var(--border);
            border-radius: 12px;
            background: #fff;
            box-shadow: var(--card-shadow);
            display: flex;
            flex-direction: column;
            transition: box-shadow 0.15s ease, transform 0.15s ease;
        }
        .slot-card:hover, .event-card:hover {
            box-shadow: 0 6px 16px rgba(20, 40, 80, 0.10);
            transform: translateY(-2px);
        }
        .slot-card {
            padding: 0.9rem 0.95rem;
            gap: 0.6rem;
        }
        .slot-card .slot-time {
            font-size: 1.28rem;
            font-weight: 800;
            color: var(--text);
            letter-spacing: -0.01em;
        }
        .event-card {
            padding: 1rem 1.1rem;
            gap: 0.65rem;
        }
        .event-card .event-name {
            font-size: 1.02rem;
            font-weight: 800;
            color: var(--text);
            line-height: 1.4;
        }
        .event-card .event-meta {
            font-size: 0.8rem;
            color: var(--text-sub);
            font-weight: 600;
        }
        /* 空き状況バッジ（カード内） */
        .badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            width: fit-content;
            padding: 0.25rem 0.6rem;
            border-radius: 999px;
            font-size: 0.82rem;
            font-weight: 700;
        }
        .badge::before {
            content: "";
            width: 6px; height: 6px;
            border-radius: 999px;
            background: currentColor;
            opacity: 0.9;
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
        /* 除外中バナー（main側） */
        .excl-banner {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.4rem;
            padding: 0.6rem 0.8rem;
            margin: 0.2rem 0 0.6rem;
            background: #F6F8FB;
            border: 1px solid var(--border);
            border-radius: 12px;
        }
        .excl-banner-label {
            font-size: 0.78rem;
            font-weight: 700;
            color: var(--text-sub);
            margin-right: 0.2rem;
        }
        .excl-chip {
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: 999px;
            font-size: 0.77rem;
            font-weight: 600;
            background: #FDEAEA;
            color: #CC3B3B;
        }

        /* 予約ボタン（カード内リンク・A:軽い導線） */
        .book-btn {
            display: flex;
            align-items: center;
            justify-content: center;
            margin-top: auto;
            padding: 0.48rem 0.8rem;
            border-radius: 9px;
            background: var(--accent);
            color: #fff !important;
            font-size: 0.84rem;
            font-weight: 700;
            letter-spacing: 0.01em;
            text-decoration: none;
            box-shadow: 0 1px 2px rgba(47,111,237,0.25);
            transition: background 0.12s ease, box-shadow 0.12s ease;
        }
        .book-btn:hover {
            background: var(--accent-strong);
            box-shadow: 0 2px 8px rgba(47,111,237,0.3);
        }
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

    excluded = load_excluded_events()

    with st.sidebar:
        st.subheader(":material/tune: 設定")
        group_size = st.number_input(
            "参加予定人数", min_value=1, max_value=20, value=4, step=1
        )
        hide_full = st.checkbox("満員の枠を非表示", value=True)

        st.markdown("---")
        excluded = render_exclude_setting(excluded)

        st.markdown("---")
        updated = get_meta_updated_at()
        if updated:
            st.caption(f"演目情報の最終更新: {updated}")
        st.caption("空き状況は2時間キャッシュされます")
        if st.button("データを今すぐ更新", icon=":material/refresh:"):
            clear_cache()          # scraperのファイルキャッシュ(data/cache.json)を削除
            st.cache_data.clear()  # Streamlitのメモリキャッシュをクリア
            st.rerun()

    tab1, tab2 = st.tabs(
        [":material/theater_comedy: 演目から探す", ":material/calendar_month: 日付から探す"]
    )

    # ── タブ1: 演目から探す ──────────────────────────────────
    with tab1:
        render_tab_event(group_size, hide_full, excluded)

    # ── タブ2: 日付から探す ──────────────────────────────────
    with tab2:
        render_tab_date(group_size, hide_full, excluded)


def render_exclude_setting(excluded):
    """サイドバーの「検索から除外する演目」設定。
    ポップアップ内に全演目のチェックボックスを並べ、選択結果（除外する演目名リスト）を返す。"""
    st.caption(":material/filter_alt: 検索から除外する演目")

    # 選択肢は現在取得できる全演目名。過去に除外したが今は一覧に無い名前も残す
    try:
        all_names = sorted({e["event_name"] for e in get_event_list()})
    except Exception:
        all_names = []
    options = sorted(set(all_names) | set(excluded))

    if not options:
        st.caption("演目を読み込めませんでした。")
        return excluded

    label = (
        f"演目を選ぶ（{len(excluded)}件 除外中）" if excluded else "演目を選ぶ"
    )
    excluded_set = set(excluded)
    selected = []
    with st.popover(label, icon=":material/filter_alt:", use_container_width=True):
        st.caption("検索結果から外したい演目にチェック")
        # 演目が多くてもポップアップが画面外に伸びないよう、高さ固定のスクロール領域に入れる
        with st.container(height=300):
            for name in options:
                if st.checkbox(name, value=(name in excluded_set), key=f"excl_{name}"):
                    selected.append(name)

    # 選択が変わったときだけ保存
    if set(selected) != excluded_set:
        save_excluded_events(selected)
        st.toast("除外設定を保存しました")

    return selected


def render_excluded_banner(excluded):
    """main側で、現在除外中の演目を見やすく一覧表示する"""
    if not excluded:
        return
    chips = "".join(
        f'<span class="excl-chip">{escape(name)}</span>' for name in excluded
    )
    st.markdown(
        f'<div class="excl-banner">'
        f'<span class="excl-banner-label">除外中（{len(excluded)}件）</span>'
        f"{chips}</div>",
        unsafe_allow_html=True,
    )


def render_tab_event(group_size, hide_full, excluded):
    with st.spinner("演目一覧を読み込み中..."):
        try:
            events = get_event_list()
        except Exception as e:
            st.error(f"演目一覧の取得に失敗しました: {e}")
            return

    # サイドバーで除外指定された演目を選択肢から外す
    events = [e for e in events if e["event_name"] not in set(excluded)]

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

    render_excluded_banner(excluded)

    # 演目メタ情報（チップ表示）
    meta_chips = []
    if ev.get("type"):
        meta_chips.append(("種別", ev["type"]))
    if ev.get("max_team_size"):
        meta_chips.append(("1チーム最大", f"{ev['max_team_size']}人"))
    meta_chips.append(("残数単位", unit))
    st.markdown(
        '<div class="meta-row">'
        + "".join(
            f'<span class="meta-chip">{escape(k)} <b>{escape(v)}</b></span>'
            for k, v in meta_chips
        )
        + "</div>",
        unsafe_allow_html=True,
    )

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
        st.markdown(
            day_head_html(items[0]["_d"], f"空き {len(items)} 枠"),
            unsafe_allow_html=True,
        )
        cards = []
        for it in items:
            badge_style = STATUS_STYLE.get(it["_status"], "")
            url = it["予約"]
            btn = (
                f'<a class="book-btn" href="{escape(url)}" target="_blank">'
                f"予約ページ{BOOK_ARROW}</a>"
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


def render_tab_date(group_size, hide_full, excluded):
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
        # 開始日グループ／終了日グループを左寄せで詰め、余ったスペースは末尾にまとめる
        lb_s, b_s1, b_s2, lb_e, b_e1, b_e2, _sp = st.columns(
            [0.7, 0.8, 0.8, 0.7, 0.8, 0.8, 1.4], gap="small"
        )
        with lb_s:
            st.caption("開始日")
        with b_s1:
            if st.button("今週", key="qs_s1", use_container_width=True):
                st.session_state["t2_s"] = next_sat(0)
        with b_s2:
            if st.button("来週", key="qs_s2", use_container_width=True):
                st.session_state["t2_s"] = next_sat(1)
        with lb_e:
            st.caption("終了日")
        with b_e1:
            if st.button("今週", key="qs_e1", use_container_width=True):
                st.session_state["t2_e"] = next_sat(0)
        with b_e2:
            if st.button("来週", key="qs_e2", use_container_width=True):
                st.session_state["t2_e"] = next_sat(1)

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

    render_excluded_banner(excluded)

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

    # 日付ごとにグループ化（除外指定された演目は外す）
    excluded_set = set(excluded)
    by_date = {}
    for r in rows:
        if r["event_name"] in excluded_set:
            continue
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
        st.markdown(
            day_head_html(d, f"{len(rendered)} 演目"),
            unsafe_allow_html=True,
        )
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
                f"予約ページ{BOOK_ARROW}</a>"
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
