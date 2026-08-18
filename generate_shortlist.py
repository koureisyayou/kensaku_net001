"""generate_shortlist.py

net_net_candidates.csv（price_metrics.py で価格指標を付与済み）を読み、
二次スクリーニング結果を shortlist.html に出力する。

除外する篩（上から順に適用）:
    1. 整理銘柄        上場廃止が決定済み。最優先で落とす
    2. 監理銘柄        上場廃止のおそれ。EXCLUDE_KANRI で切替可
    3. 株価下限        MIN_PRICE 円未満を除外
    4. 時価総額下限    MIN_MCAP_OKU 億円未満を除外
    5. 流動性          20日平均売買代金 MIN_TURNOVER_MYEN 百万円未満を除外
    6. 滞留            連続掲載 MAX_STREAK_DAYS 営業日超を除外

除外せずフラグ・列で出すもの:
    - NCAV倍率が RATIO_FLAG_ABOVE 超  →「要確認」バッジ（良すぎる数字は疑う）
    - 決算日からの経過日数            → データの鮮度
    - 安値乖離 / 騰落率 / 停滞日数     → 並べ替え用の列
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from jpx_alerts import fetch_alerts

# ----------------------------------------------------------------- 設定

CANDIDATES_CSV = Path("net_net_candidates.csv")
HISTORY_CSV = Path("screening_history.csv")
OUTPUT_HTML = Path("shortlist.html")

EXCLUDE_KANRI = True          # 監理銘柄も除外するか（整理銘柄は常に除外）
MIN_PRICE = 50.0              # 株価の下限（円）
MIN_MCAP_OKU = 5.0            # 時価総額の下限（億円）
MIN_TURNOVER_MYEN = 5.0       # 20日平均売買代金の下限（百万円）
MAX_STREAK_DAYS = 250         # 連続掲載日数の上限
RATIO_FLAG_ABOVE = 5.0        # NCAV倍率がこれを超えたら「要確認」バッジ
STALE_DATA_DAYS = 120         # 決算日からこれ以上経っていたら経過日数を強調
NEW_ENTRY_DAYS = 5            # 連続掲載日数がこれ以下なら「新規」バッジ

JST = ZoneInfo("Asia/Tokyo")

COLUMN_ALIASES = {
    "code": ["コード", "code", "Code", "証券コード"],
    "name": ["銘柄名", "name", "Name", "会社名"],
    "price": ["株価 (円)", "株価", "price", "Price"],
    "mcap": ["時価総額 (億円)", "時価総額", "market_cap"],
    "ratio": ["NCAV / 時価総額", "NCAV/時価総額", "ncav_ratio"],
    "equity": ["自己資本比率", "equity_ratio"],
    "low60": ["60日安値乖離%"],
    "ret5": ["5日騰落%"],
    "stagnant": ["停滞日数"],
    "turnover": ["20日平均売買代金(百万円)"],
    "fiscal": ["決算日", "決算期", "基準日", "会計期間末", "period_end", "fiscal_end"],
}


def resolve(df: pd.DataFrame, key: str) -> str | None:
    for name in COLUMN_ALIASES[key]:
        if name in df.columns:
            return name
    return None


def to_number(series: pd.Series) -> pd.Series:
    """「2.92 倍」「75.2%」「1,145.0」のような表記を数値にする。"""
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("倍", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


# ----------------------------------------------------- 連続掲載日数の算出

def load_streaks(path: Path, code_col_hint: str) -> dict[str, int]:
    if not path.exists():
        return {}

    hist = pd.read_csv(path, dtype=str)
    date_col = next((c for c in ["日付", "date", "Date", "更新日", "実行日"] if c in hist.columns), None)
    code_col = next((c for c in [code_col_hint, "コード", "code", "Code"] if c and c in hist.columns), None)
    if date_col is None or code_col is None:
        return {}

    hist[date_col] = pd.to_datetime(hist[date_col], errors="coerce").dt.date
    hist = hist.dropna(subset=[date_col])
    if hist.empty:
        return {}

    run_dates = sorted(hist[date_col].unique(), reverse=True)
    by_date = {d: set(hist.loc[hist[date_col] == d, code_col]) for d in run_dates}

    streaks: dict[str, int] = {}
    for code in set(hist[code_col]):
        count = 0
        for d in run_dates:
            if code in by_date[d]:
                count += 1
            else:
                break
        streaks[code] = count
    return streaks


# ------------------------------------------------------------- 絞り込み

def build_shortlist(df: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[str, int]], pd.DataFrame]:
    code_col = resolve(df, "code")
    work = df.copy()
    work[code_col] = work[code_col].astype(str).str.strip()

    # 連続掲載日数
    streaks = load_streaks(HISTORY_CSV, code_col)
    work["連続掲載日数"] = work[code_col].map(streaks)

    # 決算日からの経過日数
    fiscal_col = resolve(work, "fiscal")
    if fiscal_col:
        fiscal = pd.to_datetime(work[fiscal_col], errors="coerce")
        work["決算日経過"] = (pd.Timestamp.now(tz=None).normalize() - fiscal).dt.days
    else:
        work["決算日経過"] = None
        print("[shortlist] 決算日の列が見つかりません。run_screener.py 側で決算日を出力すると鮮度が見えます。")

    # JPX 監理・整理銘柄の突合
    alerts = fetch_alerts()
    alert_map = dict(zip(alerts["コード"].astype(str).str.strip(), alerts["区分"])) if not alerts.empty else {}
    work["JPX指定"] = work[code_col].map(alert_map)

    flagged = work[work["JPX指定"].notna()][[code_col, resolve(work, "name"), "JPX指定"]].copy()

    stages: list[tuple[str, int]] = [("一次候補", len(work))]

    def drop(mask: pd.Series, label: str) -> None:
        nonlocal work
        removed = int(mask.sum())
        work = work[~mask]
        stages.append((label, -removed))

    drop(work["JPX指定"] == "整理", "整理銘柄")
    if EXCLUDE_KANRI:
        drop(work["JPX指定"] == "監理", "監理銘柄")

    price = to_number(work[resolve(work, "price")])
    drop(price < MIN_PRICE, f"株価{MIN_PRICE:.0f}円未満")

    mcap = to_number(work[resolve(work, "mcap")])
    drop(mcap < MIN_MCAP_OKU, f"時価総額{MIN_MCAP_OKU:.0f}億未満")

    turnover_col = resolve(work, "turnover")
    if turnover_col:
        drop(to_number(work[turnover_col]).fillna(0) < MIN_TURNOVER_MYEN, "流動性不足")

    streak = work["連続掲載日数"]
    drop((streak.notna()) & (streak > MAX_STREAK_DAYS), f"連続掲載{MAX_STREAK_DAYS}日超")

    stages.append(("残り", len(work)))
    return work, stages, flagged


# ----------------------------------------------------------------- 出力

CSS = """
:root {
  --paper: #eceef1; --card: #fbfbfc; --ink: #14171c; --muted: #6b7280;
  --rule: #d3d7dd; --indigo: #1b4d7a; --amber: #a86a12; --moss: #3f6b4a; --alert: #96302c;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink);
  font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic", Meiryo, system-ui, sans-serif;
  font-size: 14px; line-height: 1.6; }
