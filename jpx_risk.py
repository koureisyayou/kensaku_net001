"""jpx_risk.py

JPX が公表している上場リスクに関する銘柄一覧を取得する。

    猶予期間  … 上場廃止基準に係る猶予期間入り銘柄
    改善期間  … 上場維持基準の改善期間該当銘柄
    監査意見  … 不適正意見・意見不表明・限定付適正意見等
    特別注意  … 内部管理体制に問題があるとされた銘柄

いずれも上場廃止の手前、あるいは財務数値の信頼性に関わる状態を示す。
ネットネット候補は「株価が資産を大きく下回る」銘柄なので、
上場廃止が近い会社や決算数値が保証されない会社が紛れ込みやすい。

jpx_alerts.py（監理・整理銘柄）とは別ファイルにしている。
あちらは「取れたページで全体を上書きし、0件なら失敗」という作りで、
区分を足すと取得失敗時に既存の監理・整理まで巻き込むため。
こちらは区分ごとに独立して扱い、取れなかった区分は
前回のキャッシュを残す。

出力: jpx_risk_cache.csv
    コード / 銘柄名 / 市場区分 / 区分 / 該当事由 / 取得日

使い方:
    python jpx_risk.py
"""

from __future__ import annotations

import io
import logging
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

JST = timezone(timedelta(hours=9))
CACHE_FILE = "jpx_risk_cache.csv"
LOG_FILE = "jpx_risk.log"

COLUMNS = ["コード", "銘柄名", "市場区分", "区分", "該当事由", "取得日"]

# (区分, URL)。区分はそのまま出力の「区分」列に入る。
SOURCES = [
    ("猶予期間", "https://www.jpx.co.jp/listing/market-alerts/grace-period/index.html"),
    ("改善期間", "https://www.jpx.co.jp/listing/market-alerts/improvement-period/index.html"),
    ("監査意見", "https://www.jpx.co.jp/listing/others/adverse-opinion/index.html"),
    ("特別注意", "https://www.jpx.co.jp/listing/measures/alert/index.html"),
]

# 「該当事由」に入れる候補。ページによって列名が違うので、
# 見つかった最初のものを使う。どれも無ければ空にする。
REASON_COLS = ["該当基準", "該当事由", "監査意見等", "猶予期間", "改善期間", "指定日"]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def pick_col(columns, keyword):
    """列名に keyword を含む最初の列を返す。無ければ None。"""
    for c in columns:
        if keyword in str(c):
            return c
    return None


def normalize_code(series) -> pd.Series:
    """コード列を4桁の文字列に揃える。

    pd.read_html は数値列を int や float で読むため、そのまま
    astype(str) すると "4933.0" になることがある。末尾の .0 を
    落としたうえで4桁に揃える。新形式コード（377A など）は
    数値化されないのでそのまま通る。
    """
    return (series.astype(str).str.strip()
            .str.replace(r"\.0$", "", regex=True)
            .str.upper().str.zfill(4))


def fetch_page(label: str, url: str) -> pd.DataFrame:
    """1ページを読み、コード列を持つ表を縦に積んで返す。

    失敗した場合は空を返す。呼び出し側が「取得できなかった区分」として
    扱えるよう、例外は投げずログに残す。

    JPX のページは Content-Type に charset を持たないため、
    requests が ISO-8859-1 と誤認して日本語が全部化ける。
    バイト列をそのまま read_html に渡し、HTML の meta タグから
    文字コードを判定させる（jpx_alerts.py は apparent_encoding を
    設定する方式で、どちらでも結果は同じ）。
    """
    try:
        res = requests.get(url, timeout=30, headers=HEADERS)
        res.raise_for_status()
    except Exception as e:
        logger.warning(f"[{label}] 取得できませんでした: {e}")
        return pd.DataFrame()

    try:
        tables = pd.read_html(io.BytesIO(res.content))
    except ValueError:
        logger.warning(f"[{label}] 表が見つかりませんでした: {url}")
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"[{label}] 表を読めませんでした: {e}")
        return pd.DataFrame()

    out = []
    for t in tables:
        code_col = pick_col(t.columns, "コード")
        if code_col is None:
            continue

        t = t.copy()
        raw = t[code_col]
        # MultiIndex や同名列があると DataFrame が返ることがある
        if isinstance(raw, pd.DataFrame):
            raw = raw.iloc[:, 0]

        t["_code"] = normalize_code(raw)
        t = t[t["_code"].str.match(r"^[0-9][0-9A-Z]{3}$", na=False)]
        if t.empty:
            continue

        name_col = pick_col(t.columns, "会社名") or pick_col(t.columns, "銘柄名")
        market_col = pick_col(t.columns, "市場")

        reason = pd.Series("", index=t.index)
        for rc in REASON_COLS:
