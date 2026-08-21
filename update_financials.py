import os
import sys
import time
import logging
import io
import zipfile
import argparse
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

# ファイルパス・定数の定義
CACHE_FILE = "financial_cache.csv"
PROCESSED_FILE = "processed_docs.csv"
LOG_FILE = "update_financials.log"
JST = timezone(timedelta(hours=9))

# 訂正報告書(130/150/170)を原本より優先するか。
# 訂正報告書は差分のみでXBRLが不完全なことが多いため、既定は False（原本優先）。
PREFER_AMENDMENT = False
AMENDMENT_TYPES = {"130", "150", "170"}

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

# EDINET API 設定
EDINET_API_KEY = os.environ.get("EDINET_API_KEY", "")

# ------------------------------------------------------------------
# 抽出対象のXBRL要素名（ローカル名の完全一致で判定する）
#   J-GAAP  : jppfs_cor    例) Assets / Liabilities / CurrentAssets / NetAssets
#   IFRS    : jpigp_cor    例) AssetsIFRS / LiabilitiesIFRS / CurrentAssetsIFRS
# 部分一致(endswith)を使うと CurrentAssets が Assets に、NetAssets が Assets に
# 誤ヒットして総資産・総負債が別科目に化けるため、完全一致にしている。
# ------------------------------------------------------------------
TAGS_CURRENT_ASSETS = ["CurrentAssets", "CurrentAssetsIFRS", "AssetsCurrent"]
TAGS_TOTAL_LIABILITIES = ["Liabilities", "LiabilitiesIFRS"]
TAGS_TOTAL_ASSETS = ["Assets", "AssetsIFRS"]
TAGS_EQUITY = [
    "EquityAttributableToOwnersOfParentIFRS",
    "NetAssets",
    "EquityIFRS",
    "EquityAttributableToOwnersOfParent",
]
TAGS_CASH = [
    "CashAndDeposits",
    "CashAndCashEquivalentsIFRS",
    "CashAndCashEquivalents",
]

# ------------------------------------------------------------------
# 発行済株式数
# 「株式等の状況」の要素を優先度順に並べる。上ほど新しい時点の値。
#   1) 提出日現在発行数    … 増資・自己株消却まで反映された最新値
#   2) 事業年度末現在発行数 … BSの基準日と揃う値
#   3) 主要な経営指標等の発行済株式総数 … 上2つが無い書類向けの保険
# 提出者独自タクソノミで拡張されている場合に取りこぼさないよう、
# 上記に一致しない場合も要素名に NumberOfIssuedShares を含むものは拾う
# （発行可能株式総数 = NumberOfAuthorizedShares... は除外する）。
# ------------------------------------------------------------------
SHARE_TAG_PRIORITY = [
    "NumberOfIssuedSharesAsOfFilingDateIssuedSharesTotalNumberOfSharesEtc",
    "NumberOfIssuedSharesAsOfFiscalYearEndIssuedSharesTotalNumberOfSharesEtc",
    "TotalNumberOfIssuedSharesSummaryOfBusinessResults",
]

# 常識外れの株数を弾くための範囲。上場企業の発行済株式数は最低でも数万株ある。
MIN_PLAUSIBLE_SHARES = 10_000
MAX_PLAUSIBLE_SHARES = 100_000_000_000


def get_edinet_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }


def request_with_retry(url, params=None, headers=None, retries=3, backoff_factor=1.0):
    for i in range(retries):
        try:
            res = requests.get(url, params=params, headers=headers, timeout=15)
            if res.status_code == 200:
                return res
            logger.warning(f"HTTP {res.status_code}: {url} (Attempt {i+1}/{retries})")
        except Exception as e:
            logger.warning(f"通信エラー ({e}): {url} (Attempt {i+1}/{retries})")
        time.sleep(backoff_factor * (2 ** i))
    return None


