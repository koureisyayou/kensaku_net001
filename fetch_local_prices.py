"""
名証（名古屋証券取引所）の株式相場表PDFから株価・売買高を抽出する。

  https://www.nse.or.jp/market/condition/quick/files/sokuhou.pdf
    日通しの株式相場表（速報）。16:00頃更新。URLは固定で毎日上書きされる。
    → 上書きされる以上、取得したPDFは raw_pdf/ に必ず残す。パース仕様を
      後から変えても、原本さえあれば過去分を作り直せる。

PDFの構造（2026年8月時点）:
  - 銘柄コードは旧5桁体系（例: 17660 = 1766、546A0 = 546A）。先頭4文字が現行コード。
  - 銘柄名は全角。マーク類（信用区分等）は半角カナ・半角記号で前後に付く。
    「ｶ」のような半角カナのマークが確認されているため、気配マーク「ｹ」も
    マークとして出現しうる前提で、「ｹ + 数値」の並びだけを気配値として扱う。
  - 銘柄名に全角数字が入ることがある（例: 73220 ３３ＦＧ）。値段欄の数値は
    すべて半角なので、数値を探す正規表現は半角に限定する（後述）。
  - 売買が成立していない銘柄は値段欄が空で「ｹ + 最終気配」だけが載る。
    名証上場銘柄の大半は東証との重複上場で、名証では売買不成立の日が多い。
  - 売買高は千株単位・小数第1位（例: 5.9 = 5,900株）。
  - 前日比は符号付き（+10 / -36）。変化なしの日は欄ごと空になる。
  - 【プレミア市場】【メイン市場】【ネクスト市場】で市場区分、＜建設業＞で業種。
  - 末尾に「監理銘柄」「整理銘柄」の区画がある。この区画には市場区分が
    書かれないため、market は None にして alert_section に区分を持たせる。

使い方:
  python fetch_local_prices.py                 # PDFを取得して local_prices.csv を出力
  python fetch_local_prices.py --file x.pdf    # ローカルのPDFを解析
  python fetch_local_prices.py --probe         # 構造をダンプ（調整用）
  python fetch_local_prices.py --no-archive    # 原本を保存しない（検証時のみ）
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
RAW_DIR = "raw_pdf"                        # 取得したPDFの原本

WINDOW_DAYS = 20    # 流動性の集計期間（営業日）
RETAIN_DAYS = 40    # 履歴として保持する営業日数

# 旧5桁コード（先頭4文字が現行の証券コード、5文字目は常に0）
CODE_RE = re.compile(r"^\s*([0-9][0-9A-Z]{3})0(?![0-9A-Z])\s*(.*)$")

# 数値の抽出は半角に限定する。
#
# ここを \d で書くと、Python の re は既定で Unicode の数字にマッチするため
# 全角数字（０-９）も拾ってしまう。相場表の値段欄は半角だが、銘柄名には
# 全角数字が入ることがある（例: 73220 ３３ＦＧ）。すると parse_row() が
# 「最初の数値より前が銘柄名」として名前を切り出す際、名前の先頭の全角数字を
# 値段の始まりと誤認し、銘柄名が空になる。実際に 7322 で毎日発生していた。
# 値段・売買高・前日比はいずれも半角なので、[0-9] に限定して支障はない。
NUM_RE = re.compile(r"[+-]?[0-9][0-9,]*(?:\.[0-9]+)?")
# 気配値は「ｹ の直後に数値」が来る並びだけを認める。
# 単独の「ｹ」は銘柄名のマークである可能性があるため分割に使わない。
QUOTE_RE = re.compile(r"ｹ\s*([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)")
MARKET_RE = re.compile(r"【(.+?)】")
SECTOR_RE = re.compile(r"[＜<](.+?)[＞>]")
# 見出しの日付。ここは全角数字が来ないため \d のままでよいが、
# 上と揃えて半角限定にしておく。
DATE_RE = re.compile(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日")
# 監理・整理の区画見出し。凡例や注記の文中に出る「監理銘柄」を拾わないよう、
# 行全体が見出しになっている場合だけを認める。
ALERT_HEADER_RE = re.compile(r"^[　\s]*(監理|整理)銘柄(（.*?）)?[　\s]*$")

# 銘柄名の前後に付くマーク。全角記号に加えて、半角英数記号(U+0020-007E)と
# 半角カナ(U+FF61-FF9F)を「名前ではないもの」として前後から落とす。
# 銘柄名そのものは全角で構成されるため、この扱いで名前は削られない。
FULLWIDTH_MARKS = "●○◎△▲□■＃♯◇◆§※★☆"
EDGE_JUNK_RE = re.compile(r"^[\s\u3000\u0020-\u007E\uFF61-\uFF9F" + FULLWIDTH_MARKS + r"]+")
EDGE_JUNK_END_RE = re.compile(r"[\s\u3000\u0020-\u007E\uFF61-\uFF9F" + FULLWIDTH_MARKS + r"]+$")

# 除外する区画（株式ではない）
NON_STOCK_MARKETS = ("証券投資信託受益証券", "新株予約権証券", "債券")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LocalPrices")


def download_pdf(url, archive=True):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    res = requests.get(url, headers=headers, timeout=30)
    res.raise_for_status()

    msg = f"PDF取得: {url} ({len(res.content):,} bytes)"

    if archive:
        # 固定URLで毎日上書きされるため、取得できた原本は必ず残す。
        # ファイル名は「取得日」。中身の相場日とずれる場合（非営業日実行）が
        # あるが、両方あるほうが後から判別できる。
        os.makedirs(RAW_DIR, exist_ok=True)
        stamp = datetime.now(JST).strftime("%Y%m%d")
        path = os.path.join(RAW_DIR, f"sokuhou_{stamp}.pdf")
        with open(path, "wb") as f:
            f.write(res.content)
        msg += f" -> {path}"

    logger.info(msg)
    return io.BytesIO(res.content)


def to_float(token):
    try:
        return float(token.replace(",", "").lstrip("+"))
    except ValueError:
        return None


def clean_name(raw):
    """銘柄名の前後からマーク類・空白・半角文字を落とす。"""
    if not raw:
        return ""
    s = raw.replace("\u3000", " ")
    s = EDGE_JUNK_RE.sub("", s)
    s = EDGE_JUNK_END_RE.sub("", s)
    return s.strip()


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

    # 「ｹ + 数値」の並びで分割する。単独の「ｹ」は銘柄名のマークなので使わない。
    qm = QUOTE_RE.search(rest)
    if qm:
        left, right = rest[:qm.start()], rest[qm.start():]
    else:
        left, right = rest, ""

    left_tokens = NUM_RE.findall(left)
    right_tokens = NUM_RE.findall(right)

    # 銘柄名は最初の半角数値より前。NUM_RE を半角限定にしてあるので、
    # 全角数字で始まる銘柄名（３３ＦＧ など）も削られない。
    first_num = NUM_RE.search(left)
    raw_name = left[:first_num.start()] if first_num else left
    name = clean_name(raw_name)

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


def _has_stock_rows(text):
    return any(CODE_RE.match(line) for line in text.split("\n"))


def extract_columns(page):
    """
    相場表は1ページが左右2カラム組みになっている。
    行単位でテキストを読むと左カラムの銘柄に右カラムの株価が連結されてしまうため、
    「コード」ヘッダーのX座標でページを切り、カラムごとにテキストを取り出す。

    ヘッダーを検出できないまま単一カラムとして扱うと、左右が連結された行が
    「約定あり」として無音で通ってしまう。銘柄行を含むページで検出に失敗した
    場合は、警告を出したうえで中央分割にフォールバックする。
    """
    header_x = sorted(
        w["x0"] for w in page.extract_words() if w["text"].startswith("コード")
    )

    if len(header_x) >= 2:
        split_x = header_x[-1] - 4
    else:
        text = page.extract_text() or ""
        if not _has_stock_rows(text):
            return [text]  # 表紙・注記など銘柄行の無いページ
        logger.warning(
            f"p.{page.page_number}: コードヘッダーを検出できませんでした。"
            "中央分割にフォールバックします（値がずれている可能性あり）。"
        )
        split_x = page.width / 2

    left = page.crop((0, 0, split_x, page.height))
    right = page.crop((split_x, 0, page.width, page.height))
    return [left.extract_text() or "", right.extract_text() or ""]


def parse_pdf(pdf_source):
    market = None
    sector = None
    alert_section = None
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
                        alert_section = None
                        continue

                    am = ALERT_HEADER_RE.match(line.strip())
                    if am:
                        # 監理・整理の区画。この区画には市場区分の記載が無いので
                        # market は None にし、区分は別列で持つ。
                        alert_section = am.group(1)
                        market = None
                        continue

                    sc = SECTOR_RE.search(line)
                    if sc and not CODE_RE.match(line):
                        sector = sc.group(1).replace("　", "")
                        continue

                    row = parse_row(line)
                    if row:
                        row["market"] = market
                        row["sector"] = sector
                        row["alert_section"] = alert_section
                        row["is_supervised"] = alert_section is not None
                        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df, price_date

    # 株式以外（ETF等）を除外
    df = df[~df["market"].isin(NON_STOCK_MARKETS)].copy()

    # 同一銘柄が通常区画と監理区画の両方に載る場合、market が None の行が
    # 残らないよう、非欠損の値を全行へ寄せてから重複を潰す。
    for col in ("market", "sector"):
        df[col] = df.groupby("sec_code")[col].transform(
            lambda s: s.dropna().iloc[0] if s.notna().any() else None
        )
    for col in ("alert_section",):
        df[col] = df.groupby("sec_code")[col].transform(
            lambda s: s.dropna().iloc[-1] if s.notna().any() else None
        )
    df["is_supervised"] = df.groupby("sec_code")["is_supervised"].transform("max")

    df = df.drop_duplicates(subset=["sec_code"], keep="last")
    df.insert(0, "date", price_date)
    return df, price_date


def probe(pdf_source):
    with pdfplumber.open(pdf_source) as pdf:
        print(f"ページ数: {len(pdf.pages)}")
        for page_no, page in enumerate(pdf.pages[:1], 1):
            print(f"\n--- PAGE {page_no} text ---")
            print((page.extract_text() or "")[:3000])


def _coerce_bools(df, cols=("traded", "is_supervised")):
    """CSV往復で bool が "True"/"False" の文字列になるのを防ぐ。"""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.lower().isin(("true", "1"))
    return df


def update_history(daily_df):
    """当日分を履歴に追記し、直近 RETAIN_DAYS 営業日分に切り詰めた履歴を返す。"""
    keep_cols = ["date", "sec_code", "name", "market", "sector",
                 "alert_section", "is_supervised",
                 "close", "last_quote", "volume_k", "traded", "turnover"]
    daily_df = daily_df[keep_cols]

    if os.path.exists(HISTORY_FILE):
        history = pd.read_csv(HISTORY_FILE, dtype={"sec_code": str, "date": str})
        history = _coerce_bools(history)
        # 旧フォーマット（alert_section 無し）への追随
        for col in keep_cols:
            if col not in history.columns:
                history[col] = pd.NA
        history = pd.concat([history[keep_cols], daily_df], ignore_index=True)
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


def _latest_non_empty(series):
    """期間内で最後に得られた非空の値。銘柄名や市場区分の欠落を埋める。"""
    s = series.dropna()
    s = s[s.astype(str).str.strip() != ""]
    return s.iloc[-1] if not s.empty else None


def summarize(history):
    """
    直近 WINDOW_DAYS 営業日から銘柄ごとの流動性指標を作る。

      price               : 期間内で最後に約定した終値（気配値は使わない）
      price_date          : その約定日
      traded_days_20      : 期間内に約定が成立した日数
      avg_turnover_20     : 1日平均売買代金・円（約定のない日は0として平均する）
      avg_turnover_20_m   : 同・百万円（price_metrics.py と単位を揃えるため）
      days_since_trade    : 最終約定日から何営業日経過したか
    """
    history = _coerce_bools(history.copy())

    dates = sorted(history["date"].dropna().unique())
    window = dates[-WINDOW_DAYS:]
    win = history[history["date"].isin(window)].copy()
    latest_date = dates[-1]

    records = []
    for sec_code, group in win.groupby("sec_code"):
        group = group.sort_values("date")
        traded = group[group["traded"]]

        if not traded.empty:
            last_trade = traded.iloc[-1]
            price = last_trade["close"]
            price_date = last_trade["date"]
            days_since = len(window) - 1 - window.index(price_date)
        else:
            price, price_date, days_since = None, None, None

        turnover_yen = round(group["turnover"].fillna(0).sum() / len(window))

        records.append({
            "sec_code": sec_code,
            # 属性は最新日ではなく「期間内で最後に取れた非空の値」を使う。
            # 名前が空で抽出された日があっても他の日の値で埋まる。
            "name": _latest_non_empty(group["name"]),
            "market": _latest_non_empty(group["market"]),
            "sector": _latest_non_empty(group["sector"]),
            "alert_section": _latest_non_empty(group["alert_section"]),
            "is_supervised": bool(group["is_supervised"].max()),
            "price": price,
            "price_date": price_date,
            "last_quote": _latest_non_empty(group["last_quote"]),
            "traded_days_20": int(group["traded"].sum()),
            "avg_turnover_20": turnover_yen,
            "avg_turnover_20_m": round(turnover_yen / 1e6, 1),
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
    parser.add_argument("--no-archive", action="store_true",
                        help="取得したPDFを raw_pdf/ に保存しない")
    args = parser.parse_args()

    source = args.file if args.file else download_pdf(args.url, archive=not args.no_archive)

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

    # 銘柄名が取れなかった行はパース不良の兆候。件数とコードを出しておく。
    blank_names = daily_df[daily_df["name"].fillna("").str.strip() == ""]
    if not blank_names.empty:
        codes = ", ".join(blank_names["sec_code"].tolist()[:20])
        logger.warning(f"⚠ 銘柄名を抽出できなかった行: {len(blank_names)}件 ({codes})")

    supervised = int(daily_df["is_supervised"].sum())
    if supervised:
        logger.info(f"監理・整理区画の銘柄: {supervised}件")

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
