# Gekko Lab 数据工程笔试提交

候选人 GitHub 账号为 `Stephen1264`。原题在 [README.md](README.md)。实现和验证由 Codex 协助，过程及限制见 [REFLECTION.md](REFLECTION.md)、[TOOLS.md](TOOLS.md) 和 [AI_LOG.md](AI_LOG.md)。

## 从空 data 目录运行

需要 Python 3.10+ 和可连接的 MySQL 8.0+。在仓库根目录创建虚拟环境，激活后安装锁定依赖。

```bash
python -m venv .venv
# Linux 或 macOS
source .venv/bin/activate
# Windows PowerShell 使用 .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

可以使用现有 MySQL 的独立测试库，也可启动本地容器。示例密码只用于本地临时实例。

```bash
docker run --rm --name gekkolab-mysql -d -p 127.0.0.1:3306:3306 -e MYSQL_ROOT_PASSWORD=local_test_password mysql:8.4
# 确认 MySQL 已经可以接受连接
export GEKKO_MYSQL_PASSWORD=local_test_password
python run_all.py
```

PowerShell 用 `$env:GEKKO_MYSQL_PASSWORD = 'local_test_password'` 设置密码，再运行 `python run_all.py`。可选变量 `GEKKO_MYSQL_HOST`、`GEKKO_MYSQL_PORT`、`GEKKO_MYSQL_USER`、`GEKKO_MYSQL_DATABASE` 默认分别为 `127.0.0.1`、`3306`、`root`、`gekkolab_olist`。账号需要独立笔试库的建表和读写权限。导入用数据内容指纹实现重复运行。默认数据路径为仓库的 `data/`，可用 `GEKKO_DATA_DIR` 指定其他目录。

缺少 CSV 时自动从题目指定的两个 Kaggle 数据集下载。若网络无法访问，可按 [原始数据说明](data/README.md) 手动准备文件，统一使用小写 `online_retail_ii.csv`。各阶段独立运行并记录退出状态。若某一阶段失败，其余仍会尝试，汇总退出码为 1。

## 单独复现

| 模块 | 入口 | 主要产物 |
| --- | --- | --- |
| Q1 | `python -m q1_data_quality.q1_code` | [字段画像](q1_data_quality/data_quality_report.md)、[数据发现](q1_data_quality/findings.md)、[清洗策略](q1_data_quality/cleaning_strategy.md) |
| Q2 | `python -m q2_sql_analysis.run_sql --benchmark` | 四条 MySQL 查询及 [执行计划分析](q2_sql_analysis/q2_4_query_optimization.md) |
| Q3 | `python -m q3_etl_pipeline.pipeline` | 本地生成三份 Parquet 和日志，[数据校验报告](q3_etl_pipeline/validation_report.md) |
| Q4 | `python -m q4_llm_extraction.extract_reviews` | [评价结果](q4_llm_extraction/extracted_issues.json)、[成本](q4_llm_extraction/cost_report.md)、[评估](q4_llm_extraction/accuracy_evaluation.md) |
| Q5 | `python run_all.py --only q5` | [系统设计与架构图](q5_system_design/real_time_pipeline_design.md) |
| Q6 | `python run_all.py --only bonus` | [AI 协作](bonus/q6_1_ai_collaboration.md)、[业务建议](bonus/q6_2_business_insights.md) |

```bash
python -m unittest discover -s tests -v
python -m q4_llm_extraction.evaluate
```

## 重跑模型

常规运行会复用已提交的缓存。缓存以正文和提示词指纹校验，空缓存仍可跑规则基线。若需从头重算本地推理，准备 llama.cpp b12241、Qwen3-4B-Instruct-2507 Q4_K_M GGUF，以及解压后的 Argos 葡语到英语 1.9 模型。Qwen 权重 SHA-256 为 `85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9`，Argos 模型包 SHA-256 为 `ae76df6f650895c16f2b582065014fab496755ca846ecb19fae81d51f332a38e`。 [llama.cpp 发行页](https://github.com/ggml-org/llama.cpp/releases/tag/b12241) · [Qwen 权重清单](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M) · [Argos 模型包](https://argos-net.com/v1/translate-pt_en-1_9.argosmodel)

```bash
python -m pip install -r q4_llm_extraction/requirements-model.txt
llama-server --model qwen3-4b-instruct-q4_k_m.gguf --alias qwen3-4b-instruct-2507 --host 127.0.0.1 --port 8080 --ctx-size 24576 --parallel 16 --no-kv-unified --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 --cache-ram 0 -ngl 99 --no-ui
# 模型服务启动后，在另一终端运行
python -m q4_llm_extraction.build_span_cache --llm-url http://127.0.0.1:8080 --translation-model /path/to/translate-pt_en-1_9 --batch-size 4 --workers 16 --checkpoint /tmp/gekkolab-q4-progress.json
python -m q4_llm_extraction.extract_reviews
python -m q4_llm_extraction.evaluate
```

若服务启用了 API 密钥，在客户端设置 `GEKKO_LLM_API_KEY`。续跑文件记录已完成的编号选择，放在仓库外。重算测试用 RTX 4070 Laptop GPU，较慢的机器可能在时限内只生成部分缓存。复现已提交结果只需运行抽取和评估入口。
