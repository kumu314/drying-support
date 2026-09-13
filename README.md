# 支撑材料

本压缩包为《药材的烘干问题》参赛论文的支撑材料，与论文附录中的
**支撑材料文件清单**与**源码表**一一对应。收录范围即论文全部数值结果所依赖的
源程序、结果数据与图件。

源码同步托管于：https://github.com/kumu314/drying-support（目录结构与本包完全一致）。

## 一、目录结构

```
支撑材料/
├─ README.md                     本说明
├─ code/                         求解源码与结果
│  ├─ common/                    公共数值内核（物性函数 + 有限体积内核 + 一致性比对）
│  ├─ prob1/ prob2/ prob3/       问题一 ~ 问题三求解与验证
│  ├─ prob4/                     问题四动边界求解与消融
│  ├─ probQ/                     品质变化动力学 Q（推广模块）
│  ├─ review/                    灵敏度、稳健性与专项复核
│  ├─ tools/                     结果汇总、出图与附录装配
│  ├─ results.json               全部子问题结果的结构化汇总（论文数字唯一来源）
│  └─ results.schema.json        results.json 的字段定义
└─ figs/                         论文全部图件（论文中写作 `../figs/`）
```

论文附录文件清单中的相对路径（如 `common/fvm.py`、`../figs/fig_p1_profiles.png`）
即以 `code` 为当前目录书写，与本包结构完全一致。

## 二、运行环境

全部程序在单机环境下运行，不依赖任何商业求解器或外部服务。

| 项目 | 版本 |
|---|---|
| Python | 3.13.14 |
| numpy | 2.5.1 |
| scipy | 1.18.0 |
| matplotlib | 3.11.1 |
| openpyxl | 3.1.5 |

上表为论文全部数值的生成环境；另在独立环境（Python 3.13.2／numpy 2.2.3／
matplotlib 3.10.1）下以另写的独立求解器复算，四问关键量（问题一 双温度、
问题三与问题四 的 t_dry、品质模块 Q̄(30 h)）与本文逐位一致，
说明结论不依赖具体库版本。

## 三、复现方法与运行命令

**第一步**：将赛题附件 `附件1.xlsx`、`附件2.xlsx` 解压到本机任意目录（无需与源码同目录）。

**第二步**：进入求解根目录。

```bat
cd code
```

**第三步**：按下列顺序运行（各问之间无依赖，`probQ` 的 `--cache` 可选）。

```bat
python prob1/solve.py  --air <附件1.xlsx 路径>
python prob2/solve.py  --air <附件1.xlsx 路径>
python prob3/solve.py  --air <附件1.xlsx 路径>
python prob4/solve.py  --air <附件1.xlsx 路径> --radius <附件2.xlsx 路径>
python probQ/solve.py  --air <附件1.xlsx 路径>
```

脚本的终端输出只使用 ASCII 标记，在默认中文 Windows 控制台（代码页 cp936）
下可直接运行，无需设置任何环境变量；若在非中文代码页的终端下运行而出现
中文乱码，可临时设置 `set PYTHONIOENCODING=utf-8` 后再运行。

**出图与汇总**（可选，需 numpy/scipy/matplotlib/openpyxl）：

```bat
python tools/make_results.py          :: 汇总 results.json 与论文表格
python tools/make_figs.py             :: 生成正文图件
python tools/make_schematic_figs.py   :: 生成机理示意图与求解流程图
python probQ/make_fig.py              :: 生成品质模块图
python tools/run_e2e.py               :: 端到端复跑并逐位比对论文口径
```

`probQ/solve.py` 另支持 `--cache <prob2 生成的 .npz>`，复用问题二时程可免去重算。

## 四、耗时与注意事项

- 本机（Python 3.13）从零跑完全链约 **599 min**，其中 `prob3`（烘干时间反解、
  1 s 步长、判停于 56.48 h）约 **9.7 h**，是全部耗时的主要来源。
- 主结果口径为 **N=20（径向 20 等分，dr = 1 mm）、dt = 1 s**；`prob1` 默认 `dt = 0.2 s`。
- 包内 `review/p2_traj_cache.npz`、`review/base_profile.npz` 为出图与核算用的
  数值缓存（合计 0.68 MB），**属可选**——删除后相关脚本自动改为现场求解，结果不变。
- 全部数字由 `results.json` 承载，论文正文、表格与图注中的数值均取自该文件，
  未作任何人工调整。

## 五、文件清单（共 72 个交付文件 + 本 README）

### 5.1 源程序（28 个）

