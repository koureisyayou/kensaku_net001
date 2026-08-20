"""
地方市場（名証）版ネットネット候補ページの生成。

  入力: net_net_candidates_local.csv （無ければ local_prices.csv にフォールバック）
  出力: local.html

東証版とは流動性の桁が違い、数字の読み方も変わるため、ページを分けて
注意書きを冒頭に固定表示する。
"""

import os
import sys
import html as html_lib
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

PRIMARY_INPUT = "net_net_candidates_local.csv"
FALLBACK_INPUT = "local_prices.csv"
HTML_FILE = "local.html"

# 表示する列の定義（存在する列だけを描画する）
COLUMN_SPECS = [
    ("sec_code",         "コード",        "code"),
    ("name",             "銘柄名",        "text"),
    ("company_name",     "銘柄名",        "text"),
    ("market",           "市場",          "text"),
    ("price",            "株価 (円)",     "price"),
    ("price_date",       "約定日",        "text"),
    ("days_since_trade", "経過営業日",    "stale"),
    ("traded_days_20",   "約定日数/20",   "int"),
    ("avg_turnover_20",  "平均売買代金",  "man"),
    ("market_cap",       "時価総額 (億円)", "oku"),
    ("ncav",             "NCAV (億円)",   "oku"),
    ("nc_ratio",         "NCAV / 時価総額", "ratio"),
    ("equity_ratio",     "自己資本比率",  "percent"),
    ("fiscal_period",    "決算期",        "text"),
]

NOTES = [
    ("流動性が東証とは2桁違います",
     "名証単独上場銘柄は1日の売買代金が数十万円程度のことも珍しくありません。"
     "画面上の株価で売買が成立する保証はなく、数百株の注文で値が飛ぶ場合があります。"),
    ("約定のない銘柄は掲載していません",
     "集計期間内に一度も売買が成立していない銘柄は、気配値しか存在しないため非表示にしています。"
     "名証の上場銘柄の大半は東証との重複上場で、名証では売買が成立しません。"),
    ("株価は「最後に約定した終値」です",
     "気配値は採用していません。経過営業日が大きい銘柄は、その価格が現在の実勢から"
     "離れている可能性があります。"),
    ("売買不成立の日が常態です",
     "約定日数が20日中1〜2日という銘柄が多数あります。約定日数の少ない銘柄ほど、"
     "平均売買代金もNCAV倍率も参考程度に見てください。"),
    ("監理・整理銘柄を含みます",
     "名証の相場表に監理・整理の区画がある銘柄にはフラグを立てています。"
     "上場廃止に向かう銘柄はネットネット指標が良く見えがちです。"),
    ("財務データは決算日時点のものです",
     "決算後の増資・大型投資・業績悪化は反映されていません。"
     "候補はあくまで一次抽出であり、投資判断の前に必ず有価証券報告書を確認してください。"),
]


def fmt(value, kind):
    if pd.isnull(value):
        return "-"
    try:
        if kind == "oku":
            return f"{float(value) / 1e8:,.2f}"
        if kind == "man":
            return f"{float(value) / 1e4:,.0f} 万円"
        if kind == "price":
            return f"{float(value):,.1f}"
        if kind == "ratio":
            return f"{float(value):,.2f} 倍"
        if kind == "percent":
            v = float(value)
            if 0 < v <= 1.0:
                v *= 100
            return f"{v:,.1f}%"
        if kind in ("int", "stale"):
            return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return "-"
    return html_lib.escape(str(value))


def build_rows(df, specs):
    out = []
    for _, r in df.iterrows():
        cells = []
        for col, _label, kind in specs:
            value = r.get(col)
            text = html_lib.escape(str(value)) if kind in ("code", "text") and pd.notnull(value) else fmt(value, kind)
            if kind == "code":
                cells.append(f'<td><strong>{text}</strong></td>')
            elif kind == "text":
                cells.append(f"<td>{text if pd.notnull(value) else '-'}</td>")
            elif kind == "ratio":
                cells.append(f'<td class="num highlight">{text}</td>')
            elif kind == "stale":
                cls = "num warn" if pd.notnull(value) and float(value) >= 5 else "num"
                cells.append(f'<td class="{cls}">{text}</td>')
            else:
                cells.append(f'<td class="num">{text}</td>')

        flag = ""
        if bool(r.get("is_supervised", False)):
            flag = '<span class="badge">監理・整理</span>'
        cells.append(f"<td>{flag}</td>")
        out.append("            <tr>\n                " + "\n                ".join(cells) + "\n            </tr>")
    return "\n".join(out)


