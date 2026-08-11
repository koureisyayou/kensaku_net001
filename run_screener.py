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

EXCLUDE_CODES = set([
    # 金融・REIT等の除外コード
])

def is_excluded_category(sec_code, filer_name):
    if sec_code in EXCLUDE_CODES:
        return True
    keywords = ["銀行", "金庫", "ホールディングス（金融）", "証券", "保険", "投資法人", "REIT"]
    for kw in keywords:
        if kw in filer_name:
            return True
    return False

def load_stock_cache(today_str):
    if not os.path.exists(STOCK_CACHE_FILE):
        return {}
    try:
        df_stock = pd.read_csv(STOCK_CACHE_FILE, dtype={"sec_code": str, "status": str})
        df_today = df_stock[df_stock["checked_at"] == today_str]
        
        cache = {}
        for _, row in df_today.iterrows():
            sec_code = str(row["sec_code"]).strip()
            status = str(row.get("status", "OK"))
            
            if status == "NO_DATA":
                cache[sec_code] = (None, None, "NO_DATA")
            else:
                m_cap = float(row["market_cap"]) if pd.notna(row.get("market_cap")) else None
                prc = float(row["price"]) if pd.notna(row.get("price")) else None
                cache[sec_code] = (m_cap, prc, "OK")
        return cache
    except Exception as e:
        logger.warning(f"株価キャッシュ読み込みエラー: {e}")
        return {}

def save_stock_cache(stock_cache_data, today_str):
    try:
        records = []
        for sec_code, item in stock_cache_data.items():
            market_cap, price, status = item
            records.append({
                "sec_code": sec_code,
                "market_cap": market_cap if market_cap is not None else "",
                "price": price if price is not None else "",
                "status": status,
                "checked_at": today_str
            })
        df = pd.DataFrame(records)
        df.to_csv(STOCK_CACHE_FILE, index=False, encoding="utf-8-sig")
        logger.info(f"株価キャッシュ（当日分）を保存しました ({len(df)} 件)")
    except Exception as e:
        logger.error(f"株価キャッシュ保存エラー: {e}")

def normalize_sec_code(sec_code_raw):
    code_str = str(sec_code_raw).strip()
    if code_str.isdigit():
        return code_str.zfill(4)
    return code_str.upper()

def get_stock_data_from_yahoo(sec_code):
    ticker_symbol = f"{sec_code}.T"
    
    yf_logger = logging.getLogger('yfinance')
    previous_level = yf_logger.level
    yf_logger.setLevel(logging.CRITICAL)

    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period="5d")
        
        if hist.empty or "Close" not in hist.columns:
            return None, None
            
        price = float(hist["Close"].iloc[-1])
        if price <= 0:
            return None, None

        info = ticker.fast_info
        market_cap = info.get("marketCap", None)

        if not market_cap:
            shares = info.get("shares", None)
            if shares and shares > 0:
                market_cap = price * shares

        if market_cap and market_cap > 0:
            return float(market_cap), float(price)

    except Exception:
        pass
    finally:
        yf_logger.setLevel(previous_level)

    return None, None

