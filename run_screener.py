import os
import sys
import time
import logging
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf

import financials
from financials import safe_get  # 移設元と同名で使えるように再エクスポート
from price_metrics import add_price_metrics

# ログ設定：ファイルと標準出力（GitHub Actionsコンソール）の両方に出力
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("screener.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("NetNetScreener")

CACHE_FILE = "stock_cache.csv"
INVALID_FILE = "invalid_financials.csv"   # 妥当性チェックで弾いた行の記録
SHARES_CACHE_DAYS = 30  # 株式数キャッシュの有効期限（日）

# 東証のみを対象にする。
# ".F"(フランクフルト) や ".S" は海外市場で、価格が外貨建てのため
# 円建ての NCAV と比較すると時価総額が桁違いに小さく算出されてしまう。
CANDIDATE_SUFFIXES = [".T"]

# スクリーニング条件
MIN_EQUITY_RATIO = 30.0   # 自己資本比率(%)
MIN_NC_RATIO = 1.0        # NCAV / 時価総額

# yfinance へのリクエスト間隔（秒）。短すぎるとレート制限で連続失敗する。
REQUEST_INTERVAL = 0.4
RETRY_INTERVAL = 1.5

# 取得失敗を表すステータス。再試行の対象であり、回復したときは
# ここから1件減らす（どれを減らすかは元のステータスで決める）。
FAILED_STATUSES = ("NO_PRICE", "YF_ERROR", "NOT_FOUND")


def load_stock_cache():
    """株価・株式数・ステータスキャッシュの読み込み"""
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_csv(CACHE_FILE, dtype={"sec_code": str})
            cache = {}
            for _, row in df.iterrows():
                sec_code = str(row["sec_code"])
                cache[sec_code] = {
                    "ticker": row.get("ticker", f"{sec_code}.T"),
                    "price": float(row["price"]) if pd.notnull(row.get("price")) else None,
                    "shares": float(row["shares"]) if pd.notnull(row.get("shares")) else None,
                    "market_cap": float(row["market_cap"]) if pd.notnull(row.get("market_cap")) else None,
                    "status": str(row.get("status", "UNKNOWN")),
                    "updated_at": str(row.get("updated_at", "")),
                    "shares_updated_at": str(row.get("shares_updated_at", ""))
                }
            logger.info(f"株価・株式数キャッシュ読み込み完了: {len(cache)}件")
            return cache
        except Exception as e:
            logger.error(f"キャッシュ読み込み失敗 (新規作成します): {e}")
            return {}
    return {}


def save_stock_cache(cache):
    """
    株価・株式数・ステータスキャッシュの保存。

    ※ ここで add_price_metrics を呼んではいけない。
      このキャッシュは第1段階を通過した全銘柄（数百〜千件）を含むため、
      日足の一括取得が重すぎるうえ、価格指標が必要なのは最終候補だけである。
      指標の付与は run_pipeline の出力直前で行う。
    """
    rows = []
    for sec_code, data in cache.items():
        rows.append({
            "sec_code": sec_code,
            "ticker": data.get("ticker", f"{sec_code}.T"),
            "price": data.get("price"),
            "shares": data.get("shares"),
            "market_cap": data.get("market_cap"),
            "status": data.get("status"),
            "updated_at": data.get("updated_at"),
            "shares_updated_at": data.get("shares_updated_at")
        })
    df = pd.DataFrame(rows)
    df.to_csv(CACHE_FILE, index=False, encoding="utf-8")
    logger.info(f"株価・株式数キャッシュ保存完了: {len(df)}件")


def fetch_shares_count(ticker):
    """【重い処理】発行済株式数のみを取得（30日毎にのみ実行）"""
    shares = None
    try:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        shares_series = ticker.get_shares_full(start=start_date)
        if shares_series is not None and not shares_series.empty:
            shares_series = shares_series.dropna()
            if not shares_series.empty:
                shares = float(shares_series.iloc[-1])
    except Exception:
        pass

    if shares is None or shares <= 0:
        try:
            fast_shares = ticker.fast_info.get("shares")
            if fast_shares is not None and float(fast_shares) > 0:
                shares = float(fast_shares)
        except Exception:
            pass

    return shares


def fetch_single_ticker(ticker_symbol, existing_shares, is_shares_expired):
    """
    単一Tickerから最新株価を取得。
    株式数が未取得または有効期限切れの場合のみ株式数を重いAPIで再取得する。
    """
    try:
        ticker = yf.Ticker(ticker_symbol)

        # 1. 【軽量】最新株価の取得 (5日分)
        hist = ticker.history(period="5d", auto_adjust=False)
        if hist.empty or "Close" not in hist.columns:
            return None, existing_shares, False, "NO_PRICE"

        close_series = hist["Close"].dropna()
        if close_series.empty:
            return None, existing_shares, False, "NO_PRICE"

        price = float(close_series.iloc[-1])
        if price <= 0:
            return None, existing_shares, False, "NO_PRICE"

        # 2. 株式数の判定（キャッシュがあれば使い回し、無ければ再取得）
        shares = existing_shares
        shares_refreshed = False

        if shares is None or shares <= 0 or is_shares_expired:
            shares = fetch_shares_count(ticker)
            shares_refreshed = True

        if shares is None or shares <= 0:
            return price, None, shares_refreshed, "NO_SHARES"

        return price, shares, shares_refreshed, "SUCCESS"

    except Exception:
        return None, existing_shares, False, "YF_ERROR"


def diagnose_and_fetch_stock_data(sec_code, cached_info, today_str):
    """国内市場(.T)から株価と株式数を取得する。取得できない銘柄は候補から外す。"""
    yf_logger = logging.getLogger("yfinance")
    prev_level = yf_logger.level
    yf_logger.setLevel(logging.CRITICAL)

    existing_shares = cached_info.get("shares") if cached_info else None
    shares_updated_at = cached_info.get("shares_updated_at", "") if cached_info else ""
    # 欠損が文字列 "nan" として保存されると日付解釈に失敗し、毎回重いAPIを叩くことになる
    if shares_updated_at in (None, "nan", "NaT", "None"):
        shares_updated_at = ""

    is_shares_expired = True
    if shares_updated_at:
        try:
            last_date = datetime.strptime(shares_updated_at, "%Y-%m-%d")
            if (datetime.now() - last_date).days < SHARES_CACHE_DAYS:
                is_shares_expired = False
        except ValueError:
            is_shares_expired = True

    last_status = "NOT_FOUND"

    try:
        for suffix in CANDIDATE_SUFFIXES:
            ticker_symbol = f"{sec_code}{suffix}"
            price, shares, shares_refreshed, status = fetch_single_ticker(
                ticker_symbol, existing_shares, is_shares_expired
            )

            if status == "SUCCESS":
                market_cap = price * shares
                shares_date = today_str if shares_refreshed or not shares_updated_at else shares_updated_at

                logger.info(f"SUCCESS: {sec_code} ({ticker_symbol}) - 株価:{price:.1f}円, "
                            f"株式数:{'再取得' if shares_refreshed else 'キャッシュ利用'}, "
                            f"時価総額:{market_cap/1e8:.2f}億円")

                return price, shares, market_cap, "SUCCESS", ticker_symbol, shares_date

            elif status == "NO_SHARES":
                last_status = "NO_SHARES"
            elif status == "NO_PRICE" and last_status != "NO_SHARES":
                last_status = "NO_PRICE"
            elif status == "YF_ERROR" and last_status not in ["NO_SHARES", "NO_PRICE"]:
                last_status = "YF_ERROR"

        logger.warning(f"DIAGNOSIS: {sec_code} -> {last_status}")
        return None, None, None, last_status, f"{sec_code}.T", shares_updated_at

    finally:
        yf_logger.setLevel(prev_level)


def run_pipeline(financial_df):
    """スクリーニングパイプライン実行"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    stock_cache = load_stock_cache()

    financial_df = financials.prepare(financial_df)
    financial_df, _ = financials.validate(financial_df, invalid_path=INVALID_FILE)
    logger.info(f"【妥当性チェック】検証を通過した銘柄: {len(financial_df)}件")

    if financial_df.empty:
        logger.error("有効な財務データがありません。financial_cache.csv を再生成してください。")
        return pd.DataFrame()

    # 1. 第1段階：一次財務スクリーニング (NCAV > 0 & 自己資本比率 >= 30%)
    financial_df["ncav"] = financial_df["current_assets"] - financial_df["total_liabilities"]

    stage1_df = financial_df[
        (financial_df["ncav"] > 0) &
        (financial_df["equity_ratio"] >= MIN_EQUITY_RATIO)
    ].copy()

    logger.info(f"【第1段階】総銘柄数: {len(financial_df)} -> 財務スクリーニング通過: {len(stage1_df)}銘柄")

    # 2. 第2段階：株価の毎日更新＆株式数の条件付き更新
    status_counts = {"SUCCESS": 0, "NOT_FOUND": 0, "NO_PRICE": 0, "NO_SHARES": 0, "YF_ERROR": 0}
    results = []
    rows_by_code = {str(row["sec_code"]): row for _, row in stage1_df.iterrows()}

    def process(sec_code, row):
        """1銘柄分の株価取得・キャッシュ更新・ネットネット判定。ステータスを返す。"""
        cached_info = stock_cache.get(sec_code)

        price, shares, market_cap, status, ticker_symbol, shares_updated_at = diagnose_and_fetch_stock_data(
            sec_code, cached_info, today_str
        )

        # 取得失敗時に前回値を捨てると、翌日また重い株式数APIを叩くことになり
        # レート制限の悪循環に陥る。直近の値を残しておく。
        if status != "SUCCESS" and cached_info:
            price = price if price is not None else cached_info.get("price")
            shares = shares if shares is not None else cached_info.get("shares")
            market_cap = market_cap if market_cap is not None else cached_info.get("market_cap")

        stock_cache[sec_code] = {
            "ticker": ticker_symbol,
            "price": price,
            "shares": shares,
            "market_cap": market_cap,
            "status": status,
            "updated_at": today_str,
            "shares_updated_at": shares_updated_at
        }

        # ネットネット判定 (NCAV / 時価総額 >= 1.0)
        if status == "SUCCESS" and market_cap and market_cap > 0:
            nc_ratio = row["ncav"] / market_cap
            if nc_ratio >= MIN_NC_RATIO:
                item = row.to_dict()
                item.update({
                    "ticker": ticker_symbol,
                    "price": price,
                    "shares": shares,
                    "market_cap": market_cap,
                    "nc_ratio": nc_ratio,
                })

                # ネットキャッシュは現金の値が取れている銘柄だけ計算する
                cash = safe_get(row, "cash_and_equivalents")
                if cash is not None:
                    net_cash = float(cash) - float(row["total_liabilities"])
                    item["net_cash"] = net_cash
                    item["net_cash_ratio"] = net_cash / market_cap

                results.append(item)

        return status

    for sec_code, row in rows_by_code.items():
        status = process(sec_code, row)
        status_counts[status] = status_counts.get(status, 0) + 1
        time.sleep(REQUEST_INTERVAL)

    # 取得失敗の再試行。
    # Yahoo側のレート制限にかかると失敗が連続して発生し、上場している銘柄まで
    # NO_PRICE として落ちてしまうため、間隔を空けて一度だけやり直す。
    retry_codes = [c for c in rows_by_code
                   if stock_cache.get(c, {}).get("status") in FAILED_STATUSES]

    if retry_codes:
        logger.info(f"↻ 取得失敗 {len(retry_codes)}銘柄を再試行します（間隔 {RETRY_INTERVAL}秒）")
        time.sleep(5)
        recovered = 0
        for sec_code in retry_codes:
            # 回復したときにどのステータスから1件減らすかを決めるため、
            # process() がキャッシュを上書きする前に元のステータスを控える。
            # 固定の順番（NO_PRICE→YF_ERROR→NOT_FOUND）で減らすと、
            # YF_ERROR だった銘柄が回復しても NO_PRICE の件数が減ってしまい、
            # 診断結果の内訳が実態とずれる。
            prev_status = stock_cache.get(sec_code, {}).get("status")

            status = process(sec_code, rows_by_code[sec_code])
            if status == "SUCCESS":
                recovered += 1
                status_counts["SUCCESS"] += 1
                if prev_status and status_counts.get(prev_status, 0) > 0:
                    status_counts[prev_status] -= 1
            time.sleep(RETRY_INTERVAL)
        logger.info(f"↻ 再試行で {recovered}/{len(retry_codes)} 銘柄が回復しました")

        if recovered > len(retry_codes) * 0.3:
            logger.warning(
                "⚠ 再試行で多数が回復しました。初回取得時にレート制限を受けている可能性があります。"
                "REQUEST_INTERVAL を大きくすることを検討してください。"
            )

    save_stock_cache(stock_cache)

    logger.info(f"【株価取得診断結果】 SUCCESS: {status_counts.get('SUCCESS', 0)}, "
                f"NOT_FOUND: {status_counts.get('NOT_FOUND', 0)}, NO_PRICE: {status_counts.get('NO_PRICE', 0)}, "
                f"NO_SHARES: {status_counts.get('NO_SHARES', 0)}, YF_ERROR: {status_counts.get('YF_ERROR', 0)}")

    candidates_df = pd.DataFrame(results)
    logger.info(f"【第2段階】ネットネット基準クリア (NCAV/時価総額 >= {MIN_NC_RATIO}): {len(candidates_df)}銘柄")

    # 3. 第3段階：出力
    if not candidates_df.empty:
        candidates_df = candidates_df.sort_values(by="nc_ratio", ascending=False)

        output_cols = [
            "sec_code", "company_name", "ticker", "price", "market_cap",
            "ncav", "nc_ratio", "equity_ratio", "cash_and_equivalents",
            "net_cash", "net_cash_ratio", "current_assets", "total_liabilities",
            "total_assets", "accounting_standard", "consolidated", "fiscal_period",
            # bs_date は貸借対照表の基準日（XBRLコンテキストの instant）。
            # fiscal_period は EDINET の periodEnd（会計年度末）で、半期報告書では
            # 未来日になるため、データの鮮度判定には bs_date を使う。
            # submit_date は既存キャッシュにも入っているので、bs_date が揃うまでの代用。
            "bs_date", "submit_date"
        ]
        available_cols = [c for c in output_cols if c in candidates_df.columns]
        summary_df = candidates_df[available_cols].copy()

        # 価格指標（安値乖離・騰落率・停滞日数・売買代金）を列として付与する。
        # 最終候補に対してのみ日足を取得するので、ここが正しい呼び出し位置。
        # 失敗してもスクリーニング自体は成立させたいので握りつぶす。
        try:
            summary_df = add_price_metrics(summary_df, ticker_col="ticker")
            logger.info("価格指標の列を付与しました。")
        except Exception as e:
            logger.warning(f"価格指標の付与に失敗しました（列なしで続行します）: {e}")

        summary_df.to_csv("net_net_candidates.csv", index=False, encoding="utf-8-sig")
        logger.info("ネットネット候補銘柄一覧を net_net_candidates.csv に出力しました。")
        return summary_df

    return pd.DataFrame()


if __name__ == "__main__":
    logger.info("--- スクリーナー実行開始 ---")

    financial_file = "financial_cache.csv"
    if not os.path.exists(financial_file):
        logger.error(f"エラー: {financial_file} が見つかりません。先に財務キャッシュ生成を行ってください。")
        sys.exit(1)

    try:
        financial_df = pd.read_csv(financial_file, dtype={"sec_code": str})
        logger.info(f"{financial_file} 読み込み完了: {len(financial_df)}件")

        run_pipeline(financial_df)

    except Exception as e:
        logger.critical(f"スクリーナー処理中に致命的なエラーが発生しました: {e}", exc_info=True)
        sys.exit(1)

    logger.info("--- スクリーナー実行完了 ---")
