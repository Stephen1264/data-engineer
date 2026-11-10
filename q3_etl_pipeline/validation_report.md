# Q3 数据校验报告

源数据 1,067,371 行。RFM 基准日为整个快照最后一天 2011-12-09。
销售事实统计正价实物毛额。取消事件单列。已匹配行不会删除原销售。

## sales_facts

行数 **1,036,977**。

| 字段 | 类型 | 空值数 | 空值率 |
| --- | --- | ---: | ---: |
| invoice_no | string | 0 | 0.00% |
| stock_code | string | 0 | 0.00% |
| description | string | 0 | 0.00% |
| quantity | int64 | 0 | 0.00% |
| unit_price | float64 | 0 | 0.00% |
| total_amount | float64 | 0 | 0.00% |
| invoice_datetime | datetime64[ns] | 0 | 0.00% |
| customer_id | string | 234,326 | 22.60% |
| country | string | 0 | 0.00% |

| 指标 | 最小 | 中位数 | P95 | 最大 |
| --- | ---: | ---: | ---: | ---: |
| quantity | 1.00 | 3.00 | 30.00 | 80,995.00 |
| unit_price | 0.00 | 2.10 | 9.95 | 1,157.15 |
| total_amount | 0.00 | 9.96 | 59.40 | 168,469.60 |

## customer_features

行数 **5,852**。

| 字段 | 类型 | 空值数 | 空值率 |
| --- | --- | ---: | ---: |
| customer_id | string | 0 | 0.00% |
| recency_days | int64 | 0 | 0.00% |
| frequency | int64 | 0 | 0.00% |
| monetary | float64 | 0 | 0.00% |
| first_purchase_date | datetime64[ns] | 0 | 0.00% |
| last_purchase_date | datetime64[ns] | 0 | 0.00% |
| unique_products | int64 | 0 | 0.00% |
| country | string | 0 | 0.00% |
| is_one_time_buyer | bool | 0 | 0.00% |

| 指标 | 最小 | 中位数 | P95 | 最大 |
| --- | ---: | ---: | ---: | ---: |
| recency_days | 0.00 | 95.00 | 623.00 | 738.00 |
| frequency | 1.00 | 3.00 | 20.00 | 373.00 |
| monetary | 2.95 | 880.38 | 9,447.67 | 608,821.65 |
| unique_products | 1.00 | 45.00 | 281.00 | 2,546.00 |

## returns_log

行数 **19,494**。

| 字段 | 类型 | 空值数 | 空值率 |
| --- | --- | ---: | ---: |
| invoice_no | string | 0 | 0.00% |
| stock_code | string | 0 | 0.00% |
| description | string | 0 | 0.00% |
| quantity | Int64 | 0 | 0.00% |
| unit_price | float64 | 0 | 0.00% |
| total_amount | float64 | 0 | 0.00% |
| invoice_datetime | datetime64[ns] | 0 | 0.00% |
| customer_id | string | 750 | 3.85% |
| country | string | 0 | 0.00% |
| matched_original_invoice | string | 13,191 | 67.67% |

| 指标 | 最小 | 中位数 | P95 | 最大 |
| --- | ---: | ---: | ---: | ---: |
| quantity | -80,995.00 | -2.00 | -1.00 | 1.00 |
| total_amount | -168,469.60 | -8.95 | -1.25 | 373.57 |

## 对账和取消匹配

- 商品销售毛额 £20,109,634.04，匿名行 234,326 条。
- RFM 消费额 £17,434,464.75，与有客户号的销售事实金额一致。单次购买客户 1,618 位。
- 6,303 条取消找到原单，占取消行 32.33%。参与匹配的正向候选 13,085 条。
- 未匹配原因互斥。缺客户号 750 条，非实物、数量或日期不合格 810 条，严格早于取消的同量候选不存在 11,424 条，较早候选已被其它取消占用 207 条。
- 键为客户、商品和取消数量绝对值。优先最近的可用正向行，同分钟的多笔正向行按源行序取最后一笔。同分钟的正向与取消不配对，避免无法判断先后时建立关联。
- 部分退货、合并退货、快照外订单保留为空。匹配结果用于分析，实际退款应依赖原单行号。
- 通过字段类型、行数、金额守恒、客户唯一性、取消覆盖率和时间方向断言。
