"""make_context.py

リポジトリの現状を CONTEXT.md 一枚にまとめる。

目的:
    スクリーナーは複数のスクリプトとCSVが噛み合って動いており、
    相談・改修のたびに全ソースを貼り直すのは現実的でない。
    「何がどこにあり、各CSVがどんな列を持ち、前回いくつ出たか」を
    機械的に書き出しておき、これ一枚を渡せば話が通じる状態にする。

    ソースコード本体は含めない（量が多すぎる）。含めるのは
    構造・列名・件数・更新時刻・ハッシュ。ハッシュがあれば
    「前に見たときと変わっているか」が判別できる。

パイプラインの最後で実行し、CONTEXT.md をコミットする想定。
どのステップが落ちても本体を止めないよう、全体を握り潰す。

使い方:
    python make_context.py
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

JST = timezone(timedelta(hours=9))
OUTPUT = Path("CONTEXT.md")

MAX_SAMPLE_ROWS = 2      # 各CSVから載せるサンプル行数
MAX_CELL_CHARS = 32      # セル値の切り詰め
MAX_COLS_SHOWN = 40      # 列が多いCSVの打ち切り

SCRIPTS = [
    "update_financials.py",
    "financials.py",
    "run_screener.py",
    "run_screener_local.py",
    "price_metrics.py",
    "save_history.py",
    "jpx_alerts.py",
    "fetch_jpx_listed.py",
    "fetch_local_prices.py",
    "generate_html.py",
    "generate_local_html.py",
    "generate_shortlist.py",
    "make_context.py",
]

DATA_FILES = [
    "financial_cache.csv",
    "stock_cache.csv",
    "net_net_candidates.csv",
    "net_net_candidates_local.csv",
    "screening_history.csv",
    "invalid_financials.csv",
    "invalid_financials_local.csv",
    "processed_docs.csv",
    "jpx_alerts_cache.csv",
    "tse_listed.csv",
    "local_price_history.csv",
    "local_prices.csv",
]

OUTPUT_PAGES = ["index.html", "shortlist.html", "local.html"]


def sha8(path: Path) -> str:
    h = hashlib.sha1(path.read_bytes()).hexdigest()
    return h[:8]


def mtime(path: Path) -> str:
    ts = datetime.fromtimestamp(path.stat().st_mtime, JST)
    return ts.strftime("%Y-%m-%d %H:%M")


def first_docline(path: Path) -> str:
    """docstring の最初の実質的な1行を返す。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return ""
    started = False
    for line in lines[:40]:
        stripped = line.strip().strip('"').strip("'").strip()
        if not started:
            if line.lstrip().startswith(('"""', "'''")):
                started = True
                # 1行目が "hoge.py" だけの体裁なら中身が無いので次行を見る
                if stripped and stripped != path.name:
                    return stripped
            continue
        if stripped and stripped != path.name:
            return stripped
    return ""


def git_info() -> dict:
    def run(*args):
        try:
            return subprocess.run(
                args, capture_output=True, text=True, timeout=10, check=True
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            return "?"

    return {
        "commit": run("git", "rev-parse", "--short", "HEAD"),
        "date": run("git", "log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M"),
        "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD"),
    }


def describe_csv(path: Path) -> list[str]:
    lines = []
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001
        return [f"- 読み込み失敗: {exc}"]

    cols = list(df.columns)
    shown = cols[:MAX_COLS_SHOWN]
    more = "" if len(cols) <= MAX_COLS_SHOWN else f" ...他{len(cols) - MAX_COLS_SHOWN}列"

    lines.append(f"- 行数: {len(df):,} / 列数: {len(cols)} / 更新: {mtime(path)}")
    lines.append(f"- 列: `{'`, `'.join(shown)}`{more}")

    # 全行が空の列は、生成側の不具合の手がかりになるので明示する
    empty_cols = [c for c in cols if (df[c].astype(str).str.strip() == "").all()]
    if empty_cols:
        lines.append(f"- ⚠ 全行が空の列: `{'`, `'.join(empty_cols)}`")

    if not df.empty:
        lines.append("")
        lines.append("```")
        head = df.head(MAX_SAMPLE_ROWS).copy()
        for c in head.columns:
            head[c] = head[c].astype(str).str.slice(0, MAX_CELL_CHARS)
        lines.append(head.to_string(index=False, max_cols=MAX_COLS_SHOWN))
        lines.append("```")

    return lines