def get_submitted_documents(date_str):
    url = "https://disclosure.edinet-fsa.go.jp/api/v2/documents.json"

    params = {
        "date": date_str,
        "type": 2,
        "Subscription-Key": EDINET_API_KEY
    }
    headers = get_edinet_headers()

    res = request_with_retry(url, params=params, headers=headers)

    if not res or res.status_code != 200:
        return []

    try:
        data = res.json()
        metadata = data.get("metadata", {})
        status = metadata.get("status")
        results = data.get("results", [])

        if status != "200":
            return []

        docs = []
        target_doc_types = {"120", "130", "140", "150", "160", "170"}

        for doc in results:
            doc_type = str(doc.get("docTypeCode") or "").strip()
            sec_code = doc.get("secCode")

            if doc_type in target_doc_types and sec_code:
                code_4 = str(sec_code)[:4]
                docs.append({
                    "doc_id": str(doc.get("docID")).strip(),
                    "sec_code": code_4,
                    "filer_name": doc.get("filerName"),
                    "doc_type": doc_type,
                    "submit_date": date_str,
                    "submit_datetime": doc.get("submitDateTime") or f"{date_str} 00:00",
                    # ※ EDINET の periodEnd は「会計年度の期末日」であって
                    #   貸借対照表の基準日ではない。半期報告書では未来の日付が入る。
                    #   BSの基準日は XBRL のコンテキスト instant から拾う（bs_date）。
                    "period_end": doc.get("periodEnd") or ""
                })

        return docs

    except Exception as e:
        logger.error(f"[{date_str}] 書類一覧パース失敗: {e}")
        return []


def select_best_documents(raw_targets):
    """証券コードごとに1件だけ採用する。決算期が新しいものを最優先。"""
    grouped = {}
    for doc in raw_targets:
        grouped.setdefault(doc["sec_code"], []).append(doc)

    selected = []
    for code, docs in grouped.items():
        docs_sorted = sorted(
            docs,
            key=lambda x: (
                x.get("period_end") or "",
                # reverse=True でソートするため「大きい値ほど優先」になる点に注意
                (1 if x.get("doc_type") in AMENDMENT_TYPES else 0) if PREFER_AMENDMENT
                else (0 if x.get("doc_type") in AMENDMENT_TYPES else 1),
                x.get("submit_datetime") or ""
            ),
            reverse=True
        )
        selected.append(docs_sorted[0])

    return selected


def parse_clean_amount(element):
    if not element or not element.text:
        return None

    unit_ref = str(element.get("unitRef") or element.get("unitref") or "").lower()
    if unit_ref:
        invalid_units = ["day", "share", "pure", "person", "month", "year"]
        if any(bad in unit_ref for bad in invalid_units):
            return None

    text_val = element.text.strip().replace(",", "")
    try:
        val = float(text_val)
    except ValueError:
        return None

    scale = element.get("scale")
    if scale is not None:
        try:
            val = val * (10 ** int(scale))
        except ValueError:
            pass

    return int(val)


def parse_share_amount(element):
    """株数専用のパーサ。

    parse_clean_amount は unitRef に share を含む要素を弾く仕様のため、
    株数にはそのまま使えない。ここでは逆に「株単位以外」を弾く。
    """
    if not element or not element.text:
        return None

    unit_ref = str(element.get("unitRef") or element.get("unitref") or "").lower()
    if unit_ref and "share" not in unit_ref:
        return None

    text_val = element.text.strip().replace(",", "")
    try:
        val = float(text_val)
    except ValueError:
        return None

    scale = element.get("scale")
    if scale is not None:
        try:
            val = val * (10 ** int(scale))
        except ValueError:
            pass

    return int(val)


def share_tag_rank(name):
    """発行済株式数の要素かどうかを判定し、小さいほど優先度が高い値を返す。"""
    for i, tag in enumerate(SHARE_TAG_PRIORITY):
        if name == tag:
            return i
    if "NumberOfIssuedShares" in name and "Authorized" not in name:
        return len(SHARE_TAG_PRIORITY)  # 提出者独自の拡張要素
    return None


