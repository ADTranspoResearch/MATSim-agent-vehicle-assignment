# 100% MATSim：五情境、五个 seed 的日指标批处理

本次只建立程序和测试文件，未启动批量实验，也未执行测试。下面命令供以后手动使用。

## 输入和默认实验

默认读取项目内的：

- `data/MATSim/events/output_events_100.xml.gz`
- `data/MATSim/vehicles/output_allVehicles_with_events_100_ids.xml.gz`
- `data/MATSim/network/network_0409.xml`
- FSA 边界及旧 agent–FSA lookup、2013–2020 个人车辆 SAAQ 文件、各 FSA 人口预测、2020 历史车型比例、历史 BEV 车身份额。

默认运行 `2020_REF` 和 `2035_bau`、`2035_acc_adopt`、`2035_del_adopt`、`2035_pol_align`，每个情境 seed 1–5。

Python 依赖列于 `requirements-batch.txt`。实际计算排放还需要 Maven、Java 21 或更新版本及 MATSim Maven 依赖。Python 侧不要求完整 population 文件。

## 手动运行

在项目根目录使用已安装依赖的 Python 环境：

```bash
# 仅打印默认的 25 次运行矩阵；不读取大数据或调用 Java。
python3 scripts/run_scenario_batch.py --dry-run

# 正式运行；默认自动续跑。
python3 scripts/run_scenario_batch.py

# 分阶段运行：先预处理并生成比例，再写车辆文件，最后运行排放与汇总。
python3 scripts/run_scenario_batch.py --stage prepare
python3 scripts/run_scenario_batch.py --stage assign
python3 scripts/run_scenario_batch.py --stage all

# 仅处理指定情境和 seed；同目录可以逐步补齐其他运行。
python3 scripts/run_scenario_batch.py --scenarios 2035_bau --seeds 1

# 使用其他输出位置及 JVM 内存。
python3 scripts/run_scenario_batch.py --output-dir /path/to/batch_100 --java-heap 4g
```

`--stage summarize` 只处理现有的、通过阶段记录验证的 emission events，不调用 Java；已完成的汇总可直接复用。`--no-resume` 强制重算当前选择的阶段。`--keep-emission-events` 保留新生成的原始排放事件，需要足够空间；已经清理的历史事件不会因为添加此参数自动恢复。

每个路径都可通过命令行覆盖，具体参数见 `--help`。同一个输出目录只允许一个批处理进程。
文件锁自动选择 Windows 内置 `msvcrt` 或 macOS/Linux 内置 `fcntl`，无需安装额外的锁依赖。

## 指标定义

全部结果针对一个模拟日，扩样系数为 **1**，不乘 10 或 365。

| 列 | 含义 |
| --- | --- |
| `vehicle_count` | FSA 内全部已分配的非公交车辆数 |
| `ev_count` | 已分配 EV 数，包含当天零里程车辆 |
| `active_ev_count` | 行驶里程大于零的 EV 数 |
| `total_co2_kg_per_day` | warm + cold CO₂，由模块输出的克数除以 1000 |
| `co2_kg_per_ev_per_day` | FSA 全部非公交车辆 CO₂ / EV 数 |
| `total_electricity_kwh_per_day` | EV 里程乘以对应车身类型的 kWh/km 后求和 |
| `electricity_kwh_per_ev_per_day` | 总电量 / EV 数 |

EV 数为零时，两项 per-EV 指标为空。每个 seed 都输出相同的 FSA 行集合，包含城市研究 FSA、定位得到的其他 FSA 和 `UNKNOWN`。公交保留在车辆输入内，沿用 emission module 的非 HBEFA 处理，不进入私人车辆 FSA 指标。

FSA 根据 **agent 的居住位置**归属，不按排放发生的 link 归属。优先使用 100% events 的 home 坐标，默认坐标系 `EPSG:32187`，与 FSA shapefile 转换到相同坐标系后空间匹配；空间匹配失败时尝试旧 lookup，再失败则归入 `UNKNOWN`。多边形公共边界按 FSA 代码排序选取，诊断中报告歧义数量。

里程沿用现有方法：对 `left link` 事件的路段长度求和，不额外估算首末路段。驾驶员映射取 `vehicle enters traffic`，不会被乘客上车事件覆盖。找不到 link、事件车辆不在输入车辆表内或同车有多个驾驶员时停止并报告，避免静默漏算。

