# CLAUDE.md — このプロジェクトについて

## アプリの概要

名古屋のリアル脱出ゲームのチケット空き状況を確認する Streamlit アプリ。

- デプロイ先: **Streamlit Community Cloud**（Vercel は使わない）
- ブランチ: `main` のみ。デプロイはプッシュで自動反映

## ファイル構成と役割

| ファイル | 役割 |
|---|---|
| `app.py` | Streamlit の UI 全体。CSS・カード描画・設定UIを含む |
| `scraper.py` | 公式サイトのスクレイピングとチケットAPIの呼び出し |
| `data/cache.json` | スクレイピング・APIのキャッシュ（git管理外） |
| `data/user_settings.json` | 除外演目などのユーザー設定（git管理外） |
| `.streamlit/config.toml` | テーマ（白ベース・青アクセント） |

## データ取得の仕組み

- **演目メタ情報**（種別・最大人数・随時スタート判定）: `fetch_event_meta()` で公式サイトをスクレイピング。24時間キャッシュ
- **チケット・空き状況**: `fetch_tickets_for_date()` で公式API（`api.scrapmagazine.com`）を叩く。2時間キャッシュ
- キャッシュは `data/cache.json` に保存。Streamlit の `@st.cache_data(ttl=7200)` でメモリにも2時間保持

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

- 絵文字は使わない。アイコンは Material Symbols（`:material/xxx:`）か SVG で統一
- カード表示: `.slot-card`（タブ1の時間枠）、`.event-card`（タブ2の演目）
- 空き状況バッジ: 緑（ok）・黄（warn）・赤（full）・グレー（unknown）
- `inject_css()` に全カスタムCSSをまとめている

## 将来の予定

- Notion の「体験済みイベントリスト」と照合して未体験のみ検索対象にする機能
  - 現在は `load_excluded_events()` がファイルから読む実装になっているので、ここを Notion API 取得に差し替えれば対応できる