def main():
    logger.info("=== スクリーニング処理を開始します ===")
    today_str = datetime.now().strftime("%Y-%m-%d")

    if not os.path.exists(CACHE_FILE):
        logger.error(f"キャッシュファイル ({CACHE_FILE}) が見つかりません。")
        generate_empty_html("財務キャッシュファイルが存在しません。")
        return

    try:
        df = pd.read_csv(CACHE_FILE, dtype=str)
        df["current_assets"] = pd.to_numeric(df.get("current_assets"), errors="coerce").fillna(0)
        df["total_liabilities"] = pd.to_numeric(df.get("total_liabilities"), errors="coerce").fillna(0)
        
        # equity_ratio を 0.0 ~ 1.0 (割合) に統一変換
        raw_eq = pd.to_numeric(df.get("equity_ratio"), errors="coerce").fillna(0)
        df["equity_ratio_norm"] = raw_eq.apply(lambda x: x / 100.0 if x > 1.0 else x)

    except Exception as e:
        logger.error(f"キャッシュ読み込み・クレンジングエラー: {e}")
        generate_empty_html("キャッシュデータの読み込みに失敗しました。")
        return

    stock_cache = load_stock_cache(today_str)
    
    # 【改修点②】ログ用の詳細カウンター
    fetches_attempted = 0
    fetches_successful = 0
    fetches_no_data = 0
    
    results = []

    logger.info(f"全対象銘柄数: {len(df)} 件")

    for idx, row in df.iterrows():
        sec_code = normalize_sec_code(row.get("sec_code", ""))
        filer_name = str(row.get("filer_name", "不明"))

        if not sec_code or is_excluded_category(sec_code, filer_name):
            continue

        current_assets = float(row["current_assets"])
        total_liabilities = float(row["total_liabilities"])
        norm_equity_ratio = float(row["equity_ratio_norm"])
        submit_date = str(row.get("submit_date", "-"))

        # 正味流動資産 (NCAV) 計算
        ncav = current_assets - total_liabilities

        # 事前フィルター: NCAV <= 0 または 自己資本比率 30% 未満はスキップ
        if ncav <= 0 or norm_equity_ratio < 0.3:
            continue

        # 株価キャッシュ確認＆取得
        market_cap, price = None, None
        if sec_code in stock_cache:
            m_cap, prc, status = stock_cache[sec_code]
            if status == "NO_DATA":
                continue  # 本日取得失敗済みの銘柄はスキップ
            market_cap, price = m_cap, prc
        else:
            fetches_attempted += 1
            market_cap, price = get_stock_data_from_yahoo(sec_code)
            
            if market_cap and price:
                fetches_successful += 1
                stock_cache[sec_code] = (market_cap, price, "OK")
            else:
                fetches_no_data += 1
                stock_cache[sec_code] = (None, None, "NO_DATA")
                continue

        if market_cap and market_cap > 0:
            # NC比率 = NCAV / 時価総額
            nc_ratio = round(ncav / market_cap, 2)
            
            # 基本スクリーニング判定
            if nc_ratio >= 1.0 and market_cap <= 50_000_000_000:
                results.append({
                    "sec_code": sec_code,
                    "filer_name": filer_name,
                    "price": price,
                    "market_cap": int(market_cap),
                    "ncav": int(ncav),
                    "nc_ratio": nc_ratio,
                    "equity_ratio": round(norm_equity_ratio * 100, 1),
                    "submit_date": submit_date
                })

    # 新規問い合わせが発生した場合のみ当日分キャッシュを更新保存
    if fetches_attempted > 0:
        save_stock_cache(stock_cache, today_str)

    results_df = pd.DataFrame(results)
    if not results_df.empty:
        results_df = results_df.sort_values(by="nc_ratio", ascending=False)

    generate_html(results_df)
    
    # 分かりやすいログ出力
    logger.info(
        f"スクリーニング完了 - 検出件数: {len(results_df)} 件 | "
        f"株価取得実行: {fetches_attempted} 件 (成功: {fetches_successful} 件 / NO_DATA: {fetches_no_data} 件)"
    )

def generate_empty_html(message):
    html_content = f"<!DOCTYPE html><html lang='ja'><body><h2>ネットネット株スクリーナー</h2><p>{message}</p></body></html>"
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)

def generate_html(df):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    table_rows = ""

    if df.empty:
        table_rows = "<tr><td colspan='8'>現在、条件に該当する銘柄はありません。</td></tr>"
    else:
        for _, row in df.iterrows():
            table_rows += f"""
            <tr>
                <td>{row['sec_code']}</td>
                <td>{row['filer_name']}</td>
                <td>¥{row['price']:,.0f}</td>
                <td>¥{row['market_cap']/100_000_000:,.1f}億円</td>
                <td>¥{row['ncav']/100_000_000:,.1f}億円</td>
                <td><strong>{row['nc_ratio']:.2f}倍</strong></td>
                <td>{row['equity_ratio']:.1f}%</td>
                <td>{row['submit_date']}</td>
            </tr>
            """

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>ネットネット株スクリーナー</title>
    <style>
        body {{ font-family: sans-serif; margin: 20px; background: #f9f9f9; }}
        h1 {{ color: #333; }}
        .info {{ color: #666; font-size: 0.9em; margin-bottom: 15px; }}
        table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #2c3e50; color: #fff; }}
        tr:hover {{ background: #f1f1f1; }}
    </style>
</head>
<body>
    <h1>ネットネット株（NCAV割安株）一覧</h1>
    <div class="info">最終更新日時: {now_str} | 検出件数: {len(df)}件</div>
    <table>
        <thead>
            <tr>
                <th>コード</th>
                <th>企業名</th>
                <th>株価</th>
                <th>時価総額</th>
                <th>NCAV</th>
                <th>NC比率</th>
                <th>自己資本比率</th>
                <th>開示日</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
</body>
</html>
"""
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)

if __name__ == "__main__":
    main()
