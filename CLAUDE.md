# CLAUDE.md — このプロジェクトについて

## アプリの概要

名古屋のリアル脱出ゲームのチケット空き状況を確認する Streamlit アプリ。

- デプロイ先: **Streamlit Community Cloud**（Vercel は使わない）。公開URL `https://escapefromtickets.streamlit.app/`
- ブランチ: `main` のみ。デプロイはプッシュで自動反映
- **iPhoneホーム画面アイコンは GitHub Pages の入口ページ（`docs/`）で出している**（後述）

## ファイル構成と役割

| ファイル | 役割 |
|---|---|
| `app.py` | Streamlit の UI 全体。CSS・カード描画・設定UIを含む |
| `scraper.py` | 公式サイトのスクレイピングとチケットAPIの呼び出し |
| `data/cache.json` | スクレイピング・APIのキャッシュ（git管理外） |
| `data/user_settings.json` | 旧ユーザー設定。現在は**ブラウザのlocalStorage**に保存。これは新規端末への引き継ぎ用の初期値としてのみ参照（git管理外） |
| `.streamlit/config.toml` | テーマ（背景 `#F5F7FA`・サイドバー `#FBFCFE`・青アクセント `#2F6FED`） |
| `icon.png` | Streamlitのページアイコン（favicon）。`app.py` の `st.set_page_config(page_icon=...)` で使用 |
| `docs/index.html` | **GitHub Pages の入口ページ**（iPhoneホーム画面アイコン用） |
| `docs/icon.png` | 入口ページが使うホーム画面アイコン（180×180） |

## データ取得の仕組み

- **演目メタ情報**（種別・最大人数・随時スタート判定）: `fetch_event_meta()` で公式サイトをスクレイピング。24時間キャッシュ
- **チケット・空き状況**: `fetch_tickets_for_date()` で公式API（`api.scrapmagazine.com`）を叩く。2時間キャッシュ
- キャッシュは `data/cache.json` に保存。Streamlit の `@st.cache_data(ttl=7200)` でメモリにも2時間保持
- **2層キャッシュに注意**: ①Streamlitメモリ（`@st.cache_data`）と ②scraperのファイル（`data/cache.json`）の2層がある。「データを今すぐ更新」ボタンは両方をクリアする必要があるため、`scraper.clear_cache()`（ファイル削除）＋ `st.cache_data.clear()`（メモリ）の両方を呼ぶ。片方だけだと最終更新時刻が変わらない

## ユーザー設定の永続化（localStorage・重要・ハマりどころ）

- 除外演目・前回選んだ演目・参加人数は **ブラウザのlocalStorage** に端末ごとに保存する（`streamlit-local-storage` パッケージ）。
  - **なぜファイルでなくlocalStorageか**: Streamlit Community Cloud のディスクは一時的で、アプリがスリープ/再起動するたびにファイルが消える。サーバー側ファイルだと設定が毎回リセットされる（しかも全ユーザー共通になる）。localStorageなら「自分のiPhone/Mac」に残る。streamlit.appは同一オリジンなので、入口ページ(`docs/`)から何度起動しても保持される。
  - キー: `escape_excluded_events` / `escape_last_event` / `escape_group_size`（`app.py` の `LS_*` 定数）。
  - 旧 `data/user_settings.json` は、新規端末への**初回引き継ぎ用の初期値**としてのみ読む（`_load_excluded_from_file()`）。
- **ハマりどころ①「読み込み直後の上書き事故」**: localStorageコンポーネントはページ読み込み直後の最初の実行ではまだ中身が空。その空状態で設定ウィジェットを作ると「空＝既定値」で初期化され、それを保存してしまうと本来の設定を消す。
  - **対策**: 保存は必ず **ユーザー操作時（`on_change` コールバック）だけ** 行う。描画のたびには保存しない。各設定に `_xxx_user_set` フラグを持ち、ユーザーが触るまでは毎回localStorageの保存値をセットし直す（読めた時点で正しく反映される）。`_on_group_size_change` / `_on_exclude_change` / `_on_event_pick_change` 参照。
