"""生成商品销售事实、RFM 特征和取消事件表。"""

import logging
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from retail import FACT_FIELDS, load_data, product_code, real_sale_mask

HERE = Path(__file__).resolve().parent
LOGGER = logging.getLogger("零售 ETL")
MATCH_KEY = ["customer_id", "stock_code", "quantity_abs"]
RFM_FIELDS = [
    "customer_id", "recency_days", "frequency", "monetary", "first_purchase_date",
    "last_purchase_date", "unique_products", "country", "is_one_time_buyer",
]


@contextmanager
def step(name: str):
    started = perf_counter()
    LOGGER.info("开始 %s", name)
    try:
        yield
    except Exception:
        LOGGER.exception("%s 失败", name)
        raise
    LOGGER.info("完成 %s，用时 %.2f 秒", name, perf_counter() - started)


def filter_real_sales(data: pd.DataFrame) -> pd.DataFrame:
    facts = data.loc[real_sale_mask(data), list(FACT_FIELDS)].copy()
    facts["quantity"] = facts["quantity"].astype("int64")
    return facts


def compute_rfm(sales: pd.DataFrame, snapshot_date: pd.Timestamp) -> pd.DataFrame:
    known = sales.loc[sales["customer_id"].notna()]
    features = known.groupby("customer_id", sort=True).agg(
        frequency=("invoice_no", "nunique"),
        monetary=("total_amount", "sum"),
        first_purchase_date=("invoice_datetime", "min"),
        last_purchase_date=("invoice_datetime", "max"),
        unique_products=("stock_code", "nunique"),
    )
    for field in ("first_purchase_date", "last_purchase_date"):
        features[field] = features[field].dt.normalize()
    features["recency_days"] = (snapshot_date - features["last_purchase_date"]).dt.days
    country_orders = (
        known[["customer_id", "invoice_no", "country"]]
        .drop_duplicates()
        .groupby(["customer_id", "country"], sort=False)
        .size()
        .rename("invoices")
        .reset_index()
    )
    country = (
        country_orders.sort_values(["customer_id", "invoices", "country"], ascending=[True, False, True])
        .drop_duplicates("customer_id")
        .set_index("customer_id")["country"]
    )
    features["country"] = country
    features["is_one_time_buyer"] = features["frequency"].eq(1)
    return features.reset_index()[RFM_FIELDS]


def match_returns(data: pd.DataFrame, sales: pd.DataFrame):
    returns = data.loc[data["invoice_no"].str.startswith("C", na=False), list(FACT_FIELDS)].copy()
    quantity = returns["quantity"]
    integral = np.isfinite(quantity) & quantity.mod(1).eq(0)
    returns["quantity"] = quantity.where(integral).astype("Int64")
    missing_customer = returns["customer_id"].isna()
    eligible = (
        ~missing_customer & product_code(returns["stock_code"])
        & returns["invoice_datetime"].notna() & returns["quantity"].lt(0).fillna(False)
    )
    cancellations = returns.loc[eligible, ["customer_id", "stock_code", "quantity", "invoice_datetime"]].copy()
    cancellations["quantity_abs"] = -cancellations.pop("quantity").astype("int64")
    candidates = sales[["customer_id", "stock_code", "quantity", "invoice_datetime"]].rename(
        columns={"quantity": "quantity_abs"},
    )
    candidates = candidates.reset_index(names="source_row").merge(
        cancellations[MATCH_KEY].drop_duplicates(), on=MATCH_KEY, how="inner",
    )
    events = pd.concat([
        cancellations.reset_index(names="source_row").assign(is_sale=False),
        candidates.assign(is_sale=True),
    ], ignore_index=True).sort_values(["invoice_datetime", "is_sale", "source_row"])

    available = defaultdict(list)
    linked_rows = {}
    stats = Counter(
        missing_customer=int(missing_customer.sum()),
        ineligible=int((~eligible & ~missing_customer).sum()),
        candidates=len(candidates),
    )
    # 只遍历有匹配键的销售候选和取消行。同时间先处理取消，确保严格早于。
    for customer, sku, count, row, is_sale in events[MATCH_KEY + ["source_row", "is_sale"]].itertuples(
        index=False, name=None,
    ):
        key = (customer, sku, count)
        if is_sale:
            available[key].append(row)
        elif available.get(key):
            linked_rows[row] = available[key].pop()
        elif key in available:
            stats["consumed"] += 1
        else:
            stats["no_prior_exact"] += 1

    linked = pd.Series(linked_rows, dtype="Int64").reindex(returns.index)
    returns["matched_original_invoice"] = linked.map(sales["invoice_no"]).astype("string")
    stats["matched"] = len(linked_rows)
    return returns, linked, stats


