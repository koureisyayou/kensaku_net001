import os
import time
import logging
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("screener.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("NetNetScreener")

CACHE_FILE = "stock_cache.csv"

def load_stock_cache():
    """株価・株式数・ステータスキャッシュの読み込み"""
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_csv(CACHE_FILE, dtype={"sec_code": str})
            cache = {}
            for _, row in df.iterrows():
                cache[str(row["sec_code"])] = {
                    "ticker": row.get("ticker", f"{row['sec_code']}.T"),
                    "price": float(row["price"]) if pd.notnull(row.get("price")) else None,
                    "shares": float(row["shares"]) if pd.notnull(row.get("shares")) else None,
                    "market_cap": float(row["market_cap"]) if pd.notnull(row.get("market_cap")) else None,
                    "status": row.get("status", "UNKNOWN"),
                    "updated_at": row.get("updated_at", "")
                }
            logger.info(f"株価キャッシュ読み込み完了: {len(cache)}件")
            return cache
        except Exception as e:
            logger.error(f"キャッシュ読み込み失敗: {e}")
            return {}
    return {}

def save_stock_cache(cache):
    """株価・株式数・ステータスキャッシュの保存"""
    rows = []
    for sec_code, data in cache.items():
        rows.append({
            "sec_code": sec_code,
            "ticker": data.get("ticker", f"{sec_code}.T"),
            "price": data.get("price"),
            "shares": data.get("shares"),
            "market_cap": data.get("market_cap"),
            "status": data.get("status"),
            "updated_at": data.get("updated_at")
        })
    df = pd.DataFrame(rows)
    df.to_csv(CACHE_FILE, index=False, encoding="utf-8")
    logger.info(f"株価キャッシュ保存完了: {len(df)}件")

def diagnose_and_fetch_stock_data(sec_code, max_retries=2):
    """
    Yahoo Finance から株価・株式数を取得し、結果と診断ステータスを返す。
    試行ティッカーは `${sec_code}.T` 固定。
    """
    ticker_symbol = f"{sec_code}.T"
    yf_logger = logging.getLogger("yfinance")
    prev_level = yf_logger.level
    yf_logger.setLevel(logging.CRITICAL)

    try:
        for attempt in range(1, max_retries + 1):
            try:
                ticker = yf.Ticker(ticker_symbol)

                # 1. 株価の取得 (5日分)
                hist = ticker.history(period="5d", auto_adjust=False)

                if hist.empty:
                    # Ticker情報自体の有無を確認する簡易チェック
                    try:
                        fast_info = ticker.fast_info
                        if not fast_info or len(fast_info) == 0:
                            logger.warning(f"DIAGNOSIS: {ticker_symbol} -> NOT_FOUND (銘柄未登録・廃止等)")
                            return None, None, None, "NOT_FOUND", ticker_symbol
                    except Exception:
                        pass
                    
                    if attempt < max_retries:
                        time.sleep(attempt * 1.0)
                        continue
                    logger.warning(f"DIAGNOSIS: {ticker_symbol} -> NO_PRICE (history rows=0)")
                    return None, None, None, "NO_PRICE", ticker_symbol

                if "Close" not in hist.columns:
                    logger.warning(f"DIAGNOSIS: {ticker_symbol} -> NO_PRICE (Close列なし)")
                    return None, None, None, "NO_PRICE", ticker_symbol

                close_series = hist["Close"].dropna()
                if close_series.empty:
                    logger.warning(f"DIAGNOSIS: {ticker_symbol} -> NO_PRICE (Close値全NaN)")
                    return None, None, None, "NO_PRICE", ticker_symbol

                price = float(close_series.iloc[-1])
                if price <= 0:
                    return None, None, None, "NO_PRICE", ticker_symbol

                # --- 株価取得成功 ---
                # 2. 発行済株式数の取得
                shares = None
                try:
                    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                    shares_series = ticker.get_shares_full(start=start_date)
                    if shares_series is not None and not shares_series.empty:
                        shares_series = shares_series.dropna()
                        if not shares_series.empty:
                            shares = float(shares_series.iloc[-1])
                except Exception as e:
                    logger.debug(f"get_shares_full error ({ticker_symbol}): {e}")

                if shares is None or shares <= 0:
                    try:
                        fast_shares = ticker.fast_info.get("shares")
                        if fast_shares is not None and float(fast_shares) > 0:
                            shares = float(fast_shares)
                    except Exception:
                        pass

                if shares is None or shares <= 0:
                    logger.warning(f"DIAGNOSIS: {ticker_symbol} -> NO_SHARES (株価={price}円, 株式数未取得)")
                    return price, None, None, "NO_SHARES", ticker_symbol

                # 株価・株式数ともに取得完了
                market_cap = price * shares
                logger.info(f"SUCCESS: {sec_code} ({ticker_symbol}) - 株価:{price:.1f}円, 時価総額:{market_cap/1e8:.2f}億円")
                return price, shares, market_cap, "SUCCESS", ticker_symbol

            except Exception as e:
                if attempt < max_retries:
                    time.sleep(attempt * 1.0)
                    continue
                logger.error(f"DIAGNOSIS: {ticker_symbol} -> YF_ERROR (通信・APIエラー: {e})")
                return None, None, None, "YF_ERROR", ticker_symbol

    finally:
        yf_logger.setLevel(prev_level)


def run_pipeline(financial_df):
    """
    スクリーニングパイプライン実行
    financial_df: 財務キャッシュデータ (DataFrame)
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    stock_cache = load_stock_cache()

    # 1. 第1段階：一次財務スクリーニング (NCAV > 0 & 自己資本比率 >= 30%)
    # ncav = 流動資産 - 全負債
    financial_df["ncav"] = financial_df["current_assets"] - financial_df["total_liabilities"]
    
    # フィルタリング
    stage1_df = financial_df[
        (financial_df["ncav"] > 0) & 
        (financial_df["equity_ratio"] >= 30.0)
    ].copy()

    logger.info(f"【第1段階】総銘柄数: {len(financial_df)} -> 財務スクリーニング通過: {len(stage1_df)}銘柄")

    # 2. 第2段階：株価・時価総額の取得と診断
    status_counts = {"SUCCESS": 0, "NOT_FOUND": 0, "NO_PRICE": 0, "NO_SHARES": 0, "YF_ERROR": 0, "CACHED": 0}
    results = []

    for _, row in stage1_df.iterrows():
        sec_code = str(row["sec_code"])
        
        # キャッシュのチェック (SUCCESSのデータのみ採用)
        if sec_code in stock_cache and stock_cache[sec_code].get("status") == "SUCCESS":
            cdata = stock_cache[sec_code]
            price = cdata["price"]
            shares = cdata["shares"]
            market_cap = cdata["market_cap"]
            status = "SUCCESS"
            ticker_symbol = cdata["ticker"]
            status_counts["CACHED"] += 1
        else:
            # 未キャッシュまたは過去にエラーだったものは新規取得試行
            price, shares, market_cap, status, ticker_symbol = diagnose_and_fetch_stock_data(sec_code)
            status_counts[status] += 1
            
            # キャッシュの更新
            stock_cache[sec_code] = {
                "ticker": ticker_symbol,
                "price": price,
                "shares": shares,
                "market_cap": market_cap,
                "status": status,
                "updated_at": today_str
            }

        if status == "SUCCESS" and market_cap and market_cap > 0:
            nc_ratio = row["ncav"] / market_cap
            if nc_ratio >= 1.0: # NCAV / 時価総額 >= 1.0 (ネットネット株)
                item = row.to_dict()
                item.update({
                    "ticker": ticker_symbol,
                    "price": price,
                    "shares": shares,
                    "market_cap": market_cap,
                    "nc_ratio": nc_ratio,
                    "net_cash_ratio": (row.get("cash_and_equivalents", 0) - row.get("total_liabilities", 0)) / market_cap
                })
                results.append(item)

    # キャッシュのディスク保存
    save_stock_cache(stock_cache)

    logger.info(f"【株価取得診断結果】 SUCCESS(新規): {status_counts['SUCCESS']}, キャッシュ利用: {status_counts['CACHED']}, "
                f"NOT_FOUND: {status_counts['NOT_FOUND']}, NO_PRICE: {status_counts['NO_PRICE']}, "
                f"NO_SHARES: {status_counts['NO_SHARES']}, YF_ERROR: {status_counts['YF_ERROR']}")

    candidates_df = pd.DataFrame(results)
    logger.info(f"【第2段階】ネットネット基準クリア (NCAV/時価総額 >= 1.0): {len(candidates_df)}銘柄")

    # 3. 第3段階・第4段階：二次スクリーニング & ランキング
    if not candidates_df.empty:
        # NCAV倍率順（割安度順）および自己資本比率・営業利益でスコアリング
        candidates_df = candidates_df.sort_values(by="nc_ratio", ascending=False)
        
        # 画面表示・ファイル出力用のカラム整理
        output_cols = [
            "sec_code", "company_name", "ticker", "price", "market_cap", 
            "ncav", "nc_ratio", "equity_ratio", "operating_income", 
            "cash_and_equivalents", "current_assets", "total_liabilities"
        ]
        available_cols = [c for c in output_cols if c in candidates_df.columns]
        summary_df = candidates_df[available_cols]
        
        # CSV等に保存
        summary_df.to_csv("net_net_candidates.csv", index=False, encoding="utf-8-sig")
        logger.info(f"ネットネット候補銘柄一覧を net_net_candidates.csv に出力しました。")
        return summary_df

    return pd.DataFrame()
