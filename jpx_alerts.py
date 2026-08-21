"""jpx_alerts.py

JPX が公開している監理・整理銘柄一覧を取得し、DataFrame で返す。

参照ページ:
    現在の指定状況 https://www.jpx.co.jp/listing/market-alerts/supervision/index.html
    指定履歴       https://www.jpx.co.jp/listing/market-alerts/supervision/01.html

指定履歴には解除済みの銘柄も含まれるため、解除年月日が空欄のものだけを
「現在有効な指定」として扱う。取得に失敗した場合は前回のキャッシュを使う
（JPX 側の障害でスクリーニング全体が止まらないようにするため）。
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

JPX_CURRENT_URL = "https://www.jpx.co.jp/listing/market-alerts/supervision/index.html"
JPX_HISTORY_URL = "https://www.jpx.co.jp/listing/market-alerts/supervision/01.html"

CACHE_CSV = Path("jpx_alerts_cache.csv")
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; net-net-screener/1.0)"}

# 列名ゆれの吸収
CODE_COLS = ["コード", "銘柄コード", "code"]
NAME_COLS = ["銘柄名", "銘柄等", "会社名"]
KIND_COLS = ["内容", "指定内容", "区分"]
FROM_COLS = ["指定年月日", "指定日"]
UNTIL_COLS = ["解除年月日", "解除日"]

# 取得経路。呼び出し側が「除外0件」と「そもそも突合できていない」を
# 区別できるようにするため、返す DataFrame に必ず記録する。
SOURCE_LIVE = "live"      # JPX から取得できた
SOURCE_CACHE = "cache"    # 取得に失敗し前回のキャッシュを使った
SOURCE_FAILED = "failed"  # 取得もキャッシュも無い＝突合できていない


def _tag(df: pd.DataFrame, source: str) -> pd.DataFrame:
    df.attrs["source"] = source
    return df


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["コード", "銘柄名", "区分", "指定年月日"])


def _pick(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _read_tables(url: str) -> list[pd.DataFrame]:
    res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    res.raise_for_status()
    res.encoding = res.apparent_encoding
    return pd.read_html(io.StringIO(res.text))


def _normalize(df: pd.DataFrame) -> pd.DataFrame | None:
    """JPX の表を コード / 銘柄名 / 区分 / 指定年月日 / 解除年月日 に整える。"""
    df.columns = [str(c).strip() for c in df.columns]
    code_col = _pick(df, CODE_COLS)
    kind_col = _pick(df, KIND_COLS)
    if code_col is None or kind_col is None:
        return None

    out = pd.DataFrame()
    out["コード"] = df[code_col].astype(str).str.strip()
    name_col = _pick(df, NAME_COLS)
    out["銘柄名"] = df[name_col].astype(str).str.strip() if name_col else ""
    out["内容"] = df[kind_col].astype(str).str.strip()

    from_col = _pick(df, FROM_COLS)
    out["指定年月日"] = df[from_col].astype(str).str.strip() if from_col else ""
    until_col = _pick(df, UNTIL_COLS)
    out["解除年月日"] = df[until_col].astype(str).str.strip() if until_col else ""

    # 整理 / 監理 の判定
    out["区分"] = out["内容"].apply(
        lambda s: "整理" if "整理" in s else ("監理" if "監理" in s else "その他")
    )
    return out[out["区分"] != "その他"]


def fetch_alerts(use_cache_on_error: bool = True) -> pd.DataFrame:
    """現在有効な監理・整理銘柄を返す。列: コード / 銘柄名 / 区分 / 指定年月日"""
    frames: list[pd.DataFrame] = []
    try:
        for url in (JPX_CURRENT_URL, JPX_HISTORY_URL):
            for table in _read_tables(url):
                normalized = _normalize(table)
                if normalized is not None and not normalized.empty:
                    frames.append(normalized)
    except Exception as exc:  # noqa: BLE001
        print(f"[jpx_alerts] 取得に失敗しました: {exc}")
        if use_cache_on_error and CACHE_CSV.exists():
            print(f"[jpx_alerts] キャッシュを使用: {CACHE_CSV}")
            return _tag(pd.read_csv(CACHE_CSV, dtype=str), SOURCE_CACHE)
        print("[jpx_alerts] ❌ 監理・整理の突合ができません。除外は行われません。")
        return _tag(_empty(), SOURCE_FAILED)

    if not frames:
        print("[jpx_alerts] 表を検出できませんでした。ページ構成が変わった可能性があります。")
        if use_cache_on_error and CACHE_CSV.exists():
            print(f"[jpx_alerts] キャッシュを使用: {CACHE_CSV}")
            return _tag(pd.read_csv(CACHE_CSV, dtype=str), SOURCE_CACHE)
        print("[jpx_alerts] ❌ 監理・整理の突合ができません。除外は行われません。")
        return _tag(_empty(), SOURCE_FAILED)

    alerts = pd.concat(frames, ignore_index=True)

    # 解除済みを落とす（"-" や空欄 / NaN が未解除）
    released = alerts["解除年月日"].fillna("").str.replace("-", "", regex=False).str.strip()
    alerts = alerts[released == ""]

    # 同一銘柄が複数回出る場合は整理を優先し、指定年月日が新しいものを残す
    alerts["_priority"] = alerts["区分"].map({"整理": 0, "監理": 1})
    alerts = (
        alerts.sort_values(["コード", "_priority", "指定年月日"], ascending=[True, True, False])
        .drop_duplicates(subset=["コード"], keep="first")
        .drop(columns=["_priority", "解除年月日", "内容"])
        .reset_index(drop=True)
    )

    alerts.to_csv(CACHE_CSV, index=False, encoding="utf-8-sig")
    print(f"[jpx_alerts] 監理 {(alerts['区分'] == '監理').sum()} 件 / 整理 {(alerts['区分'] == '整理').sum()} 件")
    return _tag(alerts, SOURCE_LIVE)


if __name__ == "__main__":
    print(fetch_alerts().to_string(index=False))
