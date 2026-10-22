# CONTEXT — ネットネット株スクリーナー

このファイルは `make_context.py` が自動生成します。手で編集しないでください。
相談時はこれ一枚を渡し、必要なスクリプト本体は指名して別途渡します。

- 生成: 2026-10-22 23:49 JST
- コミット: `3f1d529` (main) / 2026-10-21 14:52

## いまの状態

- 発行済株式数の充足: 3,835/3,837 (99.9%)
- ネットネット候補（東証）: 155件
- ネットネット候補（地方）: 4件
- 名証: 掲載324件 / 期間内に約定104件 （相場日 2026-10-22 / 蓄積 20営業日）
- 東証重複の判別: run_screener_local.py 側で実施（結果は net_net_candidates_local.csv の is_local_only 列）
- 名証の蓄積: 40営業日分 (2026-08-21 〜 2026-10-22)

## スクリプト

| ファイル | 行数 | sha1 | 更新 | 概要 |
| --- | ---: | --- | --- | --- |
| update_financials.py | 938 | `24191771` | 2026-10-22 23:24 |  |
| financials.py | 155 | `7d573865` | 2026-10-22 23:24 | financial_cache.csv の読み込み・正規化・妥当性チェック。 |
| run_screener.py | 492 | `1de82932` | 2026-10-22 23:24 |  |
| run_screener_local.py | 300 | `424a664f` | 2026-10-22 23:24 | 地方単独上場（現状は名証）のネットネット候補を抽出し、 |
| price_metrics.py | 246 | `8db84eec` | 2026-10-22 23:24 | ネットネットスクリーナー用の価格指標を計算して列として追加するモジュール。 |
| save_history.py | 197 | `386a7ea7` | 2026-10-22 23:24 |  |
| jpx_alerts.py | 138 | `c1e4138c` | 2026-10-22 23:24 | JPX が公開している監理・整理銘柄一覧を取得し、DataFrame で返す。 |
| fetch_jpx_listed.py | 244 | `227df474` | 2026-10-22 23:24 | JPXが公開している「東証上場銘柄一覧」を取得し、証券コードの一覧を作る。 |
| fetch_local_prices.py | 478 | `37172d10` | 2026-10-22 23:24 | 名証（名古屋証券取引所）の株式相場表PDFから株価・売買高を抽出する。 |
| generate_html.py | 133 | `4b7dee36` | 2026-10-22 23:24 | 社名を取り出す。 |
| generate_local_html.py | 249 | `61df2e74` | 2026-10-22 23:24 | 地方市場（名証）版ネットネット候補ページの生成。 |
| generate_shortlist.py | 522 | `585b5419` | 2026-10-22 23:24 | net_net_candidates.csv（run_screener.py が出力、price_metrics.py で価格指標付与済み） |
| make_context.py | 300 | `22a7bda8` | 2026-10-22 23:24 | リポジトリの現状を CONTEXT.md 一枚にまとめる。 |

## データファイル

### financial_cache.csv

- 行数: 3,837 / 列数: 29 / 更新: 2026-10-22 23:25
- 列: `sec_code`, `filer_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_type`, `equity_ratio`, `equity_basis`, `equity_total`, `equity_total_type`, `equity_ratio_total`, `equity_parent`, `equity_parent_type`, `equity_ratio_parent`, `cash_and_equivalents`, `cash_basis`, `cash_bs`, `cash_cf`, `shares_outstanding`, `shares_as_of`, `shares_source`, `doc_id`, `submit_date`, `doc_type`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`

```
sec_code  filer_name current_assets total_liabilities total_assets equity_value equity_type equity_ratio equity_basis equity_total equity_total_type equity_ratio_total  equity_parent equity_parent_type equity_ratio_parent cash_and_equivalents cash_basis       cash_bs       cash_cf shares_outstanding shares_as_of                    shares_source   doc_id submit_date doc_type accounting_standard consolidated fiscal_period    bs_date
    3955     株式会社イムラ     8767000000        9543000000  27781000000  18238000000   NetAssets        65.65        total  18238000000         NetAssets              65.65  16320000000.0 ShareholdersEquity               58.75         2112000000.0         bs  2112000000.0  1980000000.0         10729370.0   2026-09-14 NumberOfIssuedSharesAsOfFilingDa S100Z1WA  2026-09-15      160              J-GAAP           連結    2027-01-31 2026-07-31
    3191 株式会社ジョイフル本田    57948000000       41234000000 167672000000 126438000000   NetAssets        75.41        total 126438000000         NetAssets              75.41 124831000000.0 ShareholdersEquity               74.45        25193000000.0         bs 25193000000.0 24974000000.0         63784612.0   2026-09-15 NumberOfIssuedSharesAsOfFilingDa S100Z1T7  2026-09-15      120              J-GAAP           連結    2026-06-20 2026-06-20
