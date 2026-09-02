# CONTEXT — ネットネット株スクリーナー

このファイルは `make_context.py` が自動生成します。手で編集しないでください。
相談時はこれ一枚を渡し、必要なスクリプト本体は指名して別途渡します。

- 生成: 2026-09-02 20:55 JST
- コミット: `2280f24` (main) / 2026-09-02 20:24

## いまの状態

- 発行済株式数の充足: 3,828/3,830 (99.9%)
- ネットネット候補（東証）: 133件
- ネットネット候補（地方）: 4件
- 名証: 掲載317件 / 期間内に約定84件 （相場日 2026-09-02 / 蓄積 10営業日）
- 東証重複の判別: 未適用（is_local_only 列なし）
- 名証の蓄積: 10営業日分 (2026-08-20 〜 2026-09-02)

## スクリプト

| ファイル | 行数 | sha1 | 更新 | 概要 |
| --- | ---: | --- | --- | --- |
| update_financials.py | 889 | `15c81147` | 2026-09-02 20:27 |  |
| financials.py | 155 | `7d573865` | 2026-09-02 20:27 | financial_cache.csv の読み込み・正規化・妥当性チェック。 |
| run_screener.py | 380 | `a218ab8d` | 2026-09-02 20:27 |  |
| run_screener_local.py | 250 | `0b005c9c` | 2026-09-02 20:27 | 地方単独上場（現状は名証）のネットネット候補を抽出し、 |
| price_metrics.py | 127 | `26228d2b` | 2026-09-02 20:27 | ネットネットスクリーナー用の価格指標を計算して列として追加するモジュール。 |
| save_history.py | 159 | `7fd7268b` | 2026-09-02 20:27 |  |
| jpx_alerts.py | 138 | `c1e4138c` | 2026-09-02 20:27 | JPX が公開している監理・整理銘柄一覧を取得し、DataFrame で返す。 |
| fetch_jpx_listed.py | 232 | `646ee2d2` | 2026-09-02 20:27 | JPX が公開している「東証上場銘柄一覧」(data_j.xls) を取得し、 |
| fetch_local_prices.py | 464 | `62247852` | 2026-09-02 20:27 | 名証（名古屋証券取引所）の株式相場表PDFから株価・売買高を抽出する。 |
| generate_html.py | 133 | `4b7dee36` | 2026-09-02 20:27 | 社名を取り出す。 |
| generate_local_html.py | 249 | `61df2e74` | 2026-09-02 20:27 | 地方市場（名証）版ネットネット候補ページの生成。 |
| generate_shortlist.py | 522 | `585b5419` | 2026-09-02 20:27 | net_net_candidates.csv（run_screener.py が出力、price_metrics.py で価格指標付与済み） |
| make_context.py | 286 | `2898f857` | 2026-09-02 20:27 | リポジトリの現状を CONTEXT.md 一枚にまとめる。 |

## データファイル

### financial_cache.csv

- 行数: 3,830 / 列数: 29 / 更新: 2026-09-02 20:55
- 列: `sec_code`, `filer_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_type`, `equity_ratio`, `equity_basis`, `equity_total`, `equity_total_type`, `equity_ratio_total`, `equity_parent`, `equity_parent_type`, `equity_ratio_parent`, `cash_and_equivalents`, `cash_basis`, `cash_bs`, `cash_cf`, `shares_outstanding`, `shares_as_of`, `shares_source`, `doc_id`, `submit_date`, `doc_type`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`

```
sec_code      filer_name current_assets total_liabilities total_assets equity_value equity_type equity_ratio equity_basis equity_total equity_total_type equity_ratio_total equity_parent equity_parent_type equity_ratio_parent cash_and_equivalents cash_basis      cash_bs      cash_cf shares_outstanding shares_as_of                    shares_source   doc_id submit_date doc_type accounting_standard consolidated fiscal_period    bs_date
    2303         株式会社ドーン     2086121000         355393000   3343042000   2987648000   NetAssets        89.37        total   2987648000         NetAssets              89.37  2984193000.0 ShareholdersEquity               89.27         1801822000.0         bs 1801822000.0 1006822000.0          6600000.0   2026-08-21 NumberOfIssuedSharesAsOfFilingDa S100YXLE  2026-08-21      120              J-GAAP           個別    2026-05-31 2026-05-31
    5885 株式会社ジーデップ・アドバンス     5610435000        2257884000   5793467000   3535582000   NetAssets        61.03        total   3535582000         NetAssets              61.03  3526001000.0 ShareholdersEquity               60.86         1771944000.0         bs 1771944000.0 1771944000.0          5498400.0   2026-08-21 NumberOfIssuedSharesAsOfFilingDa S100YXZQ  2026-08-21      120              J-GAAP           個別    2026-05-31 2026-05-31
