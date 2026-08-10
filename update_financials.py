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
    for attempt in range(max_retries):
        try:
            res = requests.get(url, params=params, headers=headers, timeout=20)
            if res.status_code == 200:
                return res
            if res.status_code in [401, 403]:
                logger.error(f"認証エラー (status_code={res.status_code})。APIキーを確認してください。")
                return res
            if res.status_code in [429, 500, 502, 503, 504]:
                wait_time = backoff_factor ** attempt
                logger.warning(f"HTTP {res.status_code} 受信。 {wait_time}秒後にリトライ... ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                logger.error(f"HTTPエラー: status_code={res.status_code}, body={res.text[:200]}")
                return res
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            wait_time = backoff_factor ** attempt
            logger.warning(f"通信例外 ({e})。 {wait_time}秒後にリトライ... ({attempt+1}/{max_retries})")
            time.sleep(wait_time)
            
    logger.error(f"リクエスト失敗: {url}")
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
            return []
        
        docs = []
        results = data.get("results", [])
        for doc in results:
            # 120: 有価証券報告書, 140: 四半期報告書, 160: 半期報告書
            doc_type = doc.get("docTypeCode")
            sec_code = doc.get("secCode")
            if doc_type in ["120", "140", "160"] and sec_code:
                code_4 = sec_code[:4]
                docs.append({
                    "doc_id": doc.get("docID"),
                    "sec_code": code_4,
                    "filer_name": doc.get("filerName"),
                    "doc_type": doc_type,
                    "submit_date": date_str,
                    "submit_time": doc.get("submitDateTime", "")
                })
        return docs
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
                return None

            with z.open(xbrl_filename) as f:
                soup = BeautifulSoup(f.read(), "lxml-xml")

                def get_tag_value(tags):
                    for tag in tags:
                        # *Abstract タグは除外する
                        elements = soup.find_all(lambda e: e.name and e.name.endswith(tag) and not e.name.endswith("Abstract"))
                        for el in elements:
                            context = el.get("contextRef", "")
                            # 当期末(CurrentYearInstant)等のコンテキストを優先
                            if ("Current" in context or "Instant" in context) and "Prior" not in context:
                                try:
                                    return float(el.text)
                                except ValueError:
                                    continue
                            try:
                                return float(el.text)
                            except ValueError:
                                continue
                    return None

                # 日本基準 & IFRS の代表的タグ
                current_assets = get_tag_value(["CurrentAssets", "AssetsCurrent"])
                total_liabilities = get_tag_value(["Liabilities", "LiabilitiesTotal", "LiabilitiesCurrentAndNonCurrent"])
                total_assets = get_tag_value(["Assets", "AssetsTotal"])
                net_assets = get_tag_value(["NetAssets", "Equity", "EquityAttributableToOwnersOfParent"])

                # 0も正常値として判定するため is not None を使用
                if (current_assets is not None and 
                    total_liabilities is not None and 
                    total_assets is not None and 
                    net_assets is not None and 
                    total_assets > 0):
                    
                    equity_ratio = round(net_assets / total_assets, 4)
                    return {
                        "current_assets": int(current_assets),
                        "total_liabilities": int(total_liabilities),
                        "total_assets": int(total_assets),
                        "net_assets": int(net_assets),
                        "equity_ratio": equity_ratio
                    }
                    
    except Exception as e:
        logger.error(f"[{doc_id}] XBRL解析例外: {e}")

    return None

def select_best_documents(raw_targets):
    """
    同銘柄で複数書類がある場合の最新・優先書類選択
    優先順位: 120(有報) > 140/160(四半期/半期) > 提出日が最新
    """
    type_priority = {"120": 3, "140": 2, "160": 2}
    grouped = {}
    
    for doc in raw_targets:
        code = doc["sec_code"]
        if code not in grouped:
            grouped[code] = []
        grouped[code].append(doc)

    selected = []
    for code, docs in grouped.items():
        # 優先順位スコアと提出日時でソート
        docs_sorted = sorted(
            docs,
            key=lambda x: (type_priority.get(x["doc_type"], 1), x["submit_date"], x["submit_time"]),
            reverse=True
        )
        selected.append(docs_sorted[0])
        
    return selected

def main():
    parser = argparse.ArgumentParser(description="EDINET Financial Cache Updater")
    parser.add_argument("--full", action="store_true", help="Run full scan for past 365 days")
    args = parser.parse_args()

    logger.info("=== 財務キャッシュ更新処理を開始します ===")
    if not API_KEY:
        logger.error("❌ ERROR: EDINET_API_KEY が設定されていません。")
        sys.exit(1)

    columns = ["sec_code", "filer_name", "current_assets", "total_liabilities", "total_assets", "net_assets", "equity_ratio", "doc_id", "submit_date"]
    
    if os.path.exists(CACHE_FILE):
        try:
            df_old = pd.read_csv(CACHE_FILE, dtype={"sec_code": str}).set_index("sec_code")
        except Exception:
            df_old = pd.DataFrame(columns=columns).set_index("sec_code")
    else:
        df_old = pd.DataFrame(columns=columns).set_index("sec_code")

    df_new = df_old.copy()
    raw_targets = []

    today = datetime.now()
    # フルスキャンは全社網羅のため過去365日、日次は抜け漏れ防止のため過去5日を見る
    scan_days = 365 if args.full else 5
    logger.info(f"[モード: {'フルスキャン(過去365日)' if args.full else '差分スキャン(過去5日)'}] 書類を検索中...")

    for i in range(scan_days):
        target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        docs = get_submitted_documents(target_date)
        raw_targets.extend(docs)
        time.sleep(0.05)

    unique_targets = select_best_documents(raw_targets)
    logger.info(f"処理対象企業数 (最適化後): {len(unique_targets)} 件")

    success_count = 0
    fail_count = 0

    for doc in unique_targets:
        sec_code = doc["sec_code"]
        try:
            fin = fetch_xbrl_data(doc["doc_id"])
            if fin:
                df_new.loc[sec_code] = {
                    "filer_name": doc["filer_name"],
                    "current_assets": fin["current_assets"],
                    "total_liabilities": fin["total_liabilities"],
                    "total_assets": fin["total_assets"],
                    "net_assets": fin["net_assets"],
                    "equity_ratio": fin["equity_ratio"],
                    "doc_id": doc["doc_id"],
                    "submit_date": doc["submit_date"]
                }
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            fail_count += 1

        time.sleep(0.1)

    logger.info(f"解析完了 - 成功: {success_count}件 / 失敗: {fail_count}件")

    df_new = df_new.reset_index()
    if not df_old.reset_index().equals(df_new):
        df_new.to_csv(CACHE_FILE, index=False)
        logger.info(f"🎉 財務キャッシュ ({CACHE_FILE}) を更新・保存しました。")
    else:
        logger.info("☕ 財務データに変更はありませんでした。")

if __name__ == "__main__":
    main()
