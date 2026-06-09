# リアル脱出ゲーム 名古屋 チケット空き状況チェッカー

名古屋店のリアル脱出ゲームチケットの空き状況を確認できる **静的Webアプリ（GitHub Pages）**。

公開URL: **https://tsuka911.github.io/escape/**

サーバーは使わず、空き状況は**ブラウザから公式APIを直接ライブ取得**する。だから起動待ち（スリープ）が無く、常に最新が見られる。

## 機能

- **演目から探す** — 演目を選んで、期間内の空き枠を時間帯カードで確認
- **日付から探す** — 日付範囲を指定して、その日程に開催される全演目の空き状況を確認
- **カレンダー** — 1演目を選んで、月ごとの空き状況をヒートマップ（緑/黄/赤）で表示。日をタップでその日の枠を表示
- 空き状況を緑（余裕）・黄（人数に不足の可能性）・赤（満員）で色分け表示
- 参加人数を入力すると、その人数で参加できるかをチェック
- 気になる演目は予約ページへ直接リンク

### 設定（上部の「設定」パネル）

| 設定項目 | 内容 |
|---|---|
| 参加予定人数 | この人数で参加できるか判定するのに使用 |
| 満員の枠を非表示 | チェックすると満員枠を非表示にする |
| 絞り込み（種別・時間帯） | 未選択＝すべて表示。タップで絞り込み |
| 検索から除外する演目 | 体験済みなど不要な演目をチェックで除外 |
| データを今すぐ更新 | 取得キャッシュをクリアして最新情報を再取得 |

設定はブラウザの localStorage に端末ごと保存され、次回も維持される。

## 仕組み

- **空き状況・チケット情報**: アプリ（`docs/app.js`）が**ブラウザから公式API `api.scrapmagazine.com` を直接fetch**（CORS `*` 許可済み）。ユーザー操作（演目選択・検索ボタン・月送り）が起点。結果は10分キャッシュ
- **演目メタ情報**（種別・最大人数・随時判定）: 公式サイト `realdgame.jp` 由来でブラウザから直接取れない（CORS不可）ため、**GitHub Actions が週1回**スクレイプして `docs/data/catalog.json` に焼き出す（`build_catalog.py`）

## ローカルでの確認方法

```bash
cd ~/Vibes/escape

# 静的サイトを配信（data/catalog.json への相対fetchのためサーバー配信が必要）
python3 -m http.server 8765 --directory docs
# → ブラウザで http://localhost:8765/ を開く

# 演目カタログ(catalog.json)を再生成したいとき
pip install requests beautifulsoup4   # 初回のみ
python3 build_catalog.py
```

## ファイル構成

```
escape/
├── docs/                       # 本体（GitHub Pages で公開）
│   ├── index.html                  # アプリのHTML土台（apple-touch-iconもここ）
│   ├── app.js                      # 本体ロジック（ライブfetch・3ビュー・設定）
│   ├── style.css                   # スタイル（白×青のクリーントーン）
│   ├── icon.png                    # ホーム画面アイコン（180×180）
│   └── data/
│       └── catalog.json            # 演目メタ（週1回 Actions が自動更新）
├── build_catalog.py            # catalog.json 生成スクリプト（scraper.py を流用）
├── .github/workflows/
│   └── build-catalog.yml       # 週1回＋手動＋push時に catalog.json を更新
├── scraper.py                  # 公式サイト/APIアクセス（build_catalog.py から使用）
├── app.py                      # 旧Streamlit UI（引退・参照用に残置）
├── requirements.txt            # 旧Streamlit用（残置）
└── .streamlit/config.toml      # 旧Streamlit用（残置）
```

## デザイン

「クリーン」トーン（白×青を洗練）で統一。フォントは Zen Kaku Gothic New、
空き状況は緑/黄/赤のバッジ、曜日カラー（土=青・日=赤）でひと目で分かるレイアウト。

## デプロイ

**GitHub Pages**（Settings→Pages→`main`ブランチ`/docs`）。`main` へのプッシュで自動反映。

> 以前は Streamlit Community Cloud を使っていたが、12時間アクセスが無いとスリープして
> 起動に数十秒かかる問題があったため、静的サイトに移行して引退した。

## iPhoneホーム画面アイコン

- iOSは「ホーム画面に追加」時、ページ最初のHTMLの`<head>`にある`apple-touch-icon`しか読まない。
- いま `docs/index.html` がアプリ本体そのもので、その`<head>`に`apple-touch-icon`があるため条件を満たす。
- **ホーム画面に追加するURLは** `https://tsuka911.github.io/escape/`。
- アイコンを変えるときは `docs/icon.png`（180×180の正方形）を差し替える。
