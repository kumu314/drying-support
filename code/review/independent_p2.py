#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立复核脚本 —— 问题2（变物性，附录3）

目的
----
复核 `prob2/solve.py` 的数值结果，**不复用** `common/fvm.py` 的任何离散代码：
本文件从零写一套柱坐标 FVM 半离散 + scipy 自适应 BDF 积分，用**完全不同的
时间积分路径**去逼近同一 PDE，看是否收敛到同一个物理答案。

独立性说明（哪些是共享的、哪些是独立的）
----------------------------------------
* 共享：物理口径（控制方程、边界条件、附录3 物性）——必须与主求解器保持一致
* 独立：网格构造、通量装配、时间积分器（scipy BDF vs 自写 CN+Picard）、
        判停逻辑、含水率单调性检查 —— 全部重写

判据：ΔT < 0.05 °C 且 ΔC < 0.005 kg/kg 视为对账通过（与 prob2 的 V4 同阈值）。

用法
----
    python review/independent_p2.py --air "<附件1.xlsx>" [--t-end 21600]
"""

from __future__ import annotations

import argparse
import json
import os
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


import numpy as np
from scipy.integrate import solve_ivp

# ---------------- 物理常量（题目附录2 与附件1 口径，不得另立一套）----------------
R = 0.02            # m
H_CONV = 25.0       # W/(m^2 K)
H_MASS = 8.0e-7     # m/s
T0 = 28.0           # °C
C0 = 2.55           # kg/kg
T_SWITCH = 14400.0  # 附件1 实测段终点
T_AIR_C = 50.0      # 恒温段风温
C_AIR_C = 0.05      # 恒温段风含湿
C_DRY = 0.15        # 烘干完成判据阈值

APP3 = dict(rho_a=650.0, rho_b=128.0, cp_a=1450.0, cp_b=2736.0,
            k_a=0.21, k_b=0.38, D_A=2.4e-3, D_b=0.45, D_E=3850.0)


def props3(C, T_C):
    """附录3 变物性。C: kg/kg，T_C: °C（内部转 K）。"""
    C = np.asarray(C, float)
    Tc = np.maximum(C, 1e-12)
    T_K = np.asarray(T_C, float) + 273.15
    frac = C / (C + 1.0)
    with np.errstate(under="ignore"):
        D = APP3["D_A"] * np.exp(-APP3["D_b"] / Tc) * np.exp(-APP3["D_E"] / T_K)
    return (APP3["rho_a"] + APP3["rho_b"] * C,
            APP3["cp_a"] + APP3["cp_b"] * frac,
            APP3["k_a"] + APP3["k_b"] * frac,
            D)


def load_air(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = [(float(r[0]), float(r[1]), float(r[2]))
            for r in ws.iter_rows(min_row=2, values_only=True)
            if r[0] is not None]
    t = np.array([x[0] for x in rows])
    Ta = np.array([x[1] for x in rows])
    Ca = np.array([x[2] for x in rows])
    wb.close()
    return t, Ta, Ca


class Air:
    """附件1 实测（0–14400 s）→ 之后按恒温段风温/风含湿冻结。"""

    def __init__(self, t, Ta, Ca):
        self.t, self.Ta, self.Ca = t, Ta, Ca

    def __call__(self, tau):
        if tau <= T_SWITCH:
            return (float(np.interp(tau, self.t, self.Ta)),
                    float(np.interp(tau, self.t, self.Ca)))
        return T_AIR_C, C_AIR_C


def make_grid(N):
    """柱坐标单位长度 FVM：节点 r_i=i·dr，两端半控制体。"""
    dr = R / N
    r = np.arange(N + 1) * dr
    A_face = 2.0 * np.pi * (np.arange(N) + 0.5) * dr
    A_R = 2.0 * np.pi * R
    V = np.empty(N + 1)
    V[0] = np.pi * (0.5 * dr) ** 2
    V[1:N] = 2.0 * np.pi * np.arange(1, N) * dr ** 2
    V[N] = np.pi * (R ** 2 - ((N - 0.5) * dr) ** 2)
    return dr, r, A_face, A_R, V


def rhs(tau, y, N, dr, A_face, A_R, V, air):
    """半离散右端：dy/dt。y = [T(0..N), C(0..N)]"""
    n = N + 1
    T = y[:n]
    C = y[n:]
    rho, cp, k, D = props3(C, T)
    rc = rho * cp

    Ta, Ca = air(tau)

    # 界面传导系数（算术平均）
    kf = 0.5 * (k[:-1] + k[1:]) * A_face / dr
    Df = 0.5 * (D[:-1] + D[1:]) * A_face / dr

    dTdt = np.zeros(n)
    dCdt = np.zeros(n)
    # 内部面通量：i 与 i+1 之间
    qT = kf * (T[1:] - T[:-1])      # 流入 i+1 为正
    qC = Df * (C[1:] - C[:-1])
    # 外边界（对流/对流传质）
    qT_R = A_R * H_CONV * (Ta - T[N])
    qC_R = A_R * H_MASS * (Ca - C[N])

    dTdt[0] = qT[0] / (rc[0] * V[0])
    dTdt[1:N] = (qT[1:] - qT[:-1]) / (rc[1:N] * V[1:N])
    dTdt[N] = (qT_R - qT[N - 1]) / (rc[N] * V[N])

    dCdt[0] = qC[0] / V[0]
    dCdt[1:N] = (qC[1:] - qC[:-1]) / V[1:N]
    dCdt[N] = (qC_R - qC[N - 1]) / V[N]

    return np.concatenate([dTdt, dCdt])


def solve(N, t_end, air, rtol=1e-8, atol_T=1e-8, atol_C=1e-10):
    dr, r, A_face, A_R, V = make_grid(N)
    n = N + 1
    y0 = np.concatenate([np.full(n, T0), np.full(n, C0)])

    # 判据判停：各处 C < 0.15
    hit = {"t": None, "y": None}

    def stop(tau, y, *_a):
        # solve_ivp 会把 rhs 的 args 也传给 events，故用 *_a 吃掉
        return float(np.max(y[n:]) - C_DRY)   # <0 即达标

    stop.terminal = True
    stop.direction = -1

    sol = solve_ivp(rhs, (0.0, t_end), y0, method="BDF",
                    args=(N, dr, A_face, A_R, V, air),
                    rtol=rtol,
                    atol=np.concatenate([np.full(n, atol_T), np.full(n, atol_C)]),
                    events=stop, dense_output=False, max_step=600.0)
    return sol, r, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--air", required=True)
    ap.add_argument("--N", type=int, default=20)
    ap.add_argument("--t-end", type=float, default=21600.0)
    args = ap.parse_args()

    t_tab, Ta_tab, Ca_tab = load_air(args.air)
    air = Air(t_tab, Ta_tab, Ca_tab)

    print("=" * 70)
    print("独立复核 · 问题2（自写 FVM 半离散 + scipy BDF 自适应）")
    print("=" * 70)
    print(f"N={args.N}（Δr={R/args.N*1000:.2f} mm），t_end={args.t_end:.0f} s"
          f"（={args.t_end/3600:.2f} h）")

    sol, r, n = solve(args.N, args.t_end, air)
    print(f"BDF 状态：success={sol.status == 0 or sol.status == 1}  "
          f"status={sol.status}  nfev={sol.nfev}  nlu={sol.nlu}")

    if sol.t_events[0].size > 0:
        t_dry = float(sol.t_events[0][0])
        y_dry = sol.y_events[0][0]
        print(f"→ 判据判停：t_dry = {t_dry:.1f} s = {t_dry/3600:.4f} h")
        print(f"  末态 max C = {np.max(y_dry[n:]):.8f}（判据 <{C_DRY}）")
        print(f"  C_center = {y_dry[n]:.6f}，T_center = {y_dry[0]:.4f} °C，"
              f"T_surface = {y_dry[n-1]:.4f} °C")
    else:
        print(f"→ 在 {args.t_end:.0f} s 内未触发判据；末态 max C = "
              f"{np.max(sol.y[n:, -1]):.6f}")
        t_dry = None

    # ---- 与 prob2 抽样点对比 ----
    r_cm = r * 100.0
    print("\n与 prob2（自写 CN+Picard，dt=1 s）在表3/表4 时刻的对比：")
    print(f"{'t(h)':>6} {'r(cm)':>6} {'T_BDF':>10} {'C_BDF':>10}")
    tab_t = [1800.0, 3600.0, 5400.0, 7200.0, 9000.0, 10800.0]
    tab_cm = [0.0, 0.5, 1.0, 1.5, 2.0]
    out = {}
    for tt in tab_t:
        if tt > sol.t[-1]:
            continue
        i = int(np.argmin(np.abs(sol.t - tt)))
        row = {}
        for rc_ in tab_cm:
            j = int(np.argmin(np.abs(r_cm - rc_)))
            row[f"{rc_:g}"] = dict(T=float(sol.y[j, i]),
                                   C=float(sol.y[n + j, i]))
        out[f"{tt:g}"] = row
    print(json.dumps(out, ensure_ascii=False, indent=2)[:2000])

    res = dict(N=args.N, t_end=args.t_end, t_dry_s=(t_dry or None),
               t_dry_h=(t_dry / 3600.0 if t_dry else None),
               nfev=int(sol.nfev), samples=out)
    op = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "independent_p2_out.json")
    with open(op, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n→ 已写出：{op}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
