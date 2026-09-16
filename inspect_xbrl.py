"""inspect_xbrl.py

指定した証券コードの最新XBRLを取得し、財務タグの中身をそのまま表示する診断用スクリプト。
既存のCSVには一切書き込まない。読み取り専用。

使い方:
    python inspect_xbrl.py 7203
    python inspect_xbrl.py 7203 8001 6758      # 複数まとめて
    python inspect_xbrl.py 7203 --days 400     # 検索する日数を変える
    python inspect_xbrl.py 3133 --doc-type 160 # 半期報告書だけを探す（最新の有報を飛ばす）

出力されるもの:
    1) 名前空間ごとの要素数（jppfs_cor=日本基準 / jpigp_cor=IFRS のどちらが入っているか）
    2) 資産・負債・純資産・現金系のタグを、名前空間・値・コンテキスト付きで全部列挙
    3) いま update_financials.py が採用するはずの値（同じロジックを再現）
    4) 判定
    5) 継続企業の前提（GC）に関係する要素の一覧
    6) 本文に「継続企業の前提」を含む文章要素の一覧（重要事象等の確認用）

5) を別の節にしている理由:
    2) は amount() で数値に変換できない要素を捨てている。GC注記は
    文章（テキストブロック）で開示されるため、INTERESTING_PREFIXES に
    足すだけでは表示されない。2) の挙動を変えると既存の診断結果が
    変わるので、GC だけを別に走査する。
    要素名は未確認のため、完全一致ではなく「GoingConcern を含む」で拾う。
    コンテキストでも絞らない（どのコンテキストに付くかも未確認のため）。

6) を足した理由:
    「重要事象等」（注記には至らないが継続企業の前提に重要な疑義がある状態）は、
    有価証券報告書では「事業等のリスク」などの文章の中に書かれる。
    専用の要素があるかどうかは未確認のため、要素名ではなく本文で探す。
    ここで専用の要素が見つからなければ、取得には本文の検索が必要になる。
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

# EDINET API のホスト。
# disclosure.edinet-fsa.go.jp は画面用のホストで、API を叩いても
# 「規定外操作が行われました」という HTML が返るだけになる。
# API を使うときは必ずこちら。update_financials.py / enrich_pl.py も同じ。
EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"

# update_financials.py と同じ定義（比較のため）
TAGS_CURRENT_ASSETS = ["CurrentAssets", "CurrentAssetsIFRS", "AssetsCurrent"]
TAGS_TOTAL_LIABILITIES = ["Liabilities", "LiabilitiesIFRS"]
TAGS_TOTAL_ASSETS = ["Assets", "AssetsIFRS"]
TAGS_EQUITY_TOTAL = ["EquityIFRS", "NetAssets"]
TAGS_EQUITY_PARENT = [
    "EquityAttributableToOwnersOfParentIFRS",
    "EquityAttributableToOwnersOfParent",
    "ShareholdersEquity",
]
TAGS_CASH_BS = ["CashAndDeposits"]
TAGS_CASH_CF = ["CashAndCashEquivalentsIFRS", "CashAndCashEquivalents"]

# 表示対象にする要素名。前方一致で拾う。
# Cash を入れているのは、IFRS企業で現金がどの要素名で出ているかを探すため。
INTERESTING_PREFIXES = (
    "Assets", "Liabilities", "NetAssets", "Equity",
    "CurrentAssets", "CurrentLiabilities",
    "Cash",
)

# 継続企業の前提に関係する要素を拾うためのキーワード（部分一致）。
# 5) の節だけで使う。
GC_KEYWORD = "GoingConcern"

# 5) で表示する本文の先頭文字数。全文を出すとログが読めなくなる。
GC_PREVIEW_CHARS = 120

# 6) で本文から探す語。
GC_PHRASE = "継続企業の前提"

# 6) で、見つかった位置の前後に表示する文字数。
GC_CONTEXT_CHARS = 60


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


# 探す書類の種類の既定値。有報・四半期・半期（訂正は除く）。
DEFAULT_DOC_TYPES = ("120", "140", "160")


def find_latest_doc(sec_code, days, doc_types=DEFAULT_DOC_TYPES):
    """指定コードの最新の有報等を探して doc_id を返す。

    doc_types を絞ると、その種類の中で最新のものを返す。
    たとえば ("160",) なら、最新が有報でも、それより前の半期報告書を開ける。
    """
    target_types = set(doc_types)
    today = datetime.now(JST)
    found = []

    print(f"[{sec_code}] 過去{days}日分の書類一覧を検索中...")
    for i in range(days):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        res = get(f"{EDINET_API_BASE}/documents.json",
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
        print(f"[{sec_code}] 書類が見つかりませんでした（種別={sorted(target_types)}）。"
              "--days を増やしてください。")
        return None

    found.sort(key=lambda x: x["submit"], reverse=True)
    d = found[0]
    print(f"[{sec_code}] {d['filer']} / doc_id={d['doc_id']} "
          f"/ 種別={d['doc_type']} / 提出={d['submit']} / 会計期末={d['period_end']}")
    return d["doc_id"]


def fetch_soup(doc_id):
    res = get(f"{EDINET_API_BASE}/documents/{doc_id}",
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


def inspect_going_concern(soup):
    """継続企業の前提に関係する要素を、数値・文字列を問わず全部出す。

    要素名に GC_KEYWORD を含むものを拾う。コンテキストでは絞らない。
    文字列の場合は HTML タグを除いた本文の文字数と先頭部分を出す。
    ここでの結果を見て、enrich_pl.py での取得方法（要素の有無で判定するか、
    本文まで持つか）を決める。
    """
    print(f"\n--- 継続企業の前提（要素名に {GC_KEYWORD} を含むもの） ---")
    hits = [el for el in soup.find_all(True) if GC_KEYWORD in (el.name or "")]
    if not hits:
        print("  該当なし（この書類に該当する要素は存在しない）")
        return

    print(f"  {len(hits)} 件")
    for el in hits:
        ctx = el.get("contextRef") or el.get("contextref") or "(contextRefなし)"
        raw = (el.text or "").strip()
        # テキストブロックは中身がエスケープされたHTML。タグを除いて本文だけにする。
        body = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True) if raw else ""
        preview = body[:GC_PREVIEW_CHARS].replace("\n", " ")
        print(f"  {el.prefix or '':<12} {el.name}")
        print(f"      コンテキスト: {ctx}")
        print(f"      本文の文字数: {len(body)}")
        print(f"      先頭: {preview if preview else '(空)'}")


def inspect_going_concern_text(soup):
    """本文に GC_PHRASE を含む文章要素（TextBlock）を全部出す。

    要素名に GoingConcern を含むもの（5 で出したもの）も、区別できるよう
    印を付けて出す。本文は出現箇所の前後だけを表示する。
    「重要事象等は存在しません」と書く会社もあるので、
    該当するかどうかは表示された文を読んで判断する（ここでは判定しない）。
    """
    print(f"\n--- 本文に「{GC_PHRASE}」を含む文章要素 ---")
    hits = 0
    for el in soup.find_all(True):
        name = el.name or ""
        if not name.endswith("TextBlock"):
            continue
        raw = (el.text or "").strip()
        if not raw or GC_PHRASE not in raw:
            continue
        body = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
        positions = []
        start = 0
        while True:
            i = body.find(GC_PHRASE, start)
            if i < 0:
                break
            positions.append(i)
            start = i + len(GC_PHRASE)
        if not positions:
            continue

        hits += 1
        ctx = el.get("contextRef") or el.get("contextref") or "(contextRefなし)"
        mark = "  ※5で表示済み" if GC_KEYWORD in name else ""
        print(f"  {el.prefix or '':<12} {name}{mark}")
        print(f"      コンテキスト: {ctx}")
        print(f"      出現回数: {len(positions)}")
        for i in positions[:3]:
            a = max(0, i - GC_CONTEXT_CHARS)
            b = min(len(body), i + len(GC_PHRASE) + GC_CONTEXT_CHARS)
            print(f"      …{body[a:b]}…")
        if len(positions) > 3:
            print(f"      （残り {len(positions) - 3} 箇所は省略）")

    if hits == 0:
        print("  該当なし")


def inspect(sec_code, days, doc_types=DEFAULT_DOC_TYPES):
    print("=" * 78)
    doc_id = find_latest_doc(sec_code, days, doc_types)
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

    # --- 2) 資産・負債・純資産・現金系のタグを全部出す -----------------
    print("\n--- 資産・負債・純資産・現金系タグの一覧 ---")
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
        """本体の get_tag_value と同じく、全候補を走査してからランクで選ぶ。"""
        best = None  # (rank, order, val, ctx, prefix)
        for order, tag in enumerate(tag_names):
            for el in soup.find_all(lambda e: e.name == tag):
                cid = el.get("contextRef") or ""
                r = ranks.get(cid)
                if r is None:
                    continue
                v = amount(el)
                if v is None:
                    continue
                if best is None or (r, order) < (best[0], best[1]):
                    best = (r, order, v, cid, el.prefix or "")
        if best is None:
            return None, None, None, None
        return tag_names[best[1]], best[2], best[3], best[4]

    picked = {}
    for label, tags in (("流動資産", TAGS_CURRENT_ASSETS),
                        ("総負債", TAGS_TOTAL_LIABILITIES),
                        ("総資産", TAGS_TOTAL_ASSETS),
                        ("純資産(total)", TAGS_EQUITY_TOTAL),
                        ("純資産(parent)", TAGS_EQUITY_PARENT),
                        ("現金(BS)", TAGS_CASH_BS),
                        ("現金(CF)", TAGS_CASH_CF)):
        tag, v, ctx, pfx = pick(tags)
        picked[label] = (pfx, v)
        if tag is None:
            print(f"  {label:<14} 取得できず")
        else:
            print(f"  {label:<14} {pfx}:{tag}  = {fmt(v)}   ctx={ctx}")

    # --- 4) 判定 --------------------------------------------------------
    print("\n--- 判定 ---")
    core = ["流動資産", "総負債", "総資産", "純資産(total)"]
    prefixes = {lbl: picked[lbl][0] for lbl in core if picked.get(lbl, (None,))[0]}
    uniq = set(prefixes.values())
    if len(uniq) > 1:
        print(f"  ⚠ 本体4項目の名前空間が混在: {prefixes}")
    elif uniq:
        base = uniq.pop()
        print(f"  本体4項目の名前空間は統一: {base}")

        # 現金が本体と揃うかどうか。ここが揃わないと net_cash が計算できない。
        for lbl in ("現金(BS)", "現金(CF)"):
            ns, val = picked.get(lbl, (None, None))
            if val is None:
                print(f"  {lbl}: 取得できず")
            elif ns != base:
                print(f"  ⚠ {lbl}: 体系が本体と異なる ({ns} != {base}) → 破棄される")
            else:
                print(f"  {lbl}: 本体と同じ体系 ({ns}) → 採用される")

    ta = picked.get("総資産", (None, None))[1]
    eq = picked.get("純資産(total)", (None, None))[1]
    if ta and eq and eq > ta:
        print(f"  ⚠ 純資産({fmt(eq)}) > 総資産({fmt(ta)}) — この書類は破棄されます")

    # --- 5) 継続企業の前提 ---------------------------------------------
    inspect_going_concern(soup)

    # --- 6) 本文に「継続企業の前提」を含む文章要素 ----------------------
    inspect_going_concern_text(soup)

    soup.decompose()
    print()


def main():
    ap = argparse.ArgumentParser(description="EDINET XBRL の中身を覗く診断ツール")
    ap.add_argument("sec_codes", nargs="+", help="証券コード（4桁）")
    ap.add_argument("--days", type=int, default=400, help="書類一覧をさかのぼる日数")
    ap.add_argument("--doc-type", nargs="+", default=list(DEFAULT_DOC_TYPES),
                    choices=list(DEFAULT_DOC_TYPES),
                    help="探す書類の種類（120=有報 / 140=四半期 / 160=半期）。既定は3種すべて")
    args = ap.parse_args()

    if not EDINET_API_KEY:
        print("EDINET_API_KEY が設定されていません。")
        sys.exit(1)

    for code in args.sec_codes:
        inspect(code, args.days, tuple(args.doc_type))


if __name__ == "__main__":
    main()
