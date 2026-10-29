# 100% MATSim：五情境、十个 seed 的日指标批处理

本次只建立程序和测试文件，未启动批量实验，也未执行测试。下面命令供以后手动使用。

## 输入和默认实验

默认读取项目内的：

- `data/MATSim/events/output_events_100.xml.gz`
- `data/MATSim/vehicles/output_allVehicles_with_events_100_ids.xml.gz`
- `data/MATSim/network/QC_network_fixed_1022.xml`
- FSA 边界及旧 agent–FSA lookup、2013–2020 个人车辆 SAAQ 文件、各 FSA 人口预测、2020 历史车型比例、历史 BEV 车身份额。

默认运行 `2020_REF` 和 `2035_bau`、`2035_acc_adopt`、`2035_del_adopt`、`2035_pol_align`，每个情境 seed 1–10，共 **50 次独立排放运行**，默认串行执行。

这里的 100% 指以上交通 events 和 vehicles 输入。每次运行使用该 seed 新分配的车型生成自己的 emission events，不读取或复用 `data/MATSim/emission_events/` 中的旧情境结果。CLI 与程序内部的路网默认值一致，输入身份记录实际使用的输入路径和文件身份。自定义路径仍须确保 events、vehicles 和路网属于同一模拟。

Python 依赖列于 `requirements-batch.txt`。实际计算排放还需要 Maven、Java 21 或更新版本及 MATSim Maven 依赖。Python 侧不要求完整 population 文件。

## 新增车辆比例预测

默认使用 All-prediction Gompertz：保留原第一阶段递推，以 2020 年实际新增 EV 份额为锚点、长期上限为 100%，对第一阶段 2021—2040 年全部 EV 预测逐年等权拟合。`predict_composition_trend` 的 `end_year` 仍为不包含的输出终点；`gompertz_fit_end_year=2040` 是独立且包含的拟合终点，改变输出长度不会改变重叠年份预测。

`acc_adopt` 和 `del_adopt` 在 2021—2024 年保持 BAU；以 BAU 的 2024 年份额为锚点，将原第一阶段 2025—2040 年 EV 份额分别乘以 1.25、0.75，再拟合后续 Gompertz。倍率作用于整段拟合目标，不再约束 2035 年最终值。超出 0—100% 的目标截断并记录，非 EV 车型保持同年内部比例。`pol_align` 继续使用原逐年政策目标。

拟合参数和截断记录位于预测 DataFrame 的 `attrs["gompertz"]` 中。批处理核对实际返回的模型标识、2020 年锚点、全部拟合年份，以及加速/延迟情境的 2024 年锚点、倍率和 2025—2040 年拟合年份；参数必须有效。各 FSA 的实际拟合参数、目标值和截断记录保存到 `cache/prediction_diagnostics.json` 的 `fits`，缺失历史、拟合失败或模型校验失败记录到 `fallbacks`，按原规则使用城市加权平均。

批处理输入身份包含拟合模块、拟合终点、情境参数及 SciPy 版本，旧模型缓存不能作为新模型结果复用。历史 Two-anchor 方法仍可通过 `refit_ev_with_gompertz` 显式调用，独立对照实验继续使用它。

## 手动运行

在项目根目录使用已安装依赖的 Python 环境：

```bash
# 仅打印默认的 50 次运行矩阵；不读取大数据或调用 Java。
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
python3 scripts/run_scenario_batch.py --output-dir /path/to/batch_100_10seeds --java-heap 4g
```

`--stage summarize` 只处理现有的、通过阶段记录验证的 emission events，不调用 Java；已完成的汇总可直接复用。`--no-resume` 强制重算当前选择的阶段。`--keep-emission-events` 保留新生成的原始排放事件，需要足够空间；已经清理的历史事件不会因为添加此参数自动恢复。

每个路径都可通过命令行覆盖，具体参数见 `--help`。同一个输出目录只允许一个批处理进程。
文件锁自动选择 Windows 内置 `msvcrt` 或 macOS/Linux 内置 `fcntl`，无需安装额外的锁依赖。

### Windows 日志排错

- `FileNotFoundException: C:\Users\…\Research`：旧版程序把配置路径放入 Maven 的 `exec.args`，路径中的空格会被再次拆分。新版使用 `exec.arguments`，通过子进程环境变量传递编码后的配置文件 URI，兼容路径中的空格、逗号和引号。
- `Invalid content ... engineInformation`：旧版程序把公交车型的引擎信息追加到了 `vehicleType` 末尾。MATSim `vehicleDefinitions_v2.0.xsd` 要求它位于 `maximumVelocity` 之后、`costInformation` / `passengerCarEquivalents` / `networkMode` / `flowEfficiencyFactor` 之前；新版按该顺序插入，并保留公交的容量、尺寸和其他运行参数。

