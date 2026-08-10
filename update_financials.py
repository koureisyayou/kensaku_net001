import os
import time
import pandas as pd
import yfinance as yf

CACHE_FILE = "financial_cache.csv"
OUTPUT_HTML = "index.html"

def fetch_stock_data(sec_code):
    """yfinance から株価・時価総額・PERを取得（リトライ付き）"""
    ticker = yf.Ticker(f"{sec_code}.T")
    for attempt in range(3):
        try:
            info = ticker.fast_info
            mcap = info.get('market_cap')
            price = info.get('last_price')
            
            if mcap and price:
                pe = ticker.info.get('trailingPE', None)
                return {
                    "price": price,
                    "market_cap": mcap,
                    "pe_ratio": pe if pe is not None else 999.0
                }
        except Exception:
            time.sleep(1)
    return None

def main():
    if not os.path.exists(CACHE_FILE):
        print("財務キャッシュが存在しません。空のページを生成します。")
        generate_html([])
        return

    df_fin = pd.read_csv(CACHE_FILE, dtype={"sec_code": str})
    results = []

    print(f"キャッシュ内の {len(df_fin)} 銘柄を判定中...")

    for _, row in df_fin.iterrows():
        sec_code = row["sec_code"]
        current_assets = row["current_assets"]
        total_liabilities = row["total_liabilities"]
        equity_ratio = row["equity_ratio"]

        # 条件: 自己資本比率 50% 以上
        if equity_ratio < 0.50:
            continue

        # 条件: 負債が流動資産以下 (NC > 0)
        if total_liabilities > current_assets:
            continue

        nc = current_assets - total_liabilities

        # 株価データ取得
        stock = fetch_stock_data(sec_code)
        if not stock:
            continue

        market_cap = stock["market_cap"]
        market_cap_100m = market_cap / 1e8  # 億円単位

        # 条件: 時価総額 500億円以下
        if market_cap_100m > 500:
            continue

        # 条件: NC比率 1.0 以上
        nc_ratio = nc / market_cap if market_cap > 0 else 0
        if nc_ratio < 1.0:
            continue

        # 条件: PER 8倍以下
        pe_ratio = stock["pe_ratio"]
        if pe_ratio > 8.0:
            continue

        results.append({
            "コード": sec_code,
            "社名": row["filer_name"],
            "株価(円)": f"{stock['price']:,.0f}",
            "時価総額(億円)": f"{market_cap_100m:,.1f}",
            "PER(倍)": f"{pe_ratio:.2f}" if pe_ratio != 999.0 else "N/A",
            "自己資本比率(%)": f"{equity_ratio * 100:.1f}",
            "NC比率": f"{nc_ratio:.2f}"
        })

    generate_html(results)

def generate_html(data):
    df = pd.DataFrame(data)
    now_str = pd.Timestamp.now().strftime('%Y-%m-%d %H:%M JST')
    
    table_html = df.to_html(index=False, classes="styled-table") if not df.empty else "<p>条件に該当する銘柄はありませんでした。</p>"

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EDINET ネットネット株スクリーナー</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 40px auto; max-width: 900px; padding: 0 10px; color: #333; }}
        h1 {{ border-bottom: 2px solid #0066cc; padding-bottom: 10px; }}
        .styled-table {{ border-collapse: collapse; margin: 25px 0; font-size: 0.9em; min-width: 100%; box-shadow: 0 0 20px rgba(0, 0, 0, 0.15); }}
        .styled-table thead tr {{ background-color: #0066cc; color: #ffffff; text-align: left; }}
        .styled-table th, .styled-table td {{ padding: 12px 15px; border-bottom: 1px solid #dddddd; }}
        .styled-table tbody tr:nth-of-type(even) {{ background-color: #f3f3f3; }}
        .meta {{ color: #666; font-size: 0.85em; }}
    </style>
</head>
<body>
    <h1>ネットネット株 スクリーニング結果 (NC比率 ≥ 1.0)</h1>
    <p class="meta">最終更新日: {now_str}</p>
    <p>条件：PER 8倍以下 / 時価総額 500億円以下 / 自己資本比率 50%以上 / NC比率 1.0以上</p>
    {table_html}
</body>
</html>"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"{OUTPUT_HTML} を生成しました。")

if __name__ == "__main__":
    main()
