"""Q1 生成字段画像、异常证据和下游口径对比。"""

from pathlib import Path

import pandas as pd

from retail import COLUMNS, load_data, real_sale_mask

HERE = Path(__file__).resolve().parent
CODE_MEANINGS = {
    "ADJUST": "人工账务或库存调整",
    "ADJUST2": "第二类人工调整",
    "AMAZONFEE": "Amazon 平台费",
    "B": "坏账调整",
    "BANK CHARGES": "银行手续费",
    "C2": "运费",
    "C3": "无描述，业务用途待核对",
    "CRUK": "CRUK 佣金",
    "D": "折扣",
    "DOT": "网店运费",
    "GIFT": "疑似礼品项，缺少描述",
    "M": "人工记账项",
    "PADS": "与靠垫搭配的实体配件",
    "POST": "邮费",
    "S": "样品",
    "SP1002": "儿童黑板画架实物",
    "TEST001": "测试商品",
    "TEST002": "测试商品",
}


def md_table(headers, rows) -> str:
    def cell(value):
        return str(value).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")

    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
    return "\n".join(lines)


def money(value) -> str:
    return f"{value:,.2f}"


def share(part, whole) -> str:
    return f"{part / whole:.2%}" if whole else "分母为零"


def top_text(values, n=10) -> str:
    counts = values.dropna().value_counts().rename_axis("值").reset_index(name="行数")
    counts = counts.sort_values(["行数", "值"], ascending=[False, True])
    return "、".join(f"{value} × {count:,}" for value, count in counts.head(n).itertuples(index=False, name=None))


def profile(data: pd.DataFrame) -> str:
    base = data[list(COLUMNS.values())]
    fields = [
        (source, col, str(base[col].dtype), f"{base[col].isna().sum():,}", share(base[col].isna().sum(), len(data)))
        for source, col in COLUMNS.items()
    ]
    numeric = [
        (name, *(money(stat) for stat in (values.min(), values.max(), values.mean(), values.std(ddof=1))))
        for name, values in (("Quantity", data["quantity"]), ("Price", data["unit_price"]))
    ]
    strings = [
        (source, f"{data[name].nunique():,}", top_text(data[name]))
        for source, name in COLUMNS.items() if isinstance(data[name].dtype, pd.StringDtype)
    ]
    anonymous_sales = real_sale_mask(data) & data["customer_id"].isna()
    return f"""# Q1.1 Online Retail II 数据质量报告

读取 {len(data):,} 行，日期跨度 {data["invoice_datetime"].min()} 至 {data["invoice_datetime"].max()}。字符串先去首尾空白，空白按缺失计。客户号仅去除 CSV 浮点格式带来的 `.0`。

## 字段和缺失

{md_table(("源字段", "规范字段", "类型", "缺失行", "缺失比例"), fields)}

## 数值分布

标准差采用样本口径。

{md_table(("字段", "最小值", "最大值", "均值", "标准差"), numeric)}

## 字符串分布

去除空值后统计唯一值和前十频次。同频按字符串排序。

{md_table(("字段", "唯一值", "TOP 10"), strings)}

## 需要核对的现象

1. 数量范围为 {data["quantity"].min():,} 到 {data["quantity"].max():,}。极值的客户、商品、单价相同，应成对核对。
2. 单价小于零共 {data["unit_price"].lt(0).sum():,} 行。应先判断坏账分录，避免把金额符号当作退货类型。
3. 单价等于零共 {data["unit_price"].eq(0).sum():,} 行。零价可能来自库存调整、赠品或测试，用途需靠描述和来源确认。
4. 客户号缺失 {data["customer_id"].isna().sum():,} 行。丢弃这些行会少计 {money(data.loc[anonymous_sales, "total_amount"].sum())} 英镑的正价商品销售。
5. 规范化后八字段完全相同的后续行有 {base.duplicated().sum():,} 行。缺少行级交易主键，无法仅凭这些字段确认是重复写入还是同单重复扫描。
6. 描述缺失 {data["description"].isna().sum():,} 行，其中数量不为零的有 {(data["description"].isna() & data["quantity"].ne(0)).sum():,} 行。描述缺失不代表交易量为零。
7. 非纯数字发票有 {(~data["invoice_no"].str.fullmatch(r"[0-9]+", na=False)).sum():,} 行。只用整数存发票号会丢失取消和调整类型。
"""


def code_meaning(code: str) -> str:
    if code.startswith("gift_"):
        return f"面值 {code.rsplit('_', 1)[-1]} 英镑的礼品券"
    if code.startswith("DCGS"):
        return "店铺自定义编码，含实物或库存变动，按描述和价格区分"
    return CODE_MEANINGS.get(code.upper(), "未能仅凭编码确认，保留作核对")


def display_rows(rows: pd.DataFrame) -> str:
    fields = rows[list(COLUMNS.values())].astype("object")
    return md_table(
        ("发票", "商品码", "描述", "数量", "日期", "单价", "客户", "国家"),
        fields.where(fields.notna(), "缺失").itertuples(index=False, name=None),
    )


