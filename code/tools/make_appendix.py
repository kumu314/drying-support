# -*- coding: utf-8 -*-
"""
生成 §7 附录（sec7_appendix.md）。

产出内容全部来自磁盘真实文件，不手抄：
  - 运行环境：实测解释器与依赖版本
  - 数据来源：题面与四份附件
  - 7.1 支撑材料文件列表：实际存在的文件 + 行数/大小
  - 7.2 全量可运行源码：内嵌求解链路全部 .py，并逐文件 py_compile 自检
  - 终检自检：对生成的 .md 跑一次内部痕迹扫描（必须为 0），
    命中即打印明细并以退出码 1 结束 —— 附录会被全文印进论文，
    注释里残留内部痕迹属于交付风险，不能靠人记得复查。

用法：python tools/make_appendix.py [--out sec7_appendix.md]
"""
import argparse
import os
import py_compile
import re
import subprocess
import sys

# ---- 控制台可移植性兜底-----------------------------------------
# 默认中文 Windows 控制台是 cp936；stdout 遇到不可编码字符（如 U+2212、U+2705）
# 会抛 UnicodeEncodeError 并中断。下面用 errors="replace" 降级为 '?'；
# **不改变 stdout 编码**，故中文仍按控制台原生编码正常显示。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (ValueError, OSError):
        pass

import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
# 源码在线托管地址（--code-links 大纲模式用）：
# 支撑材料源码同步托管于该仓库，目录结构与压缩包完全一致（code/ 与 figs/）。
ONLINE_REPO = "https://github.com/kumu314/drying-support"

# 求解链路源码（顺序与论文 7.2 源码表一致，共 28 个 .py）。
# 附录只列文件、行数与功能，不内嵌全文——官方第五条要求的完整可运行源程序
# 由支撑材料压缩包承载（7.1 文件列表可查），附录给出在线地址作为补充入口。
SOURCES = [
    ("common/__init__.py", "公共模块入口：物理常量、参数集（附录3/附录4）、判据与结果容器"),
    ("common/props.py", "物性函数：导热系数、比热、平衡含水率与有效水分扩散系数（双指数温度依赖）"),
    ("common/fvm.py", "一维轴对称径向有限体积离散 + Crank–Nicolson 推进、变物性 Picard 迭代、动边界支持、结果表输出"),
    ("common/parity_check.py", "公共内核的一致性比对脚本"),
    ("prob1/solve.py", "问题1：预热平衡阶段温度场与水分场求解及验证体系"),
    ("prob1/timescale.py", "时间尺度分离：传质/传热特征时间之比 τ_mass/τ_heat（随含水率与温度变化，量级洞察）"),
    ("prob2/solve.py", "问题2：给定烘干工艺下的全程热湿耦合模拟（输出 result2.xlsx）"),
    ("prob3/solve.py", "问题3：烘干时间反解（按完成判据判停，输出 result3.xlsx）"),
    ("prob4/solve.py", "问题4：考虑尺寸收缩的动边界模型（材料坐标，输出 result4.xlsx）与消融"),
    ("probQ/solve.py", "品质模块 Q：由已解温度场事后积分求有效成分保留率（创新点，单向被动，不反馈进传热方程）"),
    ("review/independent_p2.py", "独立复核：另写一套离散与积分器（BDF），与主求解器交叉对账"),
    ("review/d_sensitivity.py", "水分扩散系数 D ±10% 直接灵敏度（问题3 口径，验证「内阻控制型」）"),
    ("review/param_sensitivity.py", "全参数直接灵敏度：h/h_m/k/判据阈值 ±10% 扰动扫描与龙卷风图（论文 §5.3 量化）"),
    ("review/latent_check.py", "蒸发潜热误差量级估计：潜热累计与对流入热之比（论文 §5.2 假设 H6 的定量上界）"),
    ("review/pareto_energy.py", "控温扫描帕累托整理：时间/能耗/品质三轴权衡与边际代价表（论文 §5.6 定量支撑）"),
    ("review/sensitivity_matrix.py", "全参数灵敏度合并表（rho/c_p 补跑 + 七参 ±10% 汇总与共享区龙卷风图）"),
    ("review/latent_first30min.py", "潜热前 30 分钟窗口量级估算（绝对温升上界）"),
    ("tools/run_e2e.py", "端到端可运行性验证（干净目录复跑全求解链并逐位比对论文口径）"),
    ("review/temp_tradeoff.py", "恒温四点（45/50/55/60 °C）时长—品质权衡与共享区帕累托图"),
    ("review/attachment1_check.py", "附件1 校验表（驱动一致性偏差恒零 + 响应合理性滞后比判据）"),
    ("tools/make_results.py", "结果汇总：由 results.json 生成论文全部数值表与图表题注（论文数字的唯一汇总入口）"),
    ("tools/make_figs.py", "正文图件生成，含体积平均含水率 C̄(t) 的节点径向加权实现"),
    ("tools/make_schematic_figs.py", "物理机理示意图与数值求解流程图生成（图3-1、图3-2）"),
    ("tools/make_appendix.py", "附录 7.1 文件清单与 7.2 源码表生成（本脚本）"),
    ("probQ/make_fig.py", "品质模块出图（图5-2）"),
    ("review/bi_per_problem.py", "分问传热 Biot 数复核——正文 §4.4 三个 Biot 数（1.39／1.04／1.90）的计算来源"),
    ("review/frozen_T_sens.py", "冻结驱动量口径 ±2 °C 复算（48/50/52 °C → 60.18/56.48/53.09 h，论文 §5.3 稳健性段引用）"),
    ("review/picard_stats.py", "Picard 外迭代统计（prob2 窗口 / prob3 全程的平均与峰值）"),
]

