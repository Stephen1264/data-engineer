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

默认用同一份输入和提示词指纹复用已校验的本地推理结果。空缓存时可独立跑规则基线。重跑推理需要 llama.cpp 和 Qwen2.5-3B Instruct Q4_K_M GGUF。测试版本为 llama.cpp b12241，模型是 Ollama 公开清单中的 `qwen2.5:3b`，权重 SHA-256 为 `5ee4f07cdb9beadbbb293e85803c569b01bd37ed059d2715faa7bb405f31caa6`。可从官方模型或发行清单取得相同权重。 [llama.cpp 发行页](https://github.com/ggml-org/llama.cpp/releases/tag/b12241) · [模型清单](https://ollama.com/library/qwen2.5:3b)

```bash
llama-server --model qwen2.5-3b.gguf --alias qwen2.5-3b --host 127.0.0.1 --port 8080 --ctx-size 8192 --parallel 2 -ngl 99 --no-ui
python -m q4_llm_extraction.extract_reviews --llm-url http://127.0.0.1:8080 --llm-limit 300 --refresh-llm
python -m q4_llm_extraction.evaluate
```

如在共享机器使用本地服务，可给服务设置 API 密钥，并给客户端设置 `GEKKO_LLM_API_KEY`。CPU 环境可以将 GPU 层设为 0，并按吞吐调低推理上限。默认运行使用随提交提供的模型结果缓存，便于在无 GPU 的环境复现。
