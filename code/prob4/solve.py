#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 题 · 问题 4 —— 考虑尺寸变化（收缩）的烘干时长

物理设定
--------
· 物性：**附录 4**（ρ=760+90C、c_p=1850+2150·C/(C+1)、k=0.12+0.20·C/(C+1)、
  D=4.2e-4·e^(-0.30/C)·e^(-3850/T)，T 用 **K**）
· 半径：**R(t) 由附件 2 给定**（145 点，0–259200 s，步长 1800 s），
  超出范围按 **半径末值** 取 1.198 cm
· 环境：同 Q2/Q3（0–14400 s 附件1 实测 → 其后冻结在 50 °C / 0.05 kg/kg）
· 判据：各处 C < 0.15 kg/kg

动边界的数值方案：**Lagrangian 归一化网格（ξ = r/R(t)）**
-----------------------------------------------------------
设 ξ = r/R(t) ∈ [0,1] 为**材料坐标**（假设收缩各向同性且均匀 => 材料点 ξ 不变）。
在材料坐标下把控制方程重写，可得到两条关键性质：

1. **干料密度 ρ_d 会自动约掉**，无需引入题面未给的量（与 H3 同源的简化）：
       V~_i · R^2(t) · dC_i/dt = Σ A~_face · D · (ΔC/Δξ)                    （湿）
       ρc_p · V~_i · R^2(t) · dT_i/dt = Σ A~_face · k · (ΔT/Δξ)              （热）
   其中 V~_i、A~_face 是 ξ 空间的**常数**几何系数（与 R 无关）。
2. 因 `A~/Δξ` 与 R 无关而 `V~ ∝ R^2`，有效扩散时间尺度 ∝ **R^2/D**
   => R 收缩使干燥变快，符合物理预期。

由此，**干基质量守恒可在机器精度上对账**（问题四的完成判据）：
    M ≡ Σ V~_i C_i ， dM/dt = 2π·h_m·(C_air - C_N)/R(t)

[WARN] 与 Q1–Q3 的自洽性：R 恒定时（Rdot=0）本格式**逐项退化为** `common/fvm.py` 的
   定网格 FVM，故不是另起一套模型，而是同一模型族的动边界推广。

为何不直接用 `fvm.solve_case`
------------------------------
`common/fvm.py` 的 `solve_case` 假定 V 恒定（其 `R_fn` 走的是"外部逐段重启动"路线，
会在每个重启动点引入插值误差）。本文件改为**每步更新 R(t)** 的严格 Lagrangian 推进，
单独实现以避免动公共模块、影响 prob1/2/3 的回归基线（`parity_check.py`）。

消融（按三组对照把「材质效应」与「几何收缩效应」分离）
------------------------------------------------------------------
| 组 | 材质 | 半径 | 说明 |
|----|------|------|------|
| A | 附录3 | 固定 2 cm | = 问题3 的结果（直接读 prob3 fragment，不重算）|
| B | 附录4 | 固定 2 cm | **材质效应** = B - A |
| C | 附录4 | R(t)      | **几何收缩效应** = C - B（本问主结果）|

输出
----
· 表 6：每隔 6 h × 距离每隔 0.5 cm，**末列 = 当时的 R(t)（「药材表面」，动态列）**
· `result4.xlsx`：每隔 **60 s** × 0.1 cm 固定网格，**r > R(t) 的格子留空**（超界留空）

用法
----
    python prob4/solve.py --air "<附件1.xlsx>" --radius "<附件2.xlsx>"
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

# ---------------- 边界条件口径（不得在代码里另立一套）----------------
T_SWITCH = 14400.0     # 附件1 实测段终点
T_AIR_C = 50.0         # 恒温段风温
C_AIR_C = 0.05         # 恒温段风含湿
H_CONV = 25.0          # 表面对流换热系数
H_MASS = 8.0e-7
C_DRY = 0.15           # 烘干完成判据阈值
R0 = 0.02              # 初始半径 [m]
R_END = 0.01198        # 附件2 半径末值（超出范围取此值）
SOLVER_VERSION = "p4-fvm-cn-lagrangian-varR-v1"