def validate_output(data, sales, features, returns, links, stats, snapshot_date) -> None:
    assert list(sales.columns) == list(FACT_FIELDS), "销售事实字段错误"
    assert list(features.columns) == RFM_FIELDS, "RFM 字段错误"
    assert list(returns.columns) == [*FACT_FIELDS, "matched_original_invoice"], "取消表字段错误"
    assert len(sales) == int(real_sale_mask(data).sum()), "销售过滤数量不一致"
    assert sales["quantity"].gt(0).all() and sales["unit_price"].gt(0).all(), "销售数量或单价不为正"
    assert np.isfinite(sales["total_amount"]).all(), "销售金额非有限数"
    assert np.allclose(sales["total_amount"], sales["quantity"] * sales["unit_price"]), "销售金额未对账"
    assert pd.api.types.is_datetime64_any_dtype(sales["invoice_datetime"]), "销售日期类型错误"
    for table in (sales, returns):
        for field in ("invoice_no", "stock_code", "customer_id"):
            assert isinstance(table[field].dtype, pd.StringDtype), f"{field} 不是字符串"
    assert features["customer_id"].notna().all() and features["customer_id"].is_unique, "客户主键不唯一"
    assert len(features) == sales["customer_id"].nunique(), "RFM 客户覆盖不完整"
    assert np.isclose(features["monetary"].sum(), sales.loc[sales["customer_id"].notna(), "total_amount"].sum())
    assert features["first_purchase_date"].le(features["last_purchase_date"]).all(), "首购晚于末购"
    assert features["recency_days"].ge(0).all(), "最近购买天数为负"
    assert features["recency_days"].eq((snapshot_date - features["last_purchase_date"]).dt.days).all()
    assert features["frequency"].ge(1).all() and features["unique_products"].ge(1).all(), "RFM 计数异常"
    assert features["is_one_time_buyer"].eq(features["frequency"].eq(1)).all(), "单次购买标志错误"
    assert returns.index.equals(data.index[data["invoice_no"].str.startswith("C", na=False)]), "取消表漏行"
    assert sales.index.intersection(returns.index).empty, "同一源行进入了销售和取消表"
    assert len(returns) == sum(stats[key] for key in (
        "matched", "missing_customer", "ineligible", "consumed", "no_prior_exact",
    )), "取消表匹配状态未覆盖"
    matched = links.dropna()
    assert matched.is_unique, "一笔销售被匹配多次"
    original = sales.loc[matched.astype("int64").to_numpy()].reset_index(drop=True)
    canceled = returns.loc[matched.index].reset_index(drop=True)
    for field in ("customer_id", "stock_code"):
        assert original[field].eq(canceled[field]).all(), f"取消匹配的 {field} 不一致"
    assert canceled["matched_original_invoice"].eq(original["invoice_no"]).all(), "原始发票映射错误"
    assert canceled["quantity"].eq(-original["quantity"]).all(), "匹配数量未严格相反"
    assert original["invoice_datetime"].lt(canceled["invoice_datetime"]).all(), "匹配到同时或未来的销售"


