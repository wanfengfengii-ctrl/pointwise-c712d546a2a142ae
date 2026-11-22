# QH-A 夜班铜检漏领

在项目根目录执行 `python3 -B incident.py`。脚本用 `samples/station_batches.json` 的桥东站批和 `samples/repack_plan.json` 的换装计划开一座临时湖，在读取原卷后换装、退役、分次交回项目索引。回件沿用 README.md 的 `work_id`、`day_id` 和原卷槽声明。

| 冻结观测 | 原卷槽 | 换卷后 |
| --- | --- | --- |
| 原站行 1，铜检 7 μg/L | `old:0` | `copper:1` |
| 原站行 2，锌检 11 μg/L | `old:1` | `zinc:0` |

| 查铜检的时点 | 应领取 |
| --- | --- |
| 只实收铜检索引，锌卷离线 | `pending`，问题卷 `zinc`，明细为空 |
| 锌检索引也实收，重开库，锌卷仍离线 | `complete`，原序号 1、青河桥东 QH-A 原站行 1、铜检 7 μg/L |
| 恢复锌卷可读后再查 | `complete`，同一条原站记录 |

脚本输出三次领取的预期及实际状态、问题卷和明细。查询偏差用 `INCIDENT_WRONG_INDEX_COVERAGE` 和退出码 1 报告。三次结果一致时退出 0。回件未实收或旧卷未退役会直接报错。

沿用 `.pointwise-runtime.json`。清单的 `verify` 运行完整原回归，`demo` 演示实际回件前后和同值异出处、缺测与实测零值。保留 README.md 的接口、校验和失败边界。换卷中止和重复初始化仍按原业务规则办理。
