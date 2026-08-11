import os
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

CANDIDATES_FILE = "net_net_candidates.csv"
HISTORY_FILE = "screening_history.csv"


def append_to_history():

    # ==============================
    # 1. 入力ファイル確認
    # ==============================
    if not os.path.exists(CANDIDATES_FILE):
        print(f"Error: {CANDIDATES_FILE} が見つかりません。")
        return

    # ==============================
    # 2. スクリーニング結果読み込み
    # ==============================
    df = pd.read_csv(CANDIDATES_FILE)

    if df.empty:
        print("スクリーニング結果が0件のため、履歴保存をスキップします。")
        return

    # ==============================
    # 3. 必須列チェック
    # ==============================
    required_columns = [
        "コード",
        "銘柄名",
        "株価 (円)",
        "時価総額 (億円)",
        "NCAV (億円)",
        "NCAV / 時価総額",
        "自己資本比率",
    ]

    missing_columns = [
        col for col in required_columns
        if col not in df.columns
    ]

    if missing_columns:
        print("Error: 必須列が不足しています。")
        print("不足列:", missing_columns)
        return

    # ==============================
    # 4. 日本時間の日付
    # ==============================
    today = datetime.now(
        ZoneInfo("Asia/Tokyo")
    ).strftime("%Y-%m-%d")

    # ==============================
    # 5. 証券コードを文字列化
    # ==============================
    df["コード"] = (
        df["コード"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
    )

    # ==============================
    # 6. ランキング
    # ==============================
    df["rank"] = range(1, len(df) + 1)

    # ==============================
    # 7. 任意列
    # ==============================
    def get_column(column):
        if column in df.columns:
            return df[column]
        return pd.Series([None] * len(df))

    # ==============================
    # 8. 履歴データ作成
    # ==============================
    history_df = pd.DataFrame({
        "date": today,
        "sec_code": df["コード"],
        "company_name": df["銘柄名"],
        "price": df["株価 (円)"],
        "market_cap": df["時価総額 (億円)"],
        "ncav": df["NCAV (億円)"],
        "ncav_ratio": df["NCAV / 時価総額"],
        "net_cash": get_column("純現金 (億円)"),
        "net_cash_ratio": get_column("純現金 / 時価総額"),
        "operating_cf": get_column("営業CF (億円)"),
        "equity_ratio": df["自己資本比率"],
        "rank": df["rank"],
    })

    # ==============================
    # 9. 既存履歴
    # ==============================
    if os.path.exists(HISTORY_FILE):

        history = pd.read_csv(
            HISTORY_FILE,
            dtype={"date": str, "sec_code": str}
        )

        # 日付を文字列として統一
        history["date"] = history["date"].astype(str)

        # 同日のデータを削除
        history = history[
            history["date"] != today
        ]

        # 新しい結果を追加
        history = pd.concat(
            [history, history_df],
            ignore_index=True
        )

    else:
        history = history_df

    # ==============================
    # 10. 並び替え
    # ==============================
    history = history.sort_values(
        ["date", "rank"],
        ascending=[True, True]
    )

    # ==============================
    # 11. 保存
    # ==============================
    history.to_csv(
        HISTORY_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print(
        f"[{today}] 履歴データを更新しました。"
    )

    print(
        f"今回: {len(history_df)} 件"
    )

    print(
        f"累計: {len(history)} 件"
    )


if __name__ == "__main__":
    append_to_history()
