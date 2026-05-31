# リアル脱出ゲーム 名古屋 チケット空き状況チェッカー

名古屋店のリアル脱出ゲームチケットの空き状況を確認できる Streamlit アプリ。

## 機能

- **演目から探す** — 演目を選んで、期間内の空き枠を時間帯カードで確認
- **日付から探す** — 日付範囲を指定して、その日程に開催される全演目の空き状況を確認
- 空き状況を緑（余裕）・黄（人数に不足の可能性）・赤（満員）で色分け表示
- 参加人数を入力すると、その人数で参加できるかをチェック
- 気になる演目は予約ページへ直接リンク

### サイドバーの設定

| 設定項目 | 内容 |
|---|---|
| 参加予定人数 | この人数で参加できるか判定するのに使用 |
| 満員の枠を非表示 | チェックすると満員枠を非表示にする |
| 検索から除外する演目 | 体験済みなど不要な演目をチェックで除外（設定は再起動後も維持） |
| データを今すぐ更新 | キャッシュ（メモリ・ファイルの両方）をクリアして最新情報を取得 |

## ローカルでの起動方法

```bash
# リポジトリをクローン
cd ~/Vibes/escape

# 依存ライブラリをインストール（初回のみ）
pip install -r requirements.txt

# アプリを起動
streamlit run app.py
```

ブラウザが自動で開きます。手動で開く場合は `http://localhost:8501` にアクセス。

## ファイル構成

```
escape/
├── app.py              # Streamlit UI（画面の描画・設定・カード表示）
├── scraper.py          # データ取得（スクレイピング・公式API呼び出し）
├── requirements.txt    # 依存ライブラリ
├── icon.png            # アプリのアイコン（Streamlitのページアイコン／favicon用）
├── docs/               # GitHub Pages 用の「入口ページ」（iPhoneアイコン対応）
│   ├── index.html          # apple-touch-iconを持ち、アプリへ転送する入口
│   └── icon.png            # ホーム画面アイコン（180×180）
├── data/
│   ├── cache.json          # スクレイピング・APIのキャッシュ（git管理外）
│   └── user_settings.json  # ユーザー設定（除外演目など、git管理外）
└── .streamlit/
    └── config.toml     # テーマ設定（薄グレー背景・青アクセント #2F6FED）
```

## デザイン

「クリーン」トーン（白×青を洗練）で統一。フォントは Zen Kaku Gothic New、
空き状況は緑/黄/赤のバッジ、曜日カラー（土=青・日=赤）でひと目で分かるレイアウト。

## データの取得元

- **演目メタ情報**（種別・最大人数など）: 公式サイト `realdgame.jp/shop/nagoya/events/` をスクレイピング（24時間キャッシュ）
- **空き状況・チケット情報**: 公式API `api.scrapmagazine.com` を使用（2時間キャッシュ）

## デプロイ

**Streamlit Community Cloud** を使用。`main` ブランチへのプッシュで自動反映。
（公開URL: `https://escapefromtickets.streamlit.app/`）

## iPhoneホーム画面アイコン

ホーム画面アイコンは **GitHub Pages の入口ページ**（`docs/`）で出している。

- iOSは「ホーム画面に追加」時、ページ最初のHTMLの`<head>`にある`apple-touch-icon`しか読まない。Streamlit Cloudはこの最初のHTMLを編集できないため、Streamlit内のJS挿入ではアイコンを出せない。
- そこで `docs/index.html`（最初から`apple-touch-icon`を持ち、開くとアプリへ転送する軽量ページ）を GitHub Pages（Settings→Pages→`main`ブランチ`/docs`）で公開している。
- **ホーム画面に追加するURLはこの入口ページ** `https://tsuka911.github.io/escape/`（Streamlit直URLではない）。
- ホーム画面アイコンを変えるときは `docs/icon.png`（180×180の正方形）を差し替える。
