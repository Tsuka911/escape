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
| `data/user_settings.json` | 除外演目などのユーザー設定（git管理外） |
| `.streamlit/config.toml` | テーマ（背景 `#F5F7FA`・サイドバー `#FBFCFE`・青アクセント `#2F6FED`） |
| `icon.png` | Streamlitのページアイコン（favicon）。`app.py` の `st.set_page_config(page_icon=...)` で使用 |
| `docs/index.html` | **GitHub Pages の入口ページ**（iPhoneホーム画面アイコン用） |
| `docs/icon.png` | 入口ページが使うホーム画面アイコン（180×180） |

## データ取得の仕組み

- **演目メタ情報**（種別・最大人数・随時スタート判定）: `fetch_event_meta()` で公式サイトをスクレイピング。24時間キャッシュ
- **チケット・空き状況**: `fetch_tickets_for_date()` で公式API（`api.scrapmagazine.com`）を叩く。2時間キャッシュ
- キャッシュは `data/cache.json` に保存。Streamlit の `@st.cache_data(ttl=7200)` でメモリにも2時間保持
- **2層キャッシュに注意**: ①Streamlitメモリ（`@st.cache_data`）と ②scraperのファイル（`data/cache.json`）の2層がある。「データを今すぐ更新」ボタンは両方をクリアする必要があるため、`scraper.clear_cache()`（ファイル削除）＋ `st.cache_data.clear()`（メモリ）の両方を呼ぶ。片方だけだと最終更新時刻が変わらない

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

- **サイドバー**: 参加人数・満員非表示・除外演目設定（ポップアップ式チェックボックス）・更新ボタン
- **タブ1「演目から探す」**: 演目セレクトボックス → 日付範囲 → 時間枠カードのグリッド表示
- **タブ2「日付から探す」**: 日付範囲（クイック選択ボタン付き） → 日付ごとに演目カードを表示
- 除外中演目は各タブの日付エリア下に赤チップのバナーで表示（`render_excluded_banner()`）

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
  - 現在は `load_excluded_events()` がファイルから読む実装になっているので、ここを Notion API 取得に差し替えれば対応できる
