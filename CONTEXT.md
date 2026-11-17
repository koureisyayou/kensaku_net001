# CONTEXT — ネットネット株スクリーナー

このファイルは `make_context.py` が自動生成します。手で編集しないでください。
相談時はこれ一枚を渡し、必要なスクリプト本体は指名して別途渡します。

- 生成: 2026-11-18 03:41 JST
- コミット: `e73cb02` (main) / 2026-11-16 19:51

## いまの状態

- 発行済株式数の充足: 3,843/3,847 (99.9%)
- ネットネット候補（東証）: 174件
- ネットネット候補（地方）: 5件
- 名証: 掲載324件 / 期間内に約定103件 （相場日 2026-11-17 / 蓄積 20営業日）
- 東証重複の判別: run_screener_local.py 側で実施（結果は net_net_candidates_local.csv の is_local_only 列）
- 名証の蓄積: 40営業日分 (2026-09-15 〜 2026-11-17)

## スクリプト

| ファイル | 行数 | sha1 | 更新 | 概要 |
| --- | ---: | --- | --- | --- |
| update_financials.py | 938 | `24191771` | 2026-11-18 03:17 |  |
| financials.py | 155 | `7d573865` | 2026-11-18 03:17 | financial_cache.csv の読み込み・正規化・妥当性チェック。 |
| run_screener.py | 492 | `1de82932` | 2026-11-18 03:17 |  |
| run_screener_local.py | 300 | `424a664f` | 2026-11-18 03:17 | 地方単独上場（現状は名証）のネットネット候補を抽出し、 |
| price_metrics.py | 246 | `8db84eec` | 2026-11-18 03:17 | ネットネットスクリーナー用の価格指標を計算して列として追加するモジュール。 |
| save_history.py | 197 | `386a7ea7` | 2026-11-18 03:17 |  |
| jpx_alerts.py | 138 | `c1e4138c` | 2026-11-18 03:17 | JPX が公開している監理・整理銘柄一覧を取得し、DataFrame で返す。 |
| fetch_jpx_listed.py | 244 | `227df474` | 2026-11-18 03:17 | JPXが公開している「東証上場銘柄一覧」を取得し、証券コードの一覧を作る。 |
| fetch_local_prices.py | 478 | `37172d10` | 2026-11-18 03:17 | 名証（名古屋証券取引所）の株式相場表PDFから株価・売買高を抽出する。 |
| generate_html.py | 133 | `4b7dee36` | 2026-11-18 03:17 | 社名を取り出す。 |
| generate_local_html.py | 249 | `61df2e74` | 2026-11-18 03:17 | 地方市場（名証）版ネットネット候補ページの生成。 |
| generate_shortlist.py | 522 | `585b5419` | 2026-11-18 03:17 | net_net_candidates.csv（run_screener.py が出力、price_metrics.py で価格指標付与済み） |
| make_context.py | 300 | `22a7bda8` | 2026-11-18 03:17 | リポジトリの現状を CONTEXT.md 一枚にまとめる。 |

## データファイル

### financial_cache.csv

- 行数: 3,847 / 列数: 29 / 更新: 2026-11-18 03:17
- 列: `sec_code`, `filer_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_type`, `equity_ratio`, `equity_basis`, `equity_total`, `equity_total_type`, `equity_ratio_total`, `equity_parent`, `equity_parent_type`, `equity_ratio_parent`, `cash_and_equivalents`, `cash_basis`, `cash_bs`, `cash_cf`, `shares_outstanding`, `shares_as_of`, `shares_source`, `doc_id`, `submit_date`, `doc_type`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`

```
sec_code  filer_name current_assets total_liabilities total_assets equity_value equity_type equity_ratio equity_basis equity_total equity_total_type equity_ratio_total  equity_parent equity_parent_type equity_ratio_parent cash_and_equivalents cash_basis       cash_bs       cash_cf shares_outstanding shares_as_of                    shares_source   doc_id submit_date doc_type accounting_standard consolidated fiscal_period    bs_date
    3955     株式会社イムラ     8767000000        9543000000  27781000000  18238000000   NetAssets        65.65        total  18238000000         NetAssets              65.65  16320000000.0 ShareholdersEquity               58.75         2112000000.0         bs  2112000000.0  1980000000.0         10729370.0   2026-09-14 NumberOfIssuedSharesAsOfFilingDa S100Z1WA  2026-09-15      160              J-GAAP           連結    2027-01-31 2026-07-31
    3191 株式会社ジョイフル本田    57948000000       41234000000 167672000000 126438000000   NetAssets        75.41        total 126438000000         NetAssets              75.41 124831000000.0 ShareholdersEquity               74.45        25193000000.0         bs 25193000000.0 24974000000.0         63784612.0   2026-09-15 NumberOfIssuedSharesAsOfFilingDa S100Z1T7  2026-09-15      120              J-GAAP           連結    2026-06-20 2026-06-20
