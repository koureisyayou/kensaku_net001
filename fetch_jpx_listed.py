"""fetch_jpx_listed.py

JPX が公開している「東証上場銘柄一覧」(data_j.xls) を取得し、
東証に上場しているコードの集合を tse_listed.csv として保存する。

用途:
    名証（および他の地方取引所）の相場表には東証との重複上場銘柄が大量に
    含まれる。地方単独上場だけを抽出するには「東証に載っていないこと」を
    確認する必要があり、その突合表がこのファイル。

参照ページ:
    東証上場銘柄一覧 https://www.jpx.co.jp/markets/statistics-equities/misc/01.html

重要な制約:
    このファイルは【月次】更新（毎月第3営業日の午前9時以降に前月末データへ差替）。
    新規上場・上場廃止の反映は最大5週間遅れる。したがって
      - 直近に東証へ上場した銘柄は一時的に「名証単独」と誤判定される
      - 直近に東証を上場廃止した銘柄は一時的に「重複上場」と誤判定される
    除外ではなくフラグとして扱い、必ず as_of（一覧の基準月末）を併記すること。

    取得に失敗した場合は前回のキャッシュを使う（JPX 側の障害でスクリーニング
    全体が止まらないようにするため）。月次更新なので、多少古くても実害は小さい。
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pandas as pd
import requests

JPX_LIST_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
JPX_XLS_FALLBACK = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)

OUTPUT_CSV = Path("tse_listed.csv")
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; net-net-screener/1.0)"}

# 「市場・商品区分」のうち内国普通株式にあたるもの。
# ETF・REIT・出資証券・外国株式・PRO Market はネットネットの対象外。
DOMESTIC_STOCK_RE = re.compile(r"内国株式")

# 列名ゆれの吸収（jpx_alerts.py と同じ方針）
CODE_COLS = ["コード", "銘柄コード", "code"]
NAME_COLS = ["銘柄名", "会社名", "name"]
SEGMENT_COLS = ["市場・商品区分", "市場区分"]
SECTOR33_COLS = ["33業種区分"]
DATE_COLS = ["日付"]


def _pick(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _resolve_xls_url() -> str:
    """掲載ページから data_j.xls の実URLを拾う。失敗したら既知のURLを使う。

    JPX は差替時にパスの英数字部分を変えることがあるため、ページ側の
    リンクを正としてハードコードを保険にする。
    """
    try:
        res = requests.get(JPX_LIST_PAGE, headers=HEADERS, timeout=TIMEOUT)
        res.raise_for_status()
        res.encoding = res.apparent_encoding
        m = re.search(r'href="([^"]*data_j\.xls)"', res.text)
        if m:
            href = m.group(1)
            url = href if href.startswith("http") else "https://www.jpx.co.jp" + href
            if url != JPX_XLS_FALLBACK:
                print(f"[jpx_listed] リンクが既知のURLと異なります: {url}")
            return url
        print("[jpx_listed] ページ内に data_j.xls のリンクが見つかりません。既知のURLを使います。")
    except Exception as exc:  # noqa: BLE001
        print(f"[jpx_listed] 掲載ページの取得に失敗: {exc}。既知のURLを使います。")
    return JPX_XLS_FALLBACK


def _normalize_code(series: pd.Series) -> pd.Series:
    """コードを4文字の文字列に揃える（130A のような英数字コードに対応）。"""
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)   # Excel 由来の 1766.0 対策
        .str.upper()
        .str.zfill(4)
    )


def fetch_tse_listed(use_cache_on_error: bool = True) -> pd.DataFrame:
    """東証上場銘柄一覧を返す。

    列: sec_code / name / market_segment / sector33 / is_domestic_stock / as_of
    """
    try:
        url = _resolve_xls_url()
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        res.raise_for_status()
        # .xls（BIFF形式）なので xlrd が必要。requirements.txt に xlrd を入れること。
        raw = pd.read_excel(io.BytesIO(res.content), dtype=str)
    except Exception as exc:  # noqa: BLE001
        print(f"[jpx_listed] 取得に失敗しました: {exc}")
        if use_cache_on_error and OUTPUT_CSV.exists():
            print(f"[jpx_listed] キャッシュを使用: {OUTPUT_CSV}")
            return pd.read_csv(OUTPUT_CSV, dtype=str)
        return pd.DataFrame(
            columns=["sec_code", "name", "market_segment", "sector33",
                     "is_domestic_stock", "as_of"]
        )

    raw.columns = [str(c).strip() for c in raw.columns]
    code_col = _pick(raw, CODE_COLS)
    segment_col = _pick(raw, SEGMENT_COLS)

    if code_col is None or segment_col is None:
        print(f"[jpx_listed] 想定した列がありません: {list(raw.columns)}")
        if use_cache_on_error and OUTPUT_CSV.exists():
            return pd.read_csv(OUTPUT_CSV, dtype=str)
        return pd.DataFrame(
            columns=["sec_code", "name", "market_segment", "sector33",
                     "is_domestic_stock", "as_of"]
        )

    out = pd.DataFrame()
    out["sec_code"] = _normalize_code(raw[code_col])

    name_col = _pick(raw, NAME_COLS)
    out["name"] = raw[name_col].astype(str).str.strip() if name_col else ""

    out["market_segment"] = raw[segment_col].astype(str).str.strip()

    sector_col = _pick(raw, SECTOR33_COLS)
    out["sector33"] = raw[sector_col].astype(str).str.strip() if sector_col else ""

    out["is_domestic_stock"] = out["market_segment"].str.contains(
        DOMESTIC_STOCK_RE, na=False
    )

    # 一覧の基準日（列にあれば採用。無ければ空欄）
    date_col = _pick(raw, DATE_COLS)
    as_of = ""
    if date_col is not None:
        values = raw[date_col].dropna().astype(str).str.strip()
        if not values.empty:
            as_of = values.iloc[0]
    out["as_of"] = as_of

    out = out.drop_duplicates(subset=["sec_code"], keep="first").reset_index(drop=True)

    domestic = int(out["is_domestic_stock"].sum())
    print(f"[jpx_listed] 全{len(out)}件（内国株式 {domestic}件） 基準: {as_of or '不明'}")

    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    return out


def load_tse_codes(domestic_only: bool = True, refresh: bool = False) -> set[str]:
    """東証上場コードの集合を返す。

    refresh=False かつ tse_listed.csv があればそれを読む（月次更新なので
    毎回取りに行く必要はない）。地方版の集計から呼ぶ側はこちらを使う。
    """
    if refresh or not OUTPUT_CSV.exists():
        df = fetch_tse_listed()
    else:
        df = pd.read_csv(OUTPUT_CSV, dtype=str)
        df["is_domestic_stock"] = (
            df["is_domestic_stock"].astype(str).str.strip().str.lower().isin(("true", "1"))
        )

    if df.empty:
        return set()
    if domestic_only:
        df = df[df["is_domestic_stock"]]
    return set(df["sec_code"].astype(str))


def annotate(local_df: pd.DataFrame, code_col: str = "sec_code") -> pd.DataFrame:
    """地方相場のDataFrameに東証重複上場のフラグを付けて返す。

    追加列:
        is_tse_listed  東証上場銘柄一覧に載っているか
        is_local_only  載っていない = 地方単独上場の候補
        tse_list_as_of 突合に使った一覧の基準（月次更新のため遅延がある）
    """
    codes = load_tse_codes()

    as_of = ""
    if OUTPUT_CSV.exists():
        cached = pd.read_csv(OUTPUT_CSV, dtype=str)
        if not cached.empty and "as_of" in cached.columns:
            as_of = str(cached["as_of"].iloc[0])

    out = local_df.copy()
    normalized = _normalize_code(out[code_col])
    out["is_tse_listed"] = normalized.isin(codes)
    out["is_local_only"] = ~out["is_tse_listed"]
    out["tse_list_as_of"] = as_of
    return out


if __name__ == "__main__":
    listed = fetch_tse_listed()
    if listed.empty:
        print("[jpx_listed] 取得できませんでした。")
        sys.exit(1)

    print(listed.head(10).to_string(index=False))

    # local_prices.csv があれば、その場で地方単独の件数を出しておく。
    local_path = Path("local_prices.csv")
    if local_path.exists():
        local = pd.read_csv(local_path, dtype={"sec_code": str})
        annotated = annotate(local)
        local_only = annotated[annotated["is_local_only"]]
        traded = local_only[local_only["price"].notnull()]
        print()
        print(f"名証掲載 {len(annotated)}件 / 東証重複 {int(annotated['is_tse_listed'].sum())}件")
        print(f"地方単独の候補 {len(local_only)}件（うち期間内に約定あり {len(traded)}件）")
        if not traded.empty:
            cols = [c for c in ("sec_code", "name", "market", "price",
                                "traded_days_20", "avg_turnover_20_m")
                    if c in traded.columns]
            print(traded[cols].head(30).to_string(index=False))
