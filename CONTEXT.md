# CONTEXT — ネットネット株スクリーナー

このファイルは `make_context.py` が自動生成します。手で編集しないでください。
相談時はこれ一枚を渡し、必要なスクリプト本体は指名して別途渡します。

- 生成: 2026-08-22 01:03 JST
- コミット: `9fe8b7c` (main) / 2026-08-21 19:49

## いまの状態

- 発行済株式数の充足: 8/3,776 (0.2%)
- ネットネット候補（東証）: 142件
- ネットネット候補（地方）: 未生成
- 名証: 掲載317件 / 期間内に約定61件 （相場日 2026-08-21 / 蓄積 2営業日）
- 東証重複の判別: 未適用（is_local_only 列なし）
- 名証の蓄積: 2営業日分 (2026-08-20 〜 2026-08-21)

## スクリプト

| ファイル | 行数 | sha1 | 更新 | 概要 |
| --- | ---: | --- | --- | --- |
| update_financials.py | 659 | `332f0e93` | 2026-08-22 00:22 |  |
| financials.py | 155 | `7d573865` | 2026-08-22 00:22 | financial_cache.csv の読み込み・正規化・妥当性チェック。 |
| run_screener.py | 380 | `a218ab8d` | 2026-08-22 00:22 |  |
| run_screener_local.py | 250 | `0b005c9c` | 2026-08-22 00:22 | 地方単独上場（現状は名証）のネットネット候補を抽出し、 |
| price_metrics.py | 127 | `26228d2b` | 2026-08-22 00:22 | ネットネットスクリーナー用の価格指標を計算して列として追加するモジュール。 |
| save_history.py | 159 | `7fd7268b` | 2026-08-22 00:22 |  |
| jpx_alerts.py | 138 | `c1e4138c` | 2026-08-22 00:22 | JPX が公開している監理・整理銘柄一覧を取得し、DataFrame で返す。 |
| fetch_jpx_listed.py | 232 | `646ee2d2` | 2026-08-22 00:22 | JPX が公開している「東証上場銘柄一覧」(data_j.xls) を取得し、 |
| fetch_local_prices.py | 464 | `c030648d` | 2026-08-22 00:22 | 名証（名古屋証券取引所）の株式相場表PDFから株価・売買高を抽出する。 |
| generate_html.py | 133 | `4b7dee36` | 2026-08-22 00:22 | 社名を取り出す。 |
| generate_local_html.py | 249 | `61df2e74` | 2026-08-22 00:22 | 地方市場（名証）版ネットネット候補ページの生成。 |
| generate_shortlist.py | 404 | `b133449f` | 2026-08-22 00:22 | net_net_candidates.csv（run_screener.py が出力、price_metrics.py で価格指標付与済み） |
| make_context.py | 286 | `2898f857` | 2026-08-22 00:22 | リポジトリの現状を CONTEXT.md 一枚にまとめる。 |

## データファイル

### financial_cache.csv

- 行数: 3,776 / 列数: 19 / 更新: 2026-08-22 01:02
- 列: `sec_code`, `filer_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_type`, `equity_ratio`, `cash_and_equivalents`, `doc_id`, `submit_date`, `doc_type`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`, `shares_outstanding`, `shares_as_of`, `shares_source`

```
sec_code    filer_name current_assets total_liabilities total_assets equity_value equity_type equity_ratio cash_and_equivalents   doc_id submit_date doc_type accounting_standard consolidated fiscal_period    bs_date shares_outstanding shares_as_of shares_source
    4011 株式会社ヘッドウォータース     3235860000        4149620000  10309272000   6159652000   NetAssets        59.75         1844881000.0 S100YX6B  2026-08-17      160              J-GAAP           個別    2026-12-31                                                         
    7363  株式会社ベビーカレンダー     1037460000        1073135000   1800808000    727673000   NetAssets        40.41          720084000.0 S100YX4F  2026-08-17      130              J-GAAP           個別               2025-12-31                                              
```

### stock_cache.csv

- 行数: 2,964 / 列数: 8 / 更新: 2026-08-22 01:02
- 列: `sec_code`, `ticker`, `price`, `shares`, `market_cap`, `status`, `updated_at`, `shares_updated_at`

```
sec_code ticker  price    shares    market_cap  status updated_at shares_updated_at
    6546 6546.T 1136.0 5285649.0  6004497264.0 SUCCESS 2026-08-21        2026-08-11
    7115 7115.T 1518.0 9818488.0 14904464784.0 SUCCESS 2026-08-21        2026-08-11
```

### net_net_candidates.csv

- 行数: 142 / 列数: 29 / 更新: 2026-08-22 01:02
- 列: `sec_code`, `company_name`, `ticker`, `price`, `market_cap`, `ncav`, `nc_ratio`, `equity_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `current_assets`, `total_liabilities`, `total_assets`, `accounting_standard`, `consolidated`, `fiscal_period`, `bs_date`, `submit_date`, `調整後終値`, `前日比%`, `5日騰落%`, `20日騰落%`, `60日安値乖離%`, `120日安値乖離%`, `52週安値乖離%`, `52週高値乖離%`, `停滞日数`, `20日平均売買代金(百万円)`
- ⚠ 全行が空の列: `bs_date`

