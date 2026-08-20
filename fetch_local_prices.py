"""
名証（名古屋証券取引所）の株式相場表PDFから株価・売買高を抽出する。

  https://www.nse.or.jp/market/condition/quick/files/sokuhou.pdf
    日通しの株式相場表（速報）。16:00頃更新。URLは固定で毎日上書きされる。

PDFの構造（2026年8月時点）:
  - 銘柄コードは旧5桁体系（例: 17660 = 1766、546A0 = 546A）。先頭4文字が現行コード。
  - 銘柄名は全角、価格・売買高は半角。この違いで数値だけを安全に抜ける。
  - 売買が成立していない銘柄は値段欄が空で「ｹ + 最終気配」だけが載る。
    名証上場銘柄の大半は東証との重複上場で、名証では売買不成立の日が多い。
  - 前日比は符号付き（+10 / -36）。変化なしの日は欄ごと空になる。
  - 【プレミア市場】【メイン市場】【ネクスト市場】で市場区分、＜建設業＞で業種。
  - 末尾に「監理銘柄」の区画があり、そこに載る銘柄は監理銘柄。

使い方:
  python fetch_local_prices.py                 # PDFを取得して local_prices.csv を出力
  python fetch_local_prices.py --file x.pdf    # ローカルのPDFを解析
  python fetch_local_prices.py --probe         # 構造をダンプ（調整用）
"""

import io
import os
import re
import sys
import argparse
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import pdfplumber

JST = timezone(timedelta(hours=9))
NSE_QUICK_PDF = "https://www.nse.or.jp/market/condition/quick/files/sokuhou.pdf"
HISTORY_FILE = "local_price_history.csv"   # 日次の生データを追記していく
OUTPUT_FILE = "local_prices.csv"           # 集計後の最新スナップショット

WINDOW_DAYS = 20    # 流動性の集計期間（営業日）
RETAIN_DAYS = 40    # 履歴として保持する営業日数

# 旧5桁コード（先頭4文字が現行の証券コード、5文字目は常に0）
CODE_RE = re.compile(r"^\s*([0-9][0-9A-Z]{3})0(?![0-9A-Z])\s*(.*)$")
NUM_RE = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?")
MARKET_RE = re.compile(r"【(.+?)】")
SECTOR_RE = re.compile(r"[＜<](.+?)[＞>]")
DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")

# 銘柄名の前後に付く記号（信用区分・売買単位・権利落ち等）
NAME_MARKS = "●○◎△□＃◇§ 　ABC"

# 除外する区画（株式ではない）
NON_STOCK_MARKETS = ("証券投資信託受益証券", "新株予約権証券", "債券")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LocalPrices")


