"""run_screener_local.py

地方単独上場（現状は名証）のネットネット候補を抽出し、
net_net_candidates_local.csv を出力する。

東証版（run_screener.py）と分けている理由:
  - 価格の出所が違う。yfinance には名証単独銘柄の日足が無いため、
    名証の株式相場表PDF（fetch_local_prices.py）から取った約定値を使う。
  - 株式数の出所が違う。yfinance が使えないので EDINET の shares_outstanding
    を使う。増資・分割の反映が遅れるため、鮮度をフラグで持つ。
  - 流動性の桁が違う。東証版の閾値（20日平均売買代金 5百万円以上）を当てると
    地方単独銘柄はほぼ全滅するため、閾値表を共有しない。

入力:
    financial_cache.csv   EDINET由来の財務・発行済株式数
    local_prices.csv      名証の相場表から作った20営業日集計
    tse_listed.csv        東証上場銘柄一覧（fetch_jpx_listed.py）

出力:
    net_net_candidates_local.csv
    invalid_financials_local.csv   妥当性チェックで弾いた行

使い方:
    python run_screener_local.py
    python run_screener_local.py --include-tse   東証重複上場も残す
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

import financials

FINANCIAL_CSV = "financial_cache.csv"
LOCAL_PRICES_CSV = "local_prices.csv"
OUTPUT_CSV = "net_net_candidates_local.csv"
INVALID_CSV = "invalid_financials_local.csv"

# --- 地方版の閾値（東証版とは意図的に別に持つ） ---
MIN_EQUITY_RATIO = 30.0     # 自己資本比率(%) 東証版と同じ
MIN_NC_RATIO = 1.0          # NCAV / 時価総額  東証版と同じ
MIN_TRADED_DAYS = 1         # 集計期間内に最低これだけ約定していること
# 売買代金の下限は設けない。地方単独は数十万円/日が常態で、
# 下限を入れると母集団が消える。列として出し、判断は人に委ねる。
MIN_TURNOVER_MYEN = 0.0

# 株数の鮮度。除外はせず列とフラグに留める。
SHARES_STALE_DAYS = 180

# 結合で落ちた銘柄をログに列挙するときの上限。
DIAG_LIST_LIMIT = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("screener_local.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("LocalScreener")


def normalize_code(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.upper()
        .str.zfill(4)
    )


def annotate_tse(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """東証重複上場のフラグを付ける。tse_listed.csv が無ければ何もしない。"""
    try:
        from fetch_jpx_listed import annotate
    except ImportError:
        logger.warning("fetch_jpx_listed.py が見つかりません。東証重複の判別を行いません。")
        return df, False

    if not Path("tse_listed.csv").exists():
        logger.warning(
            "tse_listed.csv がありません。先に python fetch_jpx_listed.py を実行してください。"
            "今回は東証重複の判別を行わずに続行します。"
        )
        return df, False

    return annotate(df), True


def log_merge_diagnosis(local: pd.DataFrame, fin: pd.DataFrame, stage1: pd.DataFrame) -> None:
    """結合で落ちた銘柄の内訳を出す。

    「財務と相場の両方が揃った銘柄: N件」だけでは、残りが
      ・財務データそのものが無い
      ・財務はあるが第1段階（NCAV>0 かつ 自己資本比率30%以上）で落ちた
    のどちらなのか分からない。前者はデータの取りこぼしで調べる価値があるが、
    後者は篩が正しく働いているだけで、対処するものではない。
    毎回この区別を手で調べ直さずに済むよう、内訳をログに残す。
    """
    local_codes = set(local["sec_code"])
    fin_codes = set(fin["sec_code"])
    stage1_codes = set(stage1["sec_code"])

    no_fin = sorted(local_codes - fin_codes)
    dropped = sorted((local_codes & fin_codes) - stage1_codes)

    def _fmt(codes):
        head = ", ".join(codes[:DIAG_LIST_LIMIT])
        return head + (" ..." if len(codes) > DIAG_LIST_LIMIT else "")

    if no_fin:
        logger.info(
            f"  ├ 財務データ無し: {len(no_fin)}件 ({_fmt(no_fin)})"
        )
        logger.info(
            "  │   EDINETに書類が無いか、証券コードが突合できていない可能性がある。"
        )
    if dropped:
        logger.info(
            f"  ├ 第1段階で除外: {len(dropped)}件 ({_fmt(dropped)})"
        )
        logger.info(
            f"  │   NCAV<=0 または 自己資本比率<{MIN_EQUITY_RATIO:.0f}%。篩が働いた結果であり異常ではない。"
        )
    if not no_fin and not dropped:
        logger.info("  └ 相場データのある銘柄はすべて第1段階を通過している。")


def main():
    parser = argparse.ArgumentParser(description="地方単独上場のネットネット候補抽出")
    parser.add_argument("--include-tse", action="store_true",
                        help="東証重複上場の銘柄も出力に残す")
    args = parser.parse_args()

    logger.info("--- 地方版スクリーナー実行開始 ---")

    for path in (FINANCIAL_CSV, LOCAL_PRICES_CSV):
        if not Path(path).exists():
            logger.error(f"{path} が見つかりません。")
            sys.exit(1)

    # ---------------------------------------------------------- 財務
    fin = financials.prepare(financials.load(FINANCIAL_CSV))
    fin, _ = financials.validate(fin, invalid_path=INVALID_CSV)
    logger.info(f"【妥当性チェック】通過: {len(fin)}件")

    if fin.empty:
        logger.error("有効な財務データがありません。")
        sys.exit(1)

    fin["sec_code"] = normalize_code(fin["sec_code"])
    fin["ncav"] = fin["current_assets"] - fin["total_liabilities"]

    stage1 = fin[(fin["ncav"] > 0) & (fin["equity_ratio"] >= MIN_EQUITY_RATIO)].copy()
    logger.info(f"【第1段階】財務スクリーニング通過: {len(stage1)}件 / {len(fin)}件")

    # ---------------------------------------------------------- 株価
    local = pd.read_csv(LOCAL_PRICES_CSV, dtype={"sec_code": str})
    local["sec_code"] = normalize_code(local["sec_code"])
    logger.info(f"名証の相場データ: {len(local)}件")

    local, tse_ok = annotate_tse(local)

    if tse_ok and not args.include_tse:
        before = len(local)
        local = local[local["is_local_only"]].copy()
        logger.info(f"【東証重複の除外】{before}件 -> 地方単独 {len(local)}件")

    # 集計期間内に約定のない銘柄（気配値のみ）は対象にしない。
    # 気配値で NCAV倍率を計算しても、その値段で売買できる根拠がない。
    before = len(local)
    local = local[
        (pd.to_numeric(local.get("traded_days_20"), errors="coerce").fillna(0) >= MIN_TRADED_DAYS)
        & local["price"].notnull()
    ].copy()
    logger.info(f"【約定フィルタ】{before}件 -> 期間内に約定あり {len(local)}件")

    if MIN_TURNOVER_MYEN > 0 and "avg_turnover_20_m" in local.columns:
        before = len(local)
        local = local[
            pd.to_numeric(local["avg_turnover_20_m"], errors="coerce").fillna(0)
            >= MIN_TURNOVER_MYEN
        ].copy()
        logger.info(f"【流動性フィルタ】{before}件 -> {len(local)}件")

    # ---------------------------------------------------------- 結合
    # 銘柄名は財務側（EDINETの提出者名）を正とし、名証側の略称は別列に残す。
    #
    # 結合相手は fin（財務データ全体）ではなく stage1（第1段階通過分）。
    # したがって「揃わなかった」銘柄には、財務データが無いものと、
    # 財務はあるが NCAV・自己資本比率の条件で落ちたものの両方が含まれる。
    local = local.rename(columns={"name": "local_name"})
    merged = stage1.merge(local, on="sec_code", how="inner", suffixes=("", "_local"))
    logger.info(
        f"【結合】第1段階を通過し、かつ相場データがある銘柄: "
        f"{len(merged)}件 / 相場データ {len(local)}件"
    )
    log_merge_diagnosis(local, fin, stage1)

    if merged.empty:
        logger.warning("結合結果が0件です。空のCSVを出力して終了します。")
        pd.DataFrame(columns=["sec_code", "company_name"]).to_csv(
            OUTPUT_CSV, index=False, encoding="utf-8-sig"
        )
        return

    # ---------------------------------------------------------- 時価総額
    if "shares_outstanding" not in merged.columns:
        logger.error(
            "financial_cache.csv に shares_outstanding 列がありません。"
            "update_financials.py を実行してキャッシュを更新してください。"
        )
        sys.exit(1)

    shares = pd.to_numeric(merged["shares_outstanding"], errors="coerce")
    no_shares = int((shares.isnull() | (shares <= 0)).sum())
    if no_shares:
        logger.warning(f"発行済株式数が無い {no_shares}件を除外します。")

    merged = merged[shares.notnull() & (shares > 0)].copy()
    if merged.empty:
        logger.warning("株式数が取れた銘柄がありません。")
        pd.DataFrame(columns=["sec_code", "company_name"]).to_csv(
            OUTPUT_CSV, index=False, encoding="utf-8-sig"
        )
        return

    merged["shares"] = pd.to_numeric(merged["shares_outstanding"], errors="coerce")
    merged["market_cap"] = pd.to_numeric(merged["price"], errors="coerce") * merged["shares"]
    merged["nc_ratio"] = merged["ncav"] / merged["market_cap"]

    # 株数の鮮度。増資・分割があると時価総額が桁でずれるため、必ず併記する。
    if "shares_as_of" in merged.columns:
        as_of = pd.to_datetime(merged["shares_as_of"], errors="coerce")
        merged["shares_age_days"] = (pd.Timestamp.now().normalize() - as_of).dt.days
        merged["shares_stale"] = merged["shares_age_days"] >= SHARES_STALE_DAYS
        stale = int(merged["shares_stale"].fillna(False).sum())
        if stale:
            logger.info(f"株数が{SHARES_STALE_DAYS}日以上前の銘柄: {stale}件（除外せずフラグ）")
    else:
        merged["shares_age_days"] = pd.NA
        merged["shares_stale"] = False

    # ネットキャッシュは現金が取れている銘柄だけ
    if "cash_and_equivalents" in merged.columns:
        cash = pd.to_numeric(merged["cash_and_equivalents"], errors="coerce")
        merged["net_cash"] = cash - merged["total_liabilities"]
        merged["net_cash_ratio"] = merged["net_cash"] / merged["market_cap"]

    # ---------------------------------------------------------- 判定
    before = len(merged)
    candidates = merged[merged["nc_ratio"] >= MIN_NC_RATIO].copy()
    logger.info(
        f"【第2段階】NCAV/時価総額 >= {MIN_NC_RATIO}: {before}件 -> {len(candidates)}件"
    )

    if candidates.empty:
        logger.warning("ネットネット基準を満たす銘柄がありませんでした。")
        pd.DataFrame(columns=["sec_code", "company_name"]).to_csv(
            OUTPUT_CSV, index=False, encoding="utf-8-sig"
        )
        return

    candidates = candidates.sort_values("nc_ratio", ascending=False)

    output_cols = [
        "sec_code", "company_name", "local_name", "market", "sector",
        "price", "price_date", "days_since_trade", "traded_days_20",
        "avg_turnover_20", "avg_turnover_20_m", "window_days", "as_of",
        "shares", "shares_as_of", "shares_age_days", "shares_stale", "shares_source",
        "market_cap", "ncav", "nc_ratio", "equity_ratio",
        "cash_and_equivalents", "net_cash", "net_cash_ratio",
        "current_assets", "total_liabilities", "total_assets",
        "accounting_standard", "consolidated", "fiscal_period", "bs_date", "submit_date",
        "alert_section", "is_supervised", "is_tse_listed", "is_local_only", "tse_list_as_of",
    ]
    available = [c for c in output_cols if c in candidates.columns]
    out = candidates[available].copy()

    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"{OUTPUT_CSV} に {len(out)}件を出力しました。")

    supervised = int(out.get("is_supervised", pd.Series(dtype=bool)).fillna(False).sum())
    if supervised:
        logger.warning(
            f"⚠ 監理・整理区画の銘柄が {supervised}件 含まれています（除外していません）。"
        )

    logger.info("--- 地方版スクリーナー実行完了 ---")


if __name__ == "__main__":
    main()
