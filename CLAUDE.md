# CLAUDE.md — このプロジェクトについて

## アプリの概要

名古屋のリアル脱出ゲームのチケット空き状況を確認するアプリ。

- **構成: GitHub Pages の静的サイト（HTML/CSS/JS）**。サーバー無し。
  - 公開URL（ホーム画面アイコンの飛び先）: `https://tsuka911.github.io/escape/`
  - 空き状況は**ブラウザから公式API（`api.scrapmagazine.com`）を直接ライブ取得**する（CORS `*` 許可を確認済み）。だから「起動待ち」が無い・常に最新が取れる
  - 演目メタ情報（種別・最大人数・随時判定）だけは公式サイト `realdgame.jp` のHTML由来でブラウザから直接取れない（CORS不可）ため、**GitHub Actions が週1回 `docs/data/catalog.json` に焼き出す**
- ブランチ: `main` のみ。GitHub Pages 設定は Settings→Pages→`main`ブランチ`/docs`
- **旧構成（Streamlit Community Cloud）は引退**。理由: 12時間アクセスが無いとスリープし、起動に数十秒待たされるため。`app.py`/`scraper.py` は残してあるがデプロイ対象ではなく、`build_catalog.py` がメタ生成に `scraper.py` を流用するだけ

## ファイル構成と役割

| ファイル | 役割 |
|---|---|
| `docs/index.html` | **本体アプリのHTML土台**（ヘッダー・画面切替・設定パネル・3ビューのコンテナ）。iPhoneホーム画面アイコンの `apple-touch-icon` もここ |
| `docs/app.js` | **アプリ本体のロジック**。catalog.json読込・公式APIへのライブfetch・3ビュー描画・localStorage設定・カレンダー |
| `docs/style.css` | 全スタイル（A:クリーン トーン。旧 `app.py` の `inject_css()` から移植） |
| `docs/data/catalog.json` | **週1回ビルドの演目カタログ**（updated_at・演目シード一覧・メタ索引 by_url/by_title）。git管理する（Actionsが自動コミット） |
| `docs/icon.png` | ホーム画面アイコン（180×180） |
| `build_catalog.py` | catalog.json を生成するビルドスクリプト。`scraper.py` の `fetch_event_meta()`/`list_events()` を流用 |
| `.github/workflows/build-catalog.yml` | 週1回＋手動＋push時に `build_catalog.py` を実行し catalog.json をコミット |
| `scraper.py` | 公式サイトのスクレイピング＆API呼び出し。**今は `build_catalog.py` からのみ使用** |
| `app.py` | 旧Streamlit UI。**引退（デプロイしない）**。ロジックの参照元として残置 |
| `.streamlit/`, `requirements.txt` | 旧Streamlit用。残置 |

## データ取得の仕組み（重要）

2系統に分かれている：

1. **演目メタ情報**（種別=ホール型/ルーム型・最大人数・随時スタート判定）
   - 元は `realdgame.jp` のHTML。ブラウザからは**CORSで取れない**ので、GitHub Actionsが週1回 `build_catalog.py` を回して `docs/data/catalog.json` に書き出す
   - メタは数週間〜数ヶ月に1回しか変わらないので週1で十分。新演目が出たらワークフローを手動実行（`workflow_dispatch`）すれば即更新できる
2. **チケット・空き状況**
   - `docs/app.js` の `fetchTicketsForDate()` が**ブラウザから公式API（`api.scrapmagazine.com`）を直接fetch**（pagination込み）。ユーザー操作（演目選択・検索ボタン・月送り）が起点
   - 取得結果は **メモリ＋localStorage に10分キャッシュ**（`escape_tickets_<日付>` / `TICKET_TTL_MS`）。「データを今すぐ更新」ボタンで全キャッシュを消して再取得
   - 複数日は `fetchSchedule()` が同時実行数4で並列取得

- **CORS依存に注意**: 公式APIが将来CORSを絞るとライブ取得が止まる（可能性は低い）。その場合の保険は「Actionsで空き状況も定期スナップショット化してフォールバック」。現状は未実装
- ロジックは旧 `scraper.py`/`app.py` からJSへ1対1移植（`capacityStatus`/`slotPeriod`/`typeCategory`/`eventPassesType`/`filterSlots`/`normalizeTitle`/`lookupMeta`/`buildDayEvents` など）。挙動を変えるときは両方の整合に注意

## ユーザー設定の永続化（localStorage）

- 参加人数・満員非表示・絞り込み（種別/時間帯）・除外演目・前回選んだ演目を **ブラウザのlocalStorage** に端末ごと保存（`app.js` の `LS` 定数）。
  - キー: `escape_group_size` / `escape_hide_full` / `escape_filter_types` / `escape_filter_times` / `escape_excluded_events` / `escape_last_event`
  - **JSではネイティブに扱える**ので、旧Streamlit版にあった「読み込み直後の上書き事故」対策（`_xxx_user_set` フラグ・on_change限定保存・`st.stop()`禁止）は**不要になった**。`saveSetting()` で直接読み書きする
  - 注意: 旧Streamlit版は `streamlit.app` オリジンに保存していた。静的サイトは `github.io` オリジンなので、移行時に既存端末の設定は一度だけリセットされる（実害小）

