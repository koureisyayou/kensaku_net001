import os
import html as html_lib
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

CSV_FILE = "net_net_candidates.csv"
HTML_FILE = "index.html"


def pick_name(row):
    """
    社名を取り出す。
    pandas の NaN は Python では真と評価されるため、`a or b` のフォールバックだと
    NaN がそのまま採用されて 'nan' と表示されてしまう。pd.notnull で判定する。
    """
    for key in ("company_name", "filer_name", "社名"):
        val = row.get(key)
        if pd.notnull(val) and str(val).strip():
            return str(val).strip()
    return ""


def fmt_num(val, digits=2, divisor=1.0):
    if pd.isnull(val):
        return "-"
    try:
        return f"{float(val) / divisor:,.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def fmt_percent(val):
    """自己資本比率の表示（％で保存されている前提。旧形式の比率も一応受ける）"""
    if pd.isnull(val):
        return "-"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "-"
    if 0 < v <= 1.0:
        v *= 100.0
    return f"{v:,.1f}%"


def generate():
    if not os.path.exists(CSV_FILE):
        print(f"Error: {CSV_FILE} が見つかりません。")
        return

    df = pd.read_csv(CSV_FILE, dtype={"sec_code": str})
    updated_at = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M")

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Net-Net Stock Screener (PAGE 1)</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background: #f8f9fa; color: #333; }}
        h1 {{ color: #1a252f; border-bottom: 2px solid #2c3e50; padding-bottom: 10px; }}
        .meta {{ margin-bottom: 20px; color: #666; font-size: 0.9em; }}
        .wrap {{ overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; white-space: nowrap; }}
        th {{ background: #2c3e50; color: #fff; position: sticky; top: 0; }}
        tr:hover {{ background: #f1f4f8; }}
        .num {{ text-align: right; font-family: monospace; }}
        .highlight {{ font-weight: bold; color: #27ae60; }}
    </style>
</head>
<body>
    <h1>Net-Net Stock Screener (一次候補発見)</h1>
    <div class="meta">
        抽出件数: <strong>{len(df)}</strong> 銘柄 |
        条件: NCAV &gt; 0 &amp; 自己資本比率 ≥ 30% &amp; NCAV/時価総額 ≥ 1.0 |
        更新: {updated_at} (JST)
    </div>
    <div class="wrap">
    <table>
        <thead>
            <tr>
                <th>コード</th>
                <th>銘柄名</th>
                <th>Ticker</th>
                <th class="num">株価 (円)</th>
                <th class="num">時価総額 (億円)</th>
                <th class="num">NCAV (億円)</th>
                <th class="num">NCAV / 時価総額</th>
                <th class="num">自己資本比率</th>
            </tr>
        </thead>
        <tbody>
"""

    for _, r in df.iterrows():
        company_name = html_lib.escape(pick_name(r))
        sec_code = html_lib.escape(str(r.get("sec_code", "") or ""))
        ticker = html_lib.escape(str(r.get("ticker", "") or ""))

        price = fmt_num(r.get("price"), digits=1)
        mcap = fmt_num(r.get("market_cap"), digits=2, divisor=1e8)
        ncav = fmt_num(r.get("ncav"), digits=2, divisor=1e8)
        nc_ratio = fmt_num(r.get("nc_ratio"), digits=2)
        eq_ratio = fmt_percent(r.get("equity_ratio"))

        html_content += f"""            <tr>
                <td><strong>{sec_code}</strong></td>
                <td>{company_name}</td>
                <td>{ticker}</td>
                <td class="num">{price}</td>
                <td class="num">{mcap}</td>
                <td class="num">{ncav}</td>
                <td class="num highlight">{nc_ratio} 倍</td>
                <td class="num">{eq_ratio}</td>
            </tr>
"""

    html_content += """        </tbody>
    </table>
    </div>
</body>
</html>
"""

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"{HTML_FILE} を正常に作成しました。({len(df)} 銘柄)")


if __name__ == "__main__":
    generate()
