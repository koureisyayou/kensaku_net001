"""yearly_high_low.py

銘柄ごとの「暦年ごとの高値・安値」を蓄積ファイルに貯める。

過去の年の高安は確定値で、二度と変わらない。だから一度取ったら取り直さない。
日々変わるのは当年の行だけなので、そこだけ毎日上書きする。

    初回        : 候補銘柄すべてが未取得 → 10年分を取得して追記
    2回目以降   : 取得済みはスキップ（当年の行だけ更新）
    新規の候補  : その銘柄だけ10年分を取得

出力: yearly_high_low.csv （累積ファイル。生成物ではないので上書きしない）
    sec_code, ticker, year, high, low, days, updated_at

days は その年に何営業日分のデータがあったか。上場年・当年は少なくなるので、
「1年まるごとの高安か」を後から判断するために持っている。

使い方:
    python yearly_high_low.py                       # net_net_candidates.csv の銘柄
    python yearly_high_low.py --source all          # financial_cache.csv の全銘柄
    python yearly_high_low.py --limit 300           # 新規取得を300銘柄で打ち切る
    python yearly_high_low.py --years 10            # さかのぼる年数
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf

HISTORY_FILE = "yearly_high_low.csv"
CANDIDATES_FILE = "net_net_candidates.csv"
FINANCIAL_CACHE = "financial_cache.csv"

CHUNK_SIZE = 50        # yfinance へ一度に投げる銘柄数
DEFAULT_YEARS = 10

COLUMNS = ["sec_code", "ticker", "year", "high", "low", "days", "updated_at"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("yearly_high_low.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- 入出力

def load_history() -> pd.DataFrame:
    if not os.path.exists(HISTORY_FILE):
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(HISTORY_FILE, dtype={"sec_code": str, "ticker": str})
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
        return df
    except Exception as e:
        logger.warning(f"蓄積ファイルの読み込みに失敗しました（新規作成します）: {e}")
        return pd.DataFrame(columns=COLUMNS)


def load_targets(source: str) -> pd.DataFrame:
    """(sec_code, ticker) の一覧を返す。"""
    if source == "all":
        if not os.path.exists(FINANCIAL_CACHE):
            logger.error(f"{FINANCIAL_CACHE} がありません。")
            return pd.DataFrame(columns=["sec_code", "ticker"])
        df = pd.read_csv(FINANCIAL_CACHE, dtype={"sec_code": str})
        out = pd.DataFrame({"sec_code": df["sec_code"].dropna().unique()})
        out["ticker"] = out["sec_code"] + ".T"
        return out

    if not os.path.exists(CANDIDATES_FILE):
        logger.error(f"{CANDIDATES_FILE} がありません。先にスクリーニングを実行してください。")
        return pd.DataFrame(columns=["sec_code", "ticker"])

    df = pd.read_csv(CANDIDATES_FILE, dtype={"sec_code": str})
    cols = [c for c in ("sec_code", "ticker") if c in df.columns]
    if "ticker" not in cols:
        df["ticker"] = df["sec_code"].astype(str) + ".T"
    return df[["sec_code", "ticker"]].dropna().drop_duplicates()


# ---------------------------------------------------------------- 取得

def download(tickers: list[str], years: int) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}

    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        logger.info(f"  取得中 [{i + 1}-{i + len(chunk)}/{len(tickers)}]")
        try:
            raw = yf.download(
                chunk,
                period=f"{years}y",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,   # 分割調整。しないと過去の高安が現在と比較できない
                threads=True,
                progress=False,
            )
        except Exception as e:
            logger.warning(f"  一括取得に失敗しました: {e}")
            continue

        if raw is None or raw.empty:
            continue

        for ticker in chunk:
            try:
                df = raw[ticker] if len(chunk) > 1 else raw
            except KeyError:
                continue
            df = df.dropna(subset=["Close"])
            if not df.empty:
                frames[ticker] = df

    return frames


def to_yearly(sec_code: str, ticker: str, df: pd.DataFrame, today: str) -> list[dict]:
    """日足を暦年ごとの高安に畳む。"""
    high_col = "High" if "High" in df.columns else "Close"
    low_col = "Low" if "Low" in df.columns else "Close"

    rows = []
    for year, part in df.groupby(df.index.year):
        hi = float(part[high_col].max())
        lo = float(part[low_col].min())
        if pd.isna(hi) or pd.isna(lo):
            continue
        rows.append({
            "sec_code": sec_code,
            "ticker": ticker,
            "year": int(year),
            "high": round(hi, 2),
            "low": round(lo, 2),
            "days": int(len(part)),
            "updated_at": today,
        })
    return rows


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser(description="年別高安の蓄積")
    ap.add_argument("--source", choices=["candidates", "all"], default="candidates",
                    help="対象銘柄。candidates=候補のみ / all=財務キャッシュの全銘柄")
    ap.add_argument("--years", type=int, default=DEFAULT_YEARS,
                    help="新規銘柄でさかのぼる年数")
    ap.add_argument("--limit", type=int, default=0,
                    help="新規取得の上限（0は無制限）。初回を分割実行する用途。")
    ap.add_argument("--refresh-current-year", action="store_true", default=True,
                    help="取得済み銘柄でも当年の行は取り直す（既定で有効）")
    args = ap.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.now().year

    history = load_history()
    targets = load_targets(args.source)

    if targets.empty:
        logger.error("対象銘柄がありません。")
        return

    known = set(history["sec_code"].dropna().astype(str)) if not history.empty else set()
    new_targets = targets[~targets["sec_code"].astype(str).isin(known)]
    old_targets = targets[targets["sec_code"].astype(str).isin(known)]

    logger.info(f"対象 {len(targets)} 銘柄 / 未取得 {len(new_targets)} / 取得済み {len(old_targets)}")
    logger.info(f"蓄積ファイル: {len(history)} 行 / {len(known)} 銘柄")

    if args.limit and len(new_targets) > args.limit:
        logger.info(f"[limit] 未取得のうち {args.limit} 銘柄のみ処理します（残りは次回）。")
        new_targets = new_targets.head(args.limit)

    added_rows = []

    # --- 未取得の銘柄: 過去N年分をまとめて取る -----------------------
    if not new_targets.empty:
        logger.info(f"未取得 {len(new_targets)} 銘柄の過去{args.years}年分を取得します。")
        frames = download(new_targets["ticker"].astype(str).tolist(), args.years)
        got = 0
        for _, row in new_targets.iterrows():
            df = frames.get(str(row["ticker"]))
            if df is None or df.empty:
                continue
            added_rows.extend(to_yearly(str(row["sec_code"]), str(row["ticker"]), df, today))
            got += 1
        logger.info(f"  → {got}/{len(new_targets)} 銘柄を取得しました。")

    # --- 取得済みの銘柄: 当年の行だけ更新 -----------------------------
    # 過去の年は確定値なので触らない。当年だけは高値・安値が動くため
    # 1年分を取り直して上書きする。
    if args.refresh_current_year and not old_targets.empty:
        logger.info(f"取得済み {len(old_targets)} 銘柄の{current_year}年分を更新します。")
        frames = download(old_targets["ticker"].astype(str).tolist(), 1)
        updated = 0
        for _, row in old_targets.iterrows():
            df = frames.get(str(row["ticker"]))
            if df is None or df.empty:
                continue
            part = df[df.index.year == current_year]
            if part.empty:
                continue
            added_rows.extend(to_yearly(str(row["sec_code"]), str(row["ticker"]), part, today))
            updated += 1
        logger.info(f"  → {updated}/{len(old_targets)} 銘柄を更新しました。")

    if not added_rows:
        logger.info("追加・更新する行がありませんでした。")
        return

    new_df = pd.DataFrame(added_rows)
    merged = pd.concat([history, new_df], ignore_index=True)

    # 同じ (銘柄, 年) は後勝ち。当年の更新はこれで上書きされる。
    merged["year"] = pd.to_numeric(merged["year"], errors="coerce").astype("Int64")
    merged = merged.drop_duplicates(subset=["sec_code", "year"], keep="last")
    merged = merged.sort_values(["sec_code", "year"]).reset_index(drop=True)

    merged[COLUMNS].to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")
    logger.info(
        f"{HISTORY_FILE} を更新しました: "
        f"{len(history)} 行 → {len(merged)} 行 / {merged['sec_code'].nunique()} 銘柄"
    )


if __name__ == "__main__":
    main()