def validation_report(data, sales, features, returns, stats, snapshot_date) -> str:
    lines = [
        "# Q3 数据校验报告", "",
        f"源数据 {len(data):,} 行。RFM 基准日为整个快照最后一天 {snapshot_date.date()}。",
        "销售事实统计正价实物毛额。取消事件单列。已匹配行不会删除原销售。",
    ]
    tables = (
        ("sales_facts", sales, ("quantity", "unit_price", "total_amount")),
        ("customer_features", features, ("recency_days", "frequency", "monetary", "unique_products")),
        ("returns_log", returns, ("quantity", "total_amount")),
    )
    for name, frame, metrics in tables:
        lines.extend([
            "", f"## {name}", "", f"行数 **{len(frame):,}**。", "",
            "| 字段 | 类型 | 空值数 | 空值率 |", "| --- | --- | ---: | ---: |",
        ])
        for field, dtype in frame.dtypes.items():
            count = int(frame[field].isna().sum())
            rate = count / len(frame) if len(frame) else 0.0
            lines.append(f"| {field} | {dtype} | {count:,} | {rate:.2%} |")
        lines.extend(["", "| 指标 | 最小 | 中位数 | P95 | 最大 |", "| --- | ---: | ---: | ---: | ---: |"])
        for metric in metrics:
            values = frame[metric].dropna()
            formatted = [
                f"{values.quantile(q):,.2f}" if len(values) else "无"
                for q in (0, 0.5, 0.95, 1)
            ]
            lines.append(f"| {metric} | {' | '.join(formatted)} |")
    matched_share = stats["matched"] / len(returns) if len(returns) else 0.0
    lines.extend([
        "", "## 对账和取消匹配", "",
        f"- 商品销售毛额 £{sales['total_amount'].sum():,.2f}，"
        f"匿名行 {sales['customer_id'].isna().sum():,} 条。",
        f"- RFM 消费额 £{features['monetary'].sum():,.2f}，与有客户号的销售事实金额一致。"
        f"单次购买客户 {features['is_one_time_buyer'].sum():,} 位。",
        f"- {stats['matched']:,} 条取消找到原单，占取消行 {matched_share:.2%}。"
        f"参与匹配的正向候选 {stats['candidates']:,} 条。",
        f"- 未匹配原因互斥。缺客户号 {stats['missing_customer']:,} 条，"
        f"非实物、数量或日期不合格 {stats['ineligible']:,} 条，"
        f"严格早于取消的同量候选不存在 {stats['no_prior_exact']:,} 条，"
        f"较早候选已被其它取消占用 {stats['consumed']:,} 条。",
        "- 键为客户、商品和取消数量绝对值。优先最近的可用正向行，同分钟的多笔正向行按源行序取最后一笔。"
        "同分钟的正向与取消不配对，避免无法判断先后时建立关联。",
        "- 部分退货、合并退货、快照外订单保留为空。匹配结果用于分析，实际退款应依赖原单行号。",
        "- 通过字段类型、行数、金额守恒、客户唯一性、取消覆盖率和时间方向断言。", "",
    ])
    return "\n".join(lines)


def write_outputs(data, sales, features, returns, stats, snapshot_date) -> None:
    target = HERE / "outputs"
    target.mkdir(exist_ok=True)
    outputs = {
        "sales_facts.parquet": sales,
        "customer_features.parquet": features,
        "returns_log.parquet": returns,
    }
    with TemporaryDirectory(prefix=".stage-", dir=target) as temporary:
        staging = Path(temporary)
        for name, frame in outputs.items():
            path = staging / name
            frame.to_parquet(path, engine="pyarrow", compression="zstd", index=False)
            stored = pq.ParquetFile(path)
            assert stored.metadata.num_rows == len(frame) and stored.schema_arrow.names == list(frame.columns), name
            stored.close()
        report = staging / "validation_report.md"
        report.write_text(validation_report(data, sales, features, returns, stats, snapshot_date), encoding="utf-8", newline="\n")
        for name in outputs:
            (staging / name).replace(target / name)
        report.replace(HERE / report.name)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(HERE / "pipeline_log.txt", mode="w", encoding="utf-8")],
    )
    started = perf_counter()
    with step("读取零售数据"):
        data = load_data()
        snapshot_date = data["invoice_datetime"].max()
        if pd.isna(snapshot_date):
            raise ValueError("零售数据中没有可用的交易日期")
        snapshot_date = snapshot_date.normalize()
    with step("提取销售事实"):
        sales = filter_real_sales(data)
    with step("计算 RFM"):
        features = compute_rfm(sales, snapshot_date)
    with step("匹配取消事件"):
        returns, links, stats = match_returns(data, sales)
        LOGGER.info(
            "取消 %d 行，匹配 %d 行，未匹配 %d 行。状态分布 %s",
            len(returns), stats["matched"], len(returns) - stats["matched"], dict(stats),
        )
    with step("校验和写入三个 Parquet"):
        validate_output(data, sales, features, returns, links, stats, snapshot_date)
        write_outputs(data, sales, features, returns, stats, snapshot_date)
    LOGGER.info("源数据 %d 行，销售 %d 行，客户 %d 位，总耗时 %.2f 秒", len(data), len(sales), len(features), perf_counter() - started)


if __name__ == "__main__":
    main()
