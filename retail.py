"""Q1 和 Q3 共享的 Online Retail II 字段及业务口径。"""

import numpy as np
import pandas as pd

from download_data import RETAIL_CSV, ensure_dataset

COLUMNS = {
    "Invoice": "invoice_no",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_datetime",
    "Price": "unit_price",
    "Customer ID": "customer_id",
    "Country": "country",
}
TEXT_FIELDS = ("Invoice", "StockCode", "Description", "Customer ID", "Country")
FACT_FIELDS = (
    "invoice_no", "stock_code", "description", "quantity", "unit_price",
    "total_amount", "invoice_datetime", "customer_id", "country",
)


def load_data() -> pd.DataFrame:
    """保留源记录顺序和空值，将标识符读作文本。"""
    path = ensure_dataset("retail") / RETAIL_CSV
    data = pd.read_csv(
        path, dtype={name: "string" for name in TEXT_FIELDS},
        keep_default_na=False, na_values=[""], encoding="utf-8-sig",
    )
    missing = COLUMNS.keys() - set(data.columns)
    if missing or data.empty:
        raise ValueError(f"Online Retail II 缺少字段或无数据，缺列 {sorted(missing)}")
    data = data[list(COLUMNS)].rename(columns=COLUMNS)
    for name in TEXT_FIELDS:
        field = COLUMNS[name]
        data[field] = data[field].str.strip().replace("", pd.NA)
    data["customer_id"] = data["customer_id"].str.replace(r"^([0-9]+)\.0+$", r"\1", regex=True)
    data["invoice_datetime"] = pd.to_datetime(
        data["invoice_datetime"], format="ISO8601", errors="coerce",
    )
    for field in ("quantity", "unit_price"):
        data[field] = pd.to_numeric(data[field], errors="coerce")
    data["unit_price"] = data["unit_price"].astype("float64")
    data["total_amount"] = data["quantity"] * data["unit_price"]
    return data


def product_code(code: pd.Series) -> pd.Series:
    """数字 SKU 和已观察到的实物编码族。后续仍须验证数量、单价及日期。"""
    normal_sku = code.str.fullmatch(r"[0-9]+[A-Za-z]*", na=False)
    catalog_sku = code.str.fullmatch(r"DCGS[0-9]{4}[A-Z]?|PADS|SP1002", na=False)
    return normal_sku | catalog_sku


def real_sale_mask(data: pd.DataFrame) -> pd.Series:
    """统计正价实物销售，保留匿名和事后被取消的原销售。"""
    quantity = data["quantity"]
    return (
        data["invoice_no"].str.fullmatch(r"[0-9]+", na=False)
        & product_code(data["stock_code"])
        & quantity.gt(0) & quantity.mod(1).eq(0)
        & data["unit_price"].gt(0) & np.isfinite(data["total_amount"])
        & data["invoice_datetime"].notna()
    )
