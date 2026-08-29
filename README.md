# portfolio-manager

SBI証券・楽天証券の「保有商品一覧」画面を **ブラウザで保存したHTML** から読み取り、SQLite に蓄積するツール。

- ログイン自動化はしない（認証情報を保持せず、規約上も通常のブラウザ利用の範囲）
- LLM に読ませず決定的にパースする（列ズレを起こさない）
- 日付ごとのスナップショットとして保存し、証券会社・口座区分（NISA フラグ）で分析できる

## セットアップ

```powershell
pip install -e .[dev]
```

## 使い方

1. 証券会社サイトにログインし、保有一覧ページを開く
   - SBI証券: 口座管理 → 外国株式 → 保有銘柄（`/account/foreign/summary`）
   - 楽天証券: 口座管理 → 保有商品一覧 → すべて
2. `Ctrl+S` → 「ウェブページ、完全」で `imports/` に保存（ファイル名は任意）
3. 取り込む

```powershell
portfolio import imports/*.html            # 取込
portfolio import imports/*.html --dry-run  # 解析結果の確認だけ
portfolio import x.html --date 2026-08-29  # 日付を明示
portfolio show                             # 最新スナップショット
portfolio show --date 2026-08-29
portfolio dates                            # 取込済み日付一覧
```

`pip install -e .` していない場合は `PYTHONPATH=src python -m portfolio ...` で同じ。

## データ

`portfolio.db`（SQLite）

- `holdings` … 1行 = 1スナップショット日 × 証券会社 × 口座区分 × 銘柄
  - `broker` (`sbi` / `rakuten`)、`account_type`（特定 / NISA / NISA成長 …）、`is_nisa`（0/1）、`asset_class`（米国株式 / 国内株式 / 外貨建MMF / 現金 …）
  - `quantity, price, avg_cost, acquisition_amount, market_value, unrealized_pnl` と各 `*_jpy`（円換算）
  - 同じキーを再取込すると上書き（冪等）
- `raw_imports` … 取り込んだHTML原本（sha256 で重複排除）。パーサ修正後の再処理用
- `latest_holdings` ビュー … 証券会社ごとの最新日付の行

例: NISA 口座だけの評価額合計

```sql
SELECT broker, SUM(market_value_jpy) FROM latest_holdings WHERE is_nisa = 1 GROUP BY broker;
```

## 注意

- 楽天証券の画面は年を表示しないため、保存ファイルの更新日時から年を補完する。古いファイルを後から取り込む場合は `--date` を指定する
- 楽天証券の「時価評価額合計」は画面側が行ごとに円未満を丸めているため、行の合計と数円ずれることがある
- SBI証券は現状 **外国株式ページのみ** 対応。国内株式・投資信託ページは別構造なので未対応
- 楽天証券の国内株式・投資信託行はサンプル未確認（列構成が同じ前提で実装）

## テスト

```powershell
pytest
```
