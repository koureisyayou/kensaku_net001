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
    df = pd.read_csv(CANDIDATES_FILE, dtype={"sec_code": str})

    if df.empty:
        print("スクリーニング結果が0件のため、履歴保存をスキップします。")
        return

    # ==============================
    # 3. 必須列チェック
    # ==============================
    required_columns = [
        "sec_code",
        "company_name",
        "price",
        "market_cap",
        "ncav",
        "nc_ratio",
        "equity_ratio",
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
    # 5. 証券コードの整形（文字列・空白除去）
    # ==============================
    df["sec_code"] = (
        df["sec_code"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
    )

    # ==============================
    # 6. ランキング
    # ==============================
    df["rank"] = range(1, len(df) + 1)

    # ==============================
    # 7. 任意列取得用ヘルパー
    # ==============================
    def get_column(column):
        if column in df.columns:
            return df[column]
        return pd.Series([None] * len(df))

    # ==============================
    # 8. 履歴データ作成（データの実義に忠実にマッピング）
    # ==============================
    history_df = pd.DataFrame({
        "date": today,
        "sec_code": df["sec_code"],
        "company_name": df["company_name"],
        "price": df["price"],
        "market_cap": df["market_cap"],
        "ncav": df["ncav"],
        "ncav_ratio": df["nc_ratio"],
        "cash_and_equivalents": get_column("cash_and_equivalents"),
        "net_cash": get_column("net_cash"),
        "net_cash_ratio": get_column("net_cash_ratio"),
        "operating_income": get_column("operating_income"),
        "operating_cf": get_column("operating_cf"),
        "equity_ratio": df["equity_ratio"],
        "rank": df["rank"],
    })

    # ==============================
    # 9. 既存履歴の読み込みと結合
    # ==============================
    if os.path.exists(HISTORY_FILE):

        history = pd.read_csv(
            HISTORY_FILE,
            dtype={"date": str, "sec_code": str}
        )

        # 日付を文字列として統一
        history["date"] = history["date"].astype(str)

        # 同日のデータを削除（上書き・再実行時の重複防止）
        history = history[history["date"] != today]

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

    print(f"[{today}] 履歴データを更新しました。")
    print(f"今回: {len(history_df)} 件")
    print(f"累計: {len(history)} 件")


if __name__ == "__main__":
    append_to_history()
