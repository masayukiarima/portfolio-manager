# portfolio-manager

SBI証券・楽天証券の「保有商品一覧」「注文照会」画面を **ブラウザで保存したHTML** から読み取り、SQLite に蓄積するツール。

- ログイン自動化はしない（認証情報を保持せず、規約上も通常のブラウザ利用の範囲）
- LLM に読ませず決定的にパースする（列ズレを起こさない）
- 日付ごとのスナップショットとして保存し、証券会社・口座区分（NISA フラグ）で分析できる

## セットアップ

[uv](https://docs.astral.sh/uv/) を使う。Python 3.11 以上。

```bash
uv sync --extra dev   # .venv 作成 + 依存関係 + portfolio コマンドをインストール
uv run pytest         # 動作確認
```

`uv run <コマンド>` で仮想環境を有効化せずに実行できる。

## 使い方

### 1. 画面を保存する

証券会社サイトにログインし、対象ページを開いて `Ctrl+S` →「ウェブページ、完全」で `imports/` 配下に保存する（ファイル名は任意。`imports/` は git 管理外）。ページ種別は内容から自動判定するので置き場所は自由だが、整理のため以下を推奨。

| 画面 | 保存先 | SBI証券 | 楽天証券 |
|---|---|---|---|
| 保有一覧（株式） | `imports/` | 口座管理 → 外国株式 → 保有銘柄 | 口座管理 → 保有商品一覧 → すべて |
| 注文照会 | `imports/orders/` | 取引 → 外国株式 → 注文照会 | 米国株式取引 → 注文照会・訂正・取消 |
| 保有一覧（国内株式・ETF + 投資信託） | `imports/funds/` | 口座管理 → 口座(円建) → 保有証券一覧（旧サイト） | （未対応） |
| 保有ファンド（投資信託のみ） | `imports/funds/` | 投資信託 → 保有ファンド ※任意 | （未対応） |
| 資産残高サマリ（現金含む） | `imports/assets/` | My資産 → 資産残高（「詳細を表示する」を開いてから保存） | 保有商品一覧の上部から自動取得（別ページ不要） |

- SBI の「保有証券一覧」は国内株式と投資信託の両方を含むので、これ1枚で `holdings`（国内株式）と `funds` の両方に入る。「保有ファンド」ページは同じ投信データに **前日比と積立設定中フラグ** を足すだけなので、不要なら保存しなくてよい（両方取り込んだ場合は同じ行が上書きされ、後から取り込んだ方が残る）
- SBI の保有証券一覧・保有ファンド画面には日付が表示されないため、保存ファイルの更新日時が `snapshot_date` になる。別の日に取り込む場合は `--date` で指定する

### 2. 取り込む

```bash
uv run portfolio import                   # imports/ 配下の HTML をすべて取込（保有/注文は自動判定）
uv run portfolio import imports/*.html    # ファイル指定
uv run portfolio import --dry-run         # DBに書かず解析結果だけ表示
uv run portfolio import x.html --date 2026-08-29   # 日付を明示して取込
```

同じ日付・同じ銘柄（注文）は上書きされるので、何度実行しても重複しない。

### 3. 見る

```bash
uv run portfolio show                    # 証券会社ごとの最新の保有状況 + 集計
uv run portfolio orders                  # 証券会社ごとの最新の注文状況
uv run portfolio funds                   # 証券会社ごとの最新の保有ファンド + 集計
uv run portfolio balances                # 商品区分別の評価額・預り金・銀行残高 + 現金同等物の合計
uv run portfolio show --date 2026-08-29  # 指定日（orders / funds / balances も同様）
uv run portfolio dates                   # 取込済みの日付一覧
```

全コマンド共通で `--db path/to/file.db` を付けると DB ファイルを変更できる（既定: `./portfolio.db`）。

### 4. 画面から取れない資産を手入力する

別口座の現金や暗号資産など。日付付きのスナップショットなので、値が変わったら同じ名前で追加すれば履歴になる。

```bash
uv run portfolio manual add "別口座現金" 1800000                                  # 既定: 現金同等物 / JPY / 今日
uv run portfolio manual add "BTC/ETH" 2700000 --class 暗号資産 --currency BTC
uv run portfolio manual add "別口座現金" 1500000 --date 2026-09-15                # 更新（履歴として残る）
uv run portfolio manual list
uv run portfolio manual delete "BTC/ETH" --date 2026-08-30
```

資産クラスは `米国株式 / 投資信託 / 金 / 国内株式 / 暗号資産 / 現金同等物 / その他`。

### 5. 銘柄の資産クラスを上書きする

分析では保有銘柄を上の資産クラスに振り分ける。既定で金 ETF（GLDM, GLD, IAU, 1540, 1326）は「金」。それ以外を変えたいとき:

```bash
uv run portfolio classify              # 既定と上書きの一覧
uv run portfolio classify PBR その他    # 上書き
uv run portfolio classify PBR --reset  # 上書きを削除
```

### 6. 分析レポート（HTML）

```bash
uv run portfolio report                 # report.html を生成（git 管理外）
uv run portfolio report --open          # 生成してブラウザで開く
uv run portfolio report -o docs/2026-08-30.html
```

外部依存なしの単一 HTML。内容:
- 総資産・含み益・NISA 残高・特定口座含み益（税額目安）・米国株比率・現金比率・逆指値カバー率
- **資産配分**（ドーナツ）と **通貨エクスポージャ**、現金同等物の内訳
- **資産推移**（積み上げ面グラフ + 合計線、ホバーで日付ごとの内訳、表切替）
- 上位ポジション（証券会社・口座横断）

推移は「各日付時点で、証券会社×テーブルごとの最新スナップショットを合算」する。取込していない日は前回値を引き継ぐので、ページによって保存日がずれても総資産が欠けない。

### 7. SQL で直接確認する

#### `portfolio sql`（sqlite3 CLI 不要）

Python 内蔵の SQLite で任意の SQL を実行する。

```bash
uv run portfolio sql "SELECT name FROM sqlite_master WHERE type IN ('table','view')"   # テーブル・ビュー一覧
uv run portfolio sql "PRAGMA table_info(orders)"                                        # 列定義
uv run portfolio sql "SELECT * FROM latest_orders WHERE broker = 'sbi'"
uv run portfolio sql --csv "SELECT * FROM latest_holdings" > holdings.csv               # CSV 出力
uv run portfolio sql -f query.sql                                                       # ファイルから実行
```

#### sqlite3 CLI を使う場合

対話的に触りたければ公式 CLI を入れる（Git Bash からは `winpty` を付けると対話モードが安定する）。

```bash
winget install SQLite.SQLite          # インストール（PowerShell/コマンドプロンプトで一度だけ）
winpty sqlite3 portfolio.db           # 対話モード
sqlite3 -header -column portfolio.db "SELECT * FROM latest_orders"   # ワンライナー
```

対話モードでよく使うメタコマンド:

```
.tables                  テーブル・ビュー一覧
.schema orders           テーブル定義
.headers on / .mode column   見やすい表形式
.mode csv / .output x.csv    CSV に書き出し（.output stdout で戻す）
.quit
```

#### GUI

[DB Browser for SQLite](https://sqlitebrowser.org/)（`winget install DBBrowserForSQLite.DBBrowserForSQLite`）で `portfolio.db` を開くと、テーブル閲覧・SQL 実行・CSV エクスポートが GUI でできる。取込中に GUI 側で書き込みロックを掴んでいると `import` が失敗するので、閲覧専用で開くこと。

## データ

`portfolio.db`（SQLite、git 管理外）

### `holdings` テーブル — 保有状況

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

### `orders` テーブル — 注文状況

1行 = スナップショット日 × 証券会社 × 注文。同じ注文でも日付ごとに行が残るので、状況（執行待ち → 約定など）の推移を追える。

| 列 | 内容 |
|---|---|
| `snapshot_date`, `broker`, `account_type`, `is_nisa`, `asset_class`, `symbol`, `name`, `market`, `currency` | `holdings` と同じ |
| `order_key` | 証券会社内で注文を識別するキー。楽天は注文番号、SBI は画面に番号が無いため `注文日時|銘柄|売買|数量|単価` の合成 |
| `order_no` / `linked_order_no` | 注文番号 / 関連注文番号（楽天の `(a-0324-2)` など） |
| `ordered_at` / `expires_on` | 注文日時 / 有効期限 |
| `status` | `注文中` / `待機中`（SBI）、`執行待ち` / `執行待ち（繰越）`（楽天）など画面表記そのまま |
| `side` | `買` / `売` |
| `quantity` / `filled_quantity` | 注文数量 / 約定数量 |
| `order_type` | `指値` / `成行` / `逆指値` / `逆指値/成行` |
| `limit_price` / `trigger_price` | 指値 / 逆指値のトリガー価格（条件文から抽出） |
| `current_price` / `avg_fill_price` | 現在値・平均約定単価（SBI のみ） |
| `settlement` | `外貨決済` / `円貨決済` |
| `condition` | 逆指値条件・IFD などの補足テキスト（複数行は ` / ` で連結） |

### `funds` テーブル — 保有ファンド（投資信託）

1行 = スナップショット日 × 証券会社 × 口座区分 × ファンド名。すべて円建て。

| 列 | 内容 |
|---|---|
| `snapshot_date`, `broker`, `is_nisa` | `holdings` と同じ |
| `account_type` | `特定` / `NISAつみたて` / `NISA成長` / `旧つみたてNISA` … |
| `name` | ファンド名（画面表記そのまま、全角） |
| `units` / `selling_units` | 保有口数 / 売却注文中の口数 |
| `nav` / `avg_cost` | 基準価額 / 取得単価（いずれも 1万口あたり・円） |
| `market_value_jpy`, `acquisition_amount_jpy`, `unrealized_pnl_jpy`, `unrealized_pnl_pct` | 評価額・取得金額・評価損益・損益率 |
| `day_change_jpy` / `day_change_pct` | 前日比 |
| `is_accumulating` | 積立設定中なら 1 |

### `balances` テーブル — 資産残高サマリ（現金・銀行残高を含む）

1行 = スナップショット日 × 証券会社 × 区分。SBI は My資産ページから、楽天は保有商品一覧の上部テーブルから取る。

| 列 | 内容 |
|---|---|
| `category` | 正規化した区分: `国内株式` / `米国株式` / `投資信託` / `外貨建MMF` / `預り金(JPY)` / `預り金(USD)` / `預り金(外貨)` / `預り金合計` / `銀行口座` / `合計` / `保有商品合計` … |
| `label` | 画面表記そのまま（`スィープ専用銀行口座`、`楽天銀行普通預金残高` など） |
| `market_value_jpy`, `unrealized_pnl_jpy`, `unrealized_pnl_pct` | 評価額・評価損益・損益率 |
| `day_change_jpy` / `day_change_pct`, `month_change_jpy` / `month_change_pct` | 前日比・前月比 |
| `realized_pnl_jpy` | 実現損益（楽天のみ） |
| `is_cash` | 現金同等物（預り金・MMF・MRF・銀行残高・保証金）なら 1 |
| `is_total` | 合計行なら 1（集計時は除外する） |

保有ゼロの区分は取り込まない。楽天の保有一覧を取り込むと `holdings` と同時に `balances` にも入る。

### その他

- `raw_imports` … 取り込んだ HTML 原本（sha256 で重複排除、`kind` = holdings/orders/funds/balances）。パーサ修正後に再処理するための保険
- `latest_holdings` / `latest_orders` / `latest_funds` / `latest_balances` ビュー … 証券会社ごとの最新日付の行だけを返す

### クエリ例

```sql
-- NISA 口座の評価額を証券会社別に
SELECT broker, SUM(market_value_jpy) FROM latest_holdings WHERE is_nisa = 1 GROUP BY broker;

-- 同一銘柄を証券会社・口座横断で合算
SELECT symbol, name, SUM(quantity) qty, SUM(market_value_jpy) mv
FROM latest_holdings WHERE asset_class = '米国株式' GROUP BY symbol ORDER BY mv DESC;

-- 評価額の推移
SELECT snapshot_date, broker, SUM(market_value_jpy) FROM holdings GROUP BY 1, 2 ORDER BY 1;

-- 現金同等物（預り金・MMF・銀行残高）の合計
SELECT broker, SUM(market_value_jpy) FROM latest_balances WHERE is_cash = 1 AND is_total = 0 GROUP BY broker;

-- 証券会社が計算した総資産（合計行）の推移
SELECT snapshot_date, broker, market_value_jpy FROM balances WHERE category = '合計' ORDER BY 1, 2;

-- 株式 + 投資信託を合わせた総資産（証券会社 × NISA 区分）
SELECT broker, is_nisa, SUM(mv) AS market_value_jpy FROM (
  SELECT broker, is_nisa, market_value_jpy AS mv FROM latest_holdings
  UNION ALL
  SELECT broker, is_nisa, market_value_jpy FROM latest_funds
) GROUP BY 1, 2;

-- 逆指値（損切り）が現在値からどれだけ下にあるか
SELECT o.broker, o.symbol, h.price, o.trigger_price,
       ROUND((o.trigger_price / h.price - 1) * 100, 1) AS pct
FROM latest_orders o
JOIN latest_holdings h ON h.broker = o.broker AND h.symbol = o.symbol AND h.asset_class = '米国株式'
WHERE o.side = '売' AND o.trigger_price IS NOT NULL ORDER BY pct;
```

## 注意

- 楽天証券の画面は年を表示しないため、保存ファイルの更新日時から年を補完する。古いファイルを後から取り込む場合は `--date` を指定する
- 楽天証券の「時価評価額合計」は画面側が行ごとに円未満を丸めているため、行の合計と数円ずれることがある
- 対応済みは **米国株式（外国株式）ページ、SBI の保有証券一覧（国内株式 + 投資信託）、SBI の保有ファンド・My資産**。楽天の投資信託ページ・国内株式注文照会は別構造なので未対応
- 楽天証券の保有一覧の国内株式・投資信託行は実サンプル未確認（列構成が同じ前提で実装）
- 同じ日付の取込は上書きされる（行は増えない）。ただし同日中に売却して銘柄が減った場合、前回取込の行は残るので、その日の行を `portfolio sql "DELETE FROM holdings WHERE snapshot_date = '...' AND broker = '...'"` で消してから再取込する
- 対象外のページを渡すと「証券会社・画面種別を判定できません」で読み飛ばす。「ウェブページ、完全」が作る `*_files/` フォルダ内の HTML は自動的に無視する

## 開発

```
src/portfolio/
  models.py                  Holding / Order / Fund / Balance … 証券会社横断の共通レコード
  parsers/__init__.py        文字コード判定・ページ種別判定（broker × holdings/orders）
  parsers/sbi.py             SBI 外国株式 保有銘柄（div 構造）
  parsers/sbi_orders.py      SBI 外国株式 注文照会
  parsers/sbi_account.py     SBI 保有証券一覧（旧サイト、国内株式 + 投資信託 → holdings と funds）
  parsers/sbi_funds.py       SBI 投資信託 保有ファンド
  parsers/sbi_assets.py      SBI My資産 資産残高（商品区分別・預り金・スイープ口座）
  parsers/rakuten.py         楽天 保有商品一覧（EUC-JP、table 構造）+ 上部の資産残高テーブル
  parsers/rakuten_orders.py  楽天 米国株式 注文照会
  db.py                      SQLite スキーマ・冪等 UPSERT・原本保存・列追加マイグレーション・手入力資産・銘柄分類
  analysis.py                資産クラス別の配分・推移・指標（NISA、税、通貨、逆指値カバー率）の計算
  report.py                  分析結果を自己完結 HTML（インライン SVG）に描画
  cli.py                     import / show / orders / funds / balances / dates / manual / classify / report / sql
tests/                       個人データを含まない合成フィクスチャでのテスト
```

```bash
uv run pytest
```

pytest の一時フォルダは `.pytest_tmp/`（`pyproject.toml` で指定、git 管理外）。
