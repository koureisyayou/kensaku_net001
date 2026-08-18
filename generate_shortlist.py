"""generate_shortlist.py

net_net_candidates.csv（run_screener.py が出力、price_metrics.py で価格指標付与済み）
を読み、二次スクリーニング結果を shortlist.html に出力する。

除外する篩:
    1. 整理銘柄        上場廃止が決定済み
    2. 監理銘柄        EXCLUDE_KANRI で切替
    3. 株価下限        MIN_PRICE 円未満
    4. 時価総額下限    MIN_MCAP_OKU 億円未満
    5. 流動性          MIN_TURNOVER_MYEN 百万円未満
    6. 滞留            連続掲載 MAX_STREAK_DAYS 営業日超

除外せず列・バッジで出すもの:
    NCAV倍率が高すぎる銘柄／決算日・提出日からの経過日数／
    安値乖離・騰落率・停滞日数

データの鮮度について:
    決算日経過は bs_date（XBRLコンテキストの instant = 貸借対照表の基準日）を使う。
    fiscal_period は EDINET の periodEnd で、会計年度末を指すため半期報告書では
    未来日が入る。よって fiscal_period は「過去日のときだけ」代用する。
    bs_date は新規取得分から順に埋まるので、当面は提出日経過が実用的な目安になる。
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

EXCLUDE_KANRI = True
MIN_PRICE = 50.0            # 円
MIN_MCAP_OKU = 5.0          # 億円
MIN_TURNOVER_MYEN = 5.0     # 百万円
MAX_STREAK_DAYS = 250       # 営業日
RATIO_FLAG_ABOVE = 5.0      # NCAV倍率がこれ超で「要確認」
STALE_DATA_DAYS = 120       # 決算日経過がこれ以上で強調
NEW_ENTRY_DAYS = 5          # 連続掲載日数がこれ以下で「新規」

OKU = 1e8                   # 円 → 億円
JST = ZoneInfo("Asia/Tokyo")

# 列名ゆれの吸収（左が本命 = run_screener.py の出力名）
COLUMN_ALIASES = {
    "code": ["sec_code", "コード", "code"],
    "name": ["company_name", "filer_name", "銘柄名"],
    "price": ["price", "株価"],
    "mcap": ["market_cap", "時価総額"],
    "ncav": ["ncav", "NCAV"],
    "ratio": ["nc_ratio", "NCAV / 時価総額"],
    "equity": ["equity_ratio", "自己資本比率"],
    "bs": ["bs_date"],
    "fiscal": ["fiscal_period"],
    "submit": ["submit_date"],
    "low60": ["60日安値乖離%"],
    "ret5": ["5日騰落%"],
    "stagnant": ["停滞日数"],
    "turnover": ["20日平均売買代金(百万円)"],
}


def resolve(df: pd.DataFrame, key: str) -> str | None:
    for name in COLUMN_ALIASES[key]:
        if name in df.columns:
            return name
    return None


def to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )


# ----------------------------------------------------- 連続掲載日数の算出

def load_streaks(path: Path, code_col_hint: str) -> dict[str, int]:
    if not path.exists():
        print(f"[shortlist] {path} が無いため連続掲載日数は算出しません。")
        return {}

    hist = pd.read_csv(path, dtype=str)
    date_col = next((c for c in ["日付", "date", "Date", "更新日", "実行日", "run_date"] if c in hist.columns), None)
    code_col = next((c for c in [code_col_hint, "sec_code", "コード", "code"] if c and c in hist.columns), None)
    if date_col is None or code_col is None:
        print(f"[shortlist] {path} の日付列またはコード列を特定できませんでした: {list(hist.columns)}")
        return {}

    hist[date_col] = pd.to_datetime(hist[date_col], errors="coerce").dt.date
    hist = hist.dropna(subset=[date_col])
    if hist.empty:
        return {}

    run_dates = sorted(hist[date_col].unique(), reverse=True)
    by_date = {d: set(hist.loc[hist[date_col] == d, code_col].astype(str)) for d in run_dates}

    streaks: dict[str, int] = {}
    for code in set(hist[code_col].astype(str)):
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
    code_col, name_col = resolve(df, "code"), resolve(df, "name")
    work = df.copy()
    work[code_col] = work[code_col].astype(str).str.strip()

    # 単位換算（円 → 億円）
    work["_時価総額億"] = to_number(work[resolve(work, "mcap")]) / OKU
    work["_株価"] = to_number(work[resolve(work, "price")])
    work["_NCAV倍率"] = to_number(work[resolve(work, "ratio")])
    work["_自己資本比率"] = to_number(work[resolve(work, "equity")])

    # 連続掲載日数
    work["連続掲載日数"] = work[code_col].map(load_streaks(HISTORY_CSV, code_col))

    # --- データの鮮度 ---
    today = pd.Timestamp.now().normalize()

    bs_col = resolve(work, "bs")
    bs = pd.to_datetime(work[bs_col], errors="coerce") if bs_col else pd.Series(pd.NaT, index=work.index)

    fiscal_col = resolve(work, "fiscal")
    if fiscal_col:
        # periodEnd は会計年度末。半期報告書では未来日になるので過去日だけ代用する。
        fallback = pd.to_datetime(work[fiscal_col], errors="coerce")
        bs = bs.fillna(fallback.where(fallback <= today))
    work["決算日経過"] = (today - bs).dt.days

    submit_col = resolve(work, "submit")
    if submit_col:
        submitted = pd.to_datetime(work[submit_col], errors="coerce")
        work["提出日経過"] = (today - submitted).dt.days
    else:
        work["提出日経過"] = pd.NA

    if work["決算日経過"].isna().all():
        print("[shortlist] 決算日経過を算出できませんでした。bs_date がまだキャッシュに入っていない可能性があります。")

    # --- JPX 監理・整理銘柄の突合 ---
    alerts = fetch_alerts()
    alert_map = dict(zip(alerts["コード"].astype(str).str.strip(), alerts["区分"])) if not alerts.empty else {}
    work["JPX指定"] = work[code_col].map(alert_map)
    flagged = work.loc[work["JPX指定"].notna(), [code_col, name_col, "JPX指定"]].copy()

    stages: list[tuple[str, int]] = [("一次候補", len(work))]

    def drop(mask: pd.Series, label: str) -> None:
        nonlocal work
        removed = int(mask.fillna(False).sum())
        work = work[~mask.fillna(False)]
        stages.append((label, -removed))

    drop(work["JPX指定"] == "整理", "整理銘柄")
    if EXCLUDE_KANRI:
        drop(work["JPX指定"] == "監理", "監理銘柄")
    drop(work["_株価"] < MIN_PRICE, f"株価{MIN_PRICE:.0f}円未満")
    drop(work["_時価総額億"] < MIN_MCAP_OKU, f"時価総額{MIN_MCAP_OKU:.0f}億未満")

    turnover_col = resolve(work, "turnover")
    if turnover_col:
        drop(to_number(work[turnover_col]).fillna(0) < MIN_TURNOVER_MYEN, "流動性不足")
    else:
        print("[shortlist] 売買代金の列がありません。run_screener.py 側で add_price_metrics を呼べていますか。")

    streak = work["連続掲載日数"]
    drop(streak.notna() & (streak > MAX_STREAK_DAYS), f"連続掲載{MAX_STREAK_DAYS}日超")

    stages.append(("残り", len(work)))
    return work, stages, flagged


# ----------------------------------------------------------------- 出力

CSS = """
:root {
  --paper:#eceef1; --card:#fbfbfc; --ink:#14171c; --muted:#6b7280;
  --rule:#d3d7dd; --indigo:#1b4d7a; --amber:#a86a12; --moss:#3f6b4a; --alert:#96302c;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,system-ui,sans-serif;
  font-size:14px;line-height:1.6}
