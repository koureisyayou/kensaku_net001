import os
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

CANDIDATES_FILE = "net_net_candidates.csv"
HISTORY_FILE = "screening_history.csv"

# ------------------------------------------------------------------
# operating_income / operating_cf の列は 2026-09 に削除した。
#
# 入力の net_net_candidates.csv にこの2列は存在せず、get_column() が
# 常に None を返していたため、蓄積した 1,811 行すべてが空欄だった。
# CONTEXT.md にも「⚠ 全行が空の列」として警告が出続けていた。
#
# 損益・CFは別リポジトリ net_my_filters の pl_cache.csv が持っている。
# こちらから参照すると一次篩が二次篩に依存することになり、
# 「kensaku_net001 は損益を扱わない」という役割分担が崩れる。
# 履歴として損益が必要になったら、net_my_filters 側で
# pl_cache.csv の履歴を取る方が構成に合う。
#
# 既存の screening_history.csv にはこの2列が残っているが、
# 読み手（generate_shortlist.py の load_streaks）は日付列と
# コード列しか見ないので、放置しても実害はない。
# 消したい場合は手動で列を落とすこと。
# ------------------------------------------------------------------


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
    # 3. 社名列のフォールバック
    #    （candidates 側が filer_name しか持っていない場合に備える）
    # ==============================
    if "company_name" not in df.columns and "filer_name" in df.columns:
        df["company_name"] = df["filer_name"]

    # ==============================
    # 4. 必須列チェック
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
    # 5. 日本時間の日付
    # ==============================
    today = datetime.now(
        ZoneInfo("Asia/Tokyo")
    ).strftime("%Y-%m-%d")

    # ==============================
    # 6. 証券コードの整形（文字列・空白除去）
    # ==============================
    df["sec_code"] = (
        df["sec_code"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
    )

    # ==============================
    # 7. ランキング
    # (run_screener.py の出力順を尊重して順位を付与)
    # ==============================
    df = df.reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)

    # ==============================
    # 8. 任意列取得用ヘルパー
    #    （インデックスを df に揃えないと結合時に値がずれる）
    #
    #    現金系の3列は run_screener.py が「現金が取れた銘柄だけ」
    #    付与するため、候補によっては列ごと存在しないことがある。
    #    そのための保険であって、存在しない列を作るためではない。
    # ==============================
    def get_column(column):
        if column in df.columns:
            return df[column]
        return pd.Series([None] * len(df), index=df.index)

    # ==============================
    # 9. 履歴データ作成（定義通りのマッピング）
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
        "equity_ratio": df["equity_ratio"],
        "rank": df["rank"],
    })

    # ==============================
    # 10. 既存履歴の読み込みと結合・同日同銘柄の重複排除
    # ==============================
    if os.path.exists(HISTORY_FILE):

        history = pd.read_csv(
            HISTORY_FILE,
            dtype={"date": str, "sec_code": str}
        )

        history["date"] = history["date"].astype(str)

        combined = pd.concat(
            [history, history_df],
            ignore_index=True
        )

        history = combined.drop_duplicates(
            subset=["date", "sec_code"],
            keep="last"
        )

    else:
        history = history_df

    # ==============================
    # 11. 並び替え（日付順・順位順）
    # ==============================
    history = history.sort_values(
        ["date", "rank"],
        ascending=[True, True]
    )

    # ==============================
    # 12. 保存
    # ==============================
    history.to_csv(
        HISTORY_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"[{today}] 履歴データを更新しました。")
    print(f"今回追加・更新: {len(history_df)} 件")
    print(f"累計保持: {len(history)} 件")


if __name__ == "__main__":
    append_to_history()
