import os
import pandas as pd
from datetime import datetime

CANDIDATES_FILE = "net_net_candidates.csv"
HISTORY_FILE = "screening_history.csv"


def append_to_history():
    if not os.path.exists(CANDIDATES_FILE):
        print(f"Error: {CANDIDATES_FILE} が見つかりません。")
        return

    # 本日のスクリーニング結果を読み込み
    df = pd.read_csv(CANDIDATES_FILE)

    if df.empty:
        print("スクリーニング結果が0件のため、履歴保存をスキップします。")
        return

    # 実行日
    today = datetime.now().strftime("%Y-%m-%d")

    # 念のためコードを文字列として統一
    df["コード"] = df["コード"].astype(str).str.replace(".0", "", regex=False)

    # 現在のランキング
    df["rank"] = range(1, len(df) + 1)

    # 履歴用データ
    history_df = pd.DataFrame({
        "date": today,
        "sec_code": df["コード"],
        "company_name": df["銘柄名"],
        "price": df["株価 (円)"],
        "market_cap": df["時価総額 (億円)"],
        "ncav": df["NCAV (億円)"],
        "ncav_ratio": df["NCAV / 時価総額"],
        "equity_ratio": df["自己資本比率"],
        "rank": df["rank"],
    })

    # 既存履歴を読み込み
    if os.path.exists(HISTORY_FILE):
        history = pd.read_csv(HISTORY_FILE)

        # 今日のデータを削除
        # → 同日に再実行しても重複しない
        history = history[history["date"].astype(str) != today]

        # 追加
        history = pd.concat(
            [history, history_df],
            ignore_index=True
        )
    else:
        history = history_df

    # 日付・銘柄コード順に整理
    history = history.sort_values(
        ["date", "rank"],
        ascending=[True, True]
    )

    # 保存
    history.to_csv(
        HISTORY_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print(
        f"[{today}] 履歴データを更新しました。"
        f" 今回 {len(history_df)} 件 / 累計 {len(history)} 件"
    )


if __name__ == "__main__":
    append_to_history()
