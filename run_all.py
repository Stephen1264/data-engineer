"""从仓库根目录运行全部模块，并汇总各阶段退出状态。"""

import argparse
import subprocess
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent
MODULES = {
    "q1": "q1_data_quality.q1_code",
    "q2": "q2_sql_analysis.run_sql",
    "q3": "q3_etl_pipeline.pipeline",
    "q4": "q4_llm_extraction.extract_reviews",
}
DOCUMENTS = {
    "q5": ("q5_system_design/real_time_pipeline_design.md",),
    "bonus": ("bonus/q6_1_ai_collaboration.md", "bonus/q6_2_business_insights.md"),
}


def main() -> int:
    choices = [*MODULES, *DOCUMENTS]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=choices, default=choices, help="独立运行指定模块")
    args = parser.parse_args()
    results = {}
    for name in dict.fromkeys(args.only):
        started = perf_counter()
        print(f"\n===== {name.upper()} =====", flush=True)
        try:
            if name in MODULES:
                process = subprocess.run(
                    [sys.executable, "-X", "utf8", "-m", MODULES[name]], cwd=ROOT, check=False,
                )
                results[name] = process.returncode == 0
            else:
                for filename in DOCUMENTS[name]:
                    if not (ROOT / filename).read_text(encoding="utf-8").strip():
                        raise ValueError(f"文档为空：{filename}")
                    print(filename, flush=True)
                results[name] = True
        except (OSError, ValueError) as error:
            results[name] = False
            print(f"{name} 执行失败：{error}", file=sys.stderr, flush=True)
        status = "成功" if results[name] else "失败"
        print(f"{name.upper()} {status}，用时 {perf_counter() - started:.2f} 秒", flush=True)
    print("\n汇总 " + "，".join(f"{name.upper()} {'成功' if ok else '失败'}" for name, ok in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
