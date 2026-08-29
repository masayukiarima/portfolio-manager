# portfolio-manager

SBI証券・楽天証券の「保有商品一覧」画面を **ブラウザで保存したHTML** から読み取り、SQLite に蓄積するツール。

- ログイン自動化はしない（認証情報を保持せず、規約上も通常のブラウザ利用の範囲）
- LLM に読ませず決定的にパースする（列ズレを起こさない）
- 日付ごとのスナップショットとして保存し、証券会社・口座区分（NISA フラグ）で分析できる

## セットアップ

[uv](https://docs.astral.sh/uv/) を使う。Python 3.11 以上。

```powershell
uv sync --extra dev   # .venv 作成 + 依存関係 + portfolio コマンドをインストール
uv run pytest         # 動作確認
```

`uv run <コマンド>` で仮想環境を有効化せずに実行できる。明示的に有効化したい場合は `.\.venv\Scripts\Activate.ps1`。

## 使い方

### 1. 保有一覧ページを保存する

証券会社サイトにログインし、保有一覧ページを開いて `Ctrl+S` →「ウェブページ、完全」で `imports/` に保存する（ファイル名は任意。`imports/` は git 管理外）。

| 証券会社 | ページ |
|---|---|
| SBI証券 | 口座管理 → 外国株式 → 保有銘柄（`/account/foreign/summary`） |
| 楽天証券 | 口座管理 → 保有商品一覧 → すべて |

### 2. 取り込む

```powershell
uv run portfolio import imports/*.html             # 取込（証券会社は自動判定）
uv run portfolio import imports/*.html --dry-run   # DBに書かず解析結果だけ表示
uv run portfolio import imports/x.html --date 2026-08-29   # 日付を明示して取込
```

同じ日付・同じ銘柄は上書きされるので、何度実行しても重複しない。

### 3. 見る

```powershell
uv run portfolio show                    # 証券会社ごとの最新スナップショット + 集計
uv run portfolio show --date 2026-08-29  # 指定日
uv run portfolio dates                   # 取込済みの日付一覧
```

全コマンド共通で `--db path/to/file.db` を付けると DB ファイルを変更できる（既定: `./portfolio.db`）。

## データ

`portfolio.db`（SQLite、git 管理外）

### `holdings` テーブル

1行 = スナップショット日 × 証券会社 × 口座区分 × 商品種別 × 銘柄。

| 列 | 内容 |
|---|---|
| `snapshot_date` | 画面上の日付（YYYY-MM-DD） |
| `broker` | `sbi` / `rakuten` |
| `account_type` | `特定` / `一般` / `NISA` / `NISA成長` … 画面表記そのまま。預り金は `-` |
| `is_nisa` | NISA 口座なら 1 |
| `asset_class` | `米国株式` / `国内株式` / `投資信託` / `外貨建MMF` / `現金` … |
| `symbol` | ティッカー・銘柄コード（無い商品は銘柄名） |
| `name` / `market` / `currency` | 銘柄名 / 市場 / 通貨（`USD`, `JPY` …） |
| `quantity` | 保有数量（株数・口数） |
| `price`, `avg_cost`, `acquisition_amount`, `market_value`, `unrealized_pnl` | 現在値・平均取得単価・取得金額・評価額・評価損益（外貨建て商品は外貨） |
| `*_jpy` | 上記の円換算 |
| `unrealized_pnl_pct` | 評価損益率（%） |
| `source_file`, `imported_at` | 取込元ファイル名・取込日時 |

### その他

- `raw_imports` … 取り込んだ HTML 原本（sha256 で重複排除）。パーサ修正後に再処理するための保険
- `latest_holdings` ビュー … 証券会社ごとの最新日付の行だけを返す

### クエリ例

```sql
-- NISA 口座の評価額を証券会社別に
SELECT broker, SUM(market_value_jpy) FROM latest_holdings WHERE is_nisa = 1 GROUP BY broker;

-- 同一銘柄を証券会社・口座横断で合算
SELECT symbol, name, SUM(quantity) qty, SUM(market_value_jpy) mv
FROM latest_holdings WHERE asset_class = '米国株式' GROUP BY symbol ORDER BY mv DESC;

-- 評価額の推移
SELECT snapshot_date, broker, SUM(market_value_jpy) FROM holdings GROUP BY 1, 2 ORDER BY 1;
```

## 注意

- 楽天証券の画面は年を表示しないため、保存ファイルの更新日時から年を補完する。古いファイルを後から取り込む場合は `--date` を指定する
- 楽天証券の「時価評価額合計」は画面側が行ごとに円未満を丸めているため、行の合計と数円ずれることがある
- SBI証券は現状 **外国株式ページのみ** 対応。国内株式・投資信託ページは別構造なので未対応
- 楽天証券の国内株式・投資信託行は実サンプル未確認（列構成が同じ前提で実装）
- 保有一覧以外のページ（注文照会など）を渡すと「証券会社を判定できません」で読み飛ばす

## 開発

```
src/portfolio/
  models.py          Holding … 証券会社横断の共通レコード
  parsers/sbi.py     SBI 外国株式ページ（div 構造）
  parsers/rakuten.py 楽天 保有商品一覧（EUC-JP、table 構造）
  db.py              SQLite スキーマ・冪等 UPSERT・原本保存
  cli.py             import / show / dates
tests/               個人データを含まない合成フィクスチャでのテスト
```

```powershell
uv run pytest
```

pytest の一時フォルダは `.pytest_tmp/`（`pyproject.toml` で指定、git 管理外）。