def build_context_ranks(soup):
    """
    残高科目に使える instant コンテキストへ優先順位を付ける。
      0: 当期・連結（ディメンション無し・CurrentYear）
      1: 当期・連結（四半期/半期など CurrentYear 以外の当期 instant）
      2: 当期・個別（NonConsolidatedMember のみ・CurrentYear）
      3: 当期・個別（上記以外）
    前期(Prior)・提出日時点(FilingDate)・セグメント等の内訳は採用しない。

    あわせて、各コンテキストの instant 日付も返す。これが貸借対照表の基準日で、
    EDINET の periodEnd（会計年度末）とは異なる。半期報告書では両者がずれる。
    """
    ranks = {}
    instants = {}
    has_nonconsolidated = False

    for ctx in soup.find_all(["context", "xbrli:context"]):
        ctx_id = ctx.get("id")
        if not ctx_id:
            continue

        # 連結を出している会社かどうかの判定材料（Prior も含めて走査する）
        if "NonConsolidated" in ctx_id:
            has_nonconsolidated = True

        instant_el = ctx.find(["instant", "xbrli:instant"])
        if not instant_el:
            continue  # 期間(duration)コンテキストは残高科目に使わない
        if "Prior" in ctx_id or "FilingDate" in ctx_id:
            continue

        member_count = ctx_id.count("Member")
        is_current_year = "CurrentYear" in ctx_id

        if member_count == 0:
            ranks[ctx_id] = 0 if is_current_year else 1
        elif member_count == 1 and "NonConsolidated" in ctx_id:
            ranks[ctx_id] = 2 if is_current_year else 3
        # それ以外（セグメント別・株式種類別などの内訳）は採用しない

        if ctx_id in ranks:
            instants[ctx_id] = (instant_el.text or "").strip()

    return ranks, instants, has_nonconsolidated


def build_share_contexts(soup):
    """発行済株式数用のコンテキスト表。残高科目とは別基準で作る。

    build_context_ranks との違いは2点。
      ・FilingDateInstant を除外しない（株数はむしろ提出日現在が最新）
      ・株式種類別（Member 付き）のコンテキストも採用対象に含める
        ／種類株がある会社は普通株式・優先株式などに分かれて出るため
    戻り値は ctx_id -> (優先度, instant日付)。
    """
    ctxs = {}

    for ctx in soup.find_all(["context", "xbrli:context"]):
        ctx_id = ctx.get("id")
        if not ctx_id or "Prior" in ctx_id:
            continue

        instant_el = ctx.find(["instant", "xbrli:instant"])
        if not instant_el:
            continue

        if "FilingDate" in ctx_id:
            prio = 0
        elif "CurrentYear" in ctx_id:
            prio = 1
        else:
            prio = 2

        ctxs[ctx_id] = (prio, (instant_el.text or "").strip())

    return ctxs


def extract_shares_outstanding(soup, share_ctxs, sec_code):
    """発行済株式数を1つ選んで (株数, 基準日, 採用した要素名) を返す。

    優先順位は (要素の優先度, コンテキストの優先度, 株数の降順)。
    株数の降順にしているのは、種類株ごとに複数行ある場合に
    「計」の行が最大値になるため。
    """
    best_key = None
    best = (None, "", None)

    for el in soup.find_all(True):
        rank = share_tag_rank(el.name)
        if rank is None:
            continue

        ctx_id = el.get("contextRef") or el.get("contextref") or ""
        ctx_info = share_ctxs.get(ctx_id)
        if ctx_info is None:
            continue

        val = parse_share_amount(el)
        if val is None or val <= 0:
            continue

        prio, ctx_date = ctx_info
        key = (rank, prio, -val)
        if best_key is None or key < best_key:
            best_key = key
            best = (val, ctx_date, el.name)

    shares, as_of, tag = best

    if shares is None:
        return None, "", None

    if not (MIN_PLAUSIBLE_SHARES <= shares <= MAX_PLAUSIBLE_SHARES):
        # 千株単位でタグ付けされている等の異常値。時価総額を数百倍ずらすので捨てる。
        logger.warning(f"[{sec_code}] 発行済株式数が範囲外のため破棄 (shares={shares}, tag={tag})")
        return None, "", None

    return shares, as_of, tag


