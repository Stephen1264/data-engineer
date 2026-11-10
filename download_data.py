"""从 Kaggle 获取公开数据集，保留已经准备好的本地 CSV。"""

import argparse
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("GEKKO_DATA_DIR", ROOT / "data")).resolve()
RETAIL_CSV = "online_retail_ii.csv"
OLIST_CSV = (
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
)
DATASETS = {
    "retail": ("mashlyn/online-retail-ii-uci", Path("."), (RETAIL_CSV,)),
    "olist": ("olistbr/brazilian-ecommerce", Path("olist"), OLIST_CSV),
}


def ensure_dataset(dataset: str) -> Path:
    """补齐一份数据集，先验证 ZIP 中的所有目标文件再移动。"""
    slug, relative_dir, filenames = DATASETS[dataset]
    directory = DATA_DIR / relative_dir
    directory.mkdir(parents=True, exist_ok=True)
    missing = [
        name for name in filenames
        if not (directory / name).is_file() or (directory / name).stat().st_size == 0
    ]
    if not missing:
        return directory

    url = f"https://www.kaggle.com/api/v1/datasets/download/{slug}"
    print(f"下载 {slug} → {directory}", flush=True)
    with TemporaryDirectory(prefix=".download-", dir=directory) as staging_dir:
        staging = Path(staging_dir)
        archive = staging / "dataset.zip"
        for attempt in range(2):
            try:
                request = Request(url, headers={"User-Agent": "gekkolab-assessment/1.0"})
                with urlopen(request, timeout=30) as response, archive.open("wb") as target:
                    shutil.copyfileobj(response, target, length=1024 * 1024)
                with ZipFile(archive) as bundle:
                    for name in missing:
                        matches = [
                            entry for entry in bundle.infolist()
                            if not entry.is_dir() and Path(entry.filename).name.casefold() == name
                        ]
                        if len(matches) != 1 or matches[0].file_size == 0:
                            raise ValueError(f"Kaggle 压缩包中的 {name} 缺失、为空或重名")
                        with bundle.open(matches[0]) as source, (staging / name).open("wb") as target:
                            shutil.copyfileobj(source, target, length=1024 * 1024)
                break
            except (OSError, BadZipFile, ValueError) as error:
                if attempt == 1:
                    raise RuntimeError(
                        f"无法下载或验证 {slug}。请检查网络，或将 Kaggle 原始 CSV 放入 {directory}。"
                    ) from error
        for name in missing:
            (staging / name).replace(directory / name)
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", default="all", choices=["all", *DATASETS])
    selection = parser.parse_args().dataset
    for key in DATASETS if selection == "all" else [selection]:
        ensure_dataset(key)
