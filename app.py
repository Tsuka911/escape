import calendar
import json
from datetime import date, timedelta
from html import escape
from pathlib import Path

from PIL import Image as PILImage
import streamlit as st
from streamlit_local_storage import LocalStorage

from scraper import (
    list_events,
    fetch_schedule,
    get_meta_updated_at,
    clear_cache,
)

# 旧バージョンのユーザー設定ファイル（localStorageへ引き継ぐための初期値としてのみ参照）
SETTINGS_PATH = Path(__file__).parent / "data" / "user_settings.json"

# ── 設定の保存先：ブラウザのlocalStorage（端末ごとに永続化）───────────
# Streamlit Community Cloud のファイルは再起動で消えるため、サーバー側ファイルでは
# 設定が毎回リセットされてしまう。そこで「自分のiPhone/Macに残す」ために、
# ブラウザのlocalStorageへ保存する。streamlit.appは同一オリジンなので、
# GitHub Pagesの入口ページから何度起動しても端末ごとに設定が保持される。
LS_EXCLUDED = "escape_excluded_events"   # 除外演目（JSON文字列）
LS_LAST_EVENT = "escape_last_event"      # タブ1で前回選んだ演目名
LS_GROUP_SIZE = "escape_group_size"      # 参加予定人数
LS_FILTER_TYPES = "escape_filter_types"  # 絞り込み：種別（JSON文字列のリスト）
LS_FILTER_TIMES = "escape_filter_times"  # 絞り込み：時間帯（JSON文字列のリスト）

# 絞り込みの選択肢
TYPE_OPTIONS = ["ホール型", "ルーム型", "その他"]
TIME_OPTIONS = ["午前", "午後", "夜"]

# 画面切り替え（旧タブ）。(表示名, アイコン)
VIEW_OPTIONS = [
    ("演目から探す", ":material/theater_comedy:"),
    ("日付から探す", ":material/calendar_month:"),
    ("カレンダー", ":material/grid_view:"),
]


def get_local_storage() -> LocalStorage:
    """localStorageコンポーネントを1セッションにつき1度だけ生成して使い回す"""
    if "_local_storage" not in st.session_state:
        st.session_state["_local_storage"] = LocalStorage()
    return st.session_state["_local_storage"]


def _load_excluded_from_file() -> list:
    """旧 data/user_settings.json から除外演目を読む（初回引き継ぎ用・無ければ空）"""
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return list(data.get("excluded_events", []))
    except Exception:
        return []


def load_excluded_events(ls: LocalStorage) -> list:
    """除外する演目名のリストをlocalStorageから読み込む。
    まだ保存が無ければ旧ファイルの内容を初期値として引き継ぐ。"""
    raw = ls.getItem(LS_EXCLUDED)
    if raw is None:
        return _load_excluded_from_file()
    try:
        return list(json.loads(raw))
    except Exception:
        return []


def save_excluded_events(ls: LocalStorage, names: list) -> None:
    """除外する演目名のリストをlocalStorageに保存する"""
    # 空リストでも保存できるようJSON文字列（"[]"）にする（空文字は保存されないため）
    ls.setItem(LS_EXCLUDED, json.dumps(names, ensure_ascii=False), key="set_excluded")


def load_group_size(ls: LocalStorage) -> int:
    """参加予定人数をlocalStorageから読む（無ければ4人）"""
    try:
        return int(ls.getItem(LS_GROUP_SIZE))
    except (TypeError, ValueError):
        return 4


def save_group_size(ls: LocalStorage, value: int) -> None:
    ls.setItem(LS_GROUP_SIZE, str(value), key="set_group_size")


def _load_list(ls: LocalStorage, key: str) -> list:
    """localStorageからJSON配列を読む（無ければ空リスト）"""
    raw = ls.getItem(key)
    if raw is None:
        return []
    try:
        return list(json.loads(raw))
    except Exception:
        return []


def save_filter_types(ls: LocalStorage, values: list) -> None:
    ls.setItem(LS_FILTER_TYPES, json.dumps(values, ensure_ascii=False), key="set_filter_types")


def save_filter_times(ls: LocalStorage, values: list) -> None:
    ls.setItem(LS_FILTER_TIMES, json.dumps(values, ensure_ascii=False), key="set_filter_times")


