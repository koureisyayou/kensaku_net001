import os
import sys
import time
import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

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
    # 金融・REIT等の除外コード（必要に応じて追加）
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
    """
    当日分の株価キャッシュを読み込む。
    成功(SUCCESS / 旧OK)したデータのみをキャッシュとして復元する。
    """
    if not os.path.exists(STOCK_CACHE_FILE):
        return {}
    try:
        df_stock = pd.read_csv(STOCK_CACHE_FILE, dtype={"sec_code": str, "status": str})
        df_today = df_stock[df_stock["checked_at"] == today_str]
        
        cache = {}
        for _, row in df_today.iterrows():
            sec_code = str(row["sec_code"]).strip()
            status = str(row.get("status", "SUCCESS"))
            
            # 成功状態のデータのみキャッシュ利用対象とする
            if status in ["OK", "SUCCESS"]:
                status = "SUCCESS"
            else:
                continue  # NO_PRICE, NO_SHARES, YF_ERROR などはキャッシュ非対象

            m_cap = float(row["market_cap"]) if pd.notna(row.get("market_cap")) else None
            prc = float(row["price"]) if pd.notna(row.get("price")) else None
            
            if m_cap is not None and prc is not None:
                cache[sec_code] = (m_cap, prc, status)
        return cache
    except Exception as e:
        logger.warning(f"株価キャッシュ読み込みエラー: {e}")
        return {}

def save_stock_cache(stock_cache_data, today_str):
    """
    株価キャッシュをCSVに保存する（SUCCESS のデータのみを厳元保存）。
    """
    try:
        records = []
        for sec_code, item in stock_cache_data.items():
            market_cap, price, status = item
            # 成功時(SUCCESS)のみ永続キャッシュ化
            if status != "SUCCESS":
                continue

            records.append({
                "sec_code": sec_code,
                "market_cap": market_cap if market_cap is not None else "",
                "price": price if price is not None else "",
                "status": status,
                "checked_at": today_str
            })
        df = pd.DataFrame(records)
        df.to_csv(STOCK_CACHE_FILE, index=False, encoding="utf-8-sig")
        logger.info(f"株価キャッシュ（当日成功分）を保存しました ({len(df)} 件)")
    except Exception as e:
        logger.error(f"株価キャッシュ保存エラー: {e}")

def normalize_sec_code(sec_code_raw):
    code_str = str(sec_code_raw).strip()
    if code_str.isdigit():
        return code_str.zfill(4)
    return code_str.upper()

def get_stock_data_from_yahoo(sec_code, max_retries=2):
    """
    Yahoo Finance から株価と株式数を取得し、時価総額を算出する。
    一時エラー（レート制限等）対策として最大 max_retries 回のリトライ処理を行う。
    
    Returns:
        (market_cap, price, status)
        - SUCCESS: 株価・株式数ともに取得成功
        - NO_PRICE: 株価の取得に失敗（※キャッシュ非対象）
        - NO_SHARES: 株価取得成功だが株式数取得失敗（※キャッシュ非対象）
        - YF_ERROR: 通信エラー等の例外発生（※キャッシュ非対象）
    """
    ticker_symbol = f"{sec_code}.T"

    yf_logger = logging.getLogger("yfinance")
    previous_level = yf_logger.level
    yf_logger.setLevel(logging.CRITICAL)

    try:
        for attempt in range(1, max_retries + 1):
            try:
                ticker = yf.Ticker(ticker_symbol)

                # 1. 株価取得 (Price)
                hist = ticker.history(period="5d", auto_adjust=False)

                if hist.empty or "Close" not in hist.columns:
                    if attempt < max_retries:
                        time.sleep( attempt * 1.5 )
                        continue
                    logger.warning(f"NO_PRICE: {ticker_symbol} - historyが空またはClose列なし")
                    return None, None, "NO_PRICE"

                close_series = hist["Close"].dropna()
                if close_series.empty:
                    if attempt < max_retries:
                        time.sleep( attempt * 1.5 )
                        continue
                    logger.warning(f"NO_PRICE: {ticker_symbol} - 有効なCloseデータなし")
                    return None, None, "NO_PRICE"

                price = float(close_series.iloc[-1])
                if price <= 0:
                    logger.warning(f"NO_PRICE: {ticker_symbol} - 株価が0以下: {price}")
                    return None, None, "NO_PRICE"

                # 2. 発行済株式数取得 (Shares)
                shares = None
                try:
                    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                    shares_series = ticker.get_shares_full(start=start_date)

                    if shares_series is not None and not shares_series.empty:
                        shares_series = shares_series.dropna()
                        if not shares_series.empty:
                            shares = float(shares_series.iloc[-1])
                except Exception as e:
                    logger.debug(f"get_shares_full 取得エラー ({ticker_symbol}): {e}")

                # 予備手段: fast_info の shares を参照
                if shares is None or shares <= 0:
                    try:
                        fast_shares = ticker.fast_info.get("shares")
                        if fast_shares is not None and float(fast_shares) > 0:
                            shares = float(fast_shares)
                    except Exception:
                        pass

                if shares is None or shares <= 0:
                    logger.warning(f"NO_SHARES: {ticker_symbol} - 株価成功({price:.1f}円)だが株式数不詳")
                    return None, price, "NO_SHARES"

                # 時価総額算出成功
                market_cap = price * shares
                return float(market_cap), float(price), "SUCCESS"

            except Exception as e:
                if attempt < max_retries:
                    time.sleep( attempt * 1.5 )
                    continue
                logger.warning(f"YF_ERROR: {ticker_symbol} - 取得例外発生 (attempt={attempt}): {e}")
                return None, None, "YF_ERROR"

    finally:
        yf_logger.setLevel(previous_level)

    return None, None, "YF_ERROR"