拉取修复后，原输出目录的代码身份会与新版不一致。保留原目录作为诊断记录，在原运行命令中把 `--output-dir` 改成**尚未使用的新目录**，例如 `C:\Users\qchen7\ResearchData\data\output\batch_100_fixed`，其余输入参数沿用原值。程序会在新目录重新生成车辆 XML；仅拉取代码不会修复旧目录中已有的车辆文件。不要手工修改 `inputs.json` 或阶段完成记录来绕过身份验证。

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
| `total_distance_km_per_day` | FSA 内全部已分配的非公交车辆日总里程，km/day |

EV 数为零时，两项 per-EV 指标为空。每个 seed 都输出相同的 FSA 行集合，包含城市研究 FSA、定位得到的其他 FSA 和 `UNKNOWN`。公交保留在车辆输入内，沿用 emission module 的非 HBEFA 处理，不进入私人车辆 FSA 指标。

FSA 根据 **agent 的居住位置**归属，不按排放发生的 link 归属。优先使用 100% events 的 home 坐标，默认坐标系 `EPSG:32187`，与 FSA shapefile 转换到相同坐标系后空间匹配；空间匹配失败时尝试旧 lookup，再失败则归入 `UNKNOWN`。多边形公共边界按 FSA 代码排序选取，诊断中报告歧义数量。

里程沿用现有方法：对 `left link` 事件的路段长度求和，不额外估算首末路段。驾驶员映射取 `vehicle enters traffic`，不会被乘客上车事件覆盖。找不到 link、事件车辆不在输入车辆表内或同车有多个驾驶员时停止并报告，避免静默漏算。

车辆、link 和 FSA 的排放范围相同，均排除公交，仅保存 CO₂。在同一遍 emission events 流式扫描中，分别按车辆和事件发生的 link 累计 warm/cold CO₂，接受 `vehicleId` / `vehicle` 与 `linkId` / `link` 两种字段。非公交排放事件缺少有效 link、出现未知车辆或缺失、负数、非有限 CO₂ 时停止，原始事件保留用于诊断。

## 车型预测与随机性

2020 REF 使用现有 `fsa_vehicle_share_2020.parquet`；未来四情境从原始 SAAQ 和人口数据重建。预测沿用正式模型的历史类型筛选、stock growth、Gompertz 调整、情境约束与退出规则；新车预测范围仍为 2021–2040，取车队在 2035 的比例用于分配，不采用独立实验目录中的 Gompertz 版本。

车型按固定车辆顺序与 `random.Random(seed)` 抽取，相同 seed 在不同情境中使用配对随机数。`ice_van/pickup` 映射为 emission module 的 `truck`。每辆非公交车辆都会分配，不受旧 10% population 覆盖范围限制。

缺失或无效 FSA 预测使用同情境、同年份的城市平均车型比例；权重为成功建模的研究 FSA 车队规模。`UNKNOWN` 车辆也采用该比例。每个运行记录回退原因与车辆数，无法建立任何有效城市平均时停止。

BEV 车身类型沿用现有的按 scenario/agent 确定性哈希分配，不额外引入 seed。2020 使用历史 2020 BEV 份额，2035 使用历史 2024 份额。电耗为 Passenger cars 0.18、Multi-purpose vehicles 0.23、Pickup trucks and vans 0.30 kWh/km。

## 输出、恢复及清理

默认输出根目录为 `output/batch_100_10seeds/`，输出版本为 **2**。原 `output/batch_100/` 保留，不自动迁移旧结果或模型缓存：

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
  vehicle_results.parquet              各车辆 warm/cold/合计 CO₂、日里程及电量
  link_results.parquet                 全路网各 link 的 warm/cold/合计 CO₂
  assignment_diagnostics.json
  summary_diagnostics.json
  *.done.json                          各阶段完成记录