```

### stock_cache.csv

- 行数: 3,043 / 列数: 8 / 更新: 2026-10-22 23:49
- 列: `sec_code`, `ticker`, `price`, `shares`, `market_cap`, `status`, `updated_at`, `shares_updated_at`

```
sec_code ticker  price    shares    market_cap  status updated_at shares_updated_at
    6546 6546.T 1183.0 5285649.0  6252922767.0 SUCCESS 2026-10-22        2026-10-12
    7115 7115.T 1366.0 9826788.0 13423392408.0 SUCCESS 2026-10-22        2026-10-12
```

### net_net_candidates.csv

- 行数: 155 / 列数: 29 / 更新: 2026-10-22 23:49
- 列: `sec_code`, `company_name`, `ticker`, `price`, `market_cap`, `ncav`, `nc_ratio`, `equity_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `current_assets`, `total_liabilities`, `total_assets`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`, `submit_date`, `調整後終値`, `前日比%`, `5日騰落%`, `20日騰落%`, `60日安値乖離%`, `120日安値乖離%`, `52週安値乖離%`, `52週高値乖離%`, `停滞日数`, `20日平均売買代金(百万円)`

```
sec_code     company_name ticker price   market_cap        ncav          nc_ratio equity_ratio cash_and_equivalents     net_cash     net_cash_ratio current_assets total_liabilities total_assets accounting_standard consolidated fiscal_period    bs_date submit_date 調整後終値 前日比% 5日騰落% 20日騰落% 60日安値乖離% 120日安値乖離% 52週安値乖離% 52週高値乖離% 停滞日数 20日平均売買代金(百万円)
    2388 株式会社ウェッジホールディングス 2388.T  12.0  509460936.0  2244469000 4.405576250109194        77.69         1302999000.0  533525000.0  1.047234365384199     3013943000         769474000   3448602000              J-GAAP           連結    2026-09-30 2026-03-31  2026-05-15  12.0  0.0   0.0  -61.3     20.0      20.0     20.0    -82.6    3           20.2
    7034  株式会社プロレド・パートナーズ 7034.T 305.0 3334136170.0 10348348000 3.103756857057221        85.15         5667289000.0 3609190000.0 1.0824962796885407    12406447000        2058099000  13861295000              J-GAAP           連結    2026-10-31 2026-04-30  2026-06-15 305.0 -2.2  -0.7   -4.1      2.7       2.7      2.7    -51.6    1            8.1
```

### net_net_candidates_local.csv

- 行数: 4 / 列数: 38 / 更新: 2026-10-22 23:49
- 列: `sec_code`, `company_name`, `local_name`, `market`, `sector`, `price`, `price_date`, `days_since_trade`, `traded_days_20`, `avg_turnover_20`, `avg_turnover_20_m`, `window_days`, `as_of`, `shares`, `shares_as_of`, `shares_age_days`, `shares_stale`, `shares_source`, `market_cap`, `ncav`, `nc_ratio`, `equity_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `current_assets`, `total_liabilities`, `total_assets`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`, `submit_date`, `alert_section`, `is_supervised`, `is_tse_listed`, `is_local_only`, `tse_list_as_of`
- ⚠ 全行が空の列: `alert_section`

```
sec_code   company_name local_name market sector  price price_date days_since_trade traded_days_20 avg_turnover_20 avg_turnover_20_m window_days      as_of    shares shares_as_of shares_age_days shares_stale                    shares_source   market_cap        ncav           nc_ratio equity_ratio cash_and_equivalents     net_cash     net_cash_ratio current_assets total_liabilities total_assets accounting_standard consolidated fiscal_period    bs_date submit_date alert_section is_supervised is_tse_listed is_local_only tse_list_as_of
    5979       カネソウ株式会社       カネソウ  メイン市場   金属製品 2576.0 2026-10-22              0.0             14         1200210               1.2          20 2026-10-22 1440000.0   2026-06-23             121        False NumberOfIssuedSharesAsOfFilingDa 3709440000.0  9862613000  2.658787579796411        87.95         9399995000.0 7264332000.0 1.9583365683229814    11998276000        2135663000  17726887000              J-GAAP           個別    2026-03-31 2026-03-31  2026-06-23                       False         False          True       20261012
    8071 東海エレクトロニクス株式会社       東海エレ  メイン市場    卸売業 2931.0 2026-10-22              0.0             14          955895               1.0          20 2026-10-22 2360263.0   2026-06-24             120        False NumberOfIssuedSharesAsOfFilingDa 6917930853.0 12722123000 1.8390069618118514        63.06        11946209000.0  958839000.0 0.1386019924706524    23709493000       10987370000  29744752000              J-GAAP           連結    2026-03-31 2026-03-31  2026-06-24                       False         False          True       20261012