```

### stock_cache.csv

- 行数: 3,035 / 列数: 8 / 更新: 2026-09-02 20:55
- 列: `sec_code`, `ticker`, `price`, `shares`, `market_cap`, `status`, `updated_at`, `shares_updated_at`

```
sec_code ticker  price    shares    market_cap  status updated_at shares_updated_at
    6546 6546.T 1155.0 5285649.0  6104924595.0 SUCCESS 2026-09-02        2026-08-11
    7115 7115.T 1467.0 9818488.0 14403721896.0 SUCCESS 2026-09-02        2026-08-11
```

### net_net_candidates.csv

- 行数: 133 / 列数: 29 / 更新: 2026-09-02 20:55
- 列: `sec_code`, `company_name`, `ticker`, `price`, `market_cap`, `ncav`, `nc_ratio`, `equity_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `current_assets`, `total_liabilities`, `total_assets`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`, `submit_date`, `調整後終値`, `前日比%`, `5日騰落%`, `20日騰落%`, `60日安値乖離%`, `120日安値乖離%`, `52週安値乖離%`, `52週高値乖離%`, `停滞日数`, `20日平均売買代金(百万円)`

```
sec_code    company_name ticker price   market_cap        ncav           nc_ratio equity_ratio cash_and_equivalents      net_cash     net_cash_ratio current_assets total_liabilities total_assets accounting_standard consolidated fiscal_period    bs_date submit_date 調整後終値 前日比% 5日騰落% 20日騰落% 60日安値乖離% 120日安値乖離% 52週安値乖離% 52週高値乖離% 停滞日数 20日平均売買代金(百万円)
    7034 株式会社プロレド・パートナーズ 7034.T 346.0 3782331524.0 10348348000 2.7359706398914807        85.15         5667289000.0  3609190000.0 0.9542235991474131    12406447000        2058099000  13861295000              J-GAAP           個別    2026-10-31 2026-04-30  2026-06-15 346.0 -2.0  -5.7   -1.7      5.5       5.5      5.5    -56.6    1           11.1
    8783         ａｂｃ株式会社 8783.T  56.0 2326493568.0  5079114000  2.183162708834104        66.42          767437000.0 -4121891000.0 -1.771718201457757     9968442000        4889328000  14561749000              J-GAAP           個別    2026-08-31 2026-02-28  2026-04-14  56.0 -3.4 -16.4   -1.8      0.0       0.0      0.0    -90.0    1           90.3
```

### net_net_candidates_local.csv

- 行数: 4 / 列数: 38 / 更新: 2026-09-02 20:55
- 列: `sec_code`, `company_name`, `local_name`, `market`, `sector`, `price`, `price_date`, `days_since_trade`, `traded_days_20`, `avg_turnover_20`, `avg_turnover_20_m`, `window_days`, `as_of`, `shares`, `shares_as_of`, `shares_age_days`, `shares_stale`, `shares_source`, `market_cap`, `ncav`, `nc_ratio`, `equity_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `current_assets`, `total_liabilities`, `total_assets`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`, `submit_date`, `alert_section`, `is_supervised`, `is_tse_listed`, `is_local_only`, `tse_list_as_of`
- ⚠ 全行が空の列: `alert_section`

```
sec_code   company_name local_name market sector  price price_date days_since_trade traded_days_20 avg_turnover_20 avg_turnover_20_m window_days      as_of    shares shares_as_of shares_age_days shares_stale                    shares_source   market_cap        ncav           nc_ratio equity_ratio cash_and_equivalents     net_cash      net_cash_ratio current_assets total_liabilities total_assets accounting_standard consolidated fiscal_period    bs_date submit_date alert_section is_supervised is_tse_listed is_local_only tse_list_as_of
    8071 東海エレクトロニクス株式会社       東海エレ  メイン市場    卸売業 3025.0 2026-09-02              0.0              8         1049590               1.0          10 2026-09-02 2360263.0   2026-06-24              70        False NumberOfIssuedSharesAsOfFilingDa 7139795575.0 12722123000 1.7818609603538964        63.06        11946209000.0  958839000.0 0.13429502146495279    23709493000       10987370000  29744752000              J-GAAP           連結    2026-03-31 2026-03-31  2026-06-24                       False         False          True       20260731
    6142       富士精工株式会社       富士精工  メイン市場    機 械 1786.0 2026-09-02              0.0             10         3723080               3.7          10 2026-09-02 3606778.0   2026-05-27              98        False NumberOfIssuedSharesAsOfFilingDa 6441705508.0 10487950000  1.628132485562238        79.02         9345945000.0 3412351000.0  0.5297278796371826    16421544000        5933594000  28276819000              J-GAAP           連結    2026-02-28 2026-02-28  2026-05-27                       False         False          True       20260731