.wrap { max-width: 1240px; margin: 0 auto; padding: 32px 20px 64px; }
header { border-bottom: 2px solid var(--ink); padding-bottom: 16px; }
h1 { font-size: 22px; letter-spacing: .08em; margin: 0 0 4px; font-weight: 700; }
.sub { color: var(--muted); font-size: 12px; letter-spacing: .04em; }
.sub a { color: var(--indigo); }
.funnel { display: flex; flex-wrap: wrap; margin: 24px 0 8px; border: 1px solid var(--rule); background: var(--card); }
.funnel div { flex: 1 1 120px; padding: 12px 14px; border-right: 1px solid var(--rule); }
.funnel div:last-child { border-right: 0; background: #f2f5f8; }
.funnel .label { font-size: 11px; color: var(--muted); letter-spacing: .04em; }
.funnel .num { font-family: ui-monospace, Menlo, monospace; font-size: 22px;
  font-variant-numeric: tabular-nums; line-height: 1.2; }
.funnel .num.minus { color: var(--amber); }
.funnel .num.keep { color: var(--indigo); }
.rule-note { font-size: 12px; color: var(--muted); margin: 0 0 20px; }
.alertbox { border-left: 4px solid var(--alert); background: #fbf3f2; padding: 12px 16px; margin: 0 0 24px; font-size: 13px; }
.alertbox h2 { font-size: 13px; margin: 0 0 6px; letter-spacing: .04em; }
.alertbox code { font-family: ui-monospace, Menlo, monospace; }
.scroll { overflow-x: auto; border: 1px solid var(--rule); background: var(--card); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 8px 10px; text-align: right; white-space: nowrap; border-bottom: 1px solid #e6e9ed; }
th:nth-child(1), th:nth-child(2), td:nth-child(1), td:nth-child(2) { text-align: left; }
thead th { position: sticky; top: 0; background: var(--ink); color: #fff; font-size: 11px;
  font-weight: 600; letter-spacing: .04em; cursor: pointer; user-select: none; }
thead th:hover { background: var(--indigo); }
thead th::after { content: " ↕"; opacity: .35; }
thead th.asc::after { content: " ↑"; opacity: 1; }
thead th.desc::after { content: " ↓"; opacity: 1; }
tbody tr:nth-child(even) { background: #f5f6f8; }
tbody tr:hover { background: #e8eef4; }
td.num { font-family: ui-monospace, Menlo, monospace; font-variant-numeric: tabular-nums; }
td.stale { color: var(--alert); font-weight: 600; }
.badge { display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 2px;
  font-size: 10px; letter-spacing: .04em; color: #fff; }
.badge.new { background: var(--moss); }
.badge.check { background: var(--amber); }
.pos { color: var(--amber); } .neg { color: var(--indigo); }
footer { margin-top: 20px; font-size: 11px; color: var(--muted); }
@media (max-width: 600px) { .wrap { padding: 20px 12px 48px; } .funnel .num { font-size: 18px; } }
"""

JS = """
document.querySelectorAll('thead th').forEach((th, idx) => {
  th.addEventListener('click', () => {
    const table = th.closest('table'), tbody = table.tBodies[0];
    const desc = !th.classList.contains('desc');
    table.querySelectorAll('th').forEach(h => h.classList.remove('asc','desc'));
    th.classList.add(desc ? 'desc' : 'asc');
    Array.from(tbody.rows).sort((a, b) => {
      const av = a.cells[idx].dataset.sort ?? a.cells[idx].textContent;
      const bv = b.cells[idx].dataset.sort ?? b.cells[idx].textContent;
      const an = parseFloat(av), bn = parseFloat(bv);
      const cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : String(av).localeCompare(String(bv), 'ja');
      return desc ? -cmp : cmp;
    }).forEach(r => tbody.appendChild(r));
  });
});
"""


def cell(value, signed=False, extra_class="") -> str:
    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return '<td class="num">–</td>'
    raw = html.escape(str(value))
    text, cls = raw, f"num {extra_class}".strip()
    if signed:
        try:
            v = float(value)
            cls += " pos" if v > 0 else " neg" if v < 0 else ""
            text = f"{v:+.1f}"
        except (TypeError, ValueError):
            pass
    return f'<td class="{cls}" data-sort="{raw}">{text}</td>'


def render(df: pd.DataFrame, stages: list[tuple[str, int]], flagged: pd.DataFrame) -> str:
    cols = [
        ("コード", resolve(df, "code"), False),
        ("銘柄名", resolve(df, "name"), False),
        ("株価", resolve(df, "price"), False),
        ("時価総額(億)", resolve(df, "mcap"), False),
        ("NCAV倍率", resolve(df, "ratio"), False),
        ("自己資本比率", resolve(df, "equity"), False),
        ("決算日経過", "決算日経過", False),
        ("60日安値乖離%", resolve(df, "low60"), True),
        ("5日騰落%", resolve(df, "ret5"), True),
        ("停滞日数", resolve(df, "stagnant"), False),
        ("売買代金(百万)", resolve(df, "turnover"), False),
        ("連続掲載日数", "連続掲載日数", False),
    ]
    cols = [c for c in cols if c[1] is not None]
    head = "".join(f"<th>{html.escape(label)}</th>" for label, *_ in cols)

    ratio_col = resolve(df, "ratio")
    rows = []
    for _, row in df.iterrows():
        tds = []
        for label, col, signed in cols:
            value = row.get(col)
            if label == "銘柄名":
                badges = ""
                streak = row.get("連続掲載日数")
                if pd.notna(streak) and streak <= NEW_ENTRY_DAYS:
                    badges += '<span class="badge new">新規</span>'
                ratio = to_number(pd.Series([row.get(ratio_col)])).iloc[0] if ratio_col else None
                if pd.notna(ratio) and ratio > RATIO_FLAG_ABOVE:
                    badges += '<span class="badge check">要確認</span>'
                tds.append(f"<td>{html.escape(str(value))}{badges}</td>")
            elif label == "決算日経過":
                stale = "stale" if pd.notna(value) and value and float(value) >= STALE_DATA_DAYS else ""
                tds.append(cell(value, extra_class=stale))
            else:
                tds.append(cell(value, signed))
        rows.append("<tr>" + "".join(tds) + "</tr>")

    funnel = "".join(
        f'<div><div class="label">{html.escape(label)}</div>'
        f'<div class="num {"minus" if n < 0 else "keep" if label == "残り" else ""}">'
        f'{n:+d}</div></div>'.replace(f">{n:+d}<", f">{n}<") if label in ("一次候補", "残り")
        else f'<div><div class="label">{html.escape(label)}</div>'
             f'<div class="num minus">{n:+d}</div></div>'
        for label, n in stages
    )

    alert_html = ""
    if not flagged.empty:
        items = "、".join(
            f'<code>{html.escape(str(r.iloc[0]))}</code> {html.escape(str(r.iloc[1]))}（{html.escape(str(r.iloc[2]))}）'
            for _, r in flagged.iterrows()
        )
        alert_html = (
            '<div class="alertbox"><h2>JPXが監理・整理銘柄に指定している銘柄が一次候補に含まれています</h2>'
            f'{items}</div>'
        )

    updated = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Net-Net Shortlist｜二次スクリーニング</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>NET-NET SHORTLIST</h1>
    <div class="sub">上場廃止リスク・規模・流動性・滞留の篩をかけた結果　|　更新 {updated} (JST)　|　<a href="index.html">一次候補リストへ戻る</a></div>
  </header>

  <div class="funnel">{funnel}</div>
  <p class="rule-note">
    整理・監理：JPX公表の指定状況と突合　/　株価 {MIN_PRICE:.0f}円以上　/　時価総額 {MIN_MCAP_OKU:.0f}億円以上　/　
    20日平均売買代金 {MIN_TURNOVER_MYEN:.0f}百万円以上　/　連続掲載 {MAX_STREAK_DAYS}営業日以下。
    NCAV倍率 {RATIO_FLAG_ABOVE:.0f}倍超は除外せず「要確認」を付けています。列見出しをクリックすると並べ替わります。
  </p>
  {alert_html}

  <div class="scroll">
    <table>
      <thead><tr>{head}</tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>

  <footer>決算日経過が長い銘柄は、決算期末以降の構造変化がNCAVに反映されていない可能性があります。数値は自動取得したもので正確性を保証しません。</footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def main() -> None:
    df = pd.read_csv(CANDIDATES_CSV)
    shortlist, stages, flagged = build_shortlist(df)
    OUTPUT_HTML.write_text(render(shortlist, stages, flagged), encoding="utf-8")
    print(" → ".join(f"{label} {n}" for label, n in stages))


if __name__ == "__main__":
    main()
