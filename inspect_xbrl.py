"""inspect_xbrl.py

指定した証券コードの最新XBRLを取得し、財務タグの中身をそのまま表示する診断用スクリプト。
既存のCSVには一切書き込まない。読み取り専用。

使い方:
    python inspect_xbrl.py 7203
    python inspect_xbrl.py 7203 8001 6758      # 複数まとめて
    python inspect_xbrl.py 7203 --days 400     # 検索する日数を変える

出力されるもの:
    1) 名前空間ごとの要素数（jppfs_cor=日本基準 / jpigp_cor=IFRS のどちらが入っているか）
    2) 資産・負債・純資産系のタグを、名前空間・値・コンテキスト付きで全部列挙
    3) いま update_financials.py が採用するはずの値（同じロジックを再現）
"""

import os
import sys
import io
import time
import zipfile
import argparse
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
EDINET_API_KEY = os.environ.get("EDINET_API_KEY", "")

# update_financials.py と同じ定義（比較のため）
TAGS_CURRENT_ASSETS = ["CurrentAssets", "CurrentAssetsIFRS", "AssetsCurrent"]
TAGS_TOTAL_LIABILITIES = ["Liabilities", "LiabilitiesIFRS"]
TAGS_TOTAL_ASSETS = ["Assets", "AssetsIFRS"]
TAGS_EQUITY = [
    "EquityAttributableToOwnersOfParentIFRS",
    "NetAssets",
    "EquityIFRS",
    "EquityAttributableToOwnersOfParent",
]

# 表示対象にする要素名。前方一致で拾う。
INTERESTING_PREFIXES = (
    "Assets", "Liabilities", "NetAssets", "Equity",
    "CurrentAssets", "CurrentLiabilities",
)