# ── 設定変更時のコールバック（保存はユーザー操作時だけ行う）─────────
# localStorageは読み込みに一瞬かかる。その「まだ空」の状態で保存処理を走らせると
# 既定値で本来の設定を上書きしてしまうため、保存は必ずユーザーが操作した
# on_changeコールバックの中だけで行う（描画のたびには保存しない）。


def _on_group_size_change(ls: LocalStorage) -> None:
    st.session_state["_grp_user_set"] = True
    save_group_size(ls, int(st.session_state["grp_input"]))


def _on_exclude_change(ls: LocalStorage, options: list) -> None:
    st.session_state["_excl_user_set"] = True
    selected = [n for n in options if st.session_state.get(f"excl_{n}")]
    save_excluded_events(ls, selected)
    st.toast("除外設定を保存しました")


def _on_event_pick_change(ls: LocalStorage, widget_key: str) -> None:
    st.session_state["_ev_user_set"] = True
    chosen = st.session_state[widget_key]
    st.session_state["sel_event"] = chosen  # タブ1とカレンダーで選択を共有する
    ls.setItem(LS_LAST_EVENT, chosen, key="set_last_event")


def _on_event_clear(ls: LocalStorage) -> None:
    """演目の選択を未選択に戻し、前回選んだ演目の記憶（localStorage）も消す。
    タブ1とカレンダーは選択を共有しているので、両方のウィジェットを未選択にする。"""
    st.session_state["_ev_user_set"] = True
    st.session_state["sel_event"] = None
    for k in ("ev_pick", "cal_ev_pick"):
        if k in st.session_state:
            st.session_state[k] = None
    ls.setItem(LS_LAST_EVENT, "", key="clear_last_event")


def _on_filter_types_change(ls: LocalStorage) -> None:
    # 種別・時間帯で別コールバックにする（同じrunで同じsetItemキーを二重に呼ぶと
    # StreamlitDuplicateElementKeyになるため、各保存は1回だけになるよう分ける）
    st.session_state["_flt_user_set"] = True
    save_filter_types(ls, st.session_state.get("flt_types") or [])


def _on_filter_times_change(ls: LocalStorage) -> None:
    st.session_state["_flt_user_set"] = True
    save_filter_times(ls, st.session_state.get("flt_times") or [])


def _shift_cal_month(delta: int) -> None:
    """カレンダーの対象月を delta ヶ月ずらす（前の月/次の月ボタンのコールバック）。"""
    y = st.session_state.get("cal_year", date.today().year)
    m = st.session_state.get("cal_month", date.today().month) + delta
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    st.session_state["cal_year"], st.session_state["cal_month"] = y, m


# ── 絞り込みの判定ヘルパー（未選択＝絞り込みなし＝全部表示）───────────


def slot_period(time_str: str) -> str:
    """時刻 "HH:MM" を 午前/午後/夜 に分類する"""
    try:
        hour = int(time_str[:2])
    except (ValueError, IndexError):
        return "午後"
    if hour < 12:
        return "午前"
    if hour < 17:
        return "午後"
    return "夜"


def type_category(event_type) -> str:
    """演目の種別を絞り込み用カテゴリ（ホール型/ルーム型/その他）に正規化する"""
    return event_type if event_type in ("ホール型", "ルーム型") else "その他"


def event_passes_type(event_type, types: list) -> bool:
    """種別フィルタを通過するか（typesが空なら全部通過）"""
    if not types:
        return True
    return type_category(event_type) in types


def filter_slots(slots: list, times: list) -> list:
    """時間帯フィルタで枠を絞る（timesが空ならそのまま）"""
    if not times:
        return slots
    return [s for s in slots if slot_period(s["time"]) in times]

_icon = PILImage.open(Path(__file__).parent / "icon.png")
st.set_page_config(
    page_title="リアル脱出ゲーム 名古屋 検索",
    page_icon=_icon,
    layout="wide",
)

# ※iPhoneホーム画面アイコンは GitHub Pages の入口ページ(docs/index.html)で対応。
#   Streamlit側のheadはiOSのアイコン取得に使えないため、ここでは何もしない。


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