- **ハマりどころ②**: `st.stop()` でロード完了を待つ方式は **不可**。`st.stop()` がlocalStorageコンポーネントをアンマウントしてしまい（コンソールに `unregistered ComponentInstance` 警告）、データが永久に届かず固まる。待ちゲートは作らないこと。

## iPhoneホーム画面アイコン（重要・ハマりどころ）

- iOS Safariは「ホーム画面に追加」時、**ページを最初に読み込んだHTMLの`<head>`にある`apple-touch-icon`しか読まない**。JSで後から差し込んだものは無視する。
- そして **Streamlit Cloud はアプリの最初のHTMLの`<head>`を編集させてくれない**。そのため Streamlit 内（`app.py`）でいくら工夫してもiOSアイコンは出せない。
- 解決策: **GitHub Pages の入口ページ `docs/index.html`** を使う。これは最初のHTMLに`apple-touch-icon`を持ち、standalone起動時はStreamlitアプリへ自動転送する軽量ページ。
  - GitHub Pages設定: Settings→Pages→`main`ブランチ`/docs`
  - **ホーム画面に追加するURLは入口ページ** `https://tsuka911.github.io/escape/`（Streamlit直URLではない）
  - ホーム画面アイコンを変える時は `docs/icon.png` を180×180で差し替える
- 試したが効かなかった方法（`app.py`内でやろうとしない・再挑戦しないこと）: `st.markdown`で`<link>`（除去される）／`data:`URI（iOSが受け付けない）／`st.html`でbodyに挿入（headに入らない）／`st.iframe`/`components.html`でJSによるhead挿入（iOSは後からJS挿入したアイコンを無視）／`/app/static/`配信（Cloudでは画像でなくアプリHTMLが返る）。

## 検索から除外される演目

`scraper.py` 冒頭の `EXCLUDE_TITLE_KEYWORDS` でキーワード除外（コードレベル）:

```python
EXCLUDE_TITLE_KEYWORDS = ("街歩き",)
```

- 随時スタートの演目も `is_anytime` フラグで除外（`exclude_anytime=True`）

ユーザーが手動で除外したい演目は `data/user_settings.json` に保存され、`app.py` の `load_excluded_events()` / `save_excluded_events()` で読み書きする。

## UIの構成

- **サイドバー**: 参加人数・満員非表示・**絞り込み（種別・時間帯）**・除外演目設定（ポップアップ式チェックボックス）・更新ボタン
  - **絞り込み**（`render_filter_setting()`）: 種別（ホール型/ルーム型/その他）と時間帯（午前/午後/夜）を `st.pills`(multi) でタップ選択。**未選択＝絞り込みなし（全部表示）**。localStorage(`escape_filter_types`/`escape_filter_times`)に端末ごと保存。判定は `event_passes_type()` / `filter_slots()` / `slot_period()`。タブ1・タブ2・カレンダーの3つすべてに同じフィルタが効く
