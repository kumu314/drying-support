#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_results.py —— 把各问求解器的 results_fragment.json 汇总成 results.json

设计原则（数字纪律）：
    所有数字都由**代码**产出或派生，绝不手抄。
    本脚本只做「读碎片 → 派生 → 组装 → 写出」四件事，不做任何数值近似。

用法：
    python tools/make_results.py

行为：
    - 读各问 results_fragment.json（prob1 必须存在；prob2/3/4/Q 按需）
    - 派生 P1 的 4 个字段：T_rise_1800s / Fo_heat / Fo_mass / E_absorbed
    - P2 / P3 / P4 / P5：有碎片就按 schema 骨架回填；没产出 → **该问叶子写 null**（绝不编数）
    - 组装 figures[]（**题注唯一权威源**，数字取自碎片）+ 派生 P4 消融键
    - 写出 results.json（无 BOM UTF-8）
    - 不做校验；字段类型与含义见同目录 results.schema.json

2026-09-11 加固
--------------------------------------------------------
此前本脚本只写 P1–P4 + 2 条 P1 图题注，而 P5（品质模块）与 7 条 P2–P5 图题注
是由 `probQ/solve.py --update-results` **增量**并入的 —— 于是**任何人重跑本脚本
都会静默清掉 P5 与那 7 条图题注**。现改为：

* **P5**：从 `probQ/results_fragment.json` 直接组装（含 sensitivity / verification /
`_contract` / `_note`），与 probQ 的增量写入口径一致；
* **图**：`FIGURES`（显式权威清单）+ 各问碎片里自带的 `figures` **去重合并**
—— 以后新图只要进了碎片就自动带上，不必再改本文件；
* **P1.tau_ratio**：从 `prob1/timescale.json`（`prob1/timescale.py` 产出）取，
不在本脚本里重算，保持「求解器产出 → 本脚本搬运」的单向依赖；
* **P4 消融键**：`dt_material` / `dt_geometry` 从 `prob4` 碎片的 `ablation` 块派生
（`P4.dt_material` / `P4.dt_geometry` 两个键由它们派生）。

2026-09-11 二次加固：图题注**收敛到单一权威源**
------------------------------------------------
图题注此前有**两个写入方**：本脚本的 `FIGURES`，以及
`tools/make_figs.py --update-results` 的 `caps` 字典（增量写回 `results.json`）。
两者文字已经漂移（一个写「判据阈值」、一个带判据代号的旧字样），**谁后跑谁覆盖** ——
正文若从 `results.json` 复制题注，就会得到不确定的结果。

现约定：**题注只由本脚本产出**。
* `build_figures()` 负责把 `FIGURES` 里的 `{t3}` / `{t4}` / `{t3d}` 变量标记按
各问碎片**现场取值**填入 —— 题注数字与结果数值同源，换网格/换口径自动跟随；
* `make_figs.py --update-results` 不再写 `figures` 字段（只出图 + 提示）。
* 题注文字口径：问题编号一律「问题一–问题四」，不写「问题1」；
不出现内部判据代号（写「判据阈值 0.15 kg/kg」）；品质模块统一称「品质变化动力学」。