def fetch_xbrl_data(doc_id, sec_code):
    url = f"https://disclosure.edinet-fsa.go.jp/api/v2/documents/{doc_id}"

    params = {
        "type": 1,
        "Subscription-Key": EDINET_API_KEY
    }
    headers = get_edinet_headers()

    try:
        res = request_with_retry(url, params=params, headers=headers)
        if not res or res.status_code != 200:
            return None

        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            xbrl_filename = next(
                (name for name in z.namelist() if name.endswith(".xbrl") and "PublicDoc" in name),
                None
            )
            if not xbrl_filename:
                return None

            with z.open(xbrl_filename) as f:
                soup = BeautifulSoup(f.read(), "lxml-xml")
                ctx_ranks, ctx_instants, has_nonconsolidated = build_context_ranks(soup)

                if not ctx_ranks:
                    soup.decompose()
                    return None

                def get_tag_value(tag_names):
                    """優先順位が最も高いコンテキストの値 -> (値, rank, タグ名, コンテキストID)"""
                    for tag in tag_names:
                        best = None
                        for el in soup.find_all(lambda e: e.name == tag):
                            ctx_id = el.get("contextRef") or ""
                            rank = ctx_ranks.get(ctx_id)
                            if rank is None:
                                continue
                            val = parse_clean_amount(el)
                            if val is None:
                                continue
                            if best is None or rank < best[0]:
                                best = (rank, val, ctx_id)
                                if rank == 0:
                                    break
                        if best is not None:
                            return best[1], best[0], tag, best[2]
                    return None, None, None, None

                ca_val, ca_rank, ca_tag, ca_ctx = get_tag_value(TAGS_CURRENT_ASSETS)
                tl_val, _, tl_tag, _ = get_tag_value(TAGS_TOTAL_LIABILITIES)
                ta_val, _, ta_tag, ta_ctx = get_tag_value(TAGS_TOTAL_ASSETS)
                eq_val, _, eq_tag, _ = get_tag_value(TAGS_EQUITY)
                cash_val, _, _, _ = get_tag_value(TAGS_CASH)

                # 発行済株式数。取れなくても財務データ自体は使えるので、
                # ここでの失敗は None を入れるだけにして書類は捨てない。
                share_ctxs = build_share_contexts(soup)
                shares_val, shares_as_of, shares_tag = extract_shares_outstanding(
                    soup, share_ctxs, sec_code
                )

                # 貸借対照表の基準日。流動資産を採ったコンテキストを第一候補にする。
                bs_date = ctx_instants.get(ca_ctx) or ctx_instants.get(ta_ctx) or ""

                used_tags = [t for t in (ca_tag, tl_tag, ta_tag, eq_tag) if t]
                accounting_std = "IFRS" if any(t.endswith("IFRS") for t in used_tags) else "J-GAAP"

                # 連結・個別の判定
                # 個別しか出していない会社には NonConsolidatedMember 自体が付かないため、
                # 「NonConsolidated コンテキストが存在する会社の、ディメンション無しの値」を連結とみなす。
                consolidated = bool(has_nonconsolidated) and ca_rank is not None and ca_rank <= 1

                soup.decompose()

                if None in (ca_val, tl_val, ta_val, eq_val):
                    return None
                if ta_val <= 0:
                    return None

                # 整合性チェック：科目の取り違えを検知して捨てる
                if ca_val > ta_val * 1.05:
                    logger.warning(f"[{sec_code}] 流動資産 > 総資産 のため破棄 (ca={ca_val}, ta={ta_val})")
                    return None
                if tl_val > ta_val * 1.05:
                    logger.warning(f"[{sec_code}] 負債 > 総資産 のため破棄 (tl={tl_val}, ta={ta_val})")
                    return None
                if eq_val > ta_val * 1.05:
                    logger.warning(f"[{sec_code}] 純資産 > 総資産 のため破棄 (eq={eq_val}, ta={ta_val})")
                    return None

                # 株数の妥当性は BPS で見る。1株純資産が 1円未満・100万円超なら
                # 桁がおかしい可能性が高いので、値は残しつつ警告だけ出す。
                if shares_val:
                    bps = eq_val / shares_val
                    if not (1.0 <= bps <= 1_000_000.0):
                        logger.warning(
                            f"[{sec_code}] BPSが異常 (bps={bps:.2f}, shares={shares_val}, tag={shares_tag})"
                        )

                # 自己資本比率は「％」で保存する（下流で単位を推測しないため）
                equity_ratio = round(eq_val / ta_val * 100.0, 2)

                return {
                    "current_assets": ca_val,
                    "total_liabilities": tl_val,
                    "total_assets": ta_val,
                    "equity_value": eq_val,
                    "equity_type": eq_tag or "Unknown",
                    "equity_ratio": equity_ratio,
                    "cash_and_equivalents": cash_val,
                    "shares_outstanding": shares_val,
                    "shares_as_of": shares_as_of,
                    "shares_source": shares_tag,
                    "consolidated": consolidated,
                    "accounting_standard": accounting_std,
                    "bs_date": bs_date
                }

    except Exception as e:
        logger.error(f"[{sec_code}] XBRL解析例外 (doc_id={doc_id}): {e}")

    return None