```
sec_code    company_name ticker price   market_cap        ncav           nc_ratio equity_ratio cash_and_equivalents      net_cash     net_cash_ratio current_assets total_liabilities total_assets accounting_standard consolidated fiscal_period bs_date submit_date 調整後終値  前日比% 5日騰落% 20日騰落% 60日安値乖離% 120日安値乖離% 52週安値乖離% 52週高値乖離% 停滞日数 20日平均売買代金(百万円)
    5103  昭和ホールディングス株式会社 5103.T   3.0  227542038.0   884713000 3.8881298936067363        41.99         1764250000.0 -1292714000.0 -5.681209553023341     3941677000        3056964000   5270064000              J-GAAP           連結    2026-03-31          2026-06-24   3.0 -25.0 -40.0  -78.6      0.0       0.0      0.0    -95.2    1           24.9
    7034 株式会社プロレド・パートナーズ 7034.T 383.0 4186800502.0 10348348000  2.471660160319719        85.15         5667289000.0  3609190000.0 0.8620401182898301    12406447000        2058099000  13861295000              J-GAAP           個別    2026-10-31          2026-06-15 383.0  -1.0   0.5   -1.3     16.8      16.8     16.8    -52.0    2           21.5
```

### net_net_candidates_local.csv

- **存在しない**

### screening_history.csv

- 行数: 717 / 列数: 14 / 更新: 2026-08-22 01:02
- 列: `date`, `sec_code`, `company_name`, `price`, `market_cap`, `ncav`, `ncav_ratio`, `cash_and_equivalents`, `net_cash`, `net_cash_ratio`, `operating_income`, `operating_cf`, `equity_ratio`, `rank`
- ⚠ 全行が空の列: `operating_income`, `operating_cf`

```
      date sec_code    company_name price   market_cap        ncav        ncav_ratio cash_and_equivalents      net_cash     net_cash_ratio operating_income operating_cf equity_ratio rank
2026-08-18     5103  昭和ホールディングス株式会社   4.0  303389384.0   884713000 2.916097420205052         1764250000.0 -1292714000.0 -4.260907164767506                                      41.99    1
2026-08-18     7034 株式会社プロレド・パートナーズ 375.0 4099347750.0 10348348000  2.52438891040654         5667289000.0  3609190000.0 0.8804303074800132                                      85.15    2
```

### invalid_financials.csv

- 行数: 124 / 列数: 12 / 更新: 2026-08-22 01:02
- 列: `sec_code`, `filer_name`, `company_name`, `current_assets`, `total_liabilities`, `total_assets`, `equity_value`, `equity_ratio`, `doc_id`, `fiscal_period`, `bs_date`, `submit_date`
- ⚠ 全行が空の列: `bs_date`

```
sec_code  filer_name company_name current_assets total_liabilities total_assets equity_value equity_ratio   doc_id fiscal_period bs_date submit_date
    9211  株式会社エフ・コード   株式会社エフ・コード    13862559000       24952589000  30091126000   8425954000         28.0 S100YX39    2026-12-31          2026-08-14
    5255 株式会社モンスターラボ  株式会社モンスターラボ     5138005000        8307237000   8913313000    660667000         7.41 S100YX3I    2026-12-31          2026-08-14
```

### invalid_financials_local.csv

- **存在しない**

### processed_docs.csv

- 行数: 3,800 / 列数: 1 / 更新: 2026-08-22 01:02
- 列: `doc_id`

```
  doc_id
S100YJF6
S100YGBS
```

### jpx_alerts_cache.csv

- 行数: 116 / 列数: 4 / 更新: 2026-08-22 01:03
- 列: `コード`, `銘柄名`, `指定年月日`, `区分`

```
 コード              銘柄名      指定年月日 区分
1382           （株）ホーブ 2026/07/23 整理
1726 （株）ビーアールホールディングス 2026/05/15 整理
```

### tse_listed.csv

- **存在しない**

### local_price_history.csv

- 行数: 633 / 列数: 12 / 更新: 2026-08-22 01:02
- 列: `date`, `sec_code`, `name`, `market`, `sector`, `alert_section`, `is_supervised`, `close`, `last_quote`, `volume_k`, `traded`, `turnover`
- ⚠ 全行が空の列: `alert_section`

```
      date sec_code     name market sector alert_section is_supervised close last_quote volume_k traded turnover
2026-08-20     138A 光フードサービス ネクスト市場    小売業                       False           3145.0      0.0  False      0.0
2026-08-20     1438     岐阜造園  メイン市場    建設業                       False           2346.0      0.0  False      0.0
```

### local_prices.csv

- 行数: 317 / 列数: 15 / 更新: 2026-08-22 01:02
- 列: `sec_code`, `name`, `market`, `sector`, `alert_section`, `is_supervised`, `price`, `price_date`, `last_quote`, `traded_days_20`, `avg_turnover_20`, `avg_turnover_20_m`, `days_since_trade`, `window_days`, `as_of`
- ⚠ 全行が空の列: `alert_section`

```
sec_code name market sector alert_section is_supervised  price price_date last_quote traded_days_20 avg_turnover_20 avg_turnover_20_m days_since_trade window_days      as_of
    6623  愛知電 プレミア市場   電気機器                       False 8760.0 2026-08-21                         2       111126000             111.1              0.0           2 2026-08-21
    7485 岡谷鋼機 プレミア市場    卸売業                       False 5080.0 2026-08-21                         2        32541500              32.5              0.0           2 2026-08-21
```

## 出力ページ

- index.html: 57 KB / 更新 2026-08-22 01:02
- shortlist.html: 50 KB / 更新 2026-08-22 01:03
- local.html: 29 KB / 更新 2026-08-22 01:02