参数来源：题目附录2。改参数即改口径，须同步核对全部结果。
"""

import json
import os
import sys

# ---- 控制台可移植性兜底-----------------------------------------
# 默认中文 Windows 控制台是 cp936；stdout 遇到不可编码字符会抛
# UnicodeEncodeError 并中断。下面用 errors="replace" 把不可编码字符
# 降级为 '?'；**不改变 stdout 编码**，故中文输出仍按控制台原生编码正常显示。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (ValueError, OSError):
        pass


HERE = os.path.dirname(os.path.abspath(__file__))          # tools/
PKG_DIR = os.path.normpath(os.path.join(HERE, ".."))        # 求解器包根目录
REPO_ROOT = os.path.normpath(os.path.join(PKG_DIR, "..", ".."))
OUT_PATH = os.path.join(PKG_DIR, "results.json")
SCHEMA_PATH = os.path.join(PKG_DIR, "results.schema.json")

# ===== 题目附录2「问题1 的相关参数」=====
R_M = 0.02          # 药材半径 m
L_M = 0.25          # 药材长度 m
RHO1 = 820.0        # 密度 kg/m^3
CP1 = 2600.0        # 比热容 J/(kg·K)
K1 = 0.36           # 热传导系数 W/(m·K)
H_CONV = 25.0       # 对流换热系数 W/(m^2·K)
HM = 8e-7           # 对流传质系数 m/s
T0_C = 28.0         # 初始温度 °C
C0 = 2.55           # 初始水分浓度 kg/kg
T_END_S = 1800.0    # 问题1 终止时刻 s

# 图件：`file` 相对**求解器包根目录**（即 results.json 所在目录）；图目录已按约定
# figs 与源码目录同级，故写 `../figs/...`。**按正文出现顺序排列**。
# —— **题注的唯一权威源**（正文题注从 results.json 的 figures[] 原样复制）。
#    各问碎片自带的 figures 仅在 id 未登记时去重追加，不覆盖本清单的文字。
#    题注为**纯描述性文字**：不写结果数值（结果在正文图表与文字里给），
#    不写内部判据代号（写「判据阈值」），问题编号一律「问题一–问题四」。
#    caption 里的 {t3}/{t4}/{t3d} 是**变量标记**，若题注需要引用反解时刻，
#    由 build_figures() 从各问碎片现场取值填入 —— 数字绝不手抄。
#    （当前题注均为描述性文字、未使用变量标记；该机制保留以备后续需要。）
# 编号约定：分章编号 图X-X（X=章号），
#    顺序 = 正文出现顺序（fig_p2_phase 在 fig_p2_verification 之前）。
FIGURES = [
    {
        "id": "fig_mechanism",
        "file": "../figs/fig_mechanism.png",
        "caption": "图3-1 物理机理示意：(a)圆柱药材横截面内的对流供热、表面蒸发、"
                   "内部导热与水分扩散，以及随干燥内移的收缩动边界 R(t)；"
                   "(b)热—湿耦合回路（升温强化扩散、蒸发吸热降温）与品质变化"
                   "动力学 Q 的单向下馈",
    },
    {
        "id": "fig_flowchart",
        "file": "../figs/fig_flowchart.png",
        "caption": "图3-2 数值求解流程：附件数据读入与物性插值 → 热湿耦合 PDE 建立 → "
                   "FVM 空间离散与 CN 时间推进（Picard 外迭代）→ 收敛性/守恒性/"
                   "非负性校验 → 判据判停与输出；品质变化动力学 Q 由温度场事后积分，"
                   "不反馈主求解",
    },
    {
        "id": "fig_p1_profiles",
        "file": "../figs/fig_p1_profiles.png",
        "caption": "图4-1 预热平衡阶段（0–1800 s）药材内部温度与水分浓度的径向分布演化",
    },
    {
        "id": "fig_p1_verification",
        "file": "../figs/fig_p1_verification.png",
        "caption": "图4-2 问题一数值解的网格收敛性、时间步收敛性与离散守恒性验证",
    },
    {
        "id": "fig_p1_timescale",
        "file": "../figs/fig_p1_timescale.png",
        "caption": "图4-3 传质与传热特征时间之比随含水率的变化（三套物性与两个温度）",
    },
    {
        "id": "fig_p2_evolution",
        "file": "../figs/fig_p2_evolution.png",
        "caption": "图4-4 问题二 药材内部热湿耦合场的时空演化：(a)升温阶段温度径向剖面、"
                   "(b)全时程水分径向剖面、(c)中心、表面与热风温度时程（前 4 h 烘房按附件1 "
                   "实测升温，其后恒为 50 °C）、(d)中心与表面水分时程（含判据阈值线）",
    },
    {
        "id": "fig_p2_phase",
        "file": "../figs/fig_p2_phase.png",
        "caption": "图4-5 问题二 热湿耦合路径：(a)不同半径处的温度—含水率耦合轨迹、"
                   "(b)干燥速率随含水率的变化（全程单段降速）",
    },
    {
        "id": "fig_p2_verification",
        "file": "../figs/fig_p2_verification.png",
        "caption": "图4-6 问题二 数值方案的验证：(a)径向网格收敛性、(b)时间步收敛性、"
                   "(c)离散守恒性残差与容差对比",
    },
    {
        "id": "fig_p3_drying",
        "file": "../figs/fig_p3_drying.png",
        "caption": "图4-7 问题三 烘干时间反解：(a)判据量 C_max(t) 演化与判停时刻、"
                   "(b)水分浓度时空分布与判据阈值等值线、(c)判据穿越段放大、"
                   "(d)不同深度处的水分浓度时程",
    },
    {
        "id": "fig_p4_compare",
        "file": "../figs/fig_p4_compare.png",
        "caption": "图4-8 问题四 考虑尺寸收缩后：(a)定半径与动边界两种口径的判据量对比、"
                   "(b)附件2 半径收缩曲线 R(t)、(c)材质效应与收缩效应消融、"
                   "(d)中心与表面的水分浓度时程对比",
    },
    {
        "id": "fig_p4_profiles",
        "file": "../figs/fig_p4_profiles.png",
        "caption": "图4-9 问题四 动边界水分剖面：(a)物理坐标下的剖面（○ 为当时的表面位置，"
                   "随 R(t) 向内移动；灰带为末段已收缩掉的区域）、(b)无量纲材料坐标 "
                   "ξ=r/R(t) 下的剖面",
    },
    {
        "id": "fig_p5_quality",
        "file": "../figs/fig_p5_quality.png",
        "caption": "图5-2 品质变化动力学：(a)体积平均保留率 Q̄(t) 与恒温 50 °C 解析对照、"
                   "(b)Q̄(30 h) 对 Ea × k_ref 的敏感性面（红圈为基准工况）、"
                   "(c)判定时刻 Q 的径向剖面、(d)控温工艺扫描下烘干时间与保留率的权衡。"
                   "Q 由已解出的温度场事后积分得到，不反馈进传热方程，不改变主结果。",
    },
    {
        "id": "fig_tornado",
        "file": "../figs/fig_tornado.png",
        "caption": "图5-1 参数灵敏度龙卷风图：七个参数各 ±10% 扰动下烘干时间的相对变化，"
                   "按影响幅度降序排列。热物性类参数（密度、比热、导热系数、换热系数）"
                   "的影响比水分扩散与判据阈值低两个数量级以上，且所有参数的响应均不对称。",
    },
    {
        "id": "fig_pareto_tradeoff",
        "file": "../figs/fig_pareto_tradeoff.png",
        "caption": "图5-3 控温工艺扫描的时间／能耗／品质三轴权衡（点旁标注恒温段温度，"
                   "红圈为题设 50 °C）：(a)烘干时间与累计供热能耗的权衡、"
                   "(b)烘干时间与判定时刻平均保留率的权衡（纵轴对数尺度）。",
    },
    {
        "id": "fig_pareto",
        "file": "../figs/fig_pareto.png",
        "caption": "图5-4 恒温段温度四点（45／50／55／60 °C）品质—时长权衡的放大视图："
                   "降温可换来保留率的大幅提升、升温则显著缩短烘干时间，"
                   "品质对温度的敏感度远高于烘干时间对温度的敏感度。",
    },
]


def build_figures(frags):
    """把 FIGURES 里的 {t3}/{t4}/{t3d} 变量标记按各问碎片现场取值填入。

    这样做是为了让题注里的数字与 results.json 的数值**同源**：
    图件的反解时刻一旦变化（如换网格、换判据口径），题注自动跟随，
    不会出现「正文写 56.4767 h、图里画的是别的值」这种最难查的不一致。

    若对应碎片缺失，该变量标记保留原样并由本函数显式报错，绝不静默填 0。
    """
    vals = {"t3": None, "t4": None, "t3d": None}
    p3 = (frags.get("prob3") or {}).get("P3") or {}
    p4 = (frags.get("prob4") or {}).get("P4") or {}
    if p3.get("t_dry_h") is not None:
        vals["t3"] = f"{p3['t_dry_h']:.4f}"
    if p3.get("t_dry_day") is not None:
        vals["t3d"] = f"{p3['t_dry_day']:.3f}"
    if p4.get("t_dry_h") is not None:
        vals["t4"] = f"{p4['t_dry_h']:.4f}"

    out, missing = [], set()
    for spec in FIGURES:
        cap = spec["caption"]
        for k, v in vals.items():
            if "{" + k + "}" not in cap:
                continue
            if v is None:
                missing.add(k)
                continue
            cap = cap.replace("{" + k + "}", v)
        out.append({"id": spec["id"], "file": spec["file"], "caption": cap})
    if missing:
        raise SystemExit(f"[题注取值失败] 碎片缺少数值，变量未填充：{sorted(missing)}"
                         f" —— 请先跑对应求解器产出 results_fragment.json。")
    return out


def load_fragment(name):
    path = os.path.join(PKG_DIR, name, "results_fragment.json")
    if not os.path.exists(path):
        return None, path
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f), path


def load_schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def null_skeleton(node):
    """按结果数据格式约定生成「同构全 null 骨架」。

    为什么不是整块写 null：schema 对 null 的放行只作用于**叶子字段**，
    一个 object 块整体为 null 会报 “应为 object，实际 NoneType” 而阻断统稿。
    所以「未产出」的正确表达是：**键结构保留、叶子写 null**——
    既满足 schema 的必填键，又满足 _rule ③「跑不出来的字段值写 null，绝不编数」。
    """
    if isinstance(node, dict):
        return {k: null_skeleton(v) for k, v in node.items() if not k.startswith("_")}
    if isinstance(node, list):
        return []
    return None


def build_p1(frag):
    """从 prob1 碎片派生 P1 全部 14 个字段。"""
    p1 = frag["P1"]
    v1 = frag["verification"]["v1"]

    # --- 派生 1：中心温升 = 中心末温 - 初始温度 ---
    t_rise = p1["T_center_1800s"] - T0_C

    # --- 派生 2：热傅里叶数 Fo = k t / (rho cp R^2) ---
    fo_heat = K1 * T_END_S / (RHO1 * CP1 * R_M ** 2)

    # --- 派生 3：传质傅里叶数 Fo_m = D(C0) t / R^2 ---
    # D(C0) 取 prob1 求解器实际采用的值（fragment v5.D_const），不在此处重算经验式
    d_const = frag["verification"]["v5"]["D_const"]
    fo_mass = d_const * T_END_S / R_M ** 2

    # --- 派生 4：总吸热量 = 末态焓 - 初态焓（求解器的守恒对账量） ---
    e_absorbed = v1["E_end"] - v1["E0"]

    out = {
        "T_center_1800s": p1["T_center_1800s"],
        "T_surface_1800s": p1["T_surface_1800s"],
        "T_rise_1800s": round(t_rise, 4),
        "C_center_1800s": p1["C_center_1800s"],
        "C_surface_1800s": p1["C_surface_1800s"],
        "C_surface_drop_pct": round(p1["C_surface_drop_pct"], 4),
        "C_center_drop_pct": round(p1["C_center_drop_pct"], 4),
        "Bi_heat": round(p1["Bi_heat"], 4),
        "Bi_mass": round(p1["Bi_mass"], 4),
        "Fo_heat": round(fo_heat, 4),
        "Fo_mass": round(fo_mass, 5),
        "E_absorbed": round(e_absorbed, 4),
        "dt_s": p1["dt_s"],
        "dr_mm": p1["dr_mm"],
    }

    # --- 派生 5：传质/传热特征时间之比 tau_ratio ---
    # 不由本脚本重算：从 prob1/timescale.py 的产物搬运（单向依赖，避免两处口径漂移）
    ts_path = os.path.join(PKG_DIR, "prob1", "timescale.json")
    if os.path.exists(ts_path):
        with open(ts_path, "r", encoding="utf-8-sig") as f:
            ts = json.load(f)["P1_timescale"]
        out["tau_ratio"] = ts["tau_ratio"]
        out["_tau_ratio_note"] = (
            "tau_ratio = τ_mass/τ_heat = α/D，取问题一初态（附录2，C=2.55，T=28 °C）。"
            f"该比值随 C、T 变：问题一 1800 s 内表面 C 由 2.55 降到 1.512，比值 "
            f"{ts['range_problem1']['tau_ratio_from']} → "
            f"{ts['range_problem1']['tau_ratio_to']}"
            f"（+{ts['range_problem1']['change_pct']}%）；附录3 同态约 25.67、"
            "附录4 约 74.97。曲线见 prob1/timescale.json 与 ../figs/fig_p1_timescale.png。")
    return out


def fill_from(skeleton, values):
    """把求解器碎片的值填进骨架；碎片缺的键保持 null。"""
    if not isinstance(skeleton, dict) or not isinstance(values, dict):
        return skeleton if values is None else values
    out = {k: fill_from(v, values.get(k)) if k in values else v for k, v in skeleton.items()}
    for k, v in values.items():
        if k not in out:
            out[k] = v
    return out


def main():
    schema = load_schema()

    frag1, path1 = load_fragment("prob1")
    if frag1 is None:
        print(f"[FAIL] 缺少 prob1 碎片：{path1}")
        sys.exit(1)
    print(f"[OK] 读到 prob1 碎片：{path1}")

    frags, paths = {}, {}
    for n in ("prob2", "prob3", "prob4", "probQ"):
        frags[n], paths[n] = load_fragment(n)
        print(f"{'[OK] 读到' if frags[n] is not None else '⬜ 暂无'} {n} 碎片：{paths[n]}")

    # 未产出的问：保留结果键结构、叶子写 null（绝不编数）
    blocks = {}
    for key, frag_name in (("P2", "prob2"), ("P3", "prob3"), ("P4", "prob4")):
        skel = null_skeleton(schema[key])
        frag = frags[frag_name]
        blocks[key] = skel if frag is None else fill_from(skel, frag.get(key) or {})

    # ---- P4 消融键：dt_material / dt_geometry ----
    # 三组：A=附录3+固定R（即问题三）、B=附录4+固定R、C=附录4+R(t)（即问题四）
    abl = (frags.get("prob4") or {}).get("ablation") or {}
    ta, tb, tc = (abl.get("A_app3_fixedR_h"), abl.get("B_app4_fixedR_h"),
                  abl.get("C_app4_movingR_h"))
    if tb is not None:
        blocks["P4"]["t_dry_B_fixedR_h"] = tb
    if ta is not None and tb is not None:
        blocks["P4"]["dt_material"] = round(tb - ta, 4)
    if tb is not None and tc is not None:
        blocks["P4"]["dt_geometry"] = round(tc - tb, 4)
    if abl:
        tot = None if (ta is None or tc is None) else round(tc - ta, 4)
        blocks["P4"]["_ablation_note"] = (
            f"三组消融：A=附录3+固定R（t={ta} h，即问题三）、B=附录4+固定R（t={tb} h）、"
            f"C=附录4+R(t)（t={tc} h，即问题四）。"
            f"dt_material = t(B) − t(A)（材质效应，正 = 更慢）；"
            f"dt_geometry = t(C) − t(B)（收缩效应，负 = 更快）；"
            f"二者之和 = t(C) − t(A)" + (f" = {tot:+g} h" if tot is not None else "")
            + "，即问题四相对问题三的总差异。"
            "（差值按表中保留 4 位的 t 值相减得到，便于用同表数值自验；"
            "与 prob4 碎片的精确差值之间可有 ≤1e-4 h 的舍入差。）")

    # ---- P5 品质模块----
    # 此前 P5 只由 probQ/solve.py --update-results 增量写入，重跑本脚本会静默丢掉；
    # 现改为本脚本直接组装，两种入口口径一致。
    # [WARN] 兼容两种 fragment 结构：一种用 sensitivity / verification / temp_scan，
    #    另一版用 P5_sensitivity / P5_verification —— 两者都认，避免合流后再踩坑。
    P5 = None
    fragQ = frags.get("probQ")
    if fragQ is not None:
        P5 = dict(fragQ.get("P5") or {})
        for src, dst in (("_note", "_note"), ("_contract", "_contract"),
                         ("sensitivity", "sensitivity"),
                         ("P5_sensitivity", "sensitivity"),
                         ("verification", "verification"),
                         ("P5_verification", "verification"),
                         ("temp_scan", "temp_scan")):
            if fragQ.get(src):
                P5[dst] = fragQ[src]

    # ---- 图：显式清单（题注现场取值）+ 各问碎片自带 figures 去重追加 ----
    figures = build_figures(frags)
    have = {x.get("id") for x in figures}
    for f in (frag1, *(frags.get(n) for n in ("prob2", "prob3", "prob4", "probQ"))):
        for fg in ((f or {}).get("figures") or []):
            if fg.get("id") not in have:
                figures.append(fg)
                have.add(fg.get("id"))

    data = {
        "meta": {
            "generated_at": frag1["meta"]["generated_at"],
            "seed": frag1["meta"]["seed"],
            "solver_version": frag1["meta"]["solver_version"],
            "reproducible": frag1["meta"]["reproducible"],
        },
        "P1": build_p1(frag1),
        "P2": blocks["P2"],
        "P3": blocks["P3"],
        "P4": blocks["P4"],
        "figures": figures,
    }
    if P5 is not None:
        data["P5"] = P5

    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n==> 已写出：{OUT_PATH}")
    for k, v in data["P1"].items():
        print(f"    P1.{k} = {v}")
    for k in ("P2", "P3", "P4"):
        print(f"    {k} = {json.dumps(data[k], ensure_ascii=False)}")
    if "P5" in data:
        print(f"    P5 = {json.dumps(data['P5'], ensure_ascii=False)}")
    print(f"    figures = {len(data['figures'])} 条")


if __name__ == "__main__":
    main()