def main():
    parser = argparse.ArgumentParser(description="EDINET Financial Cache Updater")
    parser.add_argument("--full", action="store_true", help="Run full scan for past 365 days of EDINET filings")
    args = parser.parse_args()

    logger.info("=== 財務キャッシュ更新処理を開始します ===")

    if not EDINET_API_KEY:
        logger.error("❌ ERROR: EDINET_API_KEY が設定されていません。環境変数を確認してください。")
        sys.exit(1)

    columns = [
        "sec_code", "filer_name", "current_assets", "total_liabilities",
        "total_assets", "equity_value", "equity_type", "equity_ratio",
        "cash_and_equivalents", "shares_outstanding", "shares_as_of",
        "shares_source", "doc_id", "submit_date", "doc_type",
        "accounting_standard", "consolidated", "fiscal_period", "bs_date"
    ]

    DTYPE_SPEC = {
        "sec_code": "string",
        "filer_name": "string",
        "equity_type": "string",
        "shares_as_of": "string",
        "shares_source": "string",
        "doc_id": "string",
        "submit_date": "string",
        "doc_type": "string",
        "accounting_standard": "string",
        "consolidated": "string",
        "fiscal_period": "string",
        "bs_date": "string",
    }

    NUMERIC_COLS = [
        "current_assets", "total_liabilities", "total_assets",
        "equity_value", "equity_ratio", "cash_and_equivalents",
        "shares_outstanding"
    ]

    if os.path.exists(CACHE_FILE):
        try:
            df_cache = pd.read_csv(CACHE_FILE, dtype=DTYPE_SPEC)
            df_cache = df_cache.drop_duplicates(subset=["sec_code"], keep="last").set_index("sec_code")

            for col in DTYPE_SPEC.keys():
                if col != "sec_code" and col in df_cache.columns:
                    df_cache[col] = df_cache[col].astype("string")

            for col in NUMERIC_COLS:
                if col in df_cache.columns:
                    df_cache[col] = pd.to_numeric(df_cache[col], errors="coerce")

        except Exception as e:
            logger.warning(f"キャッシュ読み込み失敗: {e}")
            df_cache = pd.DataFrame(columns=columns).set_index("sec_code")
    else:
        df_cache = pd.DataFrame(columns=columns).set_index("sec_code")

    # 新設列（cash_and_equivalents, bs_date, shares_* など）が無い旧キャッシュへの追随
    for col in columns:
        if col != "sec_code" and col not in df_cache.columns:
            df_cache[col] = pd.NA

    cached_doc_ids = set()
    if os.path.exists(PROCESSED_FILE):
        try:
            df_proc = pd.read_csv(PROCESSED_FILE, dtype={"doc_id": str})
            cached_doc_ids = set(df_proc["doc_id"].dropna().str.strip())
        except Exception:
            pass

    if "doc_id" in df_cache.columns:
        cached_doc_ids.update(df_cache["doc_id"].dropna().astype(str).str.strip().tolist())

    df_new = df_cache.copy()
    raw_targets = []

    today = datetime.now(JST)
    scan_days = 365 if args.full else 5
    logger.info(f"[モード: {'フルスキャン (過去365日分)' if args.full else '差分スキャン (過去5日分)'}] 書類一覧を検索中...")

    for i in range(scan_days):
        target_date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        docs = get_submitted_documents(target_date)
        raw_targets.extend(docs)
        time.sleep(0.05)

    unique_targets = select_best_documents(raw_targets)
    total_targets = len(unique_targets)
    logger.info(f"処理対象企業数 (最適書類抽出後): {total_targets} 件")

    success_count = 0
    fail_count = 0
    skip_count = 0
    no_shares_count = 0

    for idx, doc in enumerate(unique_targets, 1):
        sec_code = doc["sec_code"]
        doc_id = str(doc["doc_id"]).strip()

        if idx % 100 == 0 or idx == total_targets:
            logger.info(f"⏳ 進捗: [{idx}/{total_targets}] (新規成功: {success_count}, 既処理スキップ: {skip_count}, 解析失敗: {fail_count})")

        if doc_id in cached_doc_ids:
            skip_count += 1
            continue

        try:
            fin = fetch_xbrl_data(doc_id, sec_code)
            if fin:
                if not fin["shares_outstanding"]:
                    no_shares_count += 1
                    logger.info(f"[{sec_code}] 発行済株式数を取得できませんでした (doc_id={doc_id})")

                df_new.loc[sec_code] = {
                    "filer_name": doc["filer_name"],
                    "current_assets": fin["current_assets"],
                    "total_liabilities": fin["total_liabilities"],
                    "total_assets": fin["total_assets"],
                    "equity_value": fin["equity_value"],
                    "equity_type": fin["equity_type"],
                    "equity_ratio": fin["equity_ratio"],
                    "cash_and_equivalents": fin["cash_and_equivalents"],
                    "shares_outstanding": fin["shares_outstanding"],
                    "shares_as_of": fin["shares_as_of"],
                    "shares_source": fin["shares_source"],
                    "doc_id": doc_id,
                    "submit_date": doc["submit_date"],
                    "doc_type": doc["doc_type"],
                    "accounting_standard": fin["accounting_standard"],
                    "consolidated": "連結" if fin["consolidated"] else "個別",
                    "fiscal_period": doc["period_end"],
                    "bs_date": fin["bs_date"]
                }
                cached_doc_ids.add(doc_id)
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            logger.error(f"[{sec_code}] 処理エラー: {e}")
            fail_count += 1

        time.sleep(0.1)

    logger.info(f"解析完了 - 新規取得: {success_count}件 / スキップ: {skip_count}件 / 失敗: {fail_count}件")
    if success_count:
        logger.info(f"うち発行済株式数が取れなかった件数: {no_shares_count}件")

    df_new = df_new.reset_index()

    # 中身が同じでも、列構成が変わっていれば書き出す。
    # 新設列（bs_date など）を追加した直後に新規取得が0件だと、
    # equals() が真になって列の追加が永久にファイルへ反映されないため。
    df_old = df_cache.reset_index()
    schema_changed = list(df_old.columns) != list(df_new.columns)
    if not os.path.exists(CACHE_FILE) or schema_changed or not df_old.equals(df_new):
        df_new.to_csv(CACHE_FILE, index=False, encoding="utf-8-sig")
        logger.info(f"🎉 財務キャッシュ ({CACHE_FILE}) を更新しました。")

    pd.DataFrame({"doc_id": list(cached_doc_ids)}).to_csv(PROCESSED_FILE, index=False, encoding="utf-8-sig")
    logger.info(f"💾 処理済みリスト ({PROCESSED_FILE}) を更新しました。")

    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()


if __name__ == "__main__":
    main()
    sys.exit(0)
