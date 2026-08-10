import os
import sys
import logging
import pandas as pd
import yfinance as yf
from datetime import datetime

CACHE_FILE = "financial_cache.csv"
STOCK_CACHE_FILE = "stock_cache.csv"
OUTPUT_HTML = "index.html"
LOG_FILE = "screener.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 金融株・REITなどの除外用コードリスト
EXCLUDE_CODES = set([
    # 銀行・証券・保険・その他金融などの代表的コード範囲やREITコード群
])

def is_excluded_category(sec_code, filer_name):
    """金融機関やREITなどNet-Net分析に不適な銘柄を除外"""
    if sec_code in EXCLUDE_CODES:
        return True
    
    keywords = ["銀行", "金庫", "ホールディングス（金融）", "証券", "保険", "投資法人", "REIT"]
    for kw in keywords:
        if kw in filer_name:
            return True
    return False

def load_stock_cache(today_str):
    """当日の株価キャッシュを読み込む"""
    if not os.path.exists(STOCK_CACHE_FILE):
        return {}
    
    try:
        df_stock = pd.read_csv(STOCK_CACHE_FILE, dtype={"sec_code": str})
        # 今日取得したデータのみ有効とする
        df_today = df_stock[df_stock["checked_at"] == today_str]
        
        cache = {}
        for _, row in df_today.iterrows():
            sec_code = str(row["sec_code"]).zfill(4)
            cache[sec_code] = (float(row["market_cap"]), float(row["price"]))
        return cache
    except Exception as e:
        logger.warning(f"株価キャッシュ読み込みエラー: {e}")
        return {}

def save_stock_cache(stock_cache_data, today_str):
    """株価キャッシュをCSVに保存"""
    try:
        records = []
        for sec_code, (market_cap, price) in stock_cache_data.items():
            records.append({
                "sec_code": sec_code,
                "market_cap": market_cap,
                "price": price,
                "checked_at": today_str
            })
        df = pd.DataFrame(records)
        df.to_csv(STOCK_CACHE_FILE, index=False, encoding="utf-8-sig")
        logger.info(f"株価キャッシュを保存しました ({len(df)} 件)")
    except Exception as e:
        logger.error(f"株価キャッシュ保存エラー: {e}")

def get_stock_data_from_yahoo(sec_code):
    """Yahoo Finance から直接株価を取得"""
    ticker_symbol = f"{sec_code}.T"
    try:
        ticker = yf.Ticker(ticker_symbol)
        
        # 履歴データで上場確認
        hist = ticker.history(period="5d")
        if hist.empty or "Close" not in hist.columns:
            return None, None

        price = float(hist["Close"].iloc[-1])
        if price <= 0:
            return None, None

        info = ticker.fast_info
        market_cap = info.get("marketCap", None)

        # 時価総額が取れなかった場合は（株価 × 発行済株式数）で補正
        if not market_cap:
            shares = info.get("shares", None)
            if shares and shares > 0:
                market_cap = price * shares

        if market_cap and market_cap > 0:
            return float(market_cap), float(price)

    except Exception as e:
        logger.warning(f"[{sec_code}] Yahoo Finance 取得失敗: {e}")

    return None, None