def main():
    logger.info("=== スクリーニング処理を開始します ===")
    today_str = datetime.now().strftime("%Y-%m-%d")

    if not os.path.exists(CACHE_FILE):
        logger.error(f"財務キャッシュファイル ({CACHE_FILE}) が見つかりません。")
        generate_empty_html("財務キャッシュファイルが存在しません。")
        return

    try:
        df = pd.read_csv(CACHE_FILE, dtype=str)
        df["current_assets"] = pd.to_numeric(df.get("current_assets"), errors="coerce").fillna(0)
        df["total_liabilities"] = pd.to_numeric(df.get("total_liabilities"), errors="coerce").fillna(0)
        
        raw_eq = pd.to_numeric(df.get("equity_ratio"), errors="coerce").fillna(0)
        df["equity_ratio_norm"] = raw_eq.apply(lambda x: x / 100.0 if x > 1.0 else x)

    except Exception as e:
        logger.error(f"キャッシュ読み込み・クレンジングエラー: {e}")
        generate_empty_html("キャッシュデータの読み込みに失敗しました。")
        return

    stock_cache = load_stock_cache(today_str)
    
    total_tickers = len(df)
    financial_passed = 0
    cached_count = 0
    new_fetch_count = 0
    
    status_counts = {
        "SUCCESS": 0,
        "NO_PRICE": 0,
        "NO_SHARES": 0,
        "YF_ERROR": 0
    }
    
    results = []
    logger.info(f"全対象銘柄数: {total_tickers} 件")

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

        financial_passed += 1

        # --- 株価・時価総額 取得処理 ---
        if sec_code in stock_cache:
            market_cap, price, status = stock_cache[sec_code]
            cached_count += 1
        else:
            market_cap, price, status = get_stock_data_from_yahoo(sec_code)
            new_fetch_count += 1
            status_counts[status] = status_counts.get(status, 0) + 1
            
            # 【重要】SUCCESS の場合のみ当日キャッシュへ登録する
            if status == "SUCCESS":
                stock_cache[sec_code] = (market_cap, price, status)

        # スクリーニング判定 (NC比率 >= 1.0 かつ 時価総額 <= 500億円)
        if market_cap and market_cap > 0:
            nc_ratio = round(ncav / market_cap, 2)
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

    # 新規成功データがあればキャッシュを更新保存
    if new_fetch_count > 0:
        save_stock_cache(stock_cache, today_str)

    results_df = pd.DataFrame(results)
    if not results_df.empty:
        results_df = results_df.sort_values(by="nc_ratio", ascending=False)

    generate_html(results_df)
    
    # トラッキングサマリー出力
    logger.info("=== スクリーニング実行結果 summary ===")
    logger.info(f"全対象銘柄数            : {total_tickers} 件")
    logger.info(f"財務条件通過 (NCAV>0/自己資本比率>=30%): {financial_passed} 件")
    logger.info(f"株価データ取得内訳      : 既存キャッシュ {cached_count} 件 / 新規取得 {new_fetch_count} 件")
    if new_fetch_count > 0:
        logger.info(f"  ├ SUCCESS       : {status_counts['SUCCESS']} 件")
        logger.info(f"  ├ NO_PRICE      : {status_counts['NO_PRICE']} 件（※未キャッシュ・再試行対象）")
        logger.info(f"  ├ NO_SHARES     : {status_counts['NO_SHARES']} 件（※未キャッシュ・再試行対象）")
        logger.info(f"  └ YF_ERROR      : {status_counts['YF_ERROR']} 件（※未キャッシュ・再試行対象）")
    logger.info(f"最終検出件数 (NC比率>=1.0 & 時価総額<=500億): {len(results_df)} 件")
    logger.info("==========================================")

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
