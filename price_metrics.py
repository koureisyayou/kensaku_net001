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

import pandas as pd
import yfinance as yf

CHUNK_SIZE = 50          # yfinance へ一度に投げる銘柄数
HISTORY_PERIOD = "1y"    # 52週指標を出すため1年分
STAGNANT_BAND = 0.02     # 停滞判定の許容幅（±2%）


# ---------------------------------------------------------------- 取得

def _download(tickers: list[str], period: str = HISTORY_PERIOD) -> dict[str, pd.DataFrame]:
    """ティッカーごとの日足 DataFrame を辞書で返す。"""
    frames: dict[str, pd.DataFrame] = {}

    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        raw = yf.download(
            chunk,
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,   # 株式分割を調整（安値乖離を壊さないため必須）
            threads=True,
            progress=False,
        )
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
    path = "net_net_candidates.csv"
    base = pd.read_csv(path)
    enriched = add_price_metrics(base)
    enriched.to_csv(path, index=False, encoding="utf-8-sig")
    print(enriched.head())