def generate():
    if os.path.exists(PRIMARY_INPUT):
        source, note = PRIMARY_INPUT, None
    elif os.path.exists(FALLBACK_INPUT):
        source = FALLBACK_INPUT
        note = "NCAV判定前の流動性データを表示しています（発行済株式数の取得が未実装のため）。"
    else:
        print(f"Error: {PRIMARY_INPUT} も {FALLBACK_INPUT} も見つかりません。")
        sys.exit(1)

    df = pd.read_csv(source, dtype={"sec_code": str})
    total = len(df)
    print(f"{source} を読み込みました: {total}件")

    # 集計期間内に一度も約定していない銘柄は掲載しない。
    # 気配値しか無い銘柄を並べても、その値段で売買できる根拠がないため。
    hidden = 0
    if "traded_days_20" in df.columns:
        keep = df["traded_days_20"].fillna(0) > 0
        if "price" in df.columns:
            keep &= df["price"].notnull()
        hidden = int((~keep).sum())
        df = df[keep].copy()
    elif "price" in df.columns:
        hidden = int(df["price"].isnull().sum())
        df = df[df["price"].notnull()].copy()

    if hidden:
        print(f"約定のない {hidden} 銘柄を非表示にしました。残り {len(df)}件")

    # 銘柄名の列は name / company_name のどちらか一方だけを使う
    specs = [s for s in COLUMN_SPECS if s[0] in df.columns]
    if any(s[0] == "company_name" for s in specs):
        specs = [s for s in specs if s[0] != "name"]

    as_of = df["as_of"].dropna().iloc[0] if "as_of" in df.columns and df["as_of"].notnull().any() else "-"
    window = df["window_days"].dropna().iloc[0] if "window_days" in df.columns and df["window_days"].notnull().any() else None
    updated_at = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M")

    warm_up = ""
    if window is not None and int(window) < 20:
        warm_up = (f'<div class="warmup">⚠ 流動性の集計に使えた営業日は <strong>{int(window)}日</strong> です'
                   f'（本来は20営業日）。蓄積が進むまで、約定日数と平均売買代金は過小評価になります。</div>')

    fallback_note = f'<div class="warmup">{html_lib.escape(note)}</div>' if note else ""

    notes_html = "\n".join(
        f"            <li><strong>{html_lib.escape(t)}</strong><br>{html_lib.escape(b)}</li>"
        for t, b in NOTES
    )
    headers = "\n".join(
        f'                <th class="num">{html_lib.escape(label)}</th>' if kind not in ("code", "text")
        else f'                <th>{html_lib.escape(label)}</th>'
        for _col, label, kind in specs
    )

    hidden_note = f" | 非表示: {hidden} 銘柄（期間内に約定なし）" if hidden else ""
    empty_note = ('<div class="warmup">この期間に約定のあった銘柄がありません。'
                  '相場表の蓄積が進むまでお待ちください。</div>') if df.empty else ""

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Net-Net Stock Screener - 地方市場版（名証）</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background: #f8f9fa; color: #333; }}
        h1 {{ color: #1a252f; border-bottom: 2px solid #7b3f00; padding-bottom: 10px; }}
        .meta {{ margin-bottom: 16px; color: #666; font-size: 0.9em; }}
        .nav a {{ color: #2c3e50; text-decoration: none; border: 1px solid #ccc; padding: 6px 12px; border-radius: 4px; background: #fff; font-size: 0.9em; }}
        .nav {{ margin-bottom: 16px; }}
        .caution {{ background: #fff8e6; border: 1px solid #e0c068; border-left: 6px solid #b8860b; padding: 14px 18px; margin-bottom: 20px; border-radius: 4px; }}
        .caution h2 {{ margin: 0 0 10px; font-size: 1.05em; color: #7b3f00; }}
        .caution ul {{ margin: 0; padding-left: 20px; }}
        .caution li {{ margin-bottom: 10px; font-size: 0.9em; line-height: 1.6; }}
        .warmup {{ background: #eef4fb; border: 1px solid #b7cbe4; padding: 10px 14px; margin-bottom: 16px; border-radius: 4px; font-size: 0.9em; }}
        .wrap {{ overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #ddd; white-space: nowrap; }}
        th {{ background: #5a4632; color: #fff; position: sticky; top: 0; }}
        tr:hover {{ background: #f5f2ed; }}
        .num {{ text-align: right; font-family: monospace; }}
        .highlight {{ font-weight: bold; color: #27ae60; }}
        .warn {{ color: #c0392b; font-weight: bold; }}
        .badge {{ background: #c0392b; color: #fff; padding: 2px 8px; border-radius: 3px; font-size: 0.8em; }}
        footer {{ margin-top: 24px; color: #888; font-size: 0.8em; line-height: 1.6; }}
    </style>
</head>
<body>
    <h1>Net-Net Stock Screener｜地方市場版（名証）</h1>
    <div class="nav"><a href="index.html">&larr; 東証版に戻る</a></div>
    <div class="meta">
        掲載件数: <strong>{len(df)}</strong> 銘柄 |
        相場日: {html_lib.escape(str(as_of))} |
        ページ更新: {updated_at} (JST){hidden_note}
    </div>

    <div class="caution">
        <h2>このページの数字を読む前に</h2>
        <ul>
{notes_html}
        </ul>
    </div>
{warm_up}
{fallback_note}
{empty_note}
    <div class="wrap">
    <table>
        <thead>
            <tr>
{headers}
                <th>フラグ</th>
            </tr>
        </thead>
        <tbody>
{build_rows(df, specs)}
        </tbody>
    </table>
    </div>

    <footer>
        株価・売買高の出所: 名古屋証券取引所「株式相場表（速報）」<br>
        財務データの出所: 金融庁 EDINET<br>
        本ページは個人が自動生成しているものであり、投資勧誘を目的としたものではありません。掲載内容の正確性は保証されません。
    </footer>
</body>
</html>
"""

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"{HTML_FILE} を作成しました。({len(df)} 銘柄)")


if __name__ == "__main__":
    generate()
