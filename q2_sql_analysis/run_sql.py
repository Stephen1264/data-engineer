"""把 Olist 原始 CSV 导入独立的 MySQL 数据库并执行 Q2 查询。"""

import argparse
import csv
import hashlib
import os
import re
from itertools import islice
from pathlib import Path
from statistics import median
from time import perf_counter

import mysql.connector

from download_data import OLIST_CSV, ensure_dataset

HERE = Path(__file__).resolve().parent
TABLES = {
    filename.removeprefix("olist_").removesuffix("_dataset.csv").removesuffix(".csv"): filename
    for filename in OLIST_CSV
}
QUERIES = (
    "q2_1_translation_gap.sql", "q2_2_monthly_metrics.sql",
    "q2_3_top_sellers.sql", "q2_4_optimized.sql",
)
ORIGINAL = """
SELECT c.customer_state, COUNT(DISTINCT o.order_id) AS orders,
       SUM(oi.price) AS revenue, AVG(r.review_score) AS avg_score
FROM orders o
LEFT JOIN customers c ON o.customer_id = c.customer_id
LEFT JOIN order_items oi ON o.order_id = oi.order_id
LEFT JOIN order_reviews r ON o.order_id = r.order_id
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2017-01-01'
  AND LOWER(c.customer_city) LIKE '%sao%'
GROUP BY c.customer_state
ORDER BY revenue DESC
"""


def connect():
    return mysql.connector.connect(
        host=os.environ.get("GEKKO_MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("GEKKO_MYSQL_PORT", "3306")),
        user=os.environ.get("GEKKO_MYSQL_USER", "root"),
        password=os.environ.get("GEKKO_MYSQL_PASSWORD", ""),
        charset="utf8mb4", autocommit=True, connection_timeout=8,
    )


def snapshot_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for name in OLIST_CSV:
        digest.update(name.encode("ascii") + b"\0")
        with (directory / name).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def import_csv(cursor, table: str, path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        columns = next(reader)
        if not columns or any(not re.fullmatch(r"[a-z_][a-z_0-9]*", name) for name in columns):
            raise ValueError(f"{path.name} 的表头不符合预期")
        column_sql = ", ".join(f"`{name}`" for name in columns)
        values_sql = ", ".join(["%s"] * len(columns))
        statement = f"INSERT INTO `{table}` ({column_sql}) VALUES ({values_sql})"
        count = 0
        while rows := list(islice(reader, 4000)):
            if any(len(row) != len(columns) for row in rows):
                raise ValueError(f"{path.name} 第 {reader.line_num} 行附近的字段数不一致")
            values = [tuple(value if value != "" else None for value in row) for row in rows]
            cursor.executemany(statement, values)
            if cursor.rowcount != len(values):
                raise ValueError(f"{table} 本批插入行数与 CSV 不一致")
            count += cursor.rowcount
        if count == 0:
            raise ValueError(f"{path.name} 没有数据行")
        return count


def load_snapshot(connection, cursor, directory: Path) -> None:
    for statement in (HERE / "schema.sql").read_text(encoding="utf-8").split(";"):
        if statement.strip():
            cursor.execute(statement)
    digest = snapshot_digest(directory)
    cursor.execute("SELECT content_sha256 FROM gekkolab_load_manifest WHERE id = 1")
    current = cursor.fetchone()
    if current == (digest,):
        print("Olist 九表快照指纹一致，复用已导入数据", flush=True)
        return
    if current is None:
        for table in TABLES:
            cursor.execute(f"SELECT 1 FROM `{table}` LIMIT 1")
            if cursor.fetchone() is not None:
                raise RuntimeError("数据库包含未经本脚本管理的数据，请指定空的笔试数据库")

    connection.start_transaction()
    try:
        for table, name in TABLES.items():
            if current is not None:
                cursor.execute(f"DELETE FROM `{table}`")
            count = import_csv(cursor, table, directory / name)
            print(f"  {table}: {count:,} 行", flush=True)
        if snapshot_digest(directory) != digest:
            raise RuntimeError("导入期间源文件有变动，请重新运行")
        cursor.execute("DELETE FROM gekkolab_load_manifest WHERE id = 1")
        cursor.execute(
            "INSERT INTO gekkolab_load_manifest (id, content_sha256) VALUES (1, %s)", (digest,),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def query(cursor, statement: str):
    cursor.execute(statement)
    return cursor.fetchall()


def benchmark(cursor) -> None:
    optimized = (HERE / QUERIES[-1]).read_text(encoding="utf-8")
    cases = {"原题": ORIGINAL, "优化": optimized}
    for statement in cases.values():
        query(cursor, statement)
    timings = {label: [] for label in cases}
    for _ in range(5):
        for label, statement in cases.items():
            start = perf_counter()
            rows = query(cursor, statement)
            timings[label].append(1000 * (perf_counter() - start))
    for label, statement in cases.items():
        rows = query(cursor, statement)
        print(f"\n{label}五次中位数 {median(timings[label]):.1f} ms，分组 {len(rows)}")
        print(f"商品价合计 {sum(row[2] for row in rows):,.2f}")
        print("EXPLAIN ANALYZE")
        print(query(cursor, "EXPLAIN ANALYZE " + statement)[0][0])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", action="store_true", help="比较 Q2.4 并输出执行计划")
    args = parser.parse_args()
    database = os.environ.get("GEKKO_MYSQL_DATABASE", "gekkolab_olist")
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]{0,62}", database):
        raise ValueError("GEKKO_MYSQL_DATABASE 需为安全的 SQL 标识符")
    directory = ensure_dataset("olist")
    with connect() as connection, connection.cursor() as cursor:
        version = query(cursor, "SELECT VERSION()")[0][0]
        if "mariadb" in version.lower() or int(version.split(".")[0]) < 8:
            raise RuntimeError(f"需要 MySQL 8.0 或更新版本，当前为 {version}")
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        cursor.execute(f"USE `{database}`")
        print(f"MySQL {version}，数据库 {database}", flush=True)
        lock_name = "gekkolab:" + hashlib.sha256(database.lower().encode()).hexdigest()[:48]
        cursor.execute("SELECT GET_LOCK(%s, 60)", (lock_name,))
        if cursor.fetchone() != (1,):
            raise RuntimeError("另一个 Q2 导入仍在执行")
        try:
            load_snapshot(connection, cursor, directory)
        finally:
            cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
            cursor.fetchone()
        for filename in QUERIES:
            rows = query(cursor, (HERE / filename).read_text(encoding="utf-8"))
            print(f"\n{filename}，{len(rows):,} 行")
            print("\t".join(cursor.column_names))
            for row in rows:
                print("\t".join("NULL" if value is None else str(value) for value in row))
        if args.benchmark:
            benchmark(cursor)


if __name__ == "__main__":
    main()