```

### screening_history.csv

- 行数: 1,950 / 列数: 14 / 更新: 2026-09-02 20:55
- 列: `date`, `sec_code`, `company_name`, `price`, `market_cap`, `ncav`, `ncav_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `operating_income`, `operating_cf`, `equity_ratio`, `rank`
- ⚠ 全行が空の列: `operating_income`, `operating_cf`

```
      date sec_code    company_name price   market_cap        ncav        ncav_ratio cash_and_equivalents      net_cash     net_cash_ratio operating_income operating_cf equity_ratio rank
2026-08-18     5103  昭和ホールディングス株式会社   4.0  303389384.0   884713000 2.916097420205052         1764250000.0 -1292714000.0 -4.260907164767506                                      41.99    1
2026-08-18     7034 株式会社プロレド・パートナーズ 375.0 4099347750.0 10348348000  2.52438891040654         5667289000.0  3609190000.0 0.8804303074800132                                      85.15    2
```

### invalid_financials.csv

- 行数: 1 / 列数: 12 / 更新: 2026-09-02 20:55
- 列: `sec_code`, `filer_name`, `company_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_ratio`, `doc_id`, `fiscal_period`, `bs_date`, `submit_date`

```
sec_code filer_name company_name current_assets total_liabilities total_assets equity_value equity_ratio   doc_id fiscal_period    bs_date submit_date
    7445  株式会社ライトオン    株式会社ライトオン     6621000000       11586000000  11197000000   -389000000        -3.47 S100XYPY    2026-08-31 2026-02-28  2026-04-15
```

### invalid_financials_local.csv

- 行数: 1 / 列数: 12 / 更新: 2026-09-02 20:55
- 列: `sec_code`, `filer_name`, `company_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_ratio`, `doc_id`, `fiscal_period`, `bs_date`, `submit_date`

```
sec_code filer_name company_name current_assets total_liabilities total_assets equity_value equity_ratio   doc_id fiscal_period    bs_date submit_date
    7445  株式会社ライトオン    株式会社ライトオン     6621000000       11586000000  11197000000   -389000000        -3.47 S100XYPY    2026-08-31 2026-02-28  2026-04-15
```

### processed_docs.csv

- 行数: 3,919 / 列数: 1 / 更新: 2026-09-02 20:55
- 列: `doc_id`

```
  doc_id
S100YB17
S100YF7M
```

### jpx_alerts_cache.csv

- 行数: 121 / 列数: 4 / 更新: 2026-09-02 20:55
- 列: `コード`, `銘柄名`, `指定年月日`, `区分`

```
 コード              銘柄名      指定年月日 区分
1382           （株）ホーブ 2026/07/23 整理
1726 （株）ビーアールホールディングス 2026/05/15 整理
```

### tse_listed.csv

- 行数: 4,444 / 列数: 6 / 更新: 2026-09-02 20:27
- 列: `sec_code`, `name`, `market_segment`, `sector33`, `is_domestic_stock`, `as_of`

```
sec_code                   name market_segment sector33 is_domestic_stock    as_of
    1301                     極洋     プライム（内国株式）   水産・農林業              True 20260731
    1305 ｉＦｒｅｅＥＴＦ　ＴＯＰＩＸ（年１回決算型）        ETF・ETN        -             False 20260731
```

### local_price_history.csv

- 行数: 3,170 / 列数: 12 / 更新: 2026-09-02 20:55
- 列: `date`, `sec_code`, `name`, `market`, `sector`, `alert_section`, `is_supervised`, `close`, `last_quote`, `volume_k`, `traded`, `turnover`

```
      date sec_code     name market sector alert_section is_supervised close last_quote volume_k traded turnover
2026-08-20     138A 光フードサービス ネクスト市場    小売業                       False           3145.0      0.0  False      0.0
2026-08-20     1438     岐阜造園  メイン市場    建設業                       False           2346.0      0.0  False      0.0
```

### local_prices.csv

- 行数: 317 / 列数: 15 / 更新: 2026-09-02 20:55
- 列: `sec_code`, `name`, `market`, `sector`, `alert_section`, `is_supervised`, `price`, `price_date`, `last_quote`, `traded_days_20`, `avg_turnover_20`, `avg_turnover_20_m`, `days_since_trade`, `window_days`, `as_of`

```
sec_code name market sector alert_section is_supervised  price price_date last_quote traded_days_20 avg_turnover_20 avg_turnover_20_m days_since_trade window_days      as_of
    7485 岡谷鋼機 プレミア市場    卸売業                       False 5020.0 2026-09-02                        10        47025200              47.0              0.0          10 2026-09-02
    6623  愛知電 プレミア市場   電気機器                       False 8960.0 2026-09-02                        10        45589700              45.6              0.0          10 2026-09-02
```

## 出力ページ

- index.html: 54 KB / 更新 2026-09-02 20:55
- shortlist.html: 102 KB / 更新 2026-09-02 20:55
- local.html: 8 KB / 更新 2026-09-02 20:55
