# Q1.1 Online Retail II 数据质量报告

读取 1,067,371 行，日期跨度 2009-12-01 07:45:00 至 2011-12-09 12:50:00。字符串先去首尾空白，空白按缺失计。客户号仅去除 CSV 浮点格式带来的 `.0`。

## 字段和缺失

| 源字段 | 规范字段 | 类型 | 缺失行 | 缺失比例 |
| --- | --- | --- | --- | --- |
| Invoice | invoice_no | string | 0 | 0.00% |
| StockCode | stock_code | string | 0 | 0.00% |
| Description | description | string | 4,382 | 0.41% |
| Quantity | quantity | int64 | 0 | 0.00% |
| InvoiceDate | invoice_datetime | datetime64[ns] | 0 | 0.00% |
| Price | unit_price | float64 | 0 | 0.00% |
| Customer ID | customer_id | string | 243,007 | 22.77% |
| Country | country | string | 0 | 0.00% |

## 数值分布

标准差采用样本口径。

| 字段 | 最小值 | 最大值 | 均值 | 标准差 |
| --- | --- | --- | --- | --- |
| Quantity | -80,995.00 | 80,995.00 | 9.94 | 172.71 |
| Price | -53,594.36 | 38,970.00 | 4.65 | 123.55 |

## 字符串分布

去除空值后统计唯一值和前十频次。同频按字符串排序。

| 字段 | 唯一值 | TOP 10 |
| --- | --- | --- |
| Invoice | 53,628 | 537434 × 1,350、538071 × 1,304、537638 × 1,202、537237 × 1,194、536876 × 1,186、536592 × 1,184、537823 × 1,182、537240 × 1,136、573585 × 1,114、537666 × 1,072 |
| StockCode | 5,304 | 85123A × 5,829、22423 × 4,424、85099B × 4,216、21212 × 3,318、20725 × 3,259、84879 × 2,960、47566 × 2,768、21232 × 2,747、22197 × 2,549、22383 × 2,540 |
| Description | 5,655 | WHITE HANGING HEART T-LIGHT HOLDER × 5,918、REGENCY CAKESTAND 3 TIER × 4,412、JUMBO BAG RED RETROSPOT × 3,469、ASSORTED COLOUR BIRD ORNAMENT × 2,958、PARTY BUNTING × 2,765、STRAWBERRY CERAMIC TRINKET BOX × 2,613、LUNCH BAG  BLACK SKULL. × 2,529、JUMBO STORAGE BAG SUKI × 2,434、HEART OF WICKER SMALL × 2,319、JUMBO SHOPPER VINTAGE RED PAISLEY × 2,297 |
| Customer ID | 5,942 | 17841 × 13,097、14911 × 11,613、12748 × 7,307、14606 × 6,709、14096 × 5,128、15311 × 4,717、14156 × 4,130、14646 × 3,890、13089 × 3,438、16549 × 3,255 |
| Country | 43 | United Kingdom × 981,330、EIRE × 17,866、Germany × 17,624、France × 14,330、Netherlands × 5,140、Spain × 3,811、Switzerland × 3,189、Belgium × 3,123、Portugal × 2,620、Australia × 1,913 |

## 需要核对的现象

1. 数量范围为 -80,995 到 80,995。极值的客户、商品、单价相同，应成对核对。
2. 单价小于零共 5 行。应先判断坏账分录，避免把金额符号当作退货类型。
3. 单价等于零共 6,202 行。零价可能来自库存调整、赠品或测试，用途需靠描述和来源确认。
4. 客户号缺失 243,007 行。丢弃这些行会少计 2,675,169.29 英镑的正价商品销售。
5. 规范化后八字段完全相同的后续行有 34,335 行。缺少行级交易主键，无法仅凭这些字段确认是重复写入还是同单重复扫描。
6. 描述缺失 4,382 行，其中数量不为零的有 4,382 行。描述缺失不代表交易量为零。
7. 非纯数字发票有 19,500 行。只用整数存发票号会丢失取消和调整类型。