## iPhoneホーム画面アイコン（重要・ハマりどころ）

- iOS Safariは「ホーム画面に追加」時、**最初に読み込んだHTMLの`<head>`にある`apple-touch-icon`しか読まない**。JSで後から差し込んだものは無視する。
- いま入口（`docs/index.html`）が本体アプリそのものなので、その`<head>`に `apple-touch-icon` がある（条件を満たす）。
  - GitHub Pages設定: Settings→Pages→`main`ブランチ`/docs`
  - **ホーム画面に追加するURLは** `https://tsuka911.github.io/escape/`
  - アイコンを変える時は `docs/icon.png` を180×180で差し替える
- （旧Streamlit版で「Streamlitの`<head>`を編集できずアイコンが出せない」問題があったが、静的サイト化で解消。`app.py`内でアイコンを出そうとしないこと＝もう不要）

## 検索から除外される演目

- コードレベルのキーワード除外: `scraper.py` の `EXCLUDE_TITLE_KEYWORDS = ("街歩き",)`、`app.js` の `EXCLUDE_TITLE_KEYWORDS = ['街歩き']`（両方に同じ定義。片方だけ直さないこと）
- 随時スタートの演目は `is_anytime` フラグで除外（`app.js` の `integrateRows()` がメタを見て除外）
- ユーザーが手動で除外した演目は localStorage（`escape_excluded_events`）に保存

## UIの構成（docs/app.js）

- **設定パネル**（`<details class="panel">`、旧サイドバー相当）: 参加人数ステッパー・満員非表示・絞り込み（種別/時間帯の `pill`、未選択＝全部表示）・除外演目チェックリスト・「データを今すぐ更新」。スマホ主体なので上部の開閉式パネルにした
- **画面切り替え**: 上部の3ボタン（`.view-switch`）。`S.activeView`（`event`/`date`/`calendar`）を保持し `renderActiveView()` で該当ビューだけ描画
- **演目から探す**（`renderEventView`）: 演目ピッカー（モーダルのタップ選択。キーボードを出さない）→ 日付範囲（開閉式・クイック選択）→「この条件で空きを検索」ボタンで `runEventSearch()` がライブ取得 → 時間枠カード
- **日付から探す**（`renderDateView`）: 日付範囲＋並び順（`.segmented` 空き多い順/演目名順）→「この期間で空きを検索」→ 日別の演目カード（`dayEventCardsHTML`/`buildDayEvents`）
- **カレンダー**（`renderCalendarView`）: 1演目を選んで月ヒートマップ（緑=空きあり/黄=わずか/赤=満員/グレー=開催なし）。日タップで下にその日の枠（`renderCalDrill`）。演目選択は「演目から探す」と `S.selEvent` で共有
- **取得トリガーはユーザー操作**（演目選択・検索ボタン・月送り）。開いた瞬間の自動フェッチはしない方針
- 除外中演目は各ビューで開閉式バナー（`excludedBannerHTML`）

## デザイン方針

「A:クリーン」トーン（白×青）。`docs/style.css` に集約。

- 絵文字は使わない。アイコンはインラインSVGで統一
- フォントは **Zen Kaku Gothic New**（Google Fonts を `@import`）。CSS変数 `--app-font`
- カラートークンは `:root` のCSS変数（`--accent: #2F6FED` 等）
- カード: `.slot-card`（時間枠）/`.event-card`（演目）。角丸12・軽いシャドウ
- 空き状況バッジ/チップ: 緑(`s-ok`)・黄(`s-warn`)・赤(`s-full`)・グレー(`s-unknown`)
- カレンダーのヒートマップ色は `.cal-cell.s-ok/.s-warn/.s-full/.s-none`（CSS変数 `--cal-*`）
- 日付見出し `dayHeadHTML()`: 曜日カラー（土=青/日=赤）＋罫線＋右側ヒント。右側が長い場合は省略表示（`.day-count` の ellipsis）

## ローカルでの動かし方・検証

- 静的サイトの確認: `python3 -m http.server 8765 --directory docs` で配信し `http://localhost:8765/` を開く（`data/catalog.json` への相対fetchのためサーバー配信が必要）
- catalog.json の再生成: `python3 build_catalog.py`
- preview系ツールでの検証ポイント: 3ビュー表示・ライブfetch（ネットワークに `api.scrapmagazine.com` への直接リクエスト）・絞り込み/除外/並び順・カレンダー色分けとドリルイン・localStorage保持・スマホ幅で横スクロールが出ないこと

## 将来の予定

- Notion の「体験済みイベントリスト」と照合して未体験のみ検索対象にする機能
- 公式APIがCORSを絞った場合の保険として、空き状況の定期スナップショット化（フォールバック）