def summary_stats() -> list[str]:
    """相談時に真っ先に聞かれる数字を先に出しておく。"""
    lines = []

    fc = Path("financial_cache.csv")
    if fc.exists():
        try:
            df = pd.read_csv(fc, dtype=str, keep_default_na=False)
            total = len(df)
            if "shares_outstanding" in df.columns:
                filled = (df["shares_outstanding"].astype(str).str.strip() != "").sum()
                pct = filled / total * 100 if total else 0
                lines.append(
                    f"- 発行済株式数の充足: {filled:,}/{total:,} ({pct:.1f}%)"
                )
            else:
                lines.append("- 発行済株式数: 列なし（未導入）")
        except Exception:  # noqa: BLE001
            pass

    nn = Path("net_net_candidates.csv")
    if nn.exists():
        try:
            lines.append(f"- ネットネット候補（東証）: {len(pd.read_csv(nn)):,}件")
        except Exception:  # noqa: BLE001
            pass

    nnl = Path("net_net_candidates_local.csv")
    if nnl.exists():
        try:
            lines.append(f"- ネットネット候補（地方）: {len(pd.read_csv(nnl)):,}件")
        except Exception:  # noqa: BLE001
            pass
    else:
        lines.append("- ネットネット候補（地方）: 未生成")

    lp = Path("local_prices.csv")
    if lp.exists():
        try:
            df = pd.read_csv(lp, dtype=str, keep_default_na=False)
            traded = (df.get("price", pd.Series(dtype=str)).astype(str).str.strip() != "").sum()
            as_of = df["as_of"].iloc[0] if "as_of" in df.columns and not df.empty else "?"
            win = df["window_days"].iloc[0] if "window_days" in df.columns and not df.empty else "?"
            lines.append(
                f"- 名証: 掲載{len(df):,}件 / 期間内に約定{traded:,}件 "
                f"（相場日 {as_of} / 蓄積 {win}営業日）"
            )
            if "is_local_only" in df.columns:
                local_only = (df["is_local_only"].astype(str).str.lower() == "true").sum()
                lines.append(f"- うち地方単独の候補: {local_only:,}件")
            else:
                lines.append("- 東証重複の判別: 未適用（is_local_only 列なし）")
        except Exception:  # noqa: BLE001
            pass

    lph = Path("local_price_history.csv")
    if lph.exists():
        try:
            df = pd.read_csv(lph, dtype=str, keep_default_na=False)
            dates = sorted(d for d in df["date"].unique() if d)
            if dates:
                lines.append(
                    f"- 名証の蓄積: {len(dates)}営業日分 ({dates[0]} 〜 {dates[-1]})"
                )
        except Exception:  # noqa: BLE001
            pass

    return lines or ["- （集計対象のファイルがまだありません）"]


def build() -> str:
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    git = git_info()

    out = [
        "# CONTEXT — ネットネット株スクリーナー",
        "",
        "このファイルは `make_context.py` が自動生成します。手で編集しないでください。",
        "相談時はこれ一枚を渡し、必要なスクリプト本体は指名して別途渡します。",
        "",
        f"- 生成: {now}",
        f"- コミット: `{git['commit']}` ({git['branch']}) / {git['date']}",
        "",
        "## いまの状態",
        "",
    ]
    out += summary_stats()

    out += ["", "## スクリプト", "", "| ファイル | 行数 | sha1 | 更新 | 概要 |",
            "| --- | ---: | --- | --- | --- |"]
    for name in SCRIPTS:
        path = Path(name)
        if not path.exists():
            out.append(f"| {name} | — | — | — | **存在しない** |")
            continue
        n_lines = len(path.read_text(encoding="utf-8").splitlines())
        out.append(
            f"| {name} | {n_lines} | `{sha8(path)}` | {mtime(path)} | {first_docline(path)} |"
        )

    out += ["", "## データファイル", ""]
    for name in DATA_FILES:
        path = Path(name)
        out.append(f"### {name}")
        if not path.exists():
            out.append("")
            out.append("- **存在しない**")
            out.append("")
            continue
        out.append("")
        out += describe_csv(path)
        out.append("")

    out += ["## 出力ページ", ""]
    for name in OUTPUT_PAGES:
        path = Path(name)
        if path.exists():
            size_kb = path.stat().st_size / 1024
            out.append(f"- {name}: {size_kb:,.0f} KB / 更新 {mtime(path)}")
        else:
            out.append(f"- {name}: **存在しない**")

    out.append("")
    return "\n".join(out)


def main():
    try:
        OUTPUT.write_text(build(), encoding="utf-8")
        print(f"[context] {OUTPUT} を生成しました ({OUTPUT.stat().st_size:,} bytes)")
    except Exception as exc:  # noqa: BLE001
        # ここで pipeline を止める価値はない
        print(f"[context] 生成に失敗しました: {exc}")


if __name__ == "__main__":
    main()
