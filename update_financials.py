import os
import io
import sys
import time
import logging
import argparse
import zipfile
import requests
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

CACHE_FILE = "financial_cache.csv"
LOG_FILE = "screener.log"
API_KEY = os.environ.get("EDINET_API_KEY")

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def request_with_retry(url, params=None, headers=None, max_retries=4, backoff_factor=2):
    """リトライ付きHTTPリクエスト"""
    for attempt in range(max_retries):
        try:
            res = requests.get(url, params=params, headers=headers, timeout=20)
            if res.status_code == 200:
                return res
            if res.status_code in [401, 403]:
                logger.error(f"認証エラーが発生しました (status_code={res.status_code})。APIキーを確認してください。")
                return res
            if res.status_code in [429, 500, 502, 503, 504]:
                wait_time = backoff_factor ** attempt
                logger.warning(f"HTTP {res.status_code} 受信。 {wait_time}秒後にリトライ... ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                logger.error(f"HTTPエラーが発生しました: status_code={res.status_code}, body={res.text[:200]}")
                return res
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            wait_time = backoff_factor ** attempt
            logger.warning(f"通信例外発生 ({e})。 {wait_time}秒後にリトライ... ({attempt+1}/{max_retries})")
            time.sleep(wait_time)
            
    logger.error(f"最大リトライ回数に達したためリクエスト失敗: {url}")
    return None

def get_edinet_headers():
    return {
        "Ocp-Apim-Subscription-Key": API_KEY,
        "User-Agent": "NetNetScreener/1.0"
    }

def get_submitted_documents(date_str):
    url = "https://disclosure.edinet-fsa.go.jp/api/v2/documents.json"
    params = {"date": date_str, "type": 2}
    headers = get_edinet_headers()
    
    res = request_with_retry(url, params=params, headers=headers)
    if not res or res.status_code != 200:
        return []

    try:
        data = res.json()
        status = data.get("metadata", {}).get("status")
        if status != "200":
            message = data.get("metadata", {}).get("message", "不明なエラー")
            logger.warning(f"EDINET API応答ステータス非正常 ({date_str}): status={status}, message={message}")
            return []
        
        docs_dict = {}
        results = data.get("results", [])
        for doc in results:
            if doc.get("docTypeCode") in ["120", "140"] and doc.get("secCode"):
                sec_code = doc.get("secCode")[:4]
                docs_dict[sec_code] = {
                    "doc_id": doc.get("docID"),
                    "sec_code": sec_code,
                    "filer_name": doc.get("filerName")
                }
        return list(docs_dict.values())
    except Exception as e:
        logger.error(f"書類一覧パース失敗 ({date_str}): {e}")
        return []

def fetch_xbrl_data(doc_id):
    url = f"https://disclosure.edinet-fsa.go.jp/api/v2/documents/{doc_id}"
    params = {"type": 1}
    headers = get_edinet_headers()

    try:
        res = request_with_retry(url, params=params, headers=headers)
        if not res or res.status_code != 200:
            return None

        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            xbrl_filename = next((name for name in z.namelist() if name.endswith(".xbrl") and "PublicDoc" in name), None)
            if not xbrl_filename:
                logger.warning(f"[{doc_id}] ZIP内にPublicDoc XBRLファイルが見つかりません。")
                return None

            with z.open(xbrl_filename) as f:
                soup = BeautifulSoup(f.read(), "lxml-xml")

                def get_tag_value(tags):
                    for tag in tags:
                        elements = soup.find_all(lambda e: e.name and e.name.endswith(tag))
                        for el in elements:
                            context = el.get("contextRef", "")
                            if "Current" in context and "NonConsolidated" not in context:
                                try:
                                    return float(el.text)
                                except ValueError:
                                    continue
                            try:
                                return float(el.text)
                            except ValueError:
                                continue
                    return None

                current_assets = get_tag_value(["CurrentAssets"])
                total_liabilities = get_tag_value(["Liabilities", "LiabilitiesAbstract"])
                total_assets = get_tag_value(["Assets"])
                net_assets = get_tag_value(["NetAssets", "Equity", "EquityAttributableToOwnersOfParent"])

                if current_assets and total_liabilities and total_assets and net_assets:
                    equity_ratio = round(net_assets / total_assets, 4)
                    return {
                        "current_assets": int(current_assets),
                        "total_liabilities": int(total_liabilities),
                        "equity_ratio": equity_ratio
                    }
                else:
                    logger.warning(f"[{doc_id}] 必要な勘定科目タグの一部が見つかりませんでした。")
                    
    except zipfile.BadZipFile:
        logger.error(f"[{doc_id}] ZIP形式エラー。")
    except Exception as e:
        logger.error(f"[{doc_id}] XBRL解析例外 (スキップ): {e}")

    return None

def main():
    parser = argparse.ArgumentParser(description="EDINET Financial Cache Updater")
    parser.add_argument("--full", action="store_true", help="Run full scan for past documents")
    args = parser.parse_args()

    logger.info("=== 財務キャッシュ更新処理を開始します ===")
    if not API_KEY:
        logger.error("❌ エラー: EDINET_API_KEY が環境変数に設定されていません！")
        sys.exit(1)
    else:
        logger.info(f"🔑 APIキー検出完了: {API_KEY[:4]}*** (文字数: {len(API_KEY)})")

    if os.path.exists(CACHE_FILE):
        try:
            df_old = pd.read_csv(CACHE_FILE, dtype={"sec_code": str}).set_index("sec_code")
        except Exception as e:
            logger.error(f"キャッシュファイル読み込みエラー: {e}")
            df_old = pd.DataFrame(columns=["sec_code", "filer_name", "current_assets", "total_liabilities", "equity_ratio"]).set_index("sec_code")
    else:
        df_old = pd.DataFrame(columns=["sec_code", "filer_name", "current_assets", "total_liabilities", "equity_ratio"]).set_index("sec_code")

    df_new = df_old.copy()
    raw_targets = []

    if args.full:
        logger.info("[モード: フルスキャン] 過去90日分の書類を検索します")
        today = datetime.now()
        for i in range(90):
            target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            docs = get_submitted_documents(target_date)
            raw_targets.extend(docs)
            time.sleep(0.1)
    else:
        logger.info("[モード: 差分スキャン] 本日分の書類を検索します")
        today_str = datetime.now().strftime("%Y-%m-%d")
        raw_targets = get_submitted_documents(today_str)

    unique_targets_dict = {doc["sec_code"]: doc for doc in raw_targets}
    unique_targets = list(unique_targets_dict.values())

    logger.info(f"処理対象企業数 (重複除外後): {len(unique_targets)} 件")

    success_count = 0
    fail_count = 0

    for doc in unique_targets:
        sec_code = doc["sec_code"]
        logger.info(f"解析中: [{sec_code}] {doc['filer_name']} ...")

        try:
            fin = fetch_xbrl_data(doc["doc_id"])
            if fin:
                df_new.loc[sec_code] = {
                    "filer_name": doc["filer_name"],
                    "current_assets": fin["current_assets"],
                    "total_liabilities": fin["total_liabilities"],
                    "equity_ratio": fin["equity_ratio"]
                }
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            logger.error(f"[{sec_code}] スキップ: {e}")
            fail_count += 1

        time.sleep(0.2)

    logger.info(f"解析完了 - 成功: {success_count}件 / 失敗: {fail_count}件")

    df_old_sorted = df_old.sort_index().fillna("")
    df_new_sorted = df_new.sort_index().fillna("")

    if not df_old_sorted.equals(df_new_sorted):
        df_new.reset_index().to_csv(CACHE_FILE, index=False)
        logger.info(f"🎉 データ更新検知。 ({CACHE_FILE}) を上書き保存しました。")
    else:
        logger.info("☕ 財務データに変更はありませんでした。")

if __name__ == "__main__":
    main()