def main():
    logger.info("=== スクリーニング処理を開始します ===")
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    if not os.path.exists(CACHE_FILE):
        logger.error(f"キャッシュファイル ({CACHE_FILE}) が見つかりません。")
        generate_empty_html("財務キャッシュファイルが存在しません。フルスキャンを実行してください。")
        return

    try:
        df = pd.read_csv(CACHE_FILE, dtype={"sec_code": str})
    except Exception as e:
        logger.error(f"キャッシュ読み込みエラー: {e}")
        generate_empty_html("キャッシュデータの読み込みに失敗しました。")
        return

    # 1. 株価キャッシュの読み込み
    stock_cache = load_stock_cache(today_str)
    new_stock_fetches = 0

    results = []
    
    logger.info(f"全対象銘柄数: {len(df)} 件")

    for idx, row in df.iterrows():
        sec_code = str(row["sec_code"]).zfill(4)
        filer_name = str(row.get("filer_name", "不明"))

        # --- 事前フィルター①: 金融機関・REITの除外 ---
        if is_excluded_category(sec_code, filer_name):
            continue

        try:
            current_assets = float(row.get("current_assets", 0))
            total_liabilities = float(row.get("total_liabilities", 0))
            raw_equity_ratio = float(row.get("equity_ratio", 0))
            submit_date = str(row.get("submit_date", "-"))
        except (ValueError, TypeError):
            continue

        # 【追加】自己資本比率を小数(0.0 ~ 1.0)に正規化
        # キャッシュ内に 16.477 (%表記) と 0.16477 (割合表記) が混在している対策
        if raw_equity_ratio > 1.0:
            norm_equity_ratio = raw_equity_ratio / 100.0  # 例: 16.477 -> 0.16477
        else:
            norm_equity_ratio = raw_equity_ratio          # 例: 0.609 -> 0.609

        # 正味流動資産 (NCAV) 計算
        ncav = current_assets - total_liabilities

        # --- 事前フィルター②: 財務データによる超高速足切り ---
        # NCAVが0以下、または自己資本比率が30% (0.3) 未満ならSKIP
        if ncav <= 0 or norm_equity_ratio < 0.3:
            continue

        # --- 事前フィルター通過銘柄のみ 株価データ取得 ---
        if sec_code in stock_cache:
            market_cap, price = stock_cache[sec_code]
        else:
            market_cap, price = get_stock_data_from_yahoo(sec_code)
            if market_cap and price:
                stock_cache[sec_code] = (market_cap, price)
                new_stock_fetches += 1

        if market_cap and market_cap > 0:
            # NC比率 = NCAV / 時価総額
            nc_ratio = round(ncav / market_cap, 2)
            
            # --- 最終判定 ---
            # 1. NC比率 1.0以上 (時価総額がNCAV以下)
            # 2. 時価総額 500億円以下
            if nc_ratio >= 1.0 and market_cap <= 50_000_000_000:
                results.append({
                    "sec_code": sec_code,
                    "filer_name": filer_name,
                    "price": price,
                    "market_cap": int(market_cap),
                    "ncav": int(ncav),
                    "nc_ratio": nc_ratio,
                    "equity_ratio": round(norm_equity_ratio * 100, 1), # 正規化した値を100倍して表示
                    "submit_date": submit_date
                })

    # 新規取得があった場合のみ株価キャッシュを更新保存
    if new_stock_fetches > 0:
        save_stock_cache(stock_cache, today_str)

    results_df = pd.DataFrame(results)
    if not results_df.empty:
        results_df = results_df.sort_values(by="nc_ratio", ascending=False)

    generate_html(results_df)
    logger.info(f"スクリーニング完了 - 該当件数: {len(results_df)} 件 (新規株価取得: {new_stock_fetches} 件)")

def generate_empty_html(message):
    html_content = f"<html><body><h1>Net-Net Stock Screener</h1><p>{message}</p></body></html>"
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)

def generate_html(df):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    table_rows = ""
    if df.empty:
        table_rows = "<tr><td colspan='8' style='text-align:center;'>現在、条件に該当する銘柄はありません。</td></tr>"
    else:
        for _, row in df.iterrows():
            table_rows += f"""
            <tr>
                <td><strong>{row['sec_code']}</strong></td>
                <td>{row['filer_name']}</td>
                <td style='text-align:right;'>¥{row['price']:,.0f}</td>
                <td style='text-align:right;'>¥{row['market_cap']/100_000_000:,.1f}億円</td>
                <td style='text-align:right;'>¥{row['ncav']/100_000_000:,.1f}億円</td>
                <td style='text-align:right;'><strong style='color: #2e7d32;'>{row['nc_ratio']:.2f}倍</strong></td>
                <td style='text-align:right;'>{row['equity_ratio']:.1f}%</td>
                <td style='text-align:center;'>{row['submit_date']}</td>
            </tr>
            """

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Net-Net Stock Screener</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background-color: #f8f9fa; color: #333; }}
        .container {{ max-width: 1100px; margin: 0 auto; background: #fff; padding: 25px 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a202c; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; margin-top: 0; }}
        .update-time {{ color: #718096; font-size: 0.9em; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th, td {{ padding: 12px 15px; border-bottom: 1px solid #e2e8f0; text-align: left; }}
        th {{ background-color: #f7fafc; color: #4a5568; font-weight: 600; }}
        tr:hover {{ background-color: #f1f5f9; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>ネットネット株 スクリーニング結果</h1>
        <p class="update-time">最終更新日時: {now_str} (JST)</p>
        <table>
            <thead>
                <tr>
                    <th>コード</th>
                    <th>銘柄名</th>
                    <th style="text-align:right;">株価</th>
                    <th style="text-align:right;">時価総額</th>
                    <th style="text-align:right;">正味流動資産(NCAV)</th>
                    <th style="text-align:right;">NC比率</th>
                    <th style="text-align:right;">自己資本比率</th>
                    <th style="text-align:center;">決算提出日</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)

if __name__ == "__main__":
    main()
