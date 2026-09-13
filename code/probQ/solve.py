"""A 题 · 品质变化动力学模块 Q（单向被动拓展）



口径来源（不许在代码里另立一套）
--------------------------------
* 模型形式：单分子热降解动力学
    dQ/dt = -k(T)·Q,   Q(r, 0) = 1
    k(T)  = k_ref · exp[ -(Ea/R) · (1/T_K - 1/T_ref_K) ]
    Qbar(t)  = (1/V) ∫_V exp[ -∫_0^t k(T(r,τ)) dτ ] dV        （体积平均）
* 参数：
    Ea   = 73 kJ/mol      —— 云厚朴·厚朴酚（中药材直接文献）
    k_ref(50 °C) = 0.05 h^^1 —— 黑莓花青素 50 °C 实测
    校验目标：基准工况 Qbar(30 h) ≈ 0.22
* 敏感性：Ea × k_ref 双参数面，覆盖「稳定型多糖」→「高热敏花青素」

三条红线（违反任何一条 = 本模块作废）
------------------------------------
1. **单向被动**：Q 只在温度场解出后**事后积分**，绝不反馈进传热方程
   → 不改变 prob1–4 的任何主结果（本模块不改 `common/`，也不改主求解路径）。
2. **参数不得混用**：这里的 Ea 是【有效成分降解】活化能；
   附录 3/4 中 D 公式的 `exp(-3850/T)` 是【水分扩散】的温度依赖，两者**无关**。
3. **不得泛化**：Ea/k_ref 是"厚朴酚类成分 + 花青素实测速率"的假设，
   论文必须写明成分类型与出处，不得写成"所有药材"。

用法
----
    python probQ/solve.py --air <附件1.xlsx> [--cache <prob2的npz>] [--no-temp-scan]

产出
----
    probQ/results_fragment.json   P5 键 + 敏感性面 + 恒温温度扫描（帕累托数据）
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# ---- 控制台可移植性兜底-----------------------------------------
# 默认中文 Windows 控制台是 cp936；stdout 遇到不可编码字符会抛
# UnicodeEncodeError 并中断（历史上 prob4 曾在写 fragment 之前崩溃）。
# 下面用 errors="replace" 把不可编码字符降级为 '?'；
# **不改变 stdout 编码**，故中文输出仍按控制台原生编码正常显示。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (ValueError, OSError):
        pass

import time
from datetime import datetime

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))          # 公共模块目录
from common import fvm, props as props_mod          # noqa: E402

# 复用 prob2 的工况构造与常量（与 prob3/prob4 同一模式，不另立口径）
import importlib.util                               # noqa: E402

_spec2 = importlib.util.spec_from_file_location(
    "p2solve", os.path.join(os.path.dirname(_HERE), "prob2", "solve.py"))
p2 = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(p2)

SOLVER_VERSION = "pQ-passive-q-v1"

# ---------------- Q 参数（一经确定即冻结，不得改动） ----------------
EA_J_MOL = 73.0e3          # 有效成分降解活化能 [J/mol]（云厚朴·厚朴酚）
K_REF_PER_H = 0.05         # 参考温度下的速率常数 [1/h]（黑莓花青素 50 °C 实测）
T_REF_K = 273.15 + 50.0    # 参考温度 [K]（与 k_ref 的标注温度一致）
R_GAS = 8.314462618        # 气体常数 [J/(mol·K)]

# 敏感性面网格（覆盖「稳定型多糖」→「高热敏花青素」）
EA_GRID_KJMOL = [25.0, 40.0, 55.0, 73.0, 90.0]
KREF_GRID = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2]

# 恒温温度扫描（§5.6 帕累托数据）
TEMP_SCAN_C = [40.0, 50.0, 60.0, 70.0, 80.0]


def k_of_T(T_C, ea_j_mol=EA_J_MOL, k_ref=K_REF_PER_H, t_ref_k=T_REF_K):
    """Arrhenius 速率常数 [1/h]。T_C 可为标量或数组（°C）。"""
    T_K = np.asarray(T_C, dtype=float) + 273.15
    return k_ref * np.exp(-(ea_j_mol / R_GAS) * (1.0 / T_K - 1.0 / t_ref_k))


def integrate_Q(times_s, T_hist_C, ea_j_mol, k_ref, t_ref_k=T_REF_K):
    """对已解出的温度场做事后积分。

    times_s  : (nt,) 秒
    T_hist_C : (nt, N+1) °C
    返回 (Q_hist, Qbar)：
      Q_hist : (nt, N+1)  逐节点保留率
      Qbar   : (nt,)      体积平均保留率（等权体积，见下）
    体积权重由调用方传入（本函数内不依赖网格，方便敏感性复用）。
    """
    t_h = np.asarray(times_s, dtype=float) / 3600.0
    k = k_of_T(T_hist_C, ea_j_mol, k_ref, t_ref_k)          # (nt, N+1) [1/h]
    dt_h = np.diff(t_h)
    inc = 0.5 * (k[:-1, :] + k[1:, :]) * dt_h[:, None]       # 梯形
    A = np.vstack([np.zeros((1, k.shape[1])), np.cumsum(inc, axis=0)])
    return np.exp(-A)


def qbar_curve(Q_hist, V):
    """体积平均保留率曲线。Q_hist:(nt,N+1)，V:(N+1)。"""
    return (Q_hist @ V) / float(np.sum(V))


# ==========================================================================
def main():
    ap = argparse.ArgumentParser(description="A题 品质变化动力学模块 Q（单向被动）")
    ap.add_argument("--air", required=True, help="附件1.xlsx 路径")
    ap.add_argument("--out-dir", default=_HERE)
    ap.add_argument("--N", type=int, default=20)
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--t-end-cap", type=float, default=3 * 86400.0)
    ap.add_argument("--cache", default=None,
                    help="复用 prob2 的主求解缓存 .npz（N/dt/cap 一致才生效）")
    ap.add_argument("--no-temp-scan", action="store_true",
                    help="跳过恒温温度扫描（§5.6 帕累托数据）")
    ap.add_argument("--scan-dt", type=float, default=2.0,
                    help="温度扫描每个工况的时间步长（默认 2 s）")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    wall0 = time.time()

    # ---------------- 1. 取温度场（复用 prob2 缓存或重算） ----------------
    air, t_tab, Ta_tab, Ca_tab = p2.build_air(args.air)
    P = dict(R=0.02, L=0.25, h=p2.H_CONV, hm=p2.H_MASS, T0=28.0, C0=2.55,
             t_end=args.t_end_cap)
    pr3 = props_mod.props_app3

    print("=" * 74)
    print("A 题 · 品质变化动力学模块 Q —— 单向被动拓展（不改变 prob1–4 主结果）")
    print("=" * 74)
    print(f"模型  dQ/dt = -k(T)·Q；k(T)=k_ref·exp[-(Ea/R)(1/T-1/T_ref)]（单分子热降解模型）")
    print(f"参数  Ea = {EA_J_MOL/1e3:.0f} kJ/mol（厚朴酚）· "
          f"k_ref(50°C) = {K_REF_PER_H} h^^1（花青素实测）· T_ref = 50 °C")
    print(f"判据  max_r C(r,t) < {p2.C_DRY} kg/kg（与 prob2/3 同一停时）")
    print("-" * 74)

    res = None
    if args.cache:
        res = p2.cache_load(args.cache, args.N, args.dt, args.t_end_cap)
        if res is not None:
            print(f"→ 复用主求解缓存：{args.cache}")
    if res is None:
        tw = time.time()
        res = fvm.solve_case(
            args.N, args.dt, out_every=args.dt, air=air, props=pr3, P=P,
            record_all=True,
            stop_when=lambda tau, _T, C_: bool(np.max(C_) < p2.C_DRY))
        print(f"→ 主求解：{time.time()-tw:.0f} s")
    if args.cache and res is not None and not os.path.exists(args.cache):
        p2.cache_save(args.cache, res, args.N, args.dt, args.t_end_cap)

    times = np.asarray(res["times"], dtype=float)
    T_hist = np.asarray(res["T"], dtype=float)
    t_dry_s = float(res["t_final"])
    V = fvm.make_grid(args.N, P["R"])[4]

    # 自检：k(T_ref) 必须精确等于 k_ref（构造性校验）
    k_ref_check = float(k_of_T(T_REF_K - 273.15))
    assert abs(k_ref_check - K_REF_PER_H) < 1e-12, "k(T_ref) 自检失败"

    # ---------------- 2. 基准工况的 Q ----------------
    tw = time.time()
    Q_hist = integrate_Q(times, T_hist, EA_J_MOL, K_REF_PER_H)
    Qbar = qbar_curve(Q_hist, V)
    print(f"→ Q 积分完成：{time.time()-tw:.1f} s（{times.size} 帧 × {T_hist.shape[1]} 节点）")

    i_dry = int(np.argmin(np.abs(times - t_dry_s)))
    i_30h = int(np.argmin(np.abs(times - 30 * 3600.0)))

    print(f"\n主求解：t_dry = {t_dry_s:.0f} s = {t_dry_s/3600:.4f} h"
          f"（stopped_early={res['stopped_early']}）")
    print(f"\n**Qbar(t) 曲线（体积平均）**")
    marks = [0, 6, 12, 18, 24, 30, 36, 42, 48, 54]
    print("| t (h) | " + " | ".join(f"{m:d}" for m in marks) + " |")
    print("|---|" + "---|" * len(marks))
    row = []
    for m in marks:
        j = int(np.argmin(np.abs(times - m * 3600.0)))
        row.append(f"{Qbar[j]:.4f}")
    print("| Qbar | " + " | ".join(row) + " |")

    print(f"\n基准值：**Qbar(30 h) = {Qbar[i_30h]:.4f}**   "
          f"（校验目标 ≈ 0.22；等温 50 °C 解析值 exp(-0.05×30) = {np.exp(-0.05*30):.4f}）")
    print(f"烘干结束（t_dry={t_dry_s/3600:.2f} h）：Qbar = {Qbar[i_dry]:.4f}，"
          f"中心 Q = {Q_hist[i_dry, 0]:.4f}，表面 Q = {Q_hist[i_dry, -1]:.4f}")

    # Q 剖面（烘干结束时刻，21 个节点）
    prof = Q_hist[i_dry, :]
    print("\n**烘干结束时刻的 Q 剖面**（r: 0=中心 → 2.0 cm=表面）")
    print("| r (cm) | " + " | ".join(f"{x:.1f}" for x in np.linspace(0, 2.0, 21)) + " |")
    print("|---|" + "---|" * 21)
    print("| Q | " + " | ".join(f"{v:.3f}" for v in prof) + " |")

    # ---------------- 3. Ea × k_ref 敏感性面 ----------------
    print("\n" + "=" * 74)
    print("敏感性面：Qbar(30 h)（行=Ea kJ/mol，列=k_ref h^^1）")
    print("=" * 74)
    sens30, sensdry = [], []
    hdr = "| Ea\\k_ref | " + " | ".join(f"{k:g}" for k in KREF_GRID) + " |"
    print(hdr); print("|---|" + "---|" * len(KREF_GRID))
    for ea_kj in EA_GRID_KJMOL:
        r30, rdry = [], []
        for kr in KREF_GRID:
            Qs = integrate_Q(times, T_hist, ea_kj * 1e3, kr)
            qb = qbar_curve(Qs, V)
            r30.append(qb[i_30h]); rdry.append(qb[i_dry])
        sens30.append(r30); sensdry.append(rdry)
        print(f"| {ea_kj:g} | " + " | ".join(f"{v:.3f}" for v in r30) + " |")
    print("\n（同一张面在 t_dry 时刻的取值已存入 fragment 的 sensitivity.qbar_at_dry）")

    # ---------------- 4. 恒温温度扫描（§5.6 帕累托数据） ----------------
    scan = []
    if not args.no_temp_scan:
        print("\n" + "=" * 74)
        print(f"恒温温度扫描（N={args.N}，dt={args.scan_dt:g} s，T_air 恒定、C_air=0.05）")
        print("=" * 74)
        print("| T_air (°C) | t_dry (h) | Qbar(t_dry) | 能量 ∫Qdt (MJ) | 备注 |")
        print("|---|---|---|---|---|")
        for Tc in TEMP_SCAN_C:
            tw = time.time()
            a2 = fvm.ConstDriver(Tc, p2.C_AIR_C)
            Pi = dict(P, t_end=args.t_end_cap)
            r2 = fvm.solve_case(args.N, args.scan_dt, out_every=args.scan_dt,
                                air=a2, props=pr3, P=Pi, record_all=True,
                                stop_when=lambda tau, _T, C_: bool(np.max(C_) < p2.C_DRY))
            t2 = np.asarray(r2["times"], float)
            td2 = float(r2["t_final"])
            Qs = integrate_Q(t2, np.asarray(r2["T"], float), EA_J_MOL, K_REF_PER_H)
            qb2 = qbar_curve(Qs, V)
            j = int(np.argmin(np.abs(t2 - td2)))
            hit_cap = not r2["stopped_early"]
            note = "72 h 上限仍未干透" if hit_cap else "正常判停"
            print(f"| {Tc:g} | {td2/3600:.2f} | {qb2[j]:.4f} | "
                  f"{r2['cumE_eq_expect']/1e6:.2f} | {note} |")
            scan.append(dict(T_air_C=Tc, t_dry_h=td2 / 3600.0,
                             t_dry_s=td2, qbar_at_dry=float(qb2[j]),
                             qbar_at_30h=float(qb2[int(np.argmin(np.abs(t2 - 30 * 3600.0)))]),
                             energy_J=float(r2["cumE_eq_expect"]),
                             stopped_early=bool(r2["stopped_early"]),
                             max_C_at_end=float(np.max(r2["C"][-1])),
                             solve_s=round(time.time() - tw, 1)))

    # ---------------- 5. 落盘 ----------------
    frag = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "seed": 0,
            "solver_version": SOLVER_VERSION,
            "reproducible": True,
            "passive": True,
            "passive_note": ("Q 仅对已解出的 T(r,t) 事后积分，不反馈进传热方程；"
                             "本模块不改 common/，不影响 prob1–4 任何主结果"),
            "air_source": "附件1.xlsx",
            "N_radial": args.N, "dt_s": args.dt,
            "params": {
                "Ea_J_mol": EA_J_MOL, "Ea_kJ_mol": EA_J_MOL / 1e3,
                "Ea_source": "云厚朴·厚朴酚（中药材热降解文献值）",
                "k_ref_per_h": K_REF_PER_H,
                "k_ref_source": "黑莓花青素 50 °C 实测（同上）",
                "T_ref_C": 50.0, "T_ref_K": T_REF_K,
                "R_gas": R_GAS,
                "component_note": ("参数对应厚朴酚类成分 + 花青素实测速率；"
                                   "论文必须写明假设的成分类型，不得泛化为所有药材"),
            },
        },
        "P5": {
            "Q_mean_30h": float(Qbar[i_30h]),
            "Q_mean_at_dry": float(Qbar[i_dry]),
            "Q_center_at_dry": float(Q_hist[i_dry, 0]),
            "Q_surface_at_dry": float(Q_hist[i_dry, -1]),
            "Q_min_at_dry": float(np.min(Q_hist[i_dry, :])),
            "t_dry_h": t_dry_s / 3600.0,
            "isothermal_check": {
                "exp_minus_kt": float(np.exp(-K_REF_PER_H * 30.0)),
                "note": "等温 50 °C、30 h 的解析值 exp(−k_ref·t)；Q̄(30h) 略高是因预热段温度低",
            },
            "qbar_curve_h": {f"{m:d}": float(Qbar[int(np.argmin(np.abs(times - m * 3600.0)))])
                             for m in marks},
            "Q_profile_at_dry": [float(v) for v in prof],
        },
        "sensitivity": {
            "ea_grid_kJ_mol": EA_GRID_KJMOL,
            "kref_grid_per_h": KREF_GRID,
            "qbar_at_30h": sens30,
            "qbar_at_dry": sensdry,
            "note": "覆盖「稳定型多糖」(低 Ea/低 k_ref) → 「高热敏花青素」(高 Ea/高 k_ref)",
        },
        "temp_scan": scan,
        "verification": {
            "k_at_Tref_equals_kref": bool(abs(k_ref_check - K_REF_PER_H) < 1e-12),
            "q_monotone_decreasing": bool(np.all(np.diff(Qbar) <= 1e-12)),
            # 1.0 附近允许 1e-9 的浮点容差（Qbar(0)=1+ε 是求和舍入，非物理越界）
            "q_in_unit_interval": bool(float(Qbar.min()) >= -1e-12
                                       and float(Qbar.max()) <= 1.0 + 1e-9),
            "reuses_prob2_field": True,
            "tol": 1e-9,
        },
    }
    out = os.path.join(args.out_dir, "results_fragment.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(frag, f, ensure_ascii=False, indent=2)
    print(f"\n→ fragment 已写出：{out}")
    print(f"\n[OK] 品质模块 Q 完成   总用时 {time.time()-wall0:.0f} s")


if __name__ == "__main__":
    main()