```

### stock_cache.csv

- 行数: 3,064 / 列数: 8 / 更新: 2026-11-18 03:40
- 列: `sec_code`, `ticker`, `price`, `shares`, `market_cap`, `status`, `updated_at`, `shares_updated_at`

```
sec_code ticker  price    shares    market_cap  status updated_at shares_updated_at
    6546 6546.T 1146.0 5285649.0  6057353754.0 SUCCESS 2026-11-17        2026-11-11
    7115 7115.T 1126.0 9826788.0 11064963288.0 SUCCESS 2026-11-17        2026-11-11
```

### net_net_candidates.csv

- 行数: 174 / 列数: 29 / 更新: 2026-11-18 03:41
- 列: `sec_code`, `company_name`, `ticker`, `price`, `market_cap`, `ncav`, `nc_ratio`, `equity_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `current_assets`, `total_liabilities`, `total_assets`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`, `submit_date`, `調整後終値`, `前日比%`, `5日騰落%`, `20日騰落%`, `60日安値乖離%`, `120日安値乖離%`, `52週安値乖離%`, `52週高値乖離%`, `停滞日数`, `20日平均売買代金(百万円)`

```
sec_code     company_name ticker price   market_cap        ncav          nc_ratio equity_ratio cash_and_equivalents     net_cash     net_cash_ratio current_assets total_liabilities total_assets accounting_standard consolidated fiscal_period    bs_date submit_date 調整後終値  前日比% 5日騰落% 20日騰落% 60日安値乖離% 120日安値乖離% 52週安値乖離% 52週高値乖離% 停滞日数 20日平均売買代金(百万円)
    2388 株式会社ウェッジホールディングス 2388.T   9.0  382095702.0  2244469000 5.874101666812258        77.69         1302999000.0  533525000.0 1.3963124871789319     3013943000         769474000   3448602000              J-GAAP           連結    2026-09-30 2026-03-31  2026-05-15   9.0 -10.0 -10.0  -18.2      0.0       0.0      0.0    -86.6    1           11.3
    7034  株式会社プロレド・パートナーズ 7034.T 267.0 2918735598.0 10348348000 3.545490042705814        85.15         5667289000.0 3609190000.0  1.236559420617996    12406447000        2058099000  13861295000              J-GAAP           連結    2026-10-31 2026-04-30  2026-06-15 267.0   0.8   2.7  -15.2      2.7       2.7      2.7    -57.6    5            9.9
```

### net_net_candidates_local.csv

- 行数: 5 / 列数: 38 / 更新: 2026-11-18 03:41
- 列: `sec_code`, `company_name`, `local_name`, `market`, `sector`, `price`, `price_date`, `days_since_trade`, `traded_days_20`, `avg_turnover_20`, `avg_turnover_20_m`, `window_days`, `as_of`, `shares`, `shares_as_of`, `shares_age_days`, `shares_stale`, `shares_source`, `market_cap`, `ncav`, `nc_ratio`, `equity_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `current_assets`, `total_liabilities`, `total_assets`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`, `submit_date`, `alert_section`, `is_supervised`, `is_tse_listed`, `is_local_only`, `tse_list_as_of`
- ⚠ 全行が空の列: `alert_section`

```
sec_code   company_name local_name market sector  price price_date days_since_trade traded_days_20 avg_turnover_20 avg_turnover_20_m window_days      as_of    shares shares_as_of shares_age_days shares_stale                    shares_source   market_cap        ncav           nc_ratio equity_ratio cash_and_equivalents     net_cash      net_cash_ratio current_assets total_liabilities total_assets accounting_standard consolidated fiscal_period    bs_date submit_date alert_section is_supervised is_tse_listed is_local_only tse_list_as_of
    8071 東海エレクトロニクス株式会社       東海エレ  メイン市場    卸売業 2931.0 2026-10-22             17.0              3          161615               0.2          20 2026-11-17 2360263.0   2026-11-12               5        False NumberOfIssuedSharesAsOfFilingDa 6917930853.0 12531885000 1.8115076988035341        62.96        11813183000.0  541176000.0 0.07822801521141483    23803892000       11272007000  30428041000              J-GAAP           連結    2027-03-31 2026-09-30  2026-11-12                       False         False          True       20261112
    6142       富士精工株式会社       富士精工  メイン市場    機 械 1860.0 2026-11-17              0.0             11         1978495               2.0          20 2026-11-17 3606778.0   2026-10-13              35        False NumberOfIssuedSharesAsOfFilingDa 6708607080.0 10425458000 1.5540421246432576        78.79         8507785000.0 2615847000.0  0.3899240138535584    16317396000        5891938000  27775311000              J-GAAP           連結    2027-02-28 2026-08-31  2026-10-13                       False         False          True       20261112
```

### screening_history.csv

- 行数: 10,762 / 列数: 14 / 更新: 2026-11-18 03:41
- 列: `date`, `sec_code`, `company_name`, `price`, `market_cap`, `ncav`, `ncav_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `operating_income`, `operating_cf`, `equity_ratio`, `rank`
- ⚠ 全行が空の列: `operating_income`, `operating_cf`

