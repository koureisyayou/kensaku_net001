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
    """EDINET APIから指定日付の提出書類一覧を取得"""
    url = "https://disclosure.edinet-fsa.go.jp/api/v2/documents.json"
    params = {"date": date_str, "type": 2}
    headers = get_edinet_headers()
    
    res = request_with_retry(url, params=params, headers=headers)
    if not res or res.status_code != 200:
        return []

    try:
        data = res.json()
        if data.get("metadata", {}).get("status") != "200":
            return []
        
        docs = []
        results = data.get("results", [])
        for doc in results:
            doc_type = doc.get("docTypeCode")
            sec_code = doc.get("secCode")
            # 120: 有報, 130: 訂正有報, 140: 四半期, 150: 訂正四半期, 160: 半期, 170: 訂正半期
            if doc_type in ["120", "130", "140", "150", "160", "170"] and sec_code:
                code_4 = sec_code[:4]
                docs.append({
                    "doc_id": doc.get("docID"),
                    "sec_code": code_4,
                    "filer_name": doc.get("filerName"),
                    "doc_type": doc_type,
                    "submit_date": date_str,
                    "submit_datetime": doc.get("submitDateTime", f"{date_str} 00:00"),
                    "period_end": doc.get("periodEnd", "")
                })
        return docs
    except Exception as e:
        logger.error(f"書類一覧パース失敗 ({date_str}): {e}")
        return []

def select_best_documents(raw_targets):
    """
    同銘柄で複数書類がある場合の選択ロジック:
    1. 決算期末日 (period_end) が最も新しいものを優先 (対象財務期間の最新性)
    2. 決算期末日が同じ場合は、提出日時 (submit_datetime) が最も新しいものを優先 (訂正報告書の採用)
    """
    grouped = {}
    for doc in raw_targets:
        code = doc["sec_code"]
        if code not in grouped:
            grouped[code] = []
        grouped[code].append(doc)

    selected = []
    for code, docs in grouped.items():
        docs_sorted = sorted(
            docs,
            key=lambda x: (x["period_end"], x["submit_datetime"]),
            reverse=True
        )
        selected.append(docs_sorted[0])
        
    return selected

def parse_clean_amount(element):
    """
    二重換算リスクを極力排除した数値抽出ロジック。
    XBRL内のテキスト数値を純粋に取得し、scale属性が存在する場合のみ単純乗算する。
    """
    if not element or not element.text:
        return None
    
    text_val = element.text.strip().replace(",", "")
    try:
        val = float(text_val)
    except ValueError:
        return None

    # scale属性の適用（scale="6" => 1,000,000倍, scale="3" => 1,000倍）
    # ※二重推測ロジック（decimals等を使った推測）は完全に排除
    scale = element.get("scale")
    if scale is not None:
        try:
            val = val * (10 ** int(scale))
        except ValueError:
            pass

    return int(val)

def extract_valid_contexts(soup):
    """
    XBRL内の <xbrli:context> を構文解析し、期末時点 (instant) のコンテキストIDを抽出
    """
    instant_contexts = set()
    consolidated_contexts = set()
    
    for ctx in soup.find_all(["context", "xbrli:context"]):
        ctx_id = ctx.get("id")
        if not ctx_id:
            continue
            
        # 期末時点(instant)のコンテキストかを構造的に確認
        if ctx.find(["instant", "xbrli:instant"]):
            instant_contexts.add(ctx_id)
            
        # 連結・個別の文脈判定
        # (ScenarioやSegment内に Member タグがある場合やID構造から判定)
        ctx_str = str(ctx).lower()
        if "consolidated" in ctx_str and "nonconsolidated" not in ctx_str:
            consolidated_contexts.add(ctx_id)
            
    return instant_contexts, consolidated_contexts