TAB6_CM = [0.0, 0.5, 1.0, 1.5]      # 表6 固定列；末列为动态的「药材表面」
# result4.xlsx 的**固定网格**只到 1.9 cm（20 列）：模板（附件3/result4.xlsx）末列出了
# 「药材表面」而不是 r=2.0，因为收缩后真正的表面在 r=R(t) 处、随时间内移。
# 表面值作为**动态末列**单独给出（见 common/fvm.write_result_xlsx 的 last_col）。
OUT_CM = np.array([round(i * 0.1, 1) for i in range(20)])   # 0…1.9 cm，20 列


# ==========================================================================
# 附件 2 → R(t)
# ==========================================================================
def load_radius(path):
    """读附件2：时间(s) / 半径(cm)。返回 (t, R_m)。"""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = [(float(r[0]), float(r[1]))
            for r in ws.iter_rows(min_row=2, values_only=True)
            if r[0] is not None]
    wb.close()
    t = np.array([x[0] for x in rows])
    R = np.array([x[1] for x in rows]) * 0.01      # cm → m
    return t, R


class RadiusDriver:
    """R(t)：附件2 线性插值，超出末端按半径末值冻结。"""

    def __init__(self, t, R):
        self.t, self.R = t, R
        self.R_last = float(R[-1])
        assert abs(self.R_last - R_END) < 1e-9, (
            f"附件2 末值 {self.R_last} 与附件2 的半径端点值 {R_END} 不一致 —— 口径可能变了")

    def __call__(self, tau):
        if tau <= self.t[0]:
            return float(self.R[0])
        if tau >= self.t[-1]:
            return self.R_last                      # 超出范围取半径末值
        return float(np.interp(tau, self.t, self.R))


# ==========================================================================
# Lagrangian ξ 网格（单位半径）
# ==========================================================================
def make_xi_grid(N):
    """ξ ∈ [0,1] 上的柱坐标 FVM 系数（单位半径、单位长度）。

    返回 (dxi, xi, A_face, A_R, Vt)
      Vt[i]    : ξ 空间控制体（常数），Σ Vt = π
      A_face[i]: ξ 空间界面面积（常数），i = 0..N-1
      A_R      : ξ=1 处的 A（= 2π），物理面积 = A_R · R(t)
    """
    dxi = 1.0 / N
    xi = np.arange(N + 1) * dxi
    A_face = 2.0 * np.pi * (np.arange(N) + 0.5) * dxi
    A_R = 2.0 * np.pi
    Vt = np.empty(N + 1)
    Vt[0] = np.pi * (0.5 * dxi) ** 2
    Vt[1:N] = 2.0 * np.pi * np.arange(1, N) * dxi ** 2
    Vt[N] = np.pi * (1.0 ** 2 - ((N - 0.5) * dxi) ** 2)
    return dxi, xi, A_face, A_R, Vt


