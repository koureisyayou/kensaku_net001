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

JPX は該当銘柄が0件のとき、表そのものを作らず見出しだけを置く。
ページ構造が変わって読めない場合と症状が同じになるため、
両者を機械的に区別できない。安全側に倒して前回のキャッシュを残すので、
該当が外れた銘柄が残り続ける可能性がある。各行の取得日で判断すること。
実際に問題が起きたら、判定方法を見直す。

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
            col = pick_col(t.columns, rc)
            if col is not None:
                val = t[col]
                if isinstance(val, pd.DataFrame):
                    val = val.iloc[:, 0]
                reason = val.astype(str).str.strip().replace("nan", "")
                break

        def col_or_blank(col):
            if col is None:
                return ""
            v = t[col]
            if isinstance(v, pd.DataFrame):
                v = v.iloc[:, 0]
            return v.astype(str).str.strip().replace("nan", "")

        out.append(pd.DataFrame({
            "コード": t["_code"],
            "銘柄名": col_or_blank(name_col),
            "市場区分": col_or_blank(market_col),
            "区分": label,
            "該当事由": reason,
        }))

    if not out:
        logger.warning(
            f"[{label}] コード列を持つ表がありませんでした: {url}"
        )
        logger.warning(
            f"  該当銘柄が0件なのか、ページ構造が変わって読めなかったのかは"
            "ここでは区別できません。JPX は該当が無いとき表そのものを作らず、"
            "見出しだけを置くため、症状が同じになります。"
        )
        return pd.DataFrame()

    df = pd.concat(out, ignore_index=True)
    df = df.drop_duplicates(subset=["コード", "区分"], keep="first")
    logger.info(f"[{label}] {len(df)} 件")
    return df


def load_cache() -> pd.DataFrame:
    """既存キャッシュを読む。無ければ空を返す。"""
    try:
        df = pd.read_csv(CACHE_FILE, dtype=str)
    except FileNotFoundError:
        return pd.DataFrame(columns=COLUMNS)
    except Exception as e:
        logger.warning(f"{CACHE_FILE} を読めませんでした（新規作成します）: {e}")
        return pd.DataFrame(columns=COLUMNS)

    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[COLUMNS]


def main():
    today = datetime.now(JST).strftime("%Y-%m-%d")
    cache = load_cache()

    fetched = {}
    for label, url in SOURCES:
        df = fetch_page(label, url)
        if not df.empty:
            df["取得日"] = today
            fetched[label] = df

    if not fetched:
        logger.error(
            "すべての区分で取得に失敗しました。"
            f"{CACHE_FILE} は更新しません（前回の内容が残ります）。"
        )
        sys.exit(1)

    # 取れなかった区分は前回の行を残す。
    # 消してしまうと build_filters.py 側からは「該当0件」に見えて、
    # 「取得できなかった」と区別が付かなくなる。
    parts = list(fetched.values())
    missing = [label for label, _url in SOURCES if label not in fetched]
    if missing:
        logger.warning(
            f"表を読めなかった区分: {', '.join(missing)}。"
            "該当0件か取得失敗かは区別できないため、安全側に倒して"
            "前回のキャッシュをそのまま残します。"
        )
        logger.warning(
            "  そのため、実際には該当が外れた銘柄が残り続ける可能性があります。"
            "各行の取得日を見れば、いつ取れたものかが分かります。"
        )
        keep = cache[cache["区分"].isin(missing)]
        if not keep.empty:
            parts.append(keep)
            for label in missing:
                n = int((keep["区分"] == label).sum())
                if n:
                    old = keep.loc[keep["区分"] == label, "取得日"].max()
                    logger.warning(f"  [{label}] 前回の {n} 件を保持（取得日 {old}）")

    merged = pd.concat(parts, ignore_index=True)
    merged = merged.drop_duplicates(subset=["コード", "区分"], keep="first")
    merged = merged.sort_values(["区分", "コード"]).reset_index(drop=True)
    merged[COLUMNS].to_csv(CACHE_FILE, index=False, encoding="utf-8-sig")

    logger.info(f"{CACHE_FILE} を更新しました: {len(merged)} 件")
    for label, _url in SOURCES:
        n = int((merged["区分"] == label).sum())
        mark = "" if label in fetched else "（前回のまま）"
        logger.info(f"  {label}: {n} 件{mark}")

    # 同じ銘柄が複数の区分に該当することがある
    dup = merged["コード"].value_counts()
    dup = dup[dup > 1]
    if len(dup):
        logger.info(f"  複数の区分に該当: {len(dup)} 銘柄")
        for code, _n in dup.items():
            labels = sorted(merged.loc[merged["コード"] == code, "区分"])
            name = merged.loc[merged["コード"] == code, "銘柄名"].iloc[0]
            logger.info(f"    {code} {name}: {' / '.join(labels)}")


if __name__ == "__main__":
    main()