.wrap{max-width:1320px;margin:0 auto;padding:32px 20px 64px}
header{border-bottom:2px solid var(--ink);padding-bottom:16px}
h1{font-size:22px;letter-spacing:.08em;margin:0 0 4px;font-weight:700}
.sub{color:var(--muted);font-size:12px;letter-spacing:.04em}
.sub a{color:var(--indigo)}
.funnel{display:flex;flex-wrap:wrap;margin:24px 0 8px;border:1px solid var(--rule);background:var(--card)}
.funnel div{flex:1 1 110px;padding:12px 14px;border-right:1px solid var(--rule)}
.funnel div:last-child{border-right:0;background:#f2f5f8}
.funnel .label{font-size:11px;color:var(--muted);letter-spacing:.04em}
.funnel .num{font-family:ui-monospace,Menlo,monospace;font-size:22px;
  font-variant-numeric:tabular-nums;line-height:1.2}
.funnel .num.minus{color:var(--amber)}
.funnel .num.keep{color:var(--indigo)}
.rule-note{font-size:12px;color:var(--muted);margin:0 0 20px}
.alertbox{border-left:4px solid var(--alert);background:#fbf3f2;padding:12px 16px;margin:0 0 24px;font-size:13px}
.alertbox h2{font-size:13px;margin:0 0 6px;letter-spacing:.04em}
.alertbox code{font-family:ui-monospace,Menlo,monospace}
.scroll{overflow-x:auto;border:1px solid var(--rule);background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:8px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid #e6e9ed}
th:nth-child(1),th:nth-child(2),td:nth-child(1),td:nth-child(2){text-align:left}
thead th{position:sticky;top:0;background:var(--ink);color:#fff;font-size:11px;
  font-weight:600;letter-spacing:.04em;cursor:pointer;user-select:none}
thead th:hover{background:var(--indigo)}
thead th::after{content:" ↕";opacity:.35}
thead th.asc::after{content:" ↑";opacity:1}
thead th.desc::after{content:" ↓";opacity:1}
tbody tr:nth-child(even){background:#f5f6f8}
tbody tr:hover{background:#e8eef4}
td.num{font-family:ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
td.stale{color:var(--alert);font-weight:600}
.badge{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:2px;
  font-size:10px;letter-spacing:.04em;color:#fff}
.badge.new{background:var(--moss)}
.badge.check{background:var(--amber)}
.pos{color:var(--amber)}.neg{color:var(--indigo)}
footer{margin-top:20px;font-size:11px;color:var(--muted)}
@media(max-width:600px){.wrap{padding:20px 12px 48px}.funnel .num{font-size:18px}}
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


def cell(value, fmt="{:,.1f}", signed=False, extra_class="") -> str:
    if value is None or value == "" or (not isinstance(value, str) and pd.isna(value)):
        return '<td class="num">–</td>'
    cls = f"num {extra_class}".strip()
    try:
        v = float(value)
        text = f"{v:+.1f}" if signed else fmt.format(v)
        if signed:
            cls += " pos" if v > 0 else " neg" if v < 0 else ""
        return f'<td class="{cls}" data-sort="{v}">{text}</td>'
    except (TypeError, ValueError):
        raw = html.escape(str(value))
        return f'<td class="{cls}" data-sort="{raw}">{raw}</td>'


def render(df: pd.DataFrame, stages: list[tuple[str, int]], flagged: pd.DataFrame) -> str:
    code_col, name_col = resolve(df, "code"), resolve(df, "name")
    cols = [
        ("株価", "_株価", "{:,.0f}", False),
        ("時価総額(億)", "_時価総額億", "{:,.1f}", False),
        ("NCAV倍率", "_NCAV倍率", "{:,.2f}", False),
        ("自己資本比率", "_自己資本比率", "{:,.1f}", False),
        ("決算日経過", "決算日経過", "{:,.0f}", False),
        ("提出日経過", "提出日経過", "{:,.0f}", False),
        ("60日安値乖離%", resolve(df, "low60"), "{:,.1f}", True),
        ("5日騰落%", resolve(df, "ret5"), "{:,.1f}", True),
        ("停滞日数", resolve(df, "stagnant"), "{:,.0f}", False),
        ("売買代金(百万)", resolve(df, "turnover"), "{:,.1f}", False),
        ("連続掲載日数", "連続掲載日数", "{:,.0f}", False),
    ]
    cols = [c for c in cols if c[1] is not None]
    head = "<th>コード</th><th>銘柄名</th>" + "".join(f"<th>{html.escape(l)}</th>" for l, *_ in cols)

    rows = []
    for _, row in df.iterrows():
        badges = ""
        streak = row.get("連続掲載日数")
        if pd.notna(streak) and streak <= NEW_ENTRY_DAYS:
            badges += '<span class="badge new">新規</span>'
        ratio = row.get("_NCAV倍率")
        if pd.notna(ratio) and ratio > RATIO_FLAG_ABOVE:
            badges += '<span class="badge check">要確認</span>'

        tds = [
            f'<td>{html.escape(str(row[code_col]))}</td>',
            f'<td>{html.escape(str(row[name_col]))}{badges}</td>',
        ]
        for label, col, fmt, signed in cols:
            value = row.get(col)
            extra = ""
            if label in ("決算日経過", "提出日経過") and pd.notna(value) and value != "":
                try:
                    extra = "stale" if float(value) >= STALE_DATA_DAYS else ""
                except (TypeError, ValueError):
                    extra = ""
            tds.append(cell(value, fmt, signed, extra))
        rows.append("<tr>" + "".join(tds) + "</tr>")

    funnel = ""
    for label, n in stages:
        cls = "keep" if label in ("一次候補", "残り") else "minus"
        text = f"{n}" if label in ("一次候補", "残り") else f"{n:+d}"
        funnel += (f'<div><div class="label">{html.escape(label)}</div>'
                   f'<div class="num {cls}">{text}</div></div>')

    alert_html = ""
    if not flagged.empty:
        items = "、".join(
            f'<code>{html.escape(str(r.iloc[0]))}</code> {html.escape(str(r.iloc[1]))}'
            f'（{html.escape(str(r.iloc[2]))}銘柄）'
            for _, r in flagged.iterrows()
        )
        alert_html = ('<div class="alertbox"><h2>一次候補にJPXの監理・整理銘柄が含まれています</h2>'
                      f'{items}</div>')

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

  <footer>
    決算日経過は貸借対照表の基準日からの日数です。空欄の銘柄は基準日が未取得で、提出日経過を目安にしてください。
    経過が長い銘柄は、期末以降の構造変化がNCAVに反映されていない可能性があります。
    数値は自動取得したもので正確性を保証しません。
  </footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def main() -> None:
    df = pd.read_csv(CANDIDATES_CSV, dtype={"sec_code": str})
    shortlist, stages, flagged = build_shortlist(df)
    OUTPUT_HTML.write_text(render(shortlist, stages, flagged), encoding="utf-8")
    print(" → ".join(f"{label} {n}" for label, n in stages))


if __name__ == "__main__":
    main()