# ==========================================================================
# 主求解器：Lagrangian 动边界 CN + Picard
# ==========================================================================
def solve_moving(N, dt, out_every, air, Rfn, props, P, t_end,
                 max_picard=30, tol_T=1e-8, tol_C=1e-11):
    """在 ξ ∈ [0,1] 的材料坐标上推进，半径 R(t) 每步更新。"""
    dxi, xi, A_face, A_R, Vt = make_xi_grid(N)
    n = N + 1

    T = np.full(n, P["T0"], dtype=float)
    C = np.full(n, P["C0"], dtype=float)

    nsteps = int(round(t_end / dt))
    out_stride = int(round(out_every / dt))
    if abs(out_stride * dt - out_every) > 1e-9:
        raise ValueError("out_every 必须是 dt 的整数倍")

    # 历史（预分配，提前停时截断）
    n_out = nsteps // out_stride
    times = np.empty(n_out + 1)
    T_hist = np.empty((n_out + 1, n))
    C_hist = np.empty((n_out + 1, n))
    R_hist = np.empty(n_out + 1)
    times[0] = 0.0; T_hist[0] = T; C_hist[0] = C; R_hist[0] = Rfn(0.0)

    # ---- 干基质量对账累加器（问题四完成判据）----
    #   M ≡ Σ V~ C ； dM/dt = 2π h_m (C_air - C_N)/R
    def _Mwater(Cv):
        return float(np.sum(Vt * Cv))

    def _Qmass(tau, Cv):
        Ta, Ca = air(tau)
        # [WARN] 表面节点是索引 N（共 N+1 个节点），不是 N-1
        return 2.0 * np.pi * P["hm"] * (Ca - Cv[N]) / Rfn(tau)

    M_prev = _Mwater(C)
    Qm_prev = _Qmass(0.0, C)
    cumM_defect = cumM_expect = 0.0

    # ---- 能量对账（方程级口径，同 prob2 的教训）----
    def _Qheat(tau, Tv):
        Ta, _ = air(tau)
        # [WARN] 表面节点是索引 N（共 N+1 个节点），不是 N-1
        return 2.0 * np.pi * Rfn(tau) * P["h"] * (Ta - Tv[N])

    Qh_prev = _Qheat(0.0, T)
    cumE_defect = cumE_expect = 0.0

    j_last = 0
    t_final = t_end
    stopped_early = False
    picard_max = 0

    for s in range(1, nsteps + 1):
        tn = s * dt
        tnm = tn - dt
        Rn = Rfn(tnm)
        Rnp = Rfn(tn)
        Rmid = Rfn(0.5 * (tnm + tn))
        Rc2 = Rmid ** 2

        Ta_n, Ca_n = air(tnm)
        Ta_np, Ca_np = air(tn)

        T_k = T.copy()
        C_k = C.copy()
        T_new, C_new = T, C
        rc = None

        for it in range(max_picard):
            C_mid = 0.5 * (C + C_k)
            T_mid = 0.5 * (T + T_k)
            pr = props(C_mid, T_mid + 273.15)
            rc = pr["rho"] * pr["cp"]

            # ---- 热：CN（界面系数与 R 无关，体积项 ∝ R^2）----
            kf = 0.5 * (pr["k"][:-1] + pr["k"][1:])
            beta = kf * A_face / dxi
            aH = np.zeros(n); bH = np.zeros(n); cH = np.zeros(n)
            cap = rc * Vt * Rc2 / dt
            bH[0] = cap[0] + 0.5 * beta[0]
            cH[0] = -0.5 * beta[0]
            for i in range(1, N):
                bH[i] = cap[i] + 0.5 * (beta[i - 1] + beta[i])
                aH[i] = -0.5 * beta[i - 1]
                cH[i] = -0.5 * beta[i]
            bH[N] = cap[N] + 0.5 * A_R * Rnp * P["h"] + 0.5 * beta[N - 1]
            aH[N] = -0.5 * beta[N - 1]

            rhsH = cap * T
            rhsH[0] += 0.5 * beta[0] * (T[1] - T[0])
            rhsH[1:N] += 0.5 * (beta[1:N] * (T[2:N + 1] - T[1:N])
                                - beta[0:N - 1] * (T[1:N] - T[0:N - 1]))
            rhsH[N] += (0.5 * A_R * Rn * P["h"] * (Ta_n - T[N])
                        + 0.5 * A_R * Rnp * P["h"] * (Ta_np)
                        - 0.5 * beta[N - 1] * (T[N] - T[N - 1]))
            T_new = fvm.thomas(aH, bH, cH, rhsH)

            # ---- 湿：CN ----
            D = pr["D"]
            Df = 0.5 * (D[:-1] + D[1:])
            d_face = Df * A_face / dxi
            aM = np.zeros(n); bM = np.zeros(n); cM = np.zeros(n)
            capM = Vt * Rc2 / dt
            bM[0] = capM[0] + 0.5 * d_face[0]
            cM[0] = -0.5 * d_face[0]
            for i in range(1, N):
                bM[i] = capM[i] + 0.5 * (d_face[i - 1] + d_face[i])
                aM[i] = -0.5 * d_face[i - 1]
                cM[i] = -0.5 * d_face[i]
            bM[N] = capM[N] + 0.5 * A_R * Rnp * P["hm"] + 0.5 * d_face[N - 1]
            aM[N] = -0.5 * d_face[N - 1]

            rhsM = capM * C
            rhsM[0] += 0.5 * d_face[0] * (C[1] - C[0])
            rhsM[1:N] += 0.5 * (d_face[1:N] * (C[2:N + 1] - C[1:N])
                                - d_face[0:N - 1] * (C[1:N] - C[0:N - 1]))
            rhsM[N] += (0.5 * A_R * Rn * P["hm"] * (Ca_n - C[N])
                        + 0.5 * A_R * Rnp * P["hm"] * (Ca_np)
                        - 0.5 * d_face[N - 1] * (C[N] - C[N - 1]))
            C_new = fvm.thomas(aM, bM, cM, rhsM)

            picard_max = max(picard_max, it + 1)
            if (np.max(np.abs(T_new - T_k)) < tol_T
                    and np.max(np.abs(C_new - C_k)) < tol_C):
                T_k, C_k = T_new, C_new
                break
            T_k, C_k = T_new, C_new

        # ---- 对账（梯形积分，与格式一致）----
        M_now = _Mwater(C_new)
        Qm_now = _Qmass(tn, C_new)
        dM = M_now - M_prev
        dM_exp = 0.5 * dt * (Qm_prev + Qm_now)
        cumM_defect += abs(dM - dM_exp)
        cumM_expect += abs(dM_exp)

        Qh_now = _Qheat(tn, T_new)
        # 方程级：用本步 CN 的容量项 rc·Vt·R^2
        dE_eq = float(np.sum(rc * Vt * Rc2 * (T_new - T)))
        dE_exp = 0.5 * dt * (Qh_prev + Qh_now)
        cumE_defect += abs(dE_eq - dE_exp)
        cumE_expect += abs(dE_exp)

        T, C = T_new, C_new
        M_prev, Qm_prev = M_now, Qm_now
        Qh_prev = Qh_now

        if s % out_stride == 0:
            j = s // out_stride
            times[j] = tn; T_hist[j] = T; C_hist[j] = C; R_hist[j] = Rnp
            j_last = j
        if np.max(C) < C_DRY:
            stopped_early = True
            t_final = tn
            if s % out_stride != 0:
                times = np.append(times[:j_last + 1], tn)
                T_hist = np.vstack([T_hist[:j_last + 1], T])
                C_hist = np.vstack([C_hist[:j_last + 1], C])
                R_hist = np.append(R_hist[:j_last + 1], Rnp)
                j_last += 1
            break

    times = times[:j_last + 1]
    T_hist = T_hist[:j_last + 1]
    C_hist = C_hist[:j_last + 1]
    R_hist = R_hist[:j_last + 1]

    return dict(N=N, dt=dt, xi=xi, r_phys=xi * R0, times=times, T=T_hist, C=C_hist,
                R=R_hist, t_final=t_final, stopped_early=stopped_early,
                picard_max=picard_max,
                max_consM_rel=cumM_defect / max(cumM_expect, 1e-30),
                max_consE_rel=cumE_defect / max(cumE_expect, 1e-30))


