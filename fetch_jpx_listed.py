"""fetch_jpx_listed.py

JPXが公開している「東証上場銘柄一覧」を取得し、証券コードの一覧を作る。
地方単独上場（東証に重複上場していない銘柄）を判別するために使う。

    https://www.jpx.co.jp/markets/statistics-equities/misc/01.html
    → data_j.xlsx （毎月末の状態。翌月の第2営業日ごろ更新）

出力:
    tse_listed.csv   sec_code, company_name, market, as_of

使い方:
    python fetch_jpx_listed.py
    python fetch_jpx_listed.py --file data_j.xlsx   # ローカルのファイルから

他のスクリプトからは annotate() を呼ぶ:
    from fetch_jpx_listed import annotate
    df = annotate(df)   # is_tse_listed / is_local_only / tse_list_as_of を付与
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

LIST_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"

# ページ内のリンクを探して見つからなかったときに使う既定のURL。
#
# JPXがファイルを差し替えるとこのURLは変わる。実際、2026年9月に
# 拡張子が .xls から .xlsx へ変わり、旧URLが404になった。
# だから毎回まずページ内のリンクを探し、これは保険として使う。
# 404が続くようなら、ページを開いて実際のリンクを確認して差し替えること。
FALLBACK_XLS = ("https://www.jpx.co.jp/markets/statistics-equities/misc/"
                "tvdivq0000001vg2-att/data_j.xlsx")

OUTPUT_FILE = "tse_listed.csv"

# ファイル名の判定に使う語。拡張子は含めない。
# .xls と .xlsx のどちらでも拾えるようにするため。
XLS_NAME_HINT = "data_j"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("JPXListed")


def normalize_code(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.upper()
        .str.zfill(4)
    )


def find_xls_url() -> str | None:
    """一覧ページから data_j のリンクを探す。

    拡張子は判定に使わない。JPXは .xls から .xlsx へ変えた実績があり、
    次に何へ変わるか分からないため、ファイル名の主要部だけで照合する。
    """
    try:
        res = requests.get(
            LIST_PAGE, timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        res.raise_for_status()
    except Exception as e:
        logger.warning(f"[jpx_listed] 一覧ページを取得できませんでした: {e}")
        return None

    soup = BeautifulSoup(res.text, "html.parser")
    hits = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if XLS_NAME_HINT in href.lower():
            hits.append(href if href.startswith("http")
                        else "https://www.jpx.co.jp" + href)

    if not hits:
        logger.warning(
            f"[jpx_listed] ページ内に {XLS_NAME_HINT} を含むリンクが見つかりません。"
            "既知のURLを使います。ページの構造が変わった可能性があるので、"
            f"{LIST_PAGE} を開いて実際のリンクを確認してください。"
        )
        return None

    if len(hits) > 1:
        logger.info(f"[jpx_listed] 候補が {len(hits)} 件見つかりました。先頭を使います。")
    logger.info(f"[jpx_listed] リンクを検出: {hits[0]}")
    return hits[0]


def download(url: str) -> bytes | None:
    try:
        res = requests.get(
            url, timeout=60,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        res.raise_for_status()
        return res.content
    except Exception as e:
        logger.error(f"[jpx_listed] 取得に失敗しました: {e}")
        return None


def parse(content: bytes | str) -> pd.DataFrame:
    """銘柄一覧のExcelを読み、必要な列だけ取り出す。

    .xls は xlrd、.xlsx は openpyxl が必要。エンジンは指定せず pandas に
    判別させるが、openpyxl が入っていないと .xlsx で失敗するため、
    requirements.txt には openpyxl を明示している。
    """
    source = content if isinstance(content, str) else io.BytesIO(content)
    df = pd.read_excel(source, dtype=str)

    # 列名はJPX側の表記に合わせる。年によって表記ゆれがあるため候補で探す。
    col_map = {}
    for key, candidates in (
        ("sec_code", ["コード", "銘柄コード"]),
        ("company_name", ["銘柄名"]),
        ("market", ["市場・商品区分", "市場区分"]),
    ):
        for cand in candidates:
            if cand in df.columns:
                col_map[key] = cand
                break

    missing = [k for k in ("sec_code", "company_name") if k not in col_map]
    if missing:
        logger.error(
            f"[jpx_listed] 必要な列が見つかりません: {missing} / "
            f"実際の列: {list(df.columns)}"
        )
        return pd.DataFrame()

    out = pd.DataFrame({
        "sec_code": normalize_code(df[col_map["sec_code"]]),
        "company_name": df[col_map["company_name"]].astype(str).str.strip(),
    })
    if "market" in col_map:
        out["market"] = df[col_map["market"]].astype(str).str.strip()
    else:
        out["market"] = ""

    out = out[out["sec_code"].str.match(r"^[0-9][0-9A-Z]{3}$")]
    out = out.drop_duplicates(subset=["sec_code"]).reset_index(drop=True)
    out["as_of"] = datetime.now().strftime("%Y%m%d")
    return out


def load_cached() -> pd.DataFrame:
    if not os.path.exists(OUTPUT_FILE):
        return pd.DataFrame()
    try:
        df = pd.read_csv(OUTPUT_FILE, dtype={"sec_code": str, "as_of": str})
        logger.info(f"[jpx_listed] キャッシュを使用: {OUTPUT_FILE} ({len(df)}件)")
        return df
    except Exception as e:
        logger.warning(f"[jpx_listed] キャッシュを読めませんでした: {e}")
        return pd.DataFrame()


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    """東証上場かどうかのフラグを付ける。

    tse_listed.csv が無い、または読めない場合は
    is_tse_listed / is_local_only を付けずにそのまま返す。
    呼び出し側は列の有無で判別すること。
    """
    tse = load_cached()
    if tse.empty or "sec_code" not in tse.columns:
        return df

    listed = set(tse["sec_code"].astype(str))
    as_of = tse["as_of"].iloc[0] if "as_of" in tse.columns and len(tse) else ""

    out = df.copy()
    out["is_tse_listed"] = out["sec_code"].astype(str).isin(listed)
    out["is_local_only"] = ~out["is_tse_listed"]
    out["tse_list_as_of"] = as_of
    return out


def main():
    ap = argparse.ArgumentParser(description="東証上場銘柄一覧の取得")
    ap.add_argument("--file", help="ローカルの data_j.xlsx を読む")
    args = ap.parse_args()

    if args.file:
        result = parse(args.file)
    else:
        url = find_xls_url() or FALLBACK_XLS
        content = download(url)

        # ページ内のリンクで失敗したら、既定のURLでもう一度試す。
        # 逆にページのリンクが新しくなっている場合もあるため、両方試す。
        if content is None and url != FALLBACK_XLS:
            logger.info(f"[jpx_listed] 既定のURLで再試行します: {FALLBACK_XLS}")
            content = download(FALLBACK_XLS)

        if content is None:
            logger.warning(
                "[jpx_listed] 取得できませんでした。既存の tse_listed.csv をそのまま使います。"
            )
            cached = load_cached()
            if cached.empty:
                logger.error(
                    "[jpx_listed] キャッシュもありません。"
                    "東証重複の判別ができない状態です。"
                )
                sys.exit(1)
            return

        result = parse(content)

    if result.empty:
        logger.error("[jpx_listed] 銘柄を1件も取得できませんでした。既存のファイルは残します。")
        sys.exit(1)

    result.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    logger.info(f"[jpx_listed] 東証上場銘柄一覧を取得しました: {len(result)}件 -> {OUTPUT_FILE}")

    if "market" in result.columns:
        counts = result["market"].value_counts()
        for market, n in counts.head(8).items():
            logger.info(f"  {market}: {n}件")


if __name__ == "__main__":
    main()