def findings(data: pd.DataFrame) -> str:
    amount = data["total_amount"]
    prefix = data["invoice_no"].str.extract(r"^([A-Za-z]+)", expand=False)
    unusual_invoice = ~data["invoice_no"].str.fullmatch(r"[0-9]+", na=False)
    prefix_data = data.loc[unusual_invoice].assign(prefix=prefix.fillna("其他"))
    prefixes = []
    for name, group in prefix_data.groupby("prefix", sort=True):
        meanings = {"C": "取消或贷项", "A": "坏账调整"}
        prefixes.append((
            name, f"{len(group):,}", f"{group['quantity'].min():,} 至 {group['quantity'].max():,}",
            f"{group['unit_price'].min():,.2f} 至 {group['unit_price'].max():,.2f}",
            money(group["total_amount"].sum()), meanings.get(name, "待核对"),
        ))

    unusual_code = ~data["stock_code"].str.fullmatch(r"[0-9]+[A-Za-z]*", na=False)
    codes = []
    for code, group in data.loc[unusual_code].groupby("stock_code", sort=True, dropna=False):
        examples = "人工调整备注" if str(code).startswith("ADJUST") else top_text(group["description"], 1)
        codes.append((
            code, f"{len(group):,}", money(group["total_amount"].sum()),
            examples or "缺失", code_meaning(str(code)),
        ))

    extreme = data.loc[data["quantity"].isin([data["quantity"].min(), data["quantity"].max()])]
    negative = data.loc[data["unit_price"].lt(0)]
    missing = data["customer_id"].isna()
    sale = data.loc[real_sale_mask(data)]
    segments = []
    for label, mask in (("缺客户号", missing), ("有客户号", ~missing)):
        group = data.loc[mask]
        group_sales = sale.loc[mask.reindex(sale.index)]
        invoice_amounts = group_sales.groupby("invoice_no")["total_amount"].sum()
        segments.append((
            label, f"{len(group):,}", share(len(group), len(data)), money(group["total_amount"].sum()),
            share(group["total_amount"].sum(), amount.sum()), f"{len(invoice_amounts):,}",
            money(invoice_amounts.mean()), top_text(group["country"], 5), top_text(group_sales["stock_code"], 5),
        ))

    return f"""# Q1.2 数据结构与业务判断

原始行的带符号金额定义为 `quantity * unit_price`，下文用英镑，保留所有正负分录。全表带符号金额为 **£{money(amount.sum())}**。各段代码以 `data = retail.load_data()` 为起点，完整计算见 [q1_code.py](q1_code.py)。

## 1. 发票前缀

```python
prefix = data["invoice_no"].str.extract(r"^([A-Za-z]+)", expand=False)
data.loc[prefix.notna()].groupby(prefix)["total_amount"].agg(["size", "sum"])
```

{md_table(("前缀", "行数", "数量范围", "单价范围", "带符号金额", "解释"), prefixes)}

`C` 行以反向数量冲销原单，既包含商品也包含人工项、折扣或邮费。用正价商品行统计毛销售额，用取消行构造退货流并单列冲减额。`A` 行的描述是 Adjust bad debt，库存不因坏账移动。它应进入财务调整账，商品销售和退货量均排除。

## 2. 特殊商品编码

```python
unusual = ~data["stock_code"].str.fullmatch(r"[0-9]+[A-Za-z]*", na=False)
data.loc[unusual].groupby("stock_code")["total_amount"].agg(["size", "sum"])
```

去掉编码首尾空格后，不满足数字或数字加字母格式的行共 **{unusual_code.sum():,}**，占 **{share(unusual_code.sum(), len(data))}**。带符号金额为 **£{money(amount[unusual_code].sum())}**，占全表带符号金额 **{share(amount[unusual_code].sum(), amount.sum())}**。绝对金额占比为 **{share(amount[unusual_code].abs().sum(), amount.abs().sum())}**，用来观察有正负抵消的情况。形态筛查会命中实物编码，例如 `SP1002`、`PADS` 和 `DCGS` 编码族。测试、礼券、费用、坏账和未知业务项分别保留源记录。

{md_table(("编码", "行数", "带符号金额", "高频描述样例", "业务判断"), codes)}

## 3. 极值与负单价

```python
extreme = data[data["quantity"].isin([data["quantity"].min(), data["quantity"].max()])]
negative = data[data["unit_price"] < 0]
```

{display_rows(extreme)}

极值对应同一客户 16446、商品 23843 和单价 £2.08，取消发生在原单后 12 分钟。证据支持成对的下单与撤销事件。是否曾发货或客户是否误填数量需要履约日志验证。保留两行和关联，毛额计入正向交易，带冲销的金额单独核算。

{display_rows(negative)}

负单价行均为 `A` 前缀、`B` 编码、数量 1，客户号缺失。保留在财务审计层，商品毛销售、客户消费与退货数量均排除。

## 4. 匿名记录与客户口径

```python
anonymous = data["customer_id"].isna()
data.groupby(anonymous)["total_amount"].agg(["size", "sum"])
sales = data.loc[real_sale_mask(data)]
sales.groupby([sales["customer_id"].isna(), "invoice_no"])["total_amount"].sum()
```

客单价以正价实物销售按发票汇总后的均值衡量，国家使用原始行分布，高频商品使用正价实物销售行频次。原始行数比例与带符号金额比例使用同一全表范围。

{md_table(("客户身份", "行数", "行数占比", "带符号金额", "金额占比", "商品发票数", "平均客单价 £", "国家 TOP 5", "商品 TOP 5"), segments)}

匿名组集中在英国，SKU 榜与有客户号的组部分重合。商品发票数较少，但平均单张金额更高，和全表金额占比的排序不同。净额分子还含邮费和财务调整。游客购买、未采集会员号或渠道未回填都可以解释这一现象，需要渠道字段或结账日志区分。
"""


def main() -> None:
    data = load_data()
    (HERE / "data_quality_report.md").write_text(profile(data), encoding="utf-8", newline="\n")
    (HERE / "findings.md").write_text(findings(data), encoding="utf-8", newline="\n")
    print(f"Q1 已生成数据质量报告和发现文档，输入 {len(data):,} 行")


if __name__ == "__main__":
    main()