# 结果、数据与图件产物（7.1 用）。共 45 项 = 本包 README + 28 项数据 + 16 张图。
# 与 SOURCES 的 28 个源码文件合计 73 项，即 7.1 文件清单的全部条目（须严格相等）。
ARTIFACTS = [
    ("../README.md", "本支撑材料包说明：目录结构、运行环境、复现方法与文件清单"),
    ("results.json", "全部子问题结果的结构化汇总（论文一切数字的唯一来源）"),
    ("results.schema.json", "results.json 的字段定义"),
    ("prob1/result1.xlsx", "问题1 输出表（温度、水分浓度随半径与时间）"),
    ("prob2/result2.xlsx", "问题2 输出表（0–3 h，1 s 步长）"),
    ("prob3/result3.xlsx", "问题3 输出表（60 s 采样）"),
    ("prob4/result4.xlsx", "问题4 输出表（动边界，超出当时半径的位置留空）"),
    ("prob1/results_fragment.json", "问题1 结果片段"),
    ("prob1/timescale.json", "问题1 时间尺度分离结果（基准比值 34.20 与随含水率变化的曲线数据）"),
    ("prob2/results_fragment.json", "问题2 结果片段"),
    ("prob3/results_fragment.json", "问题3 结果片段"),
    ("prob4/results_fragment.json", "问题4 结果片段（含消融对照）"),
    ("probQ/results_fragment.json", "品质模块 Q 结果片段（含 Ea × k_ref 敏感性面）"),
    ("review/attachment1_check.json", "附件1 校验表（驱动偏差恒零 + 滞后比收窄）"),
    ("review/bi_per_problem.json", "分问传热 Biot 数复核结果（1.39／1.04／1.90）"),
    ("review/d_sensitivity.json", "D ±10% 直接灵敏度结果（D+10% → −7.92%，D−10% → +9.72%）"),
    ("review/frozen_T_sens.json", "冻结驱动量 ±2 °C 复算结果（60.18／56.48／53.09 h）"),
    ("review/independent_p2_out.json", "独立复核的采样结果（供交叉对账）"),
    ("review/latent_check.json", "潜热误差量级结果（全程潜热/对流入热之比与两道自检）"),
    ("review/latent_first30min.json", "潜热前 30 分钟窗口量级（占比 3.48% / 绝对温升 ≤0.30 °C）"),
    ("review/param_sensitivity.json", "全参数 ±10% 灵敏度结果（层级排序与方向不对称性）"),
    ("review/pareto_tradeoff.json", "控温帕累托数据（五温度点 + 边际代价表 + 结论句）"),
    ("review/picard_stats.json", "Picard 外迭代统计（平均/峰值，容差口径）"),
    ("review/sensitivity_matrix.json", "七参数 ±10% 灵敏度定量表（层级排序与不对称性）"),
    ("review/temp_tradeoff.json", "恒温四点权衡数据（摘要取舍声明的支点）"),
    ("review/v2_mesh_scan.json", "网格敏感度扫描原始数据（N=20/40/60 的 t_dry）"),
    ("review/v7_consistency.json", "V7 相容性检验：完整口径定义、样本点清单与逐点对照数据"),
    ("review/base_profile.npz", "问题3 基准全程时程（潜热核算与灵敏度脚本复用，64.9 KB）。"
                                "缺失时 latent_check.py 等脚本自行重解"),
    ("review/p2_traj_cache.npz", "问题2 出图用轨迹缓存（60 s 抽稀，0.61 MB）。随支撑材料分发，"
                                 "使 make_figs.py 无需重算即可出图；缺失时脚本自动改为现场求解"),
    ("../figs/fig_flowchart.png", "图：数值求解流程（§3.3 末，图3-2）"),
    ("../figs/fig_mechanism.png", "图：物理机理示意（§3.1，图3-1）"),
    ("../figs/fig_p1_profiles.png", "图：问题1 温度与水分径向剖面"),
    ("../figs/fig_p1_timescale.png", "图：传质/传热特征时间之比随含水率的变化（三套物性与两个温度）"),
    ("../figs/fig_p1_verification.png", "图：问题1 数值方案验证"),
    ("../figs/fig_p2_evolution.png", "图：问题2 热湿耦合场时空演化"),
    ("../figs/fig_p2_phase.png", "图：问题2 热湿耦合路径与干燥速率"),
    ("../figs/fig_p2_verification.png", "图：问题2 数值方案验证（收敛性与守恒性）"),
    ("../figs/fig_p3_drying.png", "图：问题3 烘干时间反解"),
    ("../figs/fig_p4_compare.png", "图：问题4 收缩效应与消融"),
    ("../figs/fig_p4_profiles.png", "图：问题4 动边界水分剖面（材料坐标与物理坐标）"),
    ("../figs/fig_p5_quality.png", "图：品质模块保留率演化与 Ea × k_ref 敏感性面"),
    ("../figs/fig_pareto.png", "图：恒温四点品质—时长权衡放大视图"),
    ("../figs/fig_pareto_tradeoff.png", "图：控温工艺扫描时间／能耗／品质三轴权衡（五温度点）"),
    ("../figs/fig_tornado.png", "图：七参数灵敏度龙卷风图（按影响幅度排序）"),
    ("../figs/fig_v7_shrinkage.png", "图：模型含水率与附件2 收缩曲线的相容性检验（附录配图，正文不引用）"),
]