```

### screening_history.csv

- 行数: 7,571 / 列数: 14 / 更新: 2026-10-22 23:49
- 列: `date`, `sec_code`, `company_name`, `price`, `market_cap`, `ncav`, `ncav_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `operating_income`, `operating_cf`, `equity_ratio`, `rank`
- ⚠ 全行が空の列: `operating_income`, `operating_cf`

```
      date sec_code    company_name price   market_cap        ncav        ncav_ratio cash_and_equivalents      net_cash     net_cash_ratio operating_income operating_cf equity_ratio rank
2026-08-18     5103  昭和ホールディングス株式会社   4.0  303389384.0   884713000 2.916097420205052         1764250000.0 -1292714000.0 -4.260907164767506                                      41.99    1
2026-08-18     7034 株式会社プロレド・パートナーズ 375.0 4099347750.0 10348348000  2.52438891040654         5667289000.0  3609190000.0 0.8804303074800132                                      85.15    2
```

### invalid_financials.csv

- 行数: 1 / 列数: 12 / 更新: 2026-10-22 23:25
- 列: `sec_code`, `filer_name`, `company_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_ratio`, `doc_id`, `fiscal_period`, `bs_date`, `submit_date`

```
sec_code filer_name company_name current_assets total_liabilities total_assets equity_value equity_ratio   doc_id fiscal_period    bs_date submit_date
    7445  株式会社ライトオン    株式会社ライトオン     6621000000       11586000000  11197000000   -389000000        -3.47 S100XYPY    2026-08-31 2026-02-28  2026-04-15
```

### invalid_financials_local.csv

- 行数: 1 / 列数: 12 / 更新: 2026-10-22 23:49
- 列: `sec_code`, `filer_name`, `company_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_ratio`, `doc_id`, `fiscal_period`, `bs_date`, `submit_date`

```
sec_code filer_name company_name current_assets total_liabilities total_assets equity_value equity_ratio   doc_id fiscal_period    bs_date submit_date
    7445  株式会社ライトオン    株式会社ライトオン     6621000000       11586000000  11197000000   -389000000        -3.47 S100XYPY    2026-08-31 2026-02-28  2026-04-15
```

### processed_docs.csv

- 行数: 4,246 / 列数: 1 / 更新: 2026-10-22 23:25
- 列: `doc_id`

```
  doc_id
S100YCIP
S100YF7Q
```

### jpx_alerts_cache.csv

- 行数: 132 / 列数: 4 / 更新: 2026-10-22 23:49
- 列: `コード`, `銘柄名`, `指定年月日`, `区分`

```
 コード              銘柄名      指定年月日 区分
1382           （株）ホーブ 2026/07/23 整理
1726 （株）ビーアールホールディングス 2026/05/15 整理
```

### tse_listed.csv

- 行数: 4,440 / 列数: 4 / 更新: 2026-10-22 23:24
- 列: `sec_code`, `company_name`, `market`, `as_of`

```
sec_code           company_name     market    as_of
    1301                     極洋 プライム（内国株式） 20261012
    1305 ｉＦｒｅｅＥＴＦ　ＴＯＰＩＸ（年１回決算型）    ETF・ETN 20261012
```

### local_price_history.csv

- 行数: 12,732 / 列数: 12 / 更新: 2026-10-22 23:49
- 列: `date`, `sec_code`, `name`, `market`, `sector`, `alert_section`, `is_supervised`, `close`, `last_quote`, `volume_k`, `traded`, `turnover`

```
      date sec_code     name market sector alert_section is_supervised close last_quote volume_k traded turnover
2026-08-21     138A 光フードサービス ネクスト市場    小売業                       False           3110.0      0.0  False      0.0
2026-08-21     1438     岐阜造園  メイン市場    建設業                       False           2322.0      0.0  False      0.0
```

### local_prices.csv

- 行数: 324 / 列数: 15 / 更新: 2026-10-22 23:49
- 列: `sec_code`, `name`, `market`, `sector`, `alert_section`, `is_supervised`, `price`, `price_date`, `last_quote`, `traded_days_20`, `avg_turnover_20`, `avg_turnover_20_m`, `days_since_trade`, `window_days`, `as_of`

```
sec_code      name market sector alert_section is_supervised price price_date last_quote traded_days_20 avg_turnover_20 avg_turnover_20_m days_since_trade window_days      as_of
    2467 ＶＬＣセキュリティ ネクスト市場  サービス業                       False 272.0 2026-10-22                        20       257591355             257.6              0.0          20 2026-10-22
    624A    かがやきＨＤ ネクスト市場  サービス業                       False 949.0 2026-10-22                        20        51579300              51.6              0.0          20 2026-10-22
```

## 出力ページ

- index.html: 62 KB / 更新 2026-10-22 23:49
- shortlist.html: 124 KB / 更新 2026-10-22 23:49
- local.html: 8 KB / 更新 2026-10-22 23:49