def download_pdf(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    res = requests.get(url, headers=headers, timeout=30)
    res.raise_for_status()
    logger.info(f"PDF取得: {url} ({len(res.content):,} bytes)")
    return io.BytesIO(res.content)


def to_float(token):
    try:
        return float(token.replace(",", "").lstrip("+"))
    except ValueError:
        return None


def parse_row(line):
    """
    1行を解析して dict を返す。銘柄行でなければ None。

    値段欄のパターン:
      A) 約定あり           : 始値 高値 安値 終値 [前日比] [ｹ 最終気配] [売買高]
      B) 売買不成立（気配のみ）: ｹ 最終気配
      C) 気配マークなしの単独値 : 参考値として扱い、約定なし扱いにする
    """
    m = CODE_RE.match(line)
    if not m:
        return None

    sec_code, rest = m.group(1), m.group(2)

    # 「ｹ」より前後で分割する（ｹ の直後の数値が最終気配）
    if "ｹ" in rest:
        left, right = rest.split("ｹ", 1)
    else:
        left, right = rest, ""

    # 銘柄名は全角のみで構成されるため、半角数値だけを拾えば値段欄が取れる
    left_tokens = NUM_RE.findall(left)
    right_tokens = NUM_RE.findall(right)

    name = left.split(NUM_RE.search(left).group())[0] if left_tokens else left
    name = name.strip().strip(NAME_MARKS).strip()

    row = {
        "sec_code": sec_code,
        "name": name,
        "open": None, "high": None, "low": None, "close": None,
        "prev_diff": None, "last_quote": None, "volume_k": 0.0,
        "traded": False,
    }

    if len(left_tokens) >= 4:
        # 約定あり
        o, h, l, c = [to_float(t) for t in left_tokens[:4]]
        row.update({"open": o, "high": h, "low": l, "close": c, "traded": True})

        for token in left_tokens[4:]:
            if token[0] in "+-":
                row["prev_diff"] = to_float(token)
            else:
                row["volume_k"] = to_float(token)

        if right_tokens:
            row["last_quote"] = to_float(right_tokens[0])
            if len(right_tokens) > 1:
                row["volume_k"] = to_float(right_tokens[1])

    elif right_tokens:
        # 売買不成立。気配値のみ
        row["last_quote"] = to_float(right_tokens[0])

    elif len(left_tokens) == 1:
        # 気配マークが取れなかった単独値。参考値として気配扱いにする
        row["last_quote"] = to_float(left_tokens[0])

    else:
        return None

    # スクリーニングで使う代表価格。約定があれば終値、なければ気配値
    row["price"] = row["close"] if row["traded"] else row["last_quote"]
    return row


def extract_columns(page):
    """
    相場表は1ページが左右2カラム組みになっている。
    行単位でテキストを読むと左カラムの銘柄に右カラムの株価が連結されてしまうため、
    「コード」ヘッダーのX座標でページを切り、カラムごとにテキストを取り出す。
    """
    header_x = sorted(
        w["x0"] for w in page.extract_words() if w["text"].startswith("コード")
    )

    if len(header_x) < 2:
        # 単一カラムのページ（表紙・注記のみ等）
        return [page.extract_text() or ""]

    split_x = header_x[-1] - 4
    left = page.crop((0, 0, split_x, page.height))
    right = page.crop((split_x, 0, page.width, page.height))
    return [left.extract_text() or "", right.extract_text() or ""]


def parse_pdf(pdf_source):
    market = None
    sector = None
    supervised = False
    price_date = None
    rows = []

    with pdfplumber.open(pdf_source) as pdf:
        for page in pdf.pages:
            for text in extract_columns(page):
                for line in text.split("\n"):
                    if price_date is None:
                        d = DATE_RE.search(line)
                        if d:
                            price_date = f"{int(d.group(1)):04d}-{int(d.group(2)):02d}-{int(d.group(3)):02d}"

                    mk = MARKET_RE.search(line)
                    if mk:
                        market = mk.group(1)
                        supervised = False
                        continue

                    if "監理銘柄" in line:
                        supervised = True
                        market = "監理銘柄"
                        continue
                    if "整理銘柄" in line:
                        supervised = True
                        market = "整理銘柄"
                        continue

                    sc = SECTOR_RE.search(line)
                    if sc and not CODE_RE.match(line):
                        sector = sc.group(1).replace("　", "")
                        continue

                    row = parse_row(line)
                    if row:
                        row["market"] = market
                        row["sector"] = sector
                        row["is_supervised"] = supervised
                        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df, price_date

    # 株式以外（ETF等）を除外
    df = df[~df["market"].isin(NON_STOCK_MARKETS)].copy()
    df = df.drop_duplicates(subset=["sec_code"], keep="last")
    df.insert(0, "date", price_date)
    return df, price_date


def probe(pdf_source):
    with pdfplumber.open(pdf_source) as pdf:
        print(f"ページ数: {len(pdf.pages)}")
        for page_no, page in enumerate(pdf.pages[:1], 1):
            print(f"\n--- PAGE {page_no} text ---")
            print((page.extract_text() or "")[:3000])


def update_history(daily_df):
    """当日分を履歴に追記し、直近 RETAIN_DAYS 営業日分に切り詰めた履歴を返す。"""
    keep_cols = ["date", "sec_code", "name", "market", "sector", "is_supervised",
                 "close", "last_quote", "volume_k", "traded", "turnover"]
    daily_df = daily_df[keep_cols]

    if os.path.exists(HISTORY_FILE):
        history = pd.read_csv(HISTORY_FILE, dtype={"sec_code": str, "date": str})
        history = pd.concat([history, daily_df], ignore_index=True)
    else:
        history = daily_df.copy()

    # 同日に複数回実行された場合は最後の取得を採用する
    history = history.drop_duplicates(subset=["date", "sec_code"], keep="last")

    # 保持する営業日を制限（相場表は営業日にしか更新されないため日付の実数で数える）
    dates = sorted(history["date"].dropna().unique())
    if len(dates) > RETAIN_DAYS:
        history = history[history["date"].isin(dates[-RETAIN_DAYS:])]

    history = history.sort_values(["date", "sec_code"])
    history.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")
    return history


def summarize(history):
    """
    直近 WINDOW_DAYS 営業日から銘柄ごとの流動性指標を作る。

      price            : 期間内で最後に約定した終値（気配値は使わない）
      price_date       : その約定日
      traded_days_20   : 期間内に約定が成立した日数
      avg_turnover_20  : 1日平均売買代金（約定のない日は0として平均する）
      days_since_trade : 最終約定日から何営業日経過したか
    """
    dates = sorted(history["date"].dropna().unique())
    window = dates[-WINDOW_DAYS:]
    win = history[history["date"].isin(window)].copy()
    latest_date = dates[-1]

    # 最新日の属性（銘柄名・市場・監理フラグ・気配値）を土台にする
    latest = win[win["date"] == latest_date].set_index("sec_code")

    records = []
    for sec_code, group in win.groupby("sec_code"):
        group = group.sort_values("date")
        traded = group[group["traded"] == True]  # noqa: E712

        if not traded.empty:
            last_trade = traded.iloc[-1]
            price = last_trade["close"]
            price_date = last_trade["date"]
            days_since = len(window) - 1 - window.index(price_date)
        else:
            price, price_date, days_since = None, None, None

        base = latest.loc[sec_code] if sec_code in latest.index else group.iloc[-1]

        records.append({
            "sec_code": sec_code,
            "name": base["name"],
            "market": base["market"],
            "sector": base["sector"],
            "is_supervised": bool(base["is_supervised"]),
            "price": price,
            "price_date": price_date,
            "last_quote": base["last_quote"],
            "traded_days_20": int(group["traded"].sum()),
            "avg_turnover_20": round(group["turnover"].fillna(0).sum() / len(window)),
            "days_since_trade": days_since,
            "window_days": len(window),
            "as_of": latest_date,
        })

    df = pd.DataFrame(records)
    return df.sort_values("avg_turnover_20", ascending=False)


def main():
    parser = argparse.ArgumentParser(description="名証相場表からの株価取得")
    parser.add_argument("--probe", action="store_true", help="構造をダンプして終了")
    parser.add_argument("--file", help="ローカルPDFを解析する")
    parser.add_argument("--url", default=NSE_QUICK_PDF)
    args = parser.parse_args()

    source = args.file if args.file else download_pdf(args.url)

    if args.probe:
        probe(source)
        return

    daily_df, price_date = parse_pdf(source)
    if daily_df.empty:
        logger.error("銘柄行を1件も抽出できませんでした。PDFのレイアウトが変わった可能性があります。")
        sys.exit(1)
    if not price_date:
        logger.error("相場日を特定できませんでした。日付なしでは履歴に追記できません。")
        sys.exit(1)

    # 売買代金（円）。売買高は千株単位で、約定のない日は0とする
    daily_df["turnover"] = (
        daily_df["close"].fillna(0) * daily_df["volume_k"].fillna(0) * 1000
    ).where(daily_df["traded"], 0)

    traded = int(daily_df["traded"].sum())
    logger.info(f"相場日: {price_date}")
    logger.info(f"抽出銘柄数: {len(daily_df)}件（約定あり {traded}件 / 気配のみ {len(daily_df) - traded}件）")

    history = update_history(daily_df)
    n_dates = history["date"].nunique()
    logger.info(f"履歴: {n_dates}営業日分 / {len(history)}行 ({HISTORY_FILE})")

    summary = summarize(history)
    summary.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    if n_dates < WINDOW_DAYS:
        logger.warning(
            f"⚠ 履歴が {n_dates}営業日分しかありません（集計期間は{WINDOW_DAYS}営業日）。"
            "流動性指標は蓄積が進むまで参考値です。"
        )

    tradable = summary[summary["price"].notnull()]
    logger.info(f"期間内に約定のあった銘柄: {len(tradable)}/{len(summary)}件")
    logger.info(f"{OUTPUT_FILE} を出力しました。")


if __name__ == "__main__":
    main()