fsa_results_all_seeds.csv               当前选择的全部运行明细
fsa_results_seed_statistics.csv         按年份、情境、FSA 汇总
all_fsa_totals_by_seed.csv              包含 UNKNOWN 的全部 FSA 总量
```

两张明细表均使用 **Parquet + Snappy** 压缩，并包含 `year、scenario、seed`。车辆表每辆非公交车辆一行，包含零里程、零排放车辆；保留 `vehicle_id、agent_id、fsa、vehicle_type、distance_km_per_day、electricity_kwh_per_day` 等原字段，新增 `warm_co2_kg_per_day、cold_co2_kg_per_day`，原 `co2_kg_per_day` 是二者合计。link 表包含 `link_id` 及同名三个 CO₂ 字段，按 link ID 排序，保留全路网无排放 link 的零值行；不按车辆 × link 展开。

统计表对每项指标（包含新增的日总里程）输出 `_mean`、`_std`（样本标准差，`ddof=1`）、`_n_valid`，并报告 `seed_count`。per-EV 指标先逐 seed 计算，再求均值，不能用跨 seed 的总量之比代替。仅一个有效值时标准差为空。自定义少于十个 seed 时，统计表反映实际选择数量；最终十 seed 表需用默认完整矩阵再运行一次，已完成的运行会复用。`all_fsa_totals_by_seed.csv` 同样包含 `total_distance_km_per_day`；交通输入相同，所以不同情境和 seed 的总里程应一致。

输入身份包含路径、大小、修改时间；64 MiB 及以下文件额外计算 SHA-256，大文件使用大小和纳秒修改时间识别。模型代码、Java 源码、因子表、人口文件、Python 和依赖库版本也纳入身份。输入、代码或运行环境变化时要求使用新的输出目录，以免混入不同模型的结果。

每次真正调用 Java 前保证 Maven 已编译，一次调用批处理最多编译一次。Java 日志流式写入文件，事件文件流式解析。先验证车辆数、EV 数、车辆/link/FSA 的 CO₂ 守恒、warm + cold 合计，以及车辆与 FSA 的里程和电量守恒。三张表原子写入后，核对 Parquet 元数据/CSV 的实际行数，在 `summary_diagnostics.json` 的 `files` 中记录各表的 `row_count、size_bytes`。

完成记录同时包含车辆表、link 表、FSA 表、诊断及运行输入文件；全部成功保存后才删除**本次生成**的原始 emission events。汇总的有效性不依赖已删除的事件文件，重复命令不会因此重跑成功的实验。任一汇总表缺失或损坏会使该 seed 的完成记录失效；原始事件已清理时，`--stage all` 重新生成该次排放，`--stage summarize` 会报告需要先生成排放。写入失败、守恒失败或中断会保留原始事件及日志，可修复后重试。

## 文件大小估算

依据现有 100% 预处理缓存的 **391,816 辆非公交车辆**、修正路网的 **64,749 条 link**，以及约 **7.2 MiB** 的分配表，估算如下。不同 seed 的压缩率可能不同，这些数字不是新实验的实测值。

| 文件或范围 | 每次运行 | 全部 50 次 |
| --- | ---: | ---: |
| `vehicle_results.parquet` | 12—20 MiB | 约 0.6—1.0 GiB |
| `link_results.parquet` | 1—3 MiB | 约 0.05—0.15 GiB |
| 连同车型、分配表、FSA 表等永久文件 | 20—40 MiB | 约 1—2 GiB |

首个 seed 成功后，可用 `summary_diagnostics.json` 中记录的实际字节数修正预算。以上不包含临时原始 emission events；当前没有经过验证的完整 100% 排放输出可用于准确估算其大小。默认串行、成功后清理，同一时间仅保留当前一次的原始事件；初次运行建议预留 **10—20 GiB 可用空间**。若启用 `--keep-emission-events`，需另外容纳全部原始事件文件。

## 测试文件（本次未执行）

```bash
# 合成数据单元测试；默认跳过真实 Java 集成测试。
python3 -m unittest discover -s tests -p 'test_scenario_batch.py'

# 明确选择后，额外运行仅两个路段的小数据 Java 集成测试。
RUN_MATSIM_BATCH_INTEGRATION=1 python3 -m unittest discover -s tests -p 'test_scenario_batch.py'
```

测试定义覆盖默认 50 次矩阵和自定义 seed、车型重复性、零 EV/零里程/零排放、车辆与 link 单遍 warm/cold 汇总、两个 link 字段、全路网零值行、守恒、实际文件大小、写入失败保留事件、清理后的续跑、损坏表只重跑受影响 seed，以及 All-prediction 拟合审计、回退诊断和 Q0Q 既有数值。保留公交元数据/XML 顺序、Windows 文件锁、路径空格和并发互斥的回归定义。

默认矩阵的流程测试使用小型合成数据并 mock Maven/Java；真实 Java 集成样例另行显式启用，包含公交车型以及带空格、逗号和引号的输出路径。本次仅修改测试定义，未执行测试或正式实验。
