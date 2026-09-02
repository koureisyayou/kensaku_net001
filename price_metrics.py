"""price_metrics.py

ネットネットスクリーナー用の価格指標を計算して列として追加するモジュール。
run_screener.py から import して、net_net_candidates.csv を書き出す直前に呼ぶ。

追加される列:
    調整後終値              分割調整後の直近終値（既存の「株価」列との照合用）
    前日比%                 前営業日比の騰落率
    5日騰落%                5営業日前比の騰落率
    20日騰落%               20営業日前比の騰落率
    60日安値乖離%           直近60営業日の安値から何%上にいるか
    120日安値乖離%          直近120営業日の安値から何%上にいるか
    52週安値乖離%           52週安値から何%上にいるか
    52週高値乖離%           52週高値から何%下にいるか（マイナス値）
    停滞日数                直近終値から±2%以内に収まっている連続日数
    20日平均売買代金(百万円) 流動性の目安
"""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50          # yfinance へ一度に投げる銘柄数
HISTORY_PERIOD = "1y"    # 52週指標を出すため1年分
STAGNANT_BAND = 0.02     # 停滞判定の許容幅（±2%）


# ---------------------------------------------------------------- 取得

def _download(tickers: list[str], period: str = HISTORY_PERIOD) -> dict[str, pd.DataFrame]:
    """ティッカーごとの日足 DataFrame を辞書で返す。

    1銘柄でも取得に失敗したら全体が無になる、という状態を避けることが
    このループの前提。ここで例外が抜けると run_screener.py 側の
    try/except が握りつぶし、価格指標の列が全銘柄で付与されないまま
    net_net_candidates.csv が書き出される。

    そうなると下流で静かに篩が緩む。generate_shortlist.py は
    「売買代金の列がありません」と出して流動性の除外をスキップし、
    net_my_filters の build_filters.py は流動性の色分けを行わない。
    警告は出るがワークフローは成功扱いになるため、ページを見ても
    篩が1段消えたことにしか気づけない。だから銘柄単位で握る。
    """
    frames: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []

    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        try:
            raw = yf.download(
                chunk,
                period=period,
                interval="1d",
                group_by="ticker",
                auto_adjust=True,   # 株式分割を調整（安値乖離を壊さないため必須）
                threads=True,
                progress=False,
            )
        except Exception as e:
            logger.warning(f"[price_metrics] 一括取得に失敗しました: {e}")
            skipped.extend(chunk)
            continue

        if raw is None or raw.empty:
            skipped.extend(chunk)
            continue

        for ticker in chunk:
            # 銘柄ごとの取り出し。
            # 依頼した銘柄数ではなく、実際に返ってきた列の形で判断する。
            # yfinance は銘柄数によって単層列と MultiIndex を使い分けるため、
            # len(chunk) で分岐すると戻り値の形と食い違うことがある。
            # 最後のチャンクがちょうど1銘柄になる件数（101件、151件など）で
            # 実際に取り違えが起き、下の dropna が KeyError を投げていた。
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    df = raw[ticker]
                else:
                    df = raw
            except KeyError:
                skipped.append(ticker)
                continue

            # 取得できなかった銘柄は Close 列を持たないことがある。
            # dropna(subset=["Close"]) は列が無いと KeyError を投げ、
            # ここを抜けると呼び出し元まで例外が伝播する。
            if "Close" not in df.columns:
                skipped.append(ticker)
                continue

            df = df.dropna(subset=["Close"])
            if df.empty:
                skipped.append(ticker)
                continue

            frames[ticker] = df

    if skipped:
        logger.warning(
            f"[price_metrics] 価格を取得できなかった銘柄 {len(skipped)} 件: "
            + ", ".join(skipped[:20]) + (" ..." if len(skipped) > 20 else "")
        )

    return frames


# ---------------------------------------------------------------- 計算

def _pct(current, base):
    """base に対する current の乖離率（%）。小数第1位まで。"""
    if base is None or pd.isna(base) or pd.isna(current) or base == 0:
        return None
    return round((current / base - 1) * 100, 1)


def _stagnant_days(close: pd.Series, band: float = STAGNANT_BAND) -> int:
    """直近終値から ±band 以内に収まっている連続日数（当日を1日目とする）。"""
    last = close.iloc[-1]
    days = 0
    for value in reversed(close.tolist()):
        if abs(value / last - 1) <= band:
            days += 1
        else:
            break
    return days


def compute_metrics(df: pd.DataFrame) -> dict:
    close = df["Close"]
    volume = df["Volume"]
    last = close.iloc[-1]

    return {
        "調整後終値": round(float(last), 1),
        "前日比%": _pct(last, close.iloc[-2]) if len(close) >= 2 else None,
        "5日騰落%": _pct(last, close.iloc[-6]) if len(close) >= 6 else None,
        "20日騰落%": _pct(last, close.iloc[-21]) if len(close) >= 21 else None,
        "60日安値乖離%": _pct(last, close.tail(60).min()),
        "120日安値乖離%": _pct(last, close.tail(120).min()),
        "52週安値乖離%": _pct(last, close.min()),
        "52週高値乖離%": _pct(last, close.max()),
        "停滞日数": _stagnant_days(close),
        "20日平均売買代金(百万円)": round(float((close * volume).tail(20).mean()) / 1e6, 1),
    }


# ---------------------------------------------------------------- 公開関数

def add_price_metrics(candidates: pd.DataFrame, ticker_col: str = "Ticker") -> pd.DataFrame:
    """抽出済みの候補 DataFrame に価格指標の列を左結合して返す。

    除外は一切しない。値が取れなかった銘柄は空欄になる。
    """
    tickers = candidates[ticker_col].dropna().astype(str).unique().tolist()
    frames = _download(tickers)

    rows = []
    for ticker in tickers:
        df = frames.get(ticker)
        metrics = compute_metrics(df) if df is not None and not df.empty else {}
        rows.append({ticker_col: ticker, **metrics})

    metrics_df = pd.DataFrame(rows)
    return candidates.merge(metrics_df, on=ticker_col, how="left")


if __name__ == "__main__":
    # 単体テスト用: 既存の CSV を読んで列を足し、上書き保存する
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    path = "net_net_candidates.csv"
    base = pd.read_csv(path)
    enriched = add_price_metrics(base)
    enriched.to_csv(path, index=False, encoding="utf-8-sig")
    print(enriched.head())
