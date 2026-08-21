"""financials.py

financial_cache.csv の読み込み・正規化・妥当性チェック。

run_screener.py（東証版）と run_screener_local.py（地方版）の両方から使う。
元は run_screener.py 内にあった to_percent / safe_get / prepare_financials /
validate_financials をそのまま移設したもので、判定条件は変更していない。

移設にあたって変えたのは2点だけ:
  - validate() の除外ファイル出力先を引数にした（東証版と地方版で別ファイルに
    したいため。None を渡せば書き出さない）
  - prepare() で shares_outstanding を数値化する（地方版が時価総額の算出に使う）
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# 財務データの許容誤差（端数・単位差を吸収するための係数）
TOLERANCE = 1.05

NUMERIC_COLS = (
    "current_assets",
    "total_liabilities",
    "total_assets",
    "equity_value",
    "cash_and_equivalents",
    "shares_outstanding",
)


def load(path: str = "financial_cache.csv") -> pd.DataFrame:
    return pd.read_csv(path, dtype={"sec_code": str})


def safe_get(row, key, default=None):
    """Series から欠損に強く値を取り出す（列が存在しない場合も default を返す）"""
    if key in row.index:
        val = row[key]
        if pd.notnull(val):
            return val
    return default


def to_percent(val):
    """
    自己資本比率を％に揃える。
    update_financials.py は％で保存するようになったが、
    比率(0〜1)で保存された旧 financial_cache.csv との互換のために残している。
    キャッシュを --full で作り直した後は削除して構わない。
    """
    if pd.isnull(val):
        return None
    try:
        val = float(val)
    except (TypeError, ValueError):
        return None
    if 0 < val <= 1.0:
        return val * 100.0
    return val


def prepare(financial_df: pd.DataFrame) -> pd.DataFrame:
    """財務キャッシュの列名・単位を、以降の処理で使う形に正規化する"""

    # 社名列の正規化：financial_cache.csv は filer_name で保存されている。
    # これを company_name に写しておかないと、候補CSV・HTML・履歴から社名が消える。
    if "company_name" not in financial_df.columns and "filer_name" in financial_df.columns:
        financial_df["company_name"] = financial_df["filer_name"]
    if "company_name" not in financial_df.columns:
        financial_df["company_name"] = ""
    financial_df["company_name"] = financial_df["company_name"].fillna("")

    # 自己資本比率の単位を％に統一する。
    # ※ equity_value / total_assets からの再計算はしない。
    #    旧キャッシュには両方とも誤抽出された行が含まれており、再計算すると
    #    1,000% 超のような不正な行を復活させてしまうため。
    #    比率が欠損している行は validate で除外する。
    if "equity_ratio" not in financial_df.columns:
        financial_df["equity_ratio"] = None
    financial_df["equity_ratio"] = financial_df["equity_ratio"].apply(to_percent)

    for col in NUMERIC_COLS:
        if col in financial_df.columns:
            financial_df[col] = pd.to_numeric(financial_df[col], errors="coerce")

    return financial_df


def validate(financial_df: pd.DataFrame, invalid_path: str | None = None):
    """
    ありえない財務データを除外する。
    XBRLの科目取り違えは「自己資本比率が100%を超える」「流動資産が総資産を超える」
    といった形で表面化するので、ここで機械的に落とす。

    invalid_path に文字列を渡すと、除外した行をそのCSVへ書き出す。
    """
    df = financial_df

    for col in ("current_assets", "total_liabilities", "total_assets"):
        if col not in df.columns:
            logger.error(f"財務キャッシュに必須列 {col} がありません。")
            return df.iloc[0:0], df

    ok = (
        df["total_assets"].notnull() & (df["total_assets"] > 0)
        & df["current_assets"].notnull() & (df["current_assets"] >= 0)
        & df["total_liabilities"].notnull() & (df["total_liabilities"] >= 0)
        & (df["current_assets"] <= df["total_assets"] * TOLERANCE)
        & (df["total_liabilities"] <= df["total_assets"] * TOLERANCE)
        # 流動資産と総資産が1円単位で一致する行は、同じ数値を二重に拾っている疑いが濃い
        # （固定資産が完全にゼロの上場企業は実質存在しない）
        & (df["current_assets"] != df["total_assets"])
        & df["equity_ratio"].notnull()
        & (df["equity_ratio"] > 0)
        & (df["equity_ratio"] <= 100.0 * TOLERANCE)
    )

    # 貸借対照表の恒等式チェック：純資産は「総資産 - 総負債」を超えられない。
    # 非支配株主持分の分だけ小さくなるのは正常なので、上振れのみを弾く。
    if "equity_value" in df.columns:
        ok = ok & (
            df["equity_value"].isnull()
            | (df["equity_value"] <= (df["total_assets"] - df["total_liabilities"]) * TOLERANCE)
        )

    valid_df = df[ok].copy()
    invalid_df = df[~ok].copy()

    # 端数由来の 100.4% などを整える
    valid_df["equity_ratio"] = valid_df["equity_ratio"].clip(upper=100.0)

    if invalid_path:
        # 除外が0件でもヘッダーのみのファイルを必ず出力する。
        # ファイルが存在しないと git-auto-commit-action の file_pattern が
        # 「pathspec did not match any files」で失敗するため。
        cols = [c for c in ["sec_code", "filer_name", "company_name", "current_assets",
                            "total_liabilities", "total_assets", "equity_value",
                            "equity_ratio", "doc_id", "fiscal_period", "bs_date",
                            "submit_date"] if c in df.columns]
        invalid_df[cols].to_csv(invalid_path, index=False, encoding="utf-8-sig")

        if not invalid_df.empty:
            logger.warning(
                f"⚠ 財務データが不正な {len(invalid_df)} 銘柄を除外しました。"
                f"内訳は {invalid_path} を確認してください（XBRL抽出の取りこぼしの可能性があります）。"
            )
        else:
            logger.info("財務データの妥当性チェック: 除外0件")

    return valid_df, invalid_df