def headers():
    return {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def get(url, params=None, retries=3):
    for i in range(retries):
        try:
            res = requests.get(url, params=params, headers=headers(), timeout=30)
            if res.status_code == 200:
                return res
            print(f"  HTTP {res.status_code} ({i+1}/{retries})")
        except Exception as e:
            print(f"  通信エラー {e} ({i+1}/{retries})")
        time.sleep(2 ** i)
    return None


def find_latest_doc(sec_code, days):
    """指定コードの最新の有報等を探して doc_id を返す。"""
    target_types = {"120", "140", "160"}  # 有報・四半期・半期（訂正は除く）
    today = datetime.now(JST)
    found = []

    print(f"[{sec_code}] 過去{days}日分の書類一覧を検索中...")
    for i in range(days):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        res = get("https://disclosure.edinet-fsa.go.jp/api/v2/documents.json",
                  params={"date": date_str, "type": 2,
                          "Subscription-Key": EDINET_API_KEY})
        if not res:
            continue
        try:
            data = res.json()
        except Exception:
            continue
        for doc in data.get("results", []):
            code = str(doc.get("secCode") or "")[:4]
            dtype = str(doc.get("docTypeCode") or "").strip()
            if code == str(sec_code) and dtype in target_types:
                found.append({
                    "doc_id": str(doc.get("docID")).strip(),
                    "doc_type": dtype,
                    "submit": doc.get("submitDateTime") or date_str,
                    "period_end": doc.get("periodEnd") or "",
                    "filer": doc.get("filerName"),
                })
        if found:
            break  # 新しい日付から探しているので最初に見つかったものが最新
        time.sleep(0.05)

    if not found:
        print(f"[{sec_code}] 書類が見つかりませんでした。--days を増やしてください。")
        return None

    found.sort(key=lambda x: x["submit"], reverse=True)
    d = found[0]
    print(f"[{sec_code}] {d['filer']} / doc_id={d['doc_id']} "
          f"/ 種別={d['doc_type']} / 提出={d['submit']} / 会計期末={d['period_end']}")
    return d["doc_id"]


def fetch_soup(doc_id):
    res = get(f"https://disclosure.edinet-fsa.go.jp/api/v2/documents/{doc_id}",
              params={"type": 1, "Subscription-Key": EDINET_API_KEY})
    if not res:
        return None
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        name = next((n for n in z.namelist()
                     if n.endswith(".xbrl") and "PublicDoc" in n), None)
        if not name:
            print("  PublicDoc の .xbrl が見つかりません")
            return None
        print(f"  XBRLファイル: {name}")
        with z.open(name) as f:
            return BeautifulSoup(f.read(), "lxml-xml")


def fmt(n):
    """円を読みやすい単位に。"""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return str(n)
    for unit, div in (("兆", 1e12), ("億", 1e8), ("万", 1e4)):
        if abs(v) >= div:
            return f"{v/div:,.2f}{unit}円"
    return f"{v:,.0f}円"


def amount(el):
    unit = str(el.get("unitRef") or "").lower()
    if unit and any(b in unit for b in ["day", "share", "pure", "person", "month", "year"]):
        return None
    try:
        v = float((el.text or "").strip().replace(",", ""))
    except (ValueError, AttributeError):
        return None
    scale = el.get("scale")
    if scale is not None:
        try:
            v = v * (10 ** int(scale))
        except ValueError:
            pass
    return v


def inspect(sec_code, days):
    print("=" * 78)
    doc_id = find_latest_doc(sec_code, days)
    if not doc_id:
        return

    soup = fetch_soup(doc_id)
    if soup is None:
        return

    # --- 1) 名前空間の分布 ---------------------------------------------
    print("\n--- 名前空間ごとの要素数 ---")
    ns_count = {}
    for el in soup.find_all(True):
        p = el.prefix or "(なし)"
        ns_count[p] = ns_count.get(p, 0) + 1
    for p, c in sorted(ns_count.items(), key=lambda x: -x[1])[:12]:
        note = ""
        if p == "jppfs_cor":
            note = "  ← 日本基準"
        elif p == "jpigp_cor":
            note = "  ← IFRS"
        print(f"  {p:20s} {c:6d}{note}")

    # --- 2) 資産・負債・純資産系のタグを全部出す -----------------------
    print("\n--- 資産・負債・純資産系タグの一覧 ---")
    print("  （同じ項目が名前空間違いで複数あるかを見る）")
    rows = []
    for el in soup.find_all(True):
        name = el.name
        if not name.startswith(INTERESTING_PREFIXES):
            continue
        ctx = el.get("contextRef") or ""
        # 内訳（セグメント別など）は数が多すぎるので当期の主要コンテキストに絞る
        if "Prior" in ctx:
            continue
        if ctx.count("Member") > 1:
            continue
        v = amount(el)
        if v is None:
            continue
        rows.append((el.prefix or "", name, ctx, v))

    if not rows:
        print("  該当なし")
    else:
        rows.sort(key=lambda r: (r[1], r[0], r[2]))
        print(f"  {'名前空間':<12} {'要素名':<44} {'値':>16}  コンテキスト")
        for pfx, name, ctx, v in rows:
            print(f"  {pfx:<12} {name:<44} {fmt(v):>16}  {ctx}")

    # --- 3) いまのロジックが選ぶ値 -------------------------------------
    print("\n--- 現行 update_financials.py が採用する値 ---")

    ranks = {}
    for ctx in soup.find_all(["context", "xbrli:context"]):
        cid = ctx.get("id")
        if not cid:
            continue
        inst = ctx.find(["instant", "xbrli:instant"])
        if not inst:
            continue
        if "Prior" in cid or "FilingDate" in cid:
            continue
        mc = cid.count("Member")
        cy = "CurrentYear" in cid
        if mc == 0:
            ranks[cid] = 0 if cy else 1
        elif mc == 1 and "NonConsolidated" in cid:
            ranks[cid] = 2 if cy else 3

    def pick(tag_names):
        for tag in tag_names:
            best = None
            for el in soup.find_all(lambda e: e.name == tag):
                cid = el.get("contextRef") or ""
                r = ranks.get(cid)
                if r is None:
                    continue
                v = amount(el)
                if v is None:
                    continue
                if best is None or r < best[0]:
                    best = (r, v, cid, el.prefix or "")
            if best is not None:
                return tag, best[1], best[2], best[3]
        return None, None, None, None

    picked = {}
    for label, tags in (("流動資産", TAGS_CURRENT_ASSETS),
                        ("総負債", TAGS_TOTAL_LIABILITIES),
                        ("総資産", TAGS_TOTAL_ASSETS),
                        ("純資産", TAGS_EQUITY)):
        tag, v, ctx, pfx = pick(tags)
        picked[label] = (pfx, v)
        if tag is None:
            print(f"  {label:<6} 取得できず")
        else:
            print(f"  {label:<6} {pfx}:{tag}  = {fmt(v)}   ctx={ctx}")

    # --- 4) 判定 --------------------------------------------------------
    print("\n--- 判定 ---")
    prefixes = {lbl: p for lbl, (p, v) in picked.items() if p}
    uniq = set(prefixes.values())
    if len(uniq) > 1:
        print(f"  ⚠ 名前空間が混在しています: {prefixes}")
        print("    → 分子と分母が別の会計体系から取られています（これが不整合の原因）")
    elif uniq:
        print(f"  名前空間は統一されています: {uniq.pop()}")

    ta = picked.get("総資産", (None, None))[1]
    eq = picked.get("純資産", (None, None))[1]
    if ta and eq and eq > ta:
        print(f"  ⚠ 純資産({fmt(eq)}) > 総資産({fmt(ta)}) — この書類は現行ロジックで破棄されます")

    soup.decompose()
    print()


def main():
    ap = argparse.ArgumentParser(description="EDINET XBRL の中身を覗く診断ツール")
    ap.add_argument("sec_codes", nargs="+", help="証券コード（4桁）")
    ap.add_argument("--days", type=int, default=400, help="書類一覧をさかのぼる日数")
    args = ap.parse_args()

    if not EDINET_API_KEY:
        print("EDINET_API_KEY が設定されていません。")
        sys.exit(1)

    for code in args.sec_codes:
        inspect(code, args.days)


if __name__ == "__main__":
    main()
