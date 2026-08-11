import os
import pandas as pd

CSV_FILE = "net_net_candidates.csv"
HTML_FILE = "index.html"

def generate():
    if not os.path.exists(CSV_FILE):
        print(f"Error: {CSV_FILE} が見つかりません。")
        return

    df = pd.read_csv(CSV_FILE, dtype={"sec_code": str})
    
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
        table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #2c3e50; color: #fff; position: sticky; top: 0; }}
        tr:hover {{ background: #f1f4f8; }}
        .num {{ text-align: right; font-family: monospace; }}
        .highlight {{ font-weight: bold; color: #27ae60; }}
    </style>
</head>
<body>
    <h1>Net-Net Stock Screener (一次候補発見)</h1>
    <div class="meta">抽出件数: <strong>{len(df)}</strong> 銘柄 | 条件: NCAV > 0 & 自己資本比率 ≥ 30% & NCAV/時価総額 ≥ 1.0</div>
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
        # 1. 企業名の取得（filer_name / company_name / 社名 の順にフォールバック）
        company_name = (
            r.get('filer_name') or 
            r.get('company_name') or 
            r.get('社名') or 
            ''
        )

        price = f"{r.get('price', 0):,.1f}" if pd.notnull(r.get('price')) else "-"
        mcap = f"{r.get('market_cap', 0)/1e8:,.2f}" if pd.notnull(r.get('market_cap')) else "-"
        ncav = f"{r.get('ncav', 0)/1e8:,.2f}" if pd.notnull(r.get('ncav')) else "-"
        nc_ratio = f"{r.get('nc_ratio', 0):,.2f}" if pd.notnull(r.get('nc_ratio')) else "-"
        
        # 2. 自己資本比率の表示判定（小数か100倍済みかを自動判定）
        raw_eq = r.get('equity_ratio')
        if pd.notnull(raw_eq):
            eq_val = float(raw_eq)
            # 値が1以下（例: 0.354）なら100倍して35.4%にする
            if abs(eq_val) <= 1.0:
                eq_val = eq_val * 100
            # 100倍して100%を超えるデータ（異常値）の安全装置（必要に応じて調整）
            eq_ratio = f"{eq_val:,.1f}%"
        else:
            eq_ratio = "-"

        html_content += f"""            <tr>
                <td><strong>{r.get('sec_code', '')}</strong></td>
                <td>{company_name}</td>
                <td>{r.get('ticker', '')}</td>
                <td class="num">{price}</td>
                <td class="num">{mcap}</td>
                <td class="num">{ncav}</td>
                <td class="num highlight">{nc_ratio} 倍</td>
                <td class="num">{eq_ratio}</td>
            </tr>
"""

    html_content += """        </tbody>
    </table>
</body>
</html>
"""

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"{HTML_FILE} を正常に作成しました。")

if __name__ == "__main__":
    generate()