```
      date sec_code    company_name price   market_cap        ncav        ncav_ratio cash_and_equivalents      net_cash     net_cash_ratio operating_income operating_cf equity_ratio rank
2026-08-18     5103  昭和ホールディングス株式会社   4.0  303389384.0   884713000 2.916097420205052         1764250000.0 -1292714000.0 -4.260907164767506                                      41.99    1
2026-08-18     7034 株式会社プロレド・パートナーズ 375.0 4099347750.0 10348348000  2.52438891040654         5667289000.0  3609190000.0 0.8804303074800132                                      85.15    2
```

### invalid_financials.csv

- 行数: 2 / 列数: 12 / 更新: 2026-11-18 03:18
- 列: `sec_code`, `filer_name`, `company_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_ratio`, `doc_id`, `fiscal_period`, `bs_date`, `submit_date`

```
sec_code filer_name company_name current_assets total_liabilities total_assets equity_value equity_ratio   doc_id fiscal_period    bs_date submit_date
    7709  クボテック株式会社    クボテック株式会社      523498000         825776000    805298000    -20478000        -2.54 S100YT1F    2027-03-31 2026-09-30  2026-11-12
    7445  株式会社ライトオン    株式会社ライトオン     6621000000       11586000000  11197000000   -389000000        -3.47 S100XYPY    2026-08-31 2026-02-28  2026-04-15
```

### invalid_financials_local.csv

- 行数: 2 / 列数: 12 / 更新: 2026-11-18 03:41
- 列: `sec_code`, `filer_name`, `company_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_ratio`, `doc_id`, `fiscal_period`, `bs_date`, `submit_date`

```
sec_code filer_name company_name current_assets total_liabilities total_assets equity_value equity_ratio   doc_id fiscal_period    bs_date submit_date
    7709  クボテック株式会社    クボテック株式会社      523498000         825776000    805298000    -20478000        -2.54 S100YT1F    2027-03-31 2026-09-30  2026-11-12
    7445  株式会社ライトオン    株式会社ライトオン     6621000000       11586000000  11197000000   -389000000        -3.47 S100XYPY    2026-08-31 2026-02-28  2026-04-15
```

### processed_docs.csv

- 行数: 6,392 / 列数: 1 / 更新: 2026-11-18 03:17
- 列: `doc_id`

```
  doc_id
S100YIGR
S100ZEH9
```

### jpx_alerts_cache.csv

- 行数: 145 / 列数: 4 / 更新: 2026-11-18 03:41
- 列: `コード`, `銘柄名`, `指定年月日`, `区分`

```
 コード     銘柄名      指定年月日 区分
1382  （株）ホーブ 2026/07/23 整理
1438 （株）岐阜造園 2026/11/13 監理
```

### tse_listed.csv

- 行数: 4,437 / 列数: 4 / 更新: 2026-11-18 03:17
- 列: `sec_code`, `company_name`, `market`, `as_of`

```
sec_code           company_name     market    as_of
    1301                     極洋 プライム（内国株式） 20261112
    1305 ｉＦｒｅｅＥＴＦ　ＴＯＰＩＸ（年１回決算型）    ETF・ETN 20261112
```

### local_price_history.csv

- 行数: 12,540 / 列数: 12 / 更新: 2026-11-18 03:41
- 列: `date`, `sec_code`, `name`, `market`, `sector`, `alert_section`, `is_supervised`, `close`, `last_quote`, `volume_k`, `traded`, `turnover`

```
      date sec_code     name market sector alert_section is_supervised close last_quote volume_k traded turnover
2026-09-15     138A 光フードサービス ネクスト市場    小売業                       False           3075.0      0.0  False      0.0
2026-09-15     1438     岐阜造園  メイン市場    建設業                       False           2245.0      0.0  False      0.0
```

### local_prices.csv

- 行数: 324 / 列数: 15 / 更新: 2026-11-18 03:41
- 列: `sec_code`, `name`, `market`, `sector`, `alert_section`, `is_supervised`, `price`, `price_date`, `last_quote`, `traded_days_20`, `avg_turnover_20`, `avg_turnover_20_m`, `days_since_trade`, `window_days`, `as_of`
- ⚠ 全行が空の列: `alert_section`

```
sec_code      name market sector alert_section is_supervised  price price_date last_quote traded_days_20 avg_turnover_20 avg_turnover_20_m days_since_trade window_days      as_of
    2467 ＶＬＣセキュリティ ネクスト市場  サービス業                       False  193.0 2026-11-17                        20       324162995             324.2              0.0          20 2026-11-17
    6623       愛知電 プレミア市場   電気機器                       False 7340.0 2026-11-17                        20       102984950             103.0              0.0          20 2026-11-17
```

## 出力ページ

- index.html: 70 KB / 更新 2026-11-18 03:41
- shortlist.html: 136 KB / 更新 2026-11-18 03:41
- local.html: 8 KB / 更新 2026-11-18 03:41
