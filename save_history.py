import os
import pandas as pd
from datetime import datetime

# ファイルパス
CANDIDATES_FILE = 'net_net_candidates.csv'  # 現在の出力ファイル名に合わせて変更
HISTORY_FILE = 'screening_history.csv'

def append_to_history():
    if not os.path.exists(CANDIDATES_FILE):
        print(f"Error: {CANDIDATES_FILE} が見つかりません。")
        return

    # 本日のスクリーニング結果を読み込み
    df = pd.read_csv(CANDIDATES_FILE)
    
    # 実行日をYYYY-MM-DDで取得
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 順位（rank）を1から付与（ソート済み前提）
    df['rank'] = range(1, len(df) + 1)
    
    # 履歴用に必要なカラムを抽出・整形
    # ※列名は実際のCSVに合わせて調整してください
    history_df = pd.DataFrame({
        'date': today,
        'sec_code': df['コード'],
        'company_name': df['銘柄名'],
        'price': df['株価 (円)'],
        'market_cap': df['時価総額 (億円)'],
        'ncav': df['NCAV (億円)'],
        'ncav_ratio': df['NCAV / 時価総額'],
        'equity_ratio': df['自己資本比率'],
        'rank': df['rank']
    })

    # ファイルが存在しなければヘッダー付きで新規作成、存在すれば追記（header=False）
    file_exists = os.path.exists(HISTORY_FILE)
    history_df.to_csv(HISTORY_FILE, mode='a', index=False, header=not file_exists, encoding='utf-8-sig')
    print(f"[{today}] 履歴データを {HISTORY_FILE} に追記しました。（{len(history_df)} 件）")

if __name__ == '__main__':
    append_to_history()
