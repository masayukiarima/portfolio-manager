"""Playwright で証券会社サイトの画面を開き、HTML を imports/ に保存する（Ctrl+S の代わり）。

設計原則:
- ログインは手動。ID・パスワード・デバイス認証コードをスクリプトに渡さない
- ブラウザは常に表示モード（headless にしない）。ログイン完了はページ状態で検知する
- やることは「認証済みのブラウザで画面を開いて DOM を保存する」まで。画像や CSS は
  パースに不要なので `page.content()`（テキスト DOM）だけを保存する
- ログイン状態は永続プロファイル（既定: tmp/pw-sbi、git 管理外）に残る。デバイス認証を
  済ませたプロファイルは他のスクリプトと共有してよいが、共有PCでは使わないこと

初回:
  uv sync --extra fetch
  uv run playwright install chromium
  uv run portfolio fetch --login-check
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = Path(os.environ.get("PORTFOLIO_PW_PROFILE", REPO / "tmp" / "pw-sbi"))
DEFAULT_IMPORT_DIR = REPO / "imports"

SBI_LOGIN_URL = "https://site1.sbisec.co.jp/ETGate/"
LOGIN_WAIT_SEC = 300
READY_WAIT_SEC = 30
LOGGED_IN_MARKER = "ログアウト"


@dataclass(frozen=True)
class PageSpec:
    key: str                 # ファイル名・コマンド引数に使う識別子
    broker: str
    url: str
    ready: tuple[str, ...]   # いずれかが本文に出たら描画完了とみなす（パーサの matches() と揃える）
    subdir: str              # imports/ 配下の保存先
    note: str = ""           # README・--help 向けの説明
    expand_buttons: tuple[str, ...] = field(default_factory=tuple)  # 保存前に押す展開ボタンの表示名


# 取込順に並べる。SBI の投信は「保有証券一覧」と「保有ファンド」の両方に載るので、
# 前日比・積立フラグを持つ保有ファンドを後にして上書きさせる。
PAGES: dict[str, PageSpec] = {
    "sbi-assets": PageSpec(
        key="sbi-assets", broker="sbi",
        url="https://site.sbisec.co.jp/account/assets",
        ready=("資産構成比率",), subdir="assets",
        note="My資産（商品区分別の評価額・預り金・銀行残高）",
        expand_buttons=("詳細を表示する",),
    ),
    "sbi-foreign": PageSpec(
        key="sbi-foreign", broker="sbi",
        url="https://member.c.sbisec.co.jp/foreign/account/assets",
        ready=("預り金", "外貨建MMF", "保有銘柄はありません"), subdir="",
        note="外国株式 > 保有銘柄（米国株・外貨建MMF・外貨預り金）",
    ),
    "sbi-account": PageSpec(
        key="sbi-account", broker="sbi",
        url=("https://site2.sbisec.co.jp/ETGate/?_ControlID=WPLETacR002Control&_PageID=DefaultPID"
             "&_DataStoreID=DSWPLETacR002Control&_ActionID=DefaultAID&getFlg=on"),
        ready=("保有証券一覧",), subdir="funds",
        note="口座管理 > 口座(円建) > 保有証券一覧（国内株式・ETF + 投資信託。旧サイト）",
    ),
    "sbi-funds": PageSpec(
        key="sbi-funds", broker="sbi",
        url="https://member.c.sbisec.co.jp/fund/account/assets",
        ready=("ファンド名", "保有ファンドはありません"), subdir="funds",
        note="投資信託 > 保有ファンド（前日比・積立設定中フラグ付き）",
    ),
    "sbi-orders": PageSpec(
        key="sbi-orders", broker="sbi",
        url="https://member.c.sbisec.co.jp/foreign/refer/us/stock",
        ready=("国内注文日時", "注文はありません", "該当する注文"), subdir="orders",
        note="外国株式 > 注文照会（米国株）",
    ),
}


def out_path(spec: PageSpec, base: Path, day: date) -> Path:
    return base / spec.subdir / f"{day:%Y%m%d}-{spec.key}.html"


def _body_text(page) -> str:
    try:
        return page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:  # noqa: BLE001 - ナビゲーション中は evaluate が失敗する
        return ""


def _has_any(page, texts: tuple[str, ...]) -> bool:
    body = _body_text(page)
    return any(t in body for t in texts)


def _wait_for_any(page, texts: tuple[str, ...], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _has_any(page, texts):
            return
        time.sleep(1)
    raise TimeoutError(f"{what} を {int(timeout)} 秒待ちましたが確認できませんでした")


def _launch(pw, profile: Path):
    profile.mkdir(parents=True, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(str(profile), headless=False, viewport={"width": 1400, "height": 1000})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def _goto(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:  # noqa: BLE001 - ポーリング系の通信で networkidle にならないサイトがある
        pass


def wait_for_login(page, timeout: float = LOGIN_WAIT_SEC) -> None:
    print(">> ブラウザでログイン（必要ならデバイス認証も）を完了してください。"
          f"完了を自動検知します（最大 {int(timeout)} 秒）…", flush=True)
    _wait_for_any(page, (LOGGED_IN_MARKER,), timeout, "ログイン完了")
    print(">> ログインを確認しました。", flush=True)


def login_check(profile: Path | None = None) -> None:
    from playwright.sync_api import sync_playwright

    profile = profile or DEFAULT_PROFILE
    with sync_playwright() as pw:
        ctx, page = _launch(pw, profile)
        _goto(page, SBI_LOGIN_URL)
        if not _has_any(page, (LOGGED_IN_MARKER,)):
            wait_for_login(page)
        ctx.close()
    print(f"プロファイルを保存しました: {profile}")


def _click_expand_buttons(page, labels: tuple[str, ...]) -> None:
    for label in labels:
        btn = page.get_by_role("button", name=label)
        try:
            n = btn.count()
            clicked = 0
            for i in range(n):
                b = btn.nth(i)
                if b.is_visible():
                    b.click()
                    clicked += 1
            if n:
                print(f"   「{label}」: {clicked}/{n} 個クリック", flush=True)
            if clicked:
                time.sleep(1)
        except Exception as e:  # noqa: BLE001 - 展開できなくても保存は続ける
            print(f"   「{label}」のクリックに失敗（{type(e).__name__}）。そのまま保存します", flush=True)


def _capture(page, spec: PageSpec) -> str:
    _goto(page, spec.url)
    if not _has_any(page, spec.ready):
        if not _has_any(page, (LOGGED_IN_MARKER,)):
            wait_for_login(page)
            _goto(page, spec.url)
        _wait_for_any(page, spec.ready, READY_WAIT_SEC, f"{spec.key} の描画（{' / '.join(spec.ready)}）")
    time.sleep(1)  # 目印が出た直後にまだ明細を描画中のことがあるので少し待つ
    _click_expand_buttons(page, spec.expand_buttons)
    # utf-8 で書き出すので、元ページの charset 宣言より先に utf-8 を宣言して decode_html に判定させる
    return f'<!-- saved by portfolio fetch from {spec.url} --><meta charset="utf-8">\n' + page.content()


def fetch(keys: list[str] | None = None, *, profile: Path | None = None,
          out_dir: Path | None = None, day: date | None = None) -> tuple[list[Path], list[str]]:
    """指定した画面を開いて HTML を保存する。(保存したファイル, 失敗した画面キー) を返す。"""
    from playwright.sync_api import sync_playwright

    profile = profile or DEFAULT_PROFILE
    out_dir = out_dir or DEFAULT_IMPORT_DIR
    specs = [PAGES[k] for k in (keys or list(PAGES))]
    day = day or date.today()
    saved: list[Path] = []
    failed: list[str] = []
    with sync_playwright() as pw:
        ctx, page = _launch(pw, profile)
        for spec in specs:
            print(f"[{spec.key}] {spec.url}", flush=True)
            try:
                html = _capture(page, spec)
            except Exception as e:  # noqa: BLE001 - 1画面の失敗で他の画面を諦めない
                print(f"   [warn] {spec.key}: {e}", flush=True)
                failed.append(spec.key)
                continue
            path = out_path(spec, out_dir, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
            shown = path.relative_to(REPO) if path.is_relative_to(REPO) else path
            print(f"   保存: {shown} ({len(html):,} 文字)", flush=True)
            saved.append(path)
        ctx.close()
    return saved, failed