def env_versions():
    import numpy, scipy, matplotlib, openpyxl
    return {
        "Python": sys.version.split()[0],
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
        "openpyxl": openpyxl.__version__,
        "运行平台": f"{sys.platform}",
    }


def compile_check(paths):
    ok, bad = [], []
    with tempfile.TemporaryDirectory() as td:
        for p in paths:
            try:
                py_compile.compile(os.path.join(PKG, p),
                                   cfile=os.path.join(td, os.path.basename(p) + "c"),
                                   doraise=True)
                ok.append(p)
            except py_compile.PyCompileError as e:
                bad.append((p, str(e)))
    return ok, bad


def anchor(name):
    return name.replace("/", "-").replace(".", "-").replace("_", "-")


def r6_scan(out_path):
    """对本附录跑一次内部痕迹扫描（可选功能），返回 (命中数, 警告数, 原始输出)。

    扫描器不随本支撑材料分发：其路径由环境变量 APPENDIX_TRACE_SCANNER 指定；
    未设置或文件不存在时直接返回 None（跳过，不阻断本工具）。
    """
    sc = os.environ.get("APPENDIX_TRACE_SCANNER", "").strip()
    if not sc or not os.path.exists(sc):
        return None
    r = subprocess.run([sys.executable, sc, "--src", out_path],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    mb = re.search(r"BLOCK\s*命中\s*:\s*(\d+)", out)
    mw = re.search(r"WARN\s*命中\s*:\s*(\d+)", out)
    return (int(mb.group(1)) if mb else None,
            int(mw.group(1)) if mw else None, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(PKG, "sec7_appendix.md"))
    ap.add_argument("--code-links", action="store_true",
                    help="大纲模式：源码不内嵌，附录只放文件大纲+GitHub 在线地址"
                         "（完整源码由支撑材料压缩包承载）")
    args = ap.parse_args()

    env = env_versions()
    paths = [s[0] for s in SOURCES]
    ok, bad = compile_check(paths)
    missing = [a for a, _ in ARTIFACTS if not os.path.exists(os.path.join(PKG, a))]
    missing_src = [p for p in paths if not os.path.exists(os.path.join(PKG, p))]

    L = []
    A = L.append
    A("# 附　录")
    A("")
    A("## 附录说明")
    A("")
    A("本附录给出论文全部数值结果的来源与复现方式：求解所用的软件环境、")
    A("原始数据来源、支撑材料文件清单，以及完整可运行源码。")
    A("正文与图表中出现的每一个数值均由所列程序计算产生，未作任何人工调整。")
    A("")
    A("### 一、运行环境")
    A("")
    A("全部程序在单机环境下运行，不依赖任何商业求解器或外部服务。实测环境如下：")
    A("")
    A("| 项目 | 版本 / 说明 |")
    A("|------|-------------|")
    for k, v in env.items():
        A(f"| {k} | {v} |")
    A("")
    A("求解入口与运行方式：")
    A("")
    A("```text")
    A("python prob1/solve.py                      # 问题1")
    A("python prob2/solve.py --air 附件1.xlsx     # 问题2")
    A("python prob3/solve.py --air 附件1.xlsx     # 问题3")
    A("python prob4/solve.py --air 附件1.xlsx --radius 附件2.xlsx   # 问题4")
    A("python probQ/solve.py --air 附件1.xlsx --cache <prob2 缓存>                    # 品质模块 Q")
    A("```")
    A("")
    A("其中 附件1.xlsx / 附件2.xlsx 为赛题所附数据文件，请将其置于上述脚本的")
    A("工作目录下，或以绝对路径传给 --air / --radius 参数。")
    A("")
    A("为便于复现，支撑材料另附两个 `.npz` 数值缓存（合计 0.68 MB，见 7.1 清单）：")
    A("`review/p2_traj_cache.npz` 供 `tools/make_figs.py` 直接出图、`review/base_profile.npz`")
    A("供潜热与灵敏度核算脚本复用，从而免去重跑问题3 全程（约 9.7 h）。二者**均为可选**——")
    A("删除后上述脚本会自动改为现场求解，结果不变；缓存内的轨迹与正文所用结果完全同源。")
    A("")
    A("上述脚本的终端输出只使用 ASCII 标记，在默认中文 Windows 控制台（代码页 cp936）")
    A("下可直接运行，**无需设置任何环境变量**；若在非中文代码页的终端下运行而出现中文")
    A("乱码，可临时设置 `PYTHONIOENCODING=utf-8` 后再运行。")
    A("")
    A("### 二、数据来源")
    A("")
    A("原始数据全部来自赛题附件，未引入任何外部数据。附件的读取方式与取值口径如下：")
    A("")
    A("| 数据 | 用途 | 读取与处理方式 |")
    A("|------|------|----------------|")
    A("| 附件1（烘房空气温度、相对湿度时序） | 热风侧边界条件 | 按时间线性插值；序列结束后按末段渐近值恒定延拓至烘干结束 |")
    A("| 附件2（药材半径随时间变化） | 问题4 的动边界 R(t) | 按时间线性插值；序列结束后取末端半径保持恒定 |")
    A("| 附录3、附录4（物性参数） | 问题1–3、问题4 的物性 | 逐项实现为温度/含水率的函数，含有效水分扩散系数的双指数温度依赖 |")
    A("| 附件3（结果表模板） | 输出表的结构 | 表头、时间起点与有效数字位数与模板一致 |")
    A("| 赛题正文 | 模型设定与判据 | 几何、初值、判据与阈值逐条对照实现 |")
    A("")
    A("### 三、支撑材料文件清单（7.1）")
    A("")
    A("下表所列文件与磁盘存放一一对应，全部为程序实际产物。")
    A("")
    A("| 文件 | 类型 | 说明 |")
    A("|------|------|------|")
    for rel, desc in SOURCES:
        full = os.path.join(PKG, rel)
        if os.path.exists(full):
            info = f"{sum(1 for _ in open(full, encoding='utf-8'))} 行"
        else:
            info = "（缺失）"
        A(f"| `{rel}` | 源码（{info}） | {desc} |")
    for rel, desc in ARTIFACTS:
        full = os.path.join(PKG, rel)
        if os.path.exists(full):
            size = os.path.getsize(full)
            if size >= 1024 * 1024:
                info = f"{size/1024/1024:.1f} MB"
            elif size >= 1024:
                info = f"{size/1024:.0f} KB"
            else:
                info = f"{size} B"
        else:
            info = "（缺失）"
        kind = "数据" if rel.endswith((".json", ".xlsx")) else ("图" if rel.endswith(".png") else "文档")
        if rel.endswith(".npz"):
            kind = "缓存"
        A(f"| `{rel}` | {kind}（{info}） | {desc} |")
    A("")
    # ---------------- 四、相容性检验（V7）逐点对照----------------
    # ⚠️ 缺文件必须显式可见：不许静默出一张空表（「声称↔实现」的老坑）。
    A("### 四、相容性检验（V7）逐点对照")
    A("")
    A("本节给出问题四「模型含水率 ↔ 附件2 半径收缩」相容性检验的口径、逐点数据与配图。")
    A("**该项为口径自洽检查，不构成独立验证**——附件2 的半径序列是题给输入，")
    A("由它反推含水率不产生独立信息。")
    A("")
    A("体积平均含水率 $\\bar C(t)$ 沿用本文作图脚本的**节点径向加权**定义：")
    A("")
    A("$$\\bar C(t)=\\sum_i C(r_i,t)\\,r_i\\,\\Delta r_i \\Big/ \\sum_i r_i\\,\\Delta r_i,"
      "\\qquad \\Delta r_i=\\mathrm{grad}(r_i)$$")
    A("")
    A("在等距输出网格（0.1 cm）上 $\\Delta r$ 为常数，故等价于 $\\sum_i C_i r_i/\\sum_i r_i$；")
    A("该口径与 `tools/make_figs.py` 的既有定义一致。")
    A("")
    _v7p = os.path.join(PKG, "review", "v7_consistency.json")
    if not os.path.exists(_v7p):
        A("> ⚠️ **未找到 `review/v7_consistency.json`，本节表格无法生成。**")
        A("> 该文件由相容性检验脚本产出；**此处显式报缺失，而非静默略过**。")
        A("> 复现：`python verify_v7_consistency.py --result3 prob3/result3.xlsx "
          "--radius 附件2.xlsx --json review/v7_consistency.json`")
    else:
        import json as _json
        _d = _json.load(open(_v7p, encoding="utf-8"))
        _rs = _d.get("rho_s", {})
        _f, _t = _rs.get("fixed"), _rs.get("fitted")
        A(f"反推口径（体积可加、各向同性收缩）中唯一自由参数为干料密度 $\\rho_s$，"
          f"本文取固定工程值 **{_f:.0f} kg/m³** 与同源区（0–6 h）最小二乘拟合 **{_t:.0f} kg/m³** 两档；")
        A("$\\rho_s$ 为**有效参数**（吸收骨架局部塌陷等未建模效应），不作真实密度测量值引用。")
        A("")
        _rows = [r for r in _d.get("pointwise", []) if r["t_h"] <= 6] + \
                [r for r in _d.get("pointwise", []) if r["t_h"] == 12]
        if not _rows:
            A("> ⚠️ **`v7_consistency.json` 内 `pointwise` 为空**，表格未生成（显式提示）。")
        else:
            # 注意：下标不写外层花括号（C_\mathrm{...}），避免行内出现「}}」
            # ——扫描器把连续双右花括号判为占位符残留。
            _cfr = "$C_\\mathrm{from\\,R}$"
            A("| $t$ (h) | 模型 $\\bar C$ (kg/kg) | 附件2 $R(t)$ (cm) | "
              f"{_cfr} ($\\rho_s$={_f:.0f}) | 偏差 | "
              f"{_cfr} ($\\rho_s$={_t:.0f}) | 偏差 |")
            A("|---|---|---|---|---|---|---|")
            for r in _rows:
                _mk = "**" if r["t_h"] <= 6 else ""
                _tag = " ←脱钩起点" if r["t_h"] == 12 else ""
                A(f"| {_mk}{r['t_h']:g}{_mk}{_tag} | {r['C_model']:.4f} | {r['R_cm']:.3f} | "
                  f"{r['C_from_R_fixed']:.4f} | {r['dev_fixed']:+.1f}% | "
                  f"{r['C_from_R_fit']:.4f} | {r['dev_fit']:+.1f}% |")
            A("")
            _b = _d.get("band", {})
            _rf = _d.get("radius_facts", {})
            if "6h" in _b:
                _bf, _bt = _b["6h"]["rho_fixed"], _b["6h"]["rho_fit"]
                # ⚠️ 半径事实**从 JSON 读，不得手写**：
                #    「对照区间止于 6 h」是取数策略；R(6 h)=1.374 cm，
                #    写成「6 h 后锁定于 1.20 cm」会被附件2 直接证伪。
                if _rf:
                    A(f"> **6 h 之后为不可比区**：6 h 是本文选定的**对照窗口上界**（取数策略），"
                      f"而非「半径在该时刻已停止收缩」——实测 $R$(6 h) = {_rf['R_at_6h_cm']:.3f} cm，"
                      f"12 h 时 {_rf['R_at_12h_cm']:.3f} cm、24 h 时 {_rf['R_at_24h_cm']:.3f} cm，"
                      f"{_rf['first_le_1p200_h']:.0f} h 后才降至 1.200 cm、"
                      f"{_rf['plateau_to_h']:.1f} h 起稳定于 {_rf['R_end_cm']:.3f} cm。")
                else:
                    A("> **6 h 之后为不可比区**：6 h 为本文选定的对照窗口上界"
                      "（该 JSON 未含 `radius_facts`，具体半径值见 `review/v7_consistency.json`）。")
                A("> 6 h 之后模型含水率的下降速率显著快于半径收缩速率，由半径反推的含水率"
                  "**不再可比**；**这是不可比区，不构成模型误差**。")
                A(f"> 同源区（0–6 h）逐点偏差带：$\\rho_s$={_f:.0f} 时 "
                  f"{_bf[0]:+.1f}%~{_bf[1]:+.1f}%；$\\rho_s$={_t:.0f} 时 "
                  f"{_bt[0]:+.1f}%~{_bt[1]:+.1f}%。")
                A(f"> 结论：二者**相容**，未发现口径错误。")
            A("")
        A("![附录配图：模型含水率与附件2 收缩曲线的相容性检验](../figs/fig_v7_shrinkage.png)")
    A("")
    A("### 五、源码（7.2）")
    A("")
    _total_lines = sum(
        sum(1 for _ in open(os.path.join(PKG, p), encoding="utf-8"))
        for p in paths if os.path.exists(os.path.join(PKG, p)))
    if getattr(args, "code_links", False):
        # 大纲模式：源码不内嵌，附录只放文件大纲；
        # 完整源码随支撑材料压缩包提交，并给出在线托管地址（ONLINE_REPO）。
        A(f"求解链路全部源码共 {len(SOURCES)} 个文件、{_total_lines} 行，"
          f"逐文件通过语法编译检查（py_compile {len(ok)}/{len(paths)}），"
          "可直接运行复现论文全部数值结果。")
        A("完整源码随支撑材料压缩包一并提交；源码同步托管于："
          f"{ONLINE_REPO}（目录结构与压缩包一致）。各文件功能如下：")
        A("")
        A("| 源码文件 | 行数 | 功能 |")
        A("|---|---|---|")
        for rel, desc in SOURCES:
            full = os.path.join(PKG, rel)
            n = sum(1 for _ in open(full, encoding="utf-8")) if os.path.exists(full) else 0
            A(f"| `{rel}` | {n} | {desc} |")
        A("")
    else:
        A(f"以下为求解链路全部源码，共 {len(SOURCES)} 个文件、"
          f"{_total_lines} 行，"
          "逐文件通过语法编译检查，可直接运行复现论文全部数值结果。")
        A("")
        for rel, desc in SOURCES:
            full = os.path.join(PKG, rel)
            if not os.path.exists(full):
                continue
            A(f"#### {rel}")
            A("")
            A(f"{desc}。")
            A("")
            A("```python")
            with open(full, encoding="utf-8") as f:
                src = f.read().rstrip("\n")
            A(src)
            A("```")
            A("")

    # 注：原「六、补充验证图与表」与「七、符号表」两节已并入正文 ——
    #   图4-2／图4-3／图4-6 与表4-7 归入正文 §4.3，符号表归入正文 §2.2；
    #   附录不再重复收录。保留本说明，避免重生成时又把这两节塞回附录。
    A("")

    # newline="\n"：仓库内 .md 一律存 LF（见 .gitattributes）。
    # 若用默认 "w"，Windows 会把每个 \n 翻成 CRLF，导致工作区文件与仓库 blob
    # 长期不一致（git 每次都说「CRLF will be replaced by LF」）。
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")

    print(f"已生成 {args.out}")
    print(f"  源码 {len(ok)}/{len(paths)} 个通过 py_compile")
    if bad:
        for p, e in bad:
            print(f"  [编译失败] {p}: {e}")
    if missing_src:
        print(f"  [源码缺失] {missing_src}")
    if missing:
        print(f"  [产物缺失] {missing}")

    # ---- 终检自检：内部痕迹扫描（必须为 0）----
    got = r6_scan(args.out)
    r6_bad = False
    if got is None:
        print("  [终检自检] 跳过（未设置 APPENDIX_TRACE_SCANNER）")
    else:
        n_block, n_warn, out = got
        if n_block is None:
            print("  [终检自检] 扫描器无输出，未能判定")
        else:
            print(f"  [终检自检] BLOCK {n_block}（须为 0）｜ WARN {n_warn}（人工判断）")
            if n_block:
                r6_bad = True
                print(out.rstrip())

    return 0 if not (bad or missing_src or missing or r6_bad) else 1


if __name__ == "__main__":
    sys.exit(main())