# カレンダー（タブ3）のヒートマップ用の塗り色（背景, 文字）。
# 1演目の空き状況を 緑=空きあり / 黄=わずか / 赤=満員 で日ごとに塗る。
CAL_COLORS = {
    "ok": ("#3DA968", "#ffffff"),
    "warn": ("#E8A13A", "#ffffff"),
    "full": ("#E0635C", "#ffffff"),
    "unknown": ("#C2CAD6", "#ffffff"),
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

        /* ── カレンダー（タブ3）の日付セル ── */
        /* スマホ幅でも7列を横並びに保つ（Streamlitは既定で縦積みにするため上書き） */
        .st-key-cal_grid [data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap !important;
            gap: 3px !important;
        }
        .st-key-cal_grid [data-testid="stColumn"] {
            flex: 1 1 0 !important;
            min-width: 0 !important;
            width: auto !important;
        }
        /* ── 画面切り替え（旧タブ）のボタンバー ── */
        .st-key-view_switch [data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap !important;
            gap: 4px !important;
        }
        .st-key-view_switch [data-testid="stColumn"] {
            flex: 1 1 0 !important;
            min-width: 0 !important;
        }
        .st-key-view_switch .stButton > button {
            border-radius: 10px;
            padding: 0.4rem 0.2rem;
            font-size: 0.8rem;
            font-weight: 700;
            white-space: nowrap;
        }
        /* 選択中（青塗り）。ホバー/フォーカス/タップ後も文字を白に保つ。
           （汎用の :hover で文字色がアクセント青になり、青背景に同化して
           読めなくなるのを防ぐ。Macのマウスオーバー・iPhoneのタップ残り対策） */
        .st-key-view_switch [data-testid="stBaseButton-primary"],
        .st-key-view_switch [data-testid="stBaseButton-primary"]:hover,
        .st-key-view_switch [data-testid="stBaseButton-primary"]:focus,
        .st-key-view_switch [data-testid="stBaseButton-primary"]:active,
        .st-key-view_switch [data-testid="stBaseButton-primary"]:focus-visible {
            background: var(--accent);
            border-color: var(--accent);
            color: #fff !important;
        }
        .st-key-view_switch [data-testid="stBaseButton-primary"]:hover {
            background: var(--accent-strong);
            border-color: var(--accent-strong);
        }
        /* 非選択（白）。ホバー時はアクセント文字＋白背景で読める状態を保つ */
        .st-key-view_switch [data-testid="stBaseButton-secondary"] {
            background: #fff;
            color: var(--text-sub);
            border-color: var(--border-soft);
        }
        .st-key-view_switch [data-testid="stBaseButton-secondary"]:hover {
            background: #fff;
            color: var(--accent) !important;
            border-color: var(--accent);
        }

        /* メイン側の汎用ボタンCSS（白・丸タグ）を打ち消し、正方形寄りのセルにする */
        .st-key-cal_grid .stButton > button {
            border-radius: 8px;
            min-height: 44px;
            padding: 0.1rem 0;
            font-size: 0.85rem;
            font-weight: 700;
            line-height: 1.1;
        }
        /* 開催なしの日は控えめなグレー（色は各日付セルのキー単位CSSで上書きする） */
        .st-key-cal_grid [data-testid="stBaseButton-secondary"] {
            color: var(--text-faint);
            background: #F2F4F8;
            border-color: #E7EBF1;
        }
        /* カレンダーの凡例 */
        .cal-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem 0.9rem;
            margin: 0.2rem 0 0.7rem;
            font-size: 0.76rem;
            color: var(--text-sub);
            font-weight: 600;
        }
        .cal-legend span { display: inline-flex; align-items: center; gap: 5px; }
        .cal-legend i {
            width: 12px; height: 12px; border-radius: 4px; display: inline-block;
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

    ls = get_local_storage()
    excluded = load_excluded_events(ls)

    with st.sidebar:
        st.subheader(":material/tune: 設定")
        # ユーザーが触るまでは、localStorageの保存値を毎回セットし直す。
        # （localStorageは読み込みに一瞬かかるため、読めた時点で反映させる）
        if not st.session_state.get("_grp_user_set"):
            st.session_state["grp_input"] = load_group_size(ls)
        group_size = st.number_input(
            "参加予定人数", min_value=1, max_value=20, step=1,
            key="grp_input", on_change=_on_group_size_change, args=(ls,),
        )
        hide_full = st.checkbox("満員の枠を非表示", value=True)

        st.markdown("---")
        filter_types, filter_times = render_filter_setting(ls)

        st.markdown("---")
        excluded = render_exclude_setting(ls, excluded)

        st.markdown("---")
        updated = get_meta_updated_at()
        if updated:
            st.caption(f"演目情報の最終更新: {updated}")
        st.caption("空き状況は2時間キャッシュされます")
        if st.button("データを今すぐ更新", icon=":material/refresh:"):
            clear_cache()          # scraperのファイルキャッシュ(data/cache.json)を削除
            st.cache_data.clear()  # Streamlitのメモリキャッシュをクリア
            st.rerun()

    # ── 画面切り替え ────────────────────────────────────────
    # st.tabs は再実行のたびに選択がリセットされ（フィルタ変更や月送り等で）
    # 別タブに飛んでしまうため、選択を session_state に持つ自前の切り替えボタンにする。
    # これでどの操作で再実行が走っても、表示中の画面が維持される。
    if "active_view" not in st.session_state:
        st.session_state["active_view"] = VIEW_OPTIONS[0][0]
    active = st.session_state["active_view"]

    with st.container(key="view_switch"):
        cols = st.columns(len(VIEW_OPTIONS), gap="small")
        for col, (name, icon) in zip(cols, VIEW_OPTIONS):
            col.button(
                name,
                icon=icon,
                use_container_width=True,
                type=("primary" if name == active else "secondary"),
                key=f"viewbtn_{name}",
                on_click=lambda n=name: st.session_state.update(active_view=n),
            )

    if active == "演目から探す":
        render_tab_event(ls, group_size, hide_full, excluded, filter_types, filter_times)
    elif active == "日付から探す":
        render_tab_date(group_size, hide_full, excluded, filter_types, filter_times)
    else:
        render_tab_calendar(ls, group_size, excluded, filter_types, filter_times)


def render_filter_setting(ls):
    """サイドバーの「絞り込み」設定（種別・時間帯）。
    タップ式のpillsでキーボードを出さない。未選択＝絞り込みなし（全部表示）。
    保存はon_changeの中だけで行い、ユーザーが触るまでは保存値をセットし直す。"""
    st.caption(":material/filter_list: 絞り込み（未選択＝すべて）")

    if not st.session_state.get("_flt_user_set"):
        st.session_state["flt_types"] = [
            v for v in _load_list(ls, LS_FILTER_TYPES) if v in TYPE_OPTIONS
        ]
        st.session_state["flt_times"] = [
            v for v in _load_list(ls, LS_FILTER_TIMES) if v in TIME_OPTIONS
        ]

    st.pills(
        "種別", TYPE_OPTIONS, selection_mode="multi",
        key="flt_types", on_change=_on_filter_types_change, args=(ls,),
    )
    st.pills(
        "時間帯", TIME_OPTIONS, selection_mode="multi",
        key="flt_times", on_change=_on_filter_times_change, args=(ls,),
    )

    return (
        st.session_state.get("flt_types") or [],
        st.session_state.get("flt_times") or [],
    )


def render_exclude_setting(ls, excluded):
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

    excluded_set = set(excluded)

    # ユーザーが触るまでは、各チェックボックスの状態を保存値に合わせ続ける。
    # （localStorageが読めた時点で正しいチェック状態に反映される）
    if not st.session_state.get("_excl_user_set"):
        for name in options:
            st.session_state[f"excl_{name}"] = name in excluded_set

    label = (
        f"演目を選ぶ（{len(excluded)}件 除外中）" if excluded else "演目を選ぶ"
    )
    with st.popover(label, icon=":material/filter_alt:", use_container_width=True):
        st.caption("検索結果から外したい演目にチェック")
        # 演目が多くてもポップアップが画面外に伸びないよう、高さ固定のスクロール領域に入れる
        with st.container(height=300):
            for name in options:
                st.checkbox(
                    name, key=f"excl_{name}",
                    on_change=_on_exclude_change, args=(ls, options),
                )

    # 現在のチェック状態を集計して返す（保存はon_changeの中だけで行う）
    return [n for n in options if st.session_state.get(f"excl_{n}")]


def render_excluded_banner(excluded):
    """main側で、現在除外中の演目を開閉式（expander）で一覧表示する。
    演目が多いときに邪魔にならないよう、既定は閉じておく。"""
    if not excluded:
        return
    chips = "".join(
        f'<span class="excl-chip">{escape(name)}</span>' for name in excluded
    )
    with st.expander(f"除外中の演目（{len(excluded)}件）", expanded=False):
        st.markdown(
            f'<div class="excl-banner">{chips}</div>',
            unsafe_allow_html=True,
        )


def format_event_label(e) -> str:
    """演目ピッカー用の表示ラベル（演目名 ＋ 種別/最大人数）。"""
    parts = [e["event_name"]]
    extra = []
    if e.get("type"):
        extra.append(e["type"])
    if e.get("max_team_size"):
        extra.append(f"最大{e['max_team_size']}人")
    if extra:
        parts.append("（" + " / ".join(extra) + "）")
    return "".join(parts)


def get_selected_event_name(ls, names: list):
    """タブ1とカレンダーで共有する「選択中の演目名」を返す。未選択なら None。
    ユーザーが触るまでは前回選んだ演目（localStorage）を既定にし続ける。
    記憶がない（初回・またはクリア済み）場合は未選択で始める。"""
    if not st.session_state.get("_ev_user_set"):
        last_event = ls.getItem(LS_LAST_EVENT)
        st.session_state["sel_event"] = last_event if last_event in names else None
    elif st.session_state.get("sel_event") not in names:
        # 選んでいた演目が一覧から消えた（種別フィルタ等）→ 未選択に戻す
        st.session_state["sel_event"] = None
    return st.session_state.get("sel_event")


def render_event_picker(ls, events, widget_key: str):
    """ポップオーバー＋ラジオのタップ選択で演目を選ぶ（キーボードを出さない）。
    選択は sel_event（タブ1/カレンダー共有）を真として、各ウィジェットはそれに追従する。
    未選択のときは None を返す。"""
    names = [e["event_name"] for e in events]
    label_map = {e["event_name"]: format_event_label(e) for e in events}

    sel = get_selected_event_name(ls, names)
    st.session_state[widget_key] = sel  # 共有状態にウィジェットを追従させる（None=未選択）

    picker_label = f"演目：{label_map[sel]}" if sel else "演目を選ぶ"
    with st.popover(
        picker_label,
        icon=":material/theater_comedy:",
        use_container_width=True,
    ):
        st.caption("演目をタップして選ぶ")
        with st.container(height=320):
            st.radio(
                "演目を選ぶ",
                names,
                format_func=lambda n: label_map[n],
                key=widget_key,
                on_change=_on_event_pick_change,
                args=(ls, widget_key),
                label_visibility="collapsed",
            )

    # 演目を選んでいるときだけ「選択をクリア」ボタンを出す
    if sel:
        st.button(
            "選択中の演目をクリア",
            icon=":material/close:",
            key=f"{widget_key}_clear",
            on_click=_on_event_clear,
            args=(ls,),
            use_container_width=True,
        )

    chosen = st.session_state[widget_key]
    if chosen is None:
        return None
    return next(e for e in events if e["event_name"] == chosen)


def render_date_range(key_prefix: str, default_end_days: int):
    """日付範囲（開始/終了/土日のみ）＋クイック選択を、開閉式（expander）で表示する。
    タブ1・タブ2共通。スマホでボタンが場所を取って検索結果が押し下げられないよう
    既定は閉じておき、閉じていても現在の期間がラベルで分かるようにする。
    戻り値: (start_d, end_d, weekend_only)"""
    today = date.today()
    s_key, e_key, we_key = f"{key_prefix}_s", f"{key_prefix}_e", f"{key_prefix}_we"
    default_end = today + timedelta(days=default_end_days)

    def next_sat(offset_weeks: int = 0) -> date:
        days = (5 - today.weekday()) % 7
        return today + timedelta(days=days + offset_weeks * 7)

    def on_start_change():
        # 開始日を動かしたとき、終了日がそれより前のままだとエラーになり煩わしいので、
        # 終了日を自動で追従させる（開始日と同じ日に合わせる）
        if st.session_state.get(e_key) is not None and st.session_state[s_key] > st.session_state[e_key]:
            st.session_state[e_key] = st.session_state[s_key]

    # 折りたたみ時もわかるよう、現在の期間をラベルに出す
    cur_s = st.session_state.get(s_key, today)
    cur_e = st.session_state.get(e_key, default_end)
    label = f"期間：{cur_s.month}/{cur_s.day} 〜 {cur_e.month}/{cur_e.day}"

    with st.expander(label, expanded=False):
        # containerで表示位置を先に確保し、日付欄が上・クイック選択が下になるよう制御
        date_row = st.container()
        quick_row = st.container()

        # ボタン処理はwidget生成より前に実行する必要があるため quick_row を先に書く
        with quick_row:
            st.caption("クイック選択（土曜日をセット）")
            lb_s, b_s1, b_s2, lb_e, b_e1, b_e2, _sp = st.columns(
                [0.7, 0.8, 0.8, 0.7, 0.8, 0.8, 1.4], gap="small"
            )
            with lb_s:
                st.caption("開始日")
            with b_s1:
                if st.button("今週", key=f"qs_{key_prefix}_s1", use_container_width=True):
                    st.session_state[s_key] = next_sat(0)
            with b_s2:
                if st.button("来週", key=f"qs_{key_prefix}_s2", use_container_width=True):
                    st.session_state[s_key] = next_sat(1)
            with lb_e:
                st.caption("終了日")
            with b_e1:
                if st.button("今週", key=f"qs_{key_prefix}_e1", use_container_width=True):
                    st.session_state[e_key] = next_sat(0)
            with b_e2:
                if st.button("来週", key=f"qs_{key_prefix}_e2", use_container_width=True):
                    st.session_state[e_key] = next_sat(1)

        # クイック選択ボタンで開始日が終了日より後になった場合に備え、
        # widget生成前に終了日を補正しておく（min_valueを下回るとエラーになるため）
        if (
            st.session_state.get(s_key) is not None
            and st.session_state.get(e_key) is not None
            and st.session_state[s_key] > st.session_state[e_key]
        ):
            st.session_state[e_key] = st.session_state[s_key]

        with date_row:
            c1, c2, c3 = st.columns([2, 2, 2])
            with c1:
                start_d = st.date_input(
                    "期間（開始）", value=today, key=s_key, on_change=on_start_change
                )
            with c2:
                # 終了日は開始日より前を選べないようにし、エラーが出ないようにする。
                # 初期値(value)も必ず開始日以上にしておく（min_valueを下回るとエラーになるため）
                end_d = st.date_input(
                    "期間（終了）",
                    value=max(default_end, start_d),
                    key=e_key,
                    min_value=start_d,
                )
            with c3:
                weekend_only = st.checkbox("土日のみ表示", value=True, key=we_key)

    return start_d, end_d, weekend_only


def get_filtered_event_list(excluded, filter_types):
    """除外演目を外し、種別フィルタも適用した演目一覧を返す（タブ1・カレンダー共通）。
    取得失敗時は None。種別フィルタは演目の選択肢自体に効かせる
    （例：ルーム型を選ぶと、選べる演目がルーム型だけになる）。"""
    try:
        events = get_event_list()
    except Exception as e:
        st.error(f"演目一覧の取得に失敗しました: {e}")
        return None
    excluded_set = set(excluded)
    return [
        e for e in events
        if e["event_name"] not in excluded_set
        and event_passes_type(e.get("type"), filter_types)
    ]


def render_tab_event(ls, group_size, hide_full, excluded, filter_types, filter_times):
    with st.spinner("演目一覧を読み込み中..."):
        events = get_filtered_event_list(excluded, filter_types)
    if events is None:
        return
    if not events:
        st.warning("条件に合う演目がありません。サイドバーの種別の絞り込みを見直してください。")
        return

    # ── 演目選択：ポップオーバー＋タップ選択（タブ1とカレンダーで共有）──
    ev = render_event_picker(ls, events, "ev_pick")
    if ev is None:
        st.info("上の「演目を選ぶ」から、空き状況を見たい演目を選んでください。")
        return
    unit = ev["order_unit"]

    start_d, end_d, weekend_only = render_date_range("t1", 60)

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
        for s in filter_slots(r["slots"], filter_times):
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


def build_day_events(day_rows, group_size, hide_full, filter_types, filter_times):
    """1日分の演目行を、絞り込み適用後の「表示用演目リスト」に整形して返す。
    タブ2とカレンダーのドリルインで共有する。空き枠が無い演目は含めない。"""
    rendered = []
    for r in day_rows:
        if not event_passes_type(r.get("type"), filter_types):
            continue
        unit = r["order_unit"]
        slots = filter_slots(r["slots"], filter_times)
        slots_info = []
        ranks = []
        for s in slots:
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
    return rendered


def render_day_event_cards(
    d, day_rows, group_size, hide_full, filter_types, filter_times, sort_mode="空き多い順"
):
    """1日分の演目カードを描画する。表示した演目数を返す（0なら何も描かない）。"""
    rendered = build_day_events(day_rows, group_size, hide_full, filter_types, filter_times)
    if not rendered:
        return 0

    if sort_mode == "演目名順":
        rendered.sort(key=lambda x: x["event_name"])
    else:
        rendered.sort(key=lambda x: x["_rank"])

    st.markdown(day_head_html(d, f"{len(rendered)} 演目"), unsafe_allow_html=True)
    cards = []
    for it in rendered:
        chips = "".join(
            f'<span class="chip" style="{STATUS_STYLE.get(si["status"], "")}">'
            f'{escape(si["label"])}</span>'
            for si in it["slots"]
        )
        meta_html = (
            f'<div class="event-meta">{escape(it["meta"])}</div>' if it["meta"] else ""
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
    return len(rendered)


def render_tab_date(group_size, hide_full, excluded, filter_types, filter_times):
    start_d, end_d, weekend_only = render_date_range("t2", 30)

    if start_d > end_d:
        st.warning("開始日が終了日より後になっています。")
        return

    render_excluded_banner(excluded)

    sort_mode = st.segmented_control(
        "並び順", ["空き多い順", "演目名順"], default="空き多い順", key="t2_sort"
    ) or "空き多い順"

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

    shown = 0
    for date_str in sorted(by_date.keys()):
        d = date.fromisoformat(date_str)
        shown += render_day_event_cards(
            d, by_date[date_str], group_size, hide_full,
            filter_types, filter_times, sort_mode,
        )

    if shown == 0:
        st.info("条件に合う空き枠のある演目が見つかりませんでした。絞り込みや期間を見直してみてください。")


def render_event_day_slots(ev, slots, group_size, filter_times):
    """カレンダーのドリルイン用：選んだ演目の、その日の時間枠をカードで表示する。"""
    unit = ev["order_unit"]
    slots = sorted(filter_slots(slots, filter_times), key=lambda s: s["time"])
    if not slots:
        st.info("この日にこの演目の枠はありませんでした。")
        return
    cards = []
    for s in slots:
        status, text = capacity_status(s["stock"], unit, group_size)
        badge_style = STATUS_STYLE.get(status, "")
        url = s.get("ticket_url") or ""
        btn = (
            f'<a class="book-btn" href="{escape(url)}" target="_blank">'
            f"予約ページ{BOOK_ARROW}</a>"
            if url
            else ""
        )
        cards.append(
            '<div class="slot-card">'
            f'<div class="slot-time">{escape(s["time"])}</div>'
            f'<span class="badge" style="{badge_style}">{escape(text)}</span>'
            f"{btn}</div>"
        )
    st.markdown(
        f'<div class="card-grid grid-slots">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def render_tab_calendar(ls, group_size, excluded, filter_types, filter_times):
    """選んだ1演目の空き状況を、月カレンダーのヒートマップで表示する。
    緑=空きあり / 黄=わずか / 赤=満員 / グレー=開催なし。
    日をタップするとその日の時間枠を下に表示する。"""
    today = date.today()

    with st.spinner("演目一覧を読み込み中..."):
        events = get_filtered_event_list(excluded, filter_types)
    if events is None:
        return
    if not events:
        st.warning("条件に合う演目がありません。サイドバーの種別の絞り込みを見直してください。")
        return

    # 演目選択（タブ1と共有）
    ev = render_event_picker(ls, events, "cal_ev_pick")
    if ev is None:
        st.info("上の「演目を選ぶ」から、カレンダーで見たい演目を選んでください。")
        return
    event_name = ev["event_name"]

    # 対象月（year, month）をセッションに保持。既定は今月。
    if "cal_year" not in st.session_state:
        st.session_state["cal_year"] = today.year
        st.session_state["cal_month"] = today.month

    cy, cm = st.session_state["cal_year"], st.session_state["cal_month"]

    # 月送りは on_click コールバックで行う。st.rerun() を明示的に呼ぶと
    # タブの選択がリセットされ「日付から探す」に戻ってしまうため使わない
    # （ボタン押下だけで再実行は走る。日付セルのタップと同じ方式）。
    nav_prev, nav_label, nav_next = st.columns([1, 2, 1], gap="small")
    with nav_prev:
        st.button(
            "前の月", use_container_width=True, key="cal_prev",
            on_click=_shift_cal_month, args=(-1,),
        )
    with nav_label:
        st.markdown(
            f'<div style="text-align:center;font-weight:800;font-size:1.1rem;'
            f'padding-top:0.3rem">{cy}年{cm}月</div>',
            unsafe_allow_html=True,
        )
    with nav_next:
        st.button(
            "次の月", use_container_width=True, key="cal_next",
            on_click=_shift_cal_month, args=(1,),
        )

    month_start = date(cy, cm, 1)
    last_day = calendar.monthrange(cy, cm)[1]
    month_end = date(cy, cm, last_day)

    # その月の空き状況を取得（全日・2時間キャッシュ）→ 選んだ演目だけ抜き出す
    with st.spinner(f"{cy}年{cm}月の「{event_name}」の空き状況を確認中..."):
        try:
            rows = get_schedule(month_start.isoformat(), month_end.isoformat(), False)
        except Exception as e:
            st.error(f"データ取得に失敗しました: {e}")
            return

    # 日付 → その演目のスロット一覧
    slots_by_date = {}
    for r in rows:
        if r["event_name"] != event_name:
            continue
        slots_by_date.setdefault(r["date"], []).extend(r["slots"])

    # 日付 → その日の状態（緑/黄/赤）。時間帯フィルタ後のスロットの最良状態。
    status_by_date = {}
    for date_str, slots in slots_by_date.items():
        fslots = filter_slots(slots, filter_times)
        if not fslots:
            continue
        best = min(
            (capacity_status(s["stock"], ev["order_unit"], group_size)[0] for s in fslots),
            key=lambda st_key: STATUS_RANK[st_key],
        )
        status_by_date[date_str] = best

    # 日付セルの色をキー単位のCSSで指定（緑/黄/赤）
    css_rules = []
    for date_str, status in status_by_date.items():
        bg, fg = CAL_COLORS.get(status, CAL_COLORS["unknown"])
        css_rules.append(
            f'.st-key-cal_{date_str} button{{background:{bg}!important;'
            f'border-color:{bg}!important;color:{fg}!important}}'
        )
    if css_rules:
        st.markdown(f"<style>{''.join(css_rules)}</style>", unsafe_allow_html=True)

    # 凡例
    st.markdown(
        '<div class="cal-legend">'
        '<span><i style="background:#3DA968"></i>空きあり</span>'
        '<span><i style="background:#E8A13A"></i>残りわずか</span>'
        '<span><i style="background:#E0635C"></i>満員</span>'
        '<span><i style="background:#EAEef3"></i>開催なし</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    # 曜日見出し＋日付セルを keyed container に入れ、カレンダー専用CSSを当てる
    with st.container(key="cal_grid"):
        week_labels = ["日", "月", "火", "水", "木", "金", "土"]
        head_cols = st.columns(7, gap="small")
        for col, wl in zip(head_cols, week_labels):
            color = "#D8453D" if wl == "日" else "#2F6FED" if wl == "土" else "#5A6678"
            col.markdown(
                f'<div style="text-align:center;font-weight:700;font-size:0.8rem;'
                f'color:{color}">{wl}</div>',
                unsafe_allow_html=True,
            )

        # 日曜始まりの月カレンダー（0は前後月の空白セル）
        cal = calendar.Calendar(firstweekday=6)
        for week in cal.monthdayscalendar(cy, cm):
            cols = st.columns(7, gap="small")
            for col, day in zip(cols, week):
                if day == 0:
                    col.write("")
                    continue
                d = date(cy, cm, day)
                date_str = d.isoformat()
                is_past = d < today
                col.button(
                    str(day),
                    key=f"cal_{date_str}",
                    use_container_width=True,
                    disabled=is_past,
                    on_click=lambda ds=date_str: st.session_state.update(cal_selected=ds),
                )

    st.caption("色のついた日付をタップすると、その日の時間枠を表示します。")

    # ドリルイン：選択した日の時間枠を下に表示
    selected = st.session_state.get("cal_selected")
    if selected and selected.startswith(f"{cy}-{cm:02d}"):
        d = date.fromisoformat(selected)
        st.markdown("---")
        st.markdown(
            day_head_html(d, format_event_label(ev)),
            unsafe_allow_html=True,
        )
        render_event_day_slots(ev, slots_by_date.get(selected, []), group_size, filter_times)


if __name__ == "__main__":
    main()