def fetch_xbrl_data(doc_id):
    """
    XBRLファイルを解析し、財務情報を抽出
    """
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

                instant_ctxs, cons_ctxs = extract_valid_contexts(soup)

                def get_tag_value(tag_names):
                    for tag in tag_names:
                        elements = soup.find_all(lambda e: e.name and e.name.endswith(tag) and not e.name.endswith("Abstract"))
                        
                        # 1. 連結 + 期末時点 (instant)
                        for el in elements:
                            ctx = el.get("contextRef", "")
                            if ctx in instant_ctxs and (ctx in cons_ctxs or "Consolidated" in ctx):
                                val = parse_clean_amount(el)
                                if val is not None:
                                    return val, True, tag

                        # 2. 個別 + 期末時点 (instant)
                        for el in elements:
                            ctx = el.get("contextRef", "")
                            if ctx in instant_ctxs:
                                val = parse_clean_amount(el)
                                if val is not None:
                                    return val, False, tag

                    return None, False, None

                # 財務項目の取得
                ca_val, cons, _ = get_tag_value(["CurrentAssets", "AssetsCurrent"])
                tl_val, _, _    = get_tag_value(["Liabilities", "LiabilitiesTotal", "LiabilitiesCurrentAndNonCurrent"])
                ta_val, _, _    = get_tag_value(["Assets", "AssetsTotal"])
                
                # 純資産 / 自己資本（優先順位と持分タイプの明確化）
                eq_val, _, eq_tag = get_tag_value([
                    "EquityAttributableToOwnersOfParent",  # 親会社所有者帰属持分
                    "NetAssets",                            # 純資産合計
                    "Equity"                                # 資本合計
                ])

                # 会計基準の簡易判定
                is_ifrs = any("AssetsCurrent" in e.name for e in soup.find_all() if e.name)
                accounting_std = "IFRS" if is_ifrs else "J-GAAP"

                if (ca_val is not None and 
                    tl_val is not None and 
                    ta_val is not None and 
                    eq_val is not None and 
                    ta_val > 0):
                    
                    equity_ratio = round(eq_val / ta_val, 4)
                    return {
                        "current_assets": ca_val,
                        "total_liabilities": tl_val,
                        "total_assets": ta_val,
                        "equity_value": eq_val,
                        "equity_type": eq_tag or "Unknown",
                        "equity_ratio": equity_ratio,
                        "consolidated": cons,
                        "accounting_standard": accounting_std
                    }
                    
    except Exception as e:
        logger.error(f"[{doc_id}] XBRL解析例外: {e}")

    return None

def main():
    parser = argparse.ArgumentParser(description="EDINET Financial Cache Updater")
    parser.add_argument("--full", action="store_true", help="Run full scan for past 365 days of EDINET filings")
    args = parser.parse_args()

    logger.info("=== 財務キャッシュ更新処理を開始します ===")
    if not API_KEY:
        logger.error("❌ ERROR: EDINET_API_KEY が設定されていません。")
        sys.exit(1)

    columns = [
        "sec_code", "filer_name", "current_assets", "total_liabilities", 
        "total_assets", "equity_value", "equity_type", "equity_ratio", 
        "doc_id", "submit_date", "doc_type", "accounting_standard", 
        "consolidated", "fiscal_period"
    ]
    
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
    scan_days = 365 if args.full else 5
    logger.info(f"[モード: {'フルスキャン (過去365日分)' if args.full else '差分スキャン (過去5日分)'}] 書類一覧を検索中...")

    for i in range(scan_days):
        target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        docs = get_submitted_documents(target_date)
        raw_targets.extend(docs)
        time.sleep(0.05)

    # 「決算期末日(period_end)の最新性」＋「提出日時(submit_datetime)の最新性」で厳密選択
    unique_targets = select_best_documents(raw_targets)
    logger.info(f"処理対象企業数 (最適書類抽出後): {len(unique_targets)} 件")

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
                    "equity_value": fin["equity_value"],
                    "equity_type": fin["equity_type"],
                    "equity_ratio": fin["equity_ratio"],
                    "doc_id": doc["doc_id"],
                    "submit_date": doc["submit_date"],
                    "doc_type": doc["doc_type"],
                    "accounting_standard": fin["accounting_standard"],
                    "consolidated": "連結" if fin["consolidated"] else "個別",
                    "fiscal_period": doc["fiscal_period"] if "fiscal_period" in doc else doc["period_end"]
                }
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            logger.error(f"[{sec_code}] 処理エラー: {e}")
            fail_count += 1

        time.sleep(0.1)

    logger.info(f"解析完了 - 成功: {success_count}件 / 失敗: {fail_count}件")

    df_new = df_new.reset_index()
    if not df_old.reset_index().equals(df_new):
        df_new.to_csv(CACHE_FILE, index=False)
        logger.info(f"🎉 財務キャッシュ ({CACHE_FILE}) を完全改修データ構造で更新しました。")
    else:
        logger.info("☕ 財務データに変更はありませんでした。")

if __name__ == "__main__":
    main()