def main():
    ap = argparse.ArgumentParser(description="A题 问题4：考虑尺寸变化的烘干时长")
    ap.add_argument("--air", required=True, help="附件1.xlsx 路径")
    ap.add_argument("--radius", required=True, help="附件2.xlsx 路径")
    ap.add_argument("--out-dir", default=_HERE)
    ap.add_argument("--N", type=int, default=20)
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--dt2", type=float, default=2.0)
    ap.add_argument("--t-end-cap", type=float, default=6 * 86400.0)
    ap.add_argument("--no-xlsx", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    wall0 = time.time()

    _h, t_air, Ta_tab, Ca_tab = fvm.load_air_table(args.air)
    air = fvm.StagedDriver(fvm.AirDriver(t_air, Ta_tab, Ca_tab), T_SWITCH,
                           fvm.ConstDriver(T_AIR_C, C_AIR_C))
    t_r, R_r = load_radius(args.radius)
    Rfn = RadiusDriver(t_r, R_r)

    P = dict(R=R0, L=0.25, h=H_CONV, hm=H_MASS, T0=28.0, C0=2.55,
             t_end=args.t_end_cap)
    pr4 = props_mod.props_app4

    print("=" * 74)
    print("A 题 · 问题4 —— 考虑尺寸变化（收缩）的烘干时长")
    print("=" * 74)
    print(f"物性  附录4（ρ=760+90C、cp、k、D 双指数 T 用 K）")
    print(f"半径  附件2 实测：{R_r[0]*100:.3f} → {R_r[-1]*100:.3f} cm"
          f"（{t_r[0]:.0f}–{t_r[-1]:.0f} s，{t_r.size} 点）；"
          f"超出按半径末值冻结 {R_END*100:.3f} cm")
    print(f"数值  Lagrangian 材料坐标 ξ=r/R(t)，N={args.N}，dt={args.dt} s，"
          f"输出步长 60 s")
    print("-" * 74)

    # ---------------- C 组（主结果）：附录4 + R(t) ----------------
    res = solve_moving(args.N, args.dt, 60.0, air, Rfn, pr4, P, args.t_end_cap)
    t_dry_s = float(res["t_final"])
    t_dry_h = t_dry_s / 3600.0
    hit_cap = not res["stopped_early"]
    C_h, T_h, ts, Rs = res["C"], res["T"], res["times"], res["R"]

    print(f"→ [C 组 附录4+R(t)] t_dry = {t_dry_s:.0f} s = {t_dry_h:.4f} h "
          f"= {t_dry_h/24:.3f} 天   stopped_early={res['stopped_early']}")
    print(f"  Picard 最大迭代 {res['picard_max']}，记录 {ts.size} 帧，"
          f"用时 {time.time()-wall0:.1f} s")
    if hit_cap:
        print(f"  [WARN] 到 {args.t_end_cap:.0f} s 上限仍未满足判据 —— 不得沿用！")
    Cmax_end = float(np.max(C_h[-1]))
    print(f"  末态：max C = {Cmax_end:.8f}（判据 <{C_DRY}），"
          f"C_center = {C_h[-1][0]:.8f}，R = {Rs[-1]*100:.4f} cm，"
          f"T_center = {T_h[-1][0]:.3f} °C")

    ver = {}
    ver["v1_dry_mass"] = dict(rel=float(res["max_consM_rel"]), tol=1e-6,
                              passed=bool(res["max_consM_rel"] < 1e-6))
    print(f"\n[V1 干基质量守恒]  rel = {res['max_consM_rel']:.4e}  → "
          f"{'[OK]' if ver['v1_dry_mass']['passed'] else '[FAIL]'}")
    ver["v1_energy_eq"] = dict(rel=float(res["max_consE_rel"]), tol=1e-6,
                               passed=bool(res["max_consE_rel"] < 1e-6))
    print(f"[V1 能量守恒(方程级)] rel = {res['max_consE_rel']:.4e}  → "
          f"{'[OK]' if ver['v1_energy_eq']['passed'] else '[FAIL]'}")
    ver["j1"] = dict(C_max_at_dry=round(Cmax_end, 8), threshold=C_DRY,
                     passed=bool(Cmax_end < C_DRY))
    print(f"[判据回验]  max C = {Cmax_end:.8f} < {C_DRY}  → "
          f"{'[OK]' if ver['j1']['passed'] else '[FAIL]'}")

    # ---------------- 表 6（每隔 6 h + 末行；末列 = 当时 R(t)）----------------
    n6 = int(t_dry_s // 21600.0)
    tab6_t = [21600.0 * i for i in range(1, n6 + 1)] + [t_dry_s]

    def _sample_C(t):
        i = int(np.argmin(np.abs(ts - t)))
        return C_h[i], Rs[i]

    print("\n" + "=" * 74)
    lines = ["**表6  药材烘干过程的水分浓度（kg/kg）**", "",
             "| 时间(h) | " + " | ".join(f"{d:g}" for d in TAB6_CM)
             + " | 药材表面 |", "|" + "---|" * (len(TAB6_CM) + 2)]
    tab6 = {}
    for t in tab6_t:
        rowC, Rc = _sample_C(t)
        r_cm = res["xi"] * Rc * 100.0
        vals = []
        for d in TAB6_CM:
            if d > Rc * 100.0 + 1e-9:
                vals.append(None)                     # 超界留空
            else:
                vals.append(round(float(np.interp(d, r_cm, rowC)), 4))
        surf = round(float(rowC[-1]), 4)
        tab6[f"{t:g}"] = dict(
            **{f"{d:g}": vals[j] for j, d in enumerate(TAB6_CM)},
            surface=surf, R_cm=round(Rc * 100.0, 4))
        label = (f"{t/3600:.4f}（烘干结束）" if abs(t - t_dry_s) < 1e-9
                 else f"{t/3600:g}")
        lines.append(f"| {label} | "
                     + " | ".join("—" if v is None else f"{v:.4f}" for v in vals)
                     + f" | {surf:.4f} |")
    print("\n".join(lines))

    # ---------------- result4.xlsx（超界留空；末列表头「药材表面」）----------------
    xlsx_path = os.path.join(args.out_dir, "result4.xlsx")
    if not args.no_xlsx:
        tw = time.time()
        # [WARN] 两个坑（与问题3 的写盘口径一致）：
        #   ① 容器名必须是附件3 模板实测的 **Sheet1**，不是「水分浓度」
        #      （实测：result1/2 模板是「温度」「水分浓度」，result3/4 模板是「Sheet1」）
        #   ② 单表必须显式传 hists=(C_h,)：否则旧逻辑 zip(sheets, (T_hist, C_hist))
        #      会被截断，把温度表写进水分 sheet —— 文件能开、数字也像，但物理量错了
        #
        # ③ 末列「药材表面」是**动态列**：材料坐标最外节点 ξ=1 就是当时的表面 r=R(t)，
        #    故取 C_h[:, -1] 逐行给出；固定网格只到 1.9 cm，r>R(t) 的格子按超界留空处理。
        #    —— 曾经的做法是把 r=2.0 那一列的表头**改个名**充当表面列，而 r=2.0 恒大于
        #    R(t)（收缩到约 1.2 cm），按留空规则整列都为空，表6 因此出不来。
        surf_h = np.asarray(C_h, dtype=float)[:, -1]        # ξ=1 → r=R(t)，逐行对齐 ts
        fvm.write_result_xlsx(xlsx_path, ts, res["r_phys"], None, None,
                              out_cm=OUT_CM, sheets=("Sheet1",),
                              hists=(C_h,), R_at=Rs, R_ref=R0,
                              last_col=("药材表面", surf_h))
        print(f"\n→ result4.xlsx 已写出：{ts.size - 1} 行 × "
              f"{OUT_CM.size} 列网格 + 1 列表面 = {OUT_CM.size + 1} 列，"
              f"{os.path.getsize(xlsx_path)/1024:.0f} KB，用时 {time.time()-tw:.1f} s")

    # ---------------- 双 dt ----------------
    res2 = solve_moving(args.N, args.dt2, 60.0, air, Rfn, pr4, P, args.t_end_cap)
    t2 = float(res2["t_final"])
    dpct = abs(t2 - t_dry_s) / t_dry_s * 100.0
    ver["dt_dual"] = dict(dt1=args.dt, dt2=args.dt2,
                          t_dry1_h=round(t_dry_h, 4), t_dry2_h=round(t2 / 3600, 4),
                          diff_pct=round(dpct, 4), passed=bool(dpct < 1.0))
    print(f"[双 dt 复核]  dt={args.dt} → {t_dry_h:.4f} h；dt={args.dt2} → "
          f"{t2/3600:.4f} h；差 {dpct:.4f}%  → "
          f"{'[OK]' if ver['dt_dual']['passed'] else '[FAIL]'}")

    # ---------------- 消融：B 组（附录4 + 固定 R）----------------
    Pfix = dict(P, R=R0, t_end=args.t_end_cap)
    resB = fvm.solve_case(args.N, args.dt, out_every=60.0, air=air, props=pr4,
                          P=Pfix, record_all=True,
                          stop_when=lambda tau, _T, C_: bool(np.max(C_) < C_DRY))
    tB_h = float(resB["t_final"]) / 3600.0

    # A 组：直接读 prob3（附录3 + 固定 R）
    tA_h = None
    p3 = os.path.join(os.path.dirname(_HERE), "prob3", "results_fragment.json")
    if os.path.exists(p3):
        try:
            with open(p3, encoding="utf-8") as f:
                tA_h = json.load(f)["P3"]["t_dry_h"]
        except Exception:
            tA_h = None

    ab = dict(A_app3_fixedR_h=tA_h, B_app4_fixedR_h=round(tB_h, 4),
              C_app4_movingR_h=round(t_dry_h, 4))
    if tA_h is not None:
        ab["材质效应_B_minus_A_h"] = round(tB_h - tA_h, 4)
    ab["收缩效应_C_minus_B_h"] = round(t_dry_h - tB_h, 4)
    print(f"\n[三组消融 A/B/C]")
    print(f"  A 附录3 + 固定R : {tA_h if tA_h is not None else '（prob3 未跑）'} h")
    print(f"  B 附录4 + 固定R : {tB_h:.4f} h")
    print(f"  C 附录4 + R(t)  : {t_dry_h:.4f} h   ← 本问主结果")
    if tA_h is not None:
        print(f"  材质效应 B-A    : {tB_h - tA_h:+.4f} h")
    print(f"  收缩效应 C-B    : {t_dry_h - tB_h:+.4f} h")

    # ---------------- fragment ----------------
    frag = dict(
        meta=dict(generated_at=datetime.now().isoformat(timespec="seconds"),
                  seed=0, solver_version=SOLVER_VERSION, reproducible=True,
                  air_source=os.path.basename(args.air),
                  radius_source=os.path.basename(args.radius),
                  props="附录4", grid="Lagrangian 材料坐标 ξ=r/R(t)",
                  N_radial=args.N, dt_s=args.dt),
        P4=dict(
            t_dry_h=round(t_dry_h, 4),
            shrink_pct=round((1.0 - float(Rs[-1]) / R0) * 100.0, 4),
            C_max_at_dry=round(Cmax_end, 8),
            # ---- 诊断 ----
            t_dry_s=round(t_dry_s, 1), t_dry_day=round(t_dry_h / 24.0, 4),
            stopped_early=bool(res["stopped_early"]),
            stop_rule=f"烘干完成判据：max_r C < {C_DRY} kg/kg",
            R0_cm=2.0, R_end_cm=round(float(Rs[-1]) * 100.0, 4),
            C_center_at_dry=round(float(C_h[-1][0]), 8),
            T_center_at_dry=round(float(T_h[-1][0]), 4),
            T_air_const_C=T_AIR_C, C_air_const=C_AIR_C,
            h_W_m2K=H_CONV, hm_m_s=H_MASS,
        ),
        ablation=ab,
        tables=dict(table6_moisture=tab6,
                    note="t 单位 s；末行为烘干结束时刻；末列「药材表面」= 当时 R(t)；"
                         "中间列若 >R(t) 记为 None（留空）"),
        verification=ver,
    )
    frag_path = os.path.join(args.out_dir, "results_fragment.json")
    with open(frag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(frag, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n→ fragment 已写出：{frag_path}")

    allpass = (all(v.get("passed", True) for v in ver.values()) and not hit_cap)
    print("\n" + "=" * 74)
    print(f"{'[OK] 问题4 全部检查通过' if allpass else '[FAIL] 有问题项未通过，见上'}"
          f"   总用时 {time.time()-wall0:.1f} s")
    print("=" * 74)
    return 0 if allpass else 1


if __name__ == "__main__":
    sys.exit(main())
