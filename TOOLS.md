# 工具与软件使用清单

| 工具 | 解决的问题与实际使用 | 可替代方案 |
| --- | --- | --- |
| Codex | 拆解五个模块，编写代码和中文文档，读原始数据，复算查询，做葡语样本预标及端到端验收。 | 候选人自己实现并安排同伴代码审查及数据复核。 |
| Chrome 与电脑操作工具 | 从 QQ 邮箱核对完整邀请、截止时间和公开 fork 要求。 | 用邮箱客户端阅读原邮件。 |
| PowerShell 及 Python 3.11.9 | 在 Windows 管理隔离环境和本地服务，运行脚本与回归。用标准库 `csv` 和 `Decimal` 独立对账。 | Bash 与同版本 Python 虚拟环境。 |
| pandas 2.3.3 与 NumPy 2.2.6 | 字段画像、布尔掩码、订单与客户聚合、取消候选的等值连接。NumPy 用于金额和有限值断言。 | Polars 表达式或显式分批聚合。 |
| PyArrow 22.0.0 | 写 Zstandard Parquet，核对存储模式与行数。 | Fastparquet 提供另一套 Parquet 引擎。 |
| MySQL Community 8.4.13 | 便携实例在本机回环地址运行，导入 Olist 九表，执行窗口函数与 `EXPLAIN ANALYZE`。 | 用 Docker 运行 MySQL 8.0+，或连接单独的 MySQL 测试库。 |
| MySQL Connector/Python 9.5.0 | 使用参数化批量写入及 InnoDB 事务，运行 SQL 和取执行计划。 | PyMySQL 配合适当的 MySQL 认证依赖。 |
| Kaggle 数据下载 API、curl 与 Python 标准库 | curl 核对下载及压缩包清单，交付脚本用 `urllib` 公开下载、用 `zipfile` 校验与规范文件名。 | Kaggle CLI、kagglehub 或手动下载。 |
| llama.cpp b12241 与 Qwen | 初版 Q4 与 Q6.1 用 Qwen2.5-3B 和 Vulkan。改版 Q4 用 CUDA 和 Qwen3-4B-Instruct-2507 批量选证据并复核类别，记录生成 token 与提示缓存用量。 | 用支持语法约束的本地推理服务，并重做吞吐和准确率验证。 |
| Argos PT→EN 1.9、CTranslate2 4.6.0 和 SentencePiece 0.2.1 | 在 CPU 上批量翻译复核通过的葡语原文，去重句子以减少计算。 | 用本地葡英翻译模型逐句译文，并重新抽查。 |
| unittest 与 Windows 进程内存接口 | 核对退货时间边界、候选只用一次和葡语证据，记录 ETL 进程内存峰值。 | pytest、系统性能监视器。 |
| Git、GitHub CLI 与 GitHub 连接器 | 拉取原始提交历史，按模块提交，核对 fork 关系和发布版本。 | GitHub 网页创建 fork，命令行 Git 提交和推送。 |

## 使用依据

- 用数据集主页确认输入来源。 [Online Retail II](https://www.kaggle.com/datasets/mashlyn/online-retail-ii-uci) · [Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
- 用厂商文档确认 MySQL 便携包和执行计划。 [MySQL Windows ZIP](https://dev.mysql.com/downloads/mysql/8.4.html?os=3) · [EXPLAIN](https://dev.mysql.com/doc/refman/8.0/en/explain.html)
- 用发行清单校验本地推理与翻译权重，生产架构估算用官方标准 token 价格。 [Qwen 清单](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M) · [Argos 索引](https://github.com/argosopentech/argospm-index) · [OpenAI 定价](https://developers.openai.com/api/docs/pricing)

选择参数化批量写入，是为了避免要求数据库打开 LOCAL INFILE。实测覆盖九表和百万级地理记录，重跑同一快照复用已导入表。评价抽取使用本地权重，提交已校验的缓存。编号选择和类别复核各有独立提示词，便于对照误报与漏报。