| 文件 | 说明 ｜ 大小 |
|---|---|---|
| `common/__init__.py` | 公共模块入口：物理常量、参数集（附录3/附录4）、判据与结果容器 | 2 KB |
| `common/fvm.py` | 一维轴对称径向有限体积离散 + Crank–Nicolson 推进、变物性 Picard 迭代、动边界支持、结果表输出 | 33 KB |
| `common/parity_check.py` | 公共内核的一致性比对脚本 | 13 KB |
| `common/props.py` | 物性函数：导热系数、比热、平衡含水率与有效水分扩散系数（双指数温度依赖） | 6 KB |
| `prob1/solve.py` | 问题1：预热平衡阶段温度场与水分场求解及验证体系 | 38 KB |
| `prob1/timescale.py` | 时间尺度分离：传质/传热特征时间之比 τ_mass/τ_heat（随含水率与温度变化，量级洞察） | 9 KB |
| `prob2/solve.py` | 问题2：给定烘干工艺下的全程热湿耦合模拟（输出 result2.xlsx） | 18 KB |
| `prob3/solve.py` | 问题3：烘干时间反解（按完成判据判停，输出 result3.xlsx） | 12 KB |
| `prob4/solve.py` | 问题4：考虑尺寸收缩的动边界模型（材料坐标，输出 result4.xlsx）与消融 | 24 KB |
| `probQ/make_fig.py` | 品质模块出图（图5-2） | 8 KB |
| `probQ/solve.py` | 品质模块 Q：由已解温度场事后积分求有效成分保留率（创新点，单向被动，不反馈进传热方程） | 15 KB |
| `review/attachment1_check.py` | 附件1 校验表（驱动一致性偏差恒零 + 响应合理性滞后比判据） | 7 KB |
| `review/bi_per_problem.py` | 分问传热 Biot 数复核——正文 §4.4 三个 Biot 数（1.39／1.04／1.90）的计算来源 | 3 KB |
| `review/d_sensitivity.py` | 水分扩散系数 D ±10% 直接灵敏度（问题3 口径，验证「内阻控制型」） | 6 KB |
| `review/frozen_T_sens.py` | 冻结驱动量口径 ±2 °C 复算（48/50/52 °C → 60.18/56.48/53.09 h，论文 §5.3 稳健性段引用） | 5 KB |
| `review/independent_p2.py` | 独立复核：另写一套离散与积分器（BDF），与主求解器交叉对账 | 8 KB |
| `review/latent_check.py` | 蒸发潜热误差量级估计：潜热累计与对流入热之比（论文 §5.2 假设 H6 的定量上界） | 6 KB |
| `review/latent_first30min.py` | 潜热前 30 分钟窗口量级估算（绝对温升上界） | 5 KB |
| `review/param_sensitivity.py` | 全参数直接灵敏度：h/h_m/k/判据阈值 ±10% 扰动扫描与龙卷风图（论文 §5.3 量化） | 10 KB |
| `review/pareto_energy.py` | 控温扫描帕累托整理：时间/能耗/品质三轴权衡与边际代价表（论文 §5.6 定量支撑） | 8 KB |
| `review/picard_stats.py` | Picard 外迭代统计（prob2 窗口 / prob3 全程的平均与峰值） | 5 KB |
| `review/sensitivity_matrix.py` | 全参数灵敏度合并表（rho/c_p 补跑 + 七参 ±10% 汇总与共享区龙卷风图） | 8 KB |
| `review/temp_tradeoff.py` | 恒温四点（45/50/55/60 °C）时长—品质权衡与共享区帕累托图 | 7 KB |
| `tools/make_appendix.py` | 附录 7.1 文件清单与 7.2 源码表生成 | 25 KB |
| `tools/make_figs.py` | 正文图件生成，含体积平均含水率 C̄(t) 的节点径向加权实现 | 28 KB |
| `tools/make_results.py` | 结果汇总：由 results.json 生成论文全部数值表与图表题注（论文数字的唯一汇总入口） | 20 KB |
| `tools/make_schematic_figs.py` | 物理机理示意图与数值求解流程图生成（图3-1、图3-2） | 11 KB |
| `tools/run_e2e.py` | 端到端可运行性验证（干净目录复跑全求解链并逐位比对论文口径） | 6 KB |

### 5.2 结果数据（28 个）

| 文件 | 大小 |
|---|---|
| `results.json` | 13 KB |
| `results.schema.json` | 3 KB |
| `prob1/result1.xlsx` | 356 KB |
| `prob1/results_fragment.json` | 9 KB |
| `prob1/timescale.json` | 5 KB |
| `prob2/result2.xlsx` | 2.3 MB |
| `prob2/results_fragment.json` | 6 KB |
| `prob3/result3.xlsx` | 324 KB |
| `prob3/results_fragment.json` | 3 KB |
| `prob4/result4.xlsx` | 223 KB |
| `prob4/results_fragment.json` | 3 KB |
| `probQ/results_fragment.json` | 6 KB |
| `review/attachment1_check.json` | 4 KB |
| `review/base_profile.npz` | 65 KB |
| `review/bi_per_problem.json` | 1 KB |
| `review/d_sensitivity.json` | 1 KB |
| `review/frozen_T_sens.json` | 2 KB |
| `review/independent_p2_out.json` | 3 KB |
| `review/latent_check.json` | 1 KB |
| `review/latent_first30min.json` | 1 KB |
| `review/p2_traj_cache.npz` | 628 KB |
| `review/param_sensitivity.json` | 2 KB |
| `review/pareto_tradeoff.json` | 3 KB |
| `review/picard_stats.json` | 1 KB |
| `review/sensitivity_matrix.json` | 3 KB |
| `review/temp_tradeoff.json` | 2 KB |
| `review/v2_mesh_scan.json` | 2 KB |
| `review/v7_consistency.json` | 10 KB |

### 5.3 图件（16 个）

| 文件 | 大小 |
|---|---|
| `fig_flowchart.png` | 82 KB |
| `fig_mechanism.png` | 111 KB |
| `fig_p1_profiles.png` | 256 KB |
| `fig_p1_timescale.png` | 98 KB |
| `fig_p1_verification.png` | 197 KB |
| `fig_p2_evolution.png` | 275 KB |
| `fig_p2_phase.png` | 203 KB |
| `fig_p2_verification.png` | 155 KB |
| `fig_p3_drying.png` | 293 KB |
| `fig_p4_compare.png` | 280 KB |
| `fig_p4_profiles.png` | 195 KB |
| `fig_p5_quality.png` | 185 KB |
| `fig_pareto.png` | 32 KB |
| `fig_pareto_tradeoff.png` | 61 KB |
| `fig_tornado.png` | 41 KB |
| `fig_v7_shrinkage.png` | 94 KB |