## 车型预测与随机性

2020 REF 使用现有 `fsa_vehicle_share_2020.parquet`；未来四情境从原始 SAAQ 和人口数据重建。预测沿用正式模型的历史类型筛选、stock growth、Gompertz 调整、情境约束与退出规则；新车预测范围仍为 2021–2040，取车队在 2035 的比例用于分配，不采用独立实验目录中的 Gompertz 版本。

车型按固定车辆顺序与 `random.Random(seed)` 抽取，相同 seed 在不同情境中使用配对随机数。`ice_van/pickup` 映射为 emission module 的 `truck`。每辆非公交车辆都会分配，不受旧 10% population 覆盖范围限制。

缺失或无效 FSA 预测使用同情境、同年份的城市平均车型比例；权重为成功建模的研究 FSA 车队规模。`UNKNOWN` 车辆也采用该比例。每个运行记录回退原因与车辆数，无法建立任何有效城市平均时停止。

BEV 车身类型沿用现有的按 scenario/agent 确定性哈希分配，不额外引入 seed。2020 使用历史 2020 BEV 份额，2035 使用历史 2024 份额。电耗为 Passenger cars 0.18、Multi-purpose vehicles 0.23、Pickup trucks and vans 0.30 kWh/km。

## 输出、恢复及清理

默认输出根目录为 `output/batch_100/`：

```text
inputs.json                            输入身份、代码身份、模型参数
batch_status.json                      当前选择的运行矩阵及完成情况
cache/                                 一次预处理的里程、居住 FSA、历史计数、车型比例及诊断
2020_REF/seed1/                         各情境、各 seed 独立目录
  vehicles.xml.gz                      分配后的 MATSim 车辆输入
  assignments.parquet                  分配类型、归属、里程、电耗、回退来源
  emission_config.xml                  独立离线排放配置，不加载旧 population
  emission.log                         Maven/Java 完整运行日志
  fsa_results.csv                      该 seed 的日指标
  vehicle_results.parquet              包含 CO₂ 的车辆明细，供守恒核对
  assignment_diagnostics.json
  summary_diagnostics.json
  *.done.json                          各阶段完成记录
fsa_results_all_seeds.csv               当前选择的全部运行明细
fsa_results_seed_statistics.csv         按年份、情境、FSA 汇总
all_fsa_totals_by_seed.csv              包含 UNKNOWN 的全部 FSA 总量
```

统计表对每项指标输出 `_mean`、`_std`（样本标准差，`ddof=1`）、`_n_valid`，并报告 `seed_count`。per-EV 指标先逐 seed 计算，再求均值，不能用跨 seed 的总量之比代替。仅一个有效值时标准差为空。选择少于五个 seed 时，统计表反映实际选择数量；最终五 seed 表需用默认完整矩阵再运行一次，已完成的运行会复用。

输入身份包含路径、大小、修改时间；64 MiB 及以下文件额外计算 SHA-256，大文件使用大小和纳秒修改时间识别。模型代码、Java 源码、因子表、人口文件、Python 和依赖库版本也纳入身份。输入、代码或运行环境变化时要求使用新的输出目录，以免混入不同模型的结果。

每次真正调用 Java 前保证 Maven 已编译，一次调用批处理最多编译一次。Java 日志流式写入文件，事件文件流式解析。验证车辆数、EV 数及 CO₂/电量守恒后，先保存汇总和独立完成记录，再删除**本次生成**的原始 emission events。汇总的有效性不依赖已删除的事件文件，重复命令不会因此重跑成功的实验。失败或中断会保留未完成文件及日志，可以修复后重试。

## 测试文件（本次未执行）

```bash
# 合成数据单元测试；默认跳过真实 Java 集成测试。
python3 -m unittest discover -s tests -p 'test_scenario_batch.py'

# 明确选择后，额外运行仅两个路段的小数据 Java 集成测试。
RUN_MATSIM_BATCH_INTEGRATION=1 python3 -m unittest discover -s tests -p 'test_scenario_batch.py'
```

测试覆盖重复 seed、排序稳定性、公交元数据、缺失 FSA、驾驶员映射、零 EV、零里程 EV、日单位、warm/cold 汇总、样本标准差、事件清理后的恢复、Windows 文件锁选择、并发互斥与异常后释放，以及正式模型显式情境参数的兼容性。