- **タブ1「演目から探す」**: 演目ピッカー（ポップオーバー＋ラジオのタップ選択。iPhoneでキーボードが出ないよう`selectbox`をやめた） → 日付範囲 → 時間枠カードのグリッド表示。時間帯フィルタが枠に効く
- **タブ2「日付から探す」**: 日付範囲（クイック選択ボタン付き）＋**並び順**（`st.segmented_control` で「空き多い順／演目名順」） → 日付ごとに演目カードを表示
- **タブ3「カレンダー」**（`render_tab_calendar()`）: **1演目を選んで、その演目の空き状況を月カレンダーでヒートマップ表示**する。演目ピッカー（タブ1と共有）＋前の月/次の月。各日を `st.columns(7)` の `st.button` グリッドで描き、その日の最良ステータス（`capacity_status`）に応じて **緑=空きあり / 黄=残りわずか / 赤=満員 / グレー=開催なし**（`CAL_COLORS`）で塗る。日をタップすると下にその日の時間枠を表示（`render_event_day_slots()`）
  - **演目選択はタブ1とカレンダーで共有**：真の状態は `st.session_state["sel_event"]`、各ピッカー（`ev_pick`/`cal_ev_pick`）はそれに追従。選択ロジックは `get_selected_event_name()` / `render_event_picker()`。保存は前と同じく on_change だけ・`_ev_user_set` ガード
  - **セルの色付け方法**：各日ボタンに `key=f"cal_{日付}"` を付けると Streamlit が `st-key-cal_<日付>` クラスを付与するので、`<style>` で `.st-key-cal_2026-06-06 button{background:...!important}` のように**日付ごとに色を当てる**（`type="primary"` 等では4色を出せないため）
  - **ハマりどころ**: `st.columns` はスマホ幅で既定だと縦積みになる。7列を横並びに保つため、カレンダーを `st.container(key="cal_grid")` で囲み、`.st-key-cal_grid [data-testid="stHorizontalBlock"]{flex-wrap:nowrap}` 等のCSSで上書きしている
  - **タブ維持**：`st.tabs` の選択はフロント側状態で再実行をまたいで保持される（カレンダーで日付や演目を操作してもカレンダータブに留まる）
- **タブ2の1日分の演目カード描画は `render_day_event_cards()` / `build_day_events()` に共通化**している
- 除外中演目は各タブの日付エリア下に**開閉式（`st.expander`）の赤チップバナー**で表示（`render_excluded_banner()`）。演目が多いとき邪魔にならないよう既定は閉じる

## デザイン方針

「A:クリーン」トーンで統一（白×青の洗練版）。Claude Design でトーン比較して決定した方向。

- 絵文字は使わない。アイコンは Material Symbols（`:material/xxx:`）か SVG で統一
- フォントは **Zen Kaku Gothic New**（Google Fonts を `@import`）。CSS変数 `--app-font` で管理
  - **注意**: `st.markdown` で描いたカスタムHTML（日付見出し・時刻・演目名・バッジ等）はStreamlit既定フォント(Source Sans)に上書きされるため、それらのクラスにだけ `font-family: var(--app-font) !important` を当てている
  - **`*`（全要素）には当てない**。Material Symbols のアイコン専用フォントまで上書きしてしまい、アイコンが文字名（例: `theater_comedy`）で表示されてしまうため
- カラートークンは `:root` のCSS変数で管理（`--accent: #2F6FED` 等）
- カード表示: `.slot-card`（タブ1の時間枠）、`.event-card`（タブ2の演目）。角丸12・軽いシャドウ
- 空き状況バッジ: 緑（ok）・黄（warn）・赤（full）・グレー（unknown）。左に状態ドット（`::before`）。`warn` は色のみで表現しテキストは「残りN人」（「N人には不足」は付けない）
- 日付見出し `day_head_html()`: 曜日カラー（土=青 / 日=赤）＋罫線＋右側に「空きN枠 / N演目」。タブ1/2共通
- 予約ボタン `.book-btn`: 単色アクセント＋外部リンク矢印SVG（`BOOK_ARROW`）
- 演目メタ情報はチップ表示（`.meta-row` / `.meta-chip`）
- サイドバーは Streamlit 標準ウィジェットを `data-testid` セレクタでモック風に寄せている（人数ステッパー・チェックボックス・ポップオーバー・更新ボタン）。完全一致はできず、Streamlitバージョンで `data-testid` が変わると一部効かなくなる点に注意
- `inject_css()` に全カスタムCSSをまとめている

## 将来の予定

- Notion の「体験済みイベントリスト」と照合して未体験のみ検索対象にする機能
  - 現在は `load_excluded_events()` がlocalStorageから読む実装になっているので、ここを Notion API 取得に差し替えれば対応できる
