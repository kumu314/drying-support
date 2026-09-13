#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parity_check.py —— **等价性证明**

用 `common/` 新内核 + 附录2 常物性，重跑问题1 场景，逐项对比重构前基线
（来源：`prob1/solve.py` 运行时生成的 `verify_report.md` 与
`prob1/results_fragment.json`）。

任何一项超出容差即 exit 1 —— 这道闸是"重构没改行为"的唯一证据，
**不许为了让它变绿而放宽容差**（放宽等于把证据改成摆设）。

用法
----
python common/parity_check.py --air "<附件1.xlsx 路径>"

附件不入库（防泄题），必须外部传路径。
"""

from __future__ import annotations

import argparse
import json
import math
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


import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import fvm, props as props_mod  # noqa: E402

# --------------------------------------------------------------------------
# 基线：重构前 solve.py 的实测值（prob1/verify_report.md + results_fragment.json，
#       前者由 prob1/solve.py 运行时生成）
# --------------------------------------------------------------------------
BASE = dict(
    v1_energy_rel=4.7514728163595615e-12,
    v1_moisture_rel=9.8965547544333e-12,
    v4_T_max_abs_diff=6.659831797151128e-09,
    v4_C_max_abs_diff=5.303715244764362e-10,
    v5_max_abs_diff=1.485974268646828e-04,
    E_absorbed=19208.90014580436,
    Bi_heat=1.3888888888888888,
)

# 末态状态量的**全精度**基线（prob1/results_fragment.json → verification.v2.rows[0]，
# 即 N=20 的生产配置）。[WARN] 不要拿 results_fragment.json 顶层 P1 的 33.5752 比 ——
# 那是给论文用的 **4 位小数舍入值**，舍入误差 ±5e-5 比我们要验的差异大 4 个量级。
BASE_N20_T = [33.575196323081386, 34.36402509517685, 36.78528770348607]
BASE_N20_C = [2.54998252402923, 2.537606530582786, 1.5120245111648885]

TOL_ABS_STATE = 1e-9    # 末态温/浓度：常物性重构应**逐位一致**，容差只挡浮点末位
TOL_ABS_ENERGY = 1e-6   # 吸热量 [J/m]

# [WARN] D0/Da 从 props.APP2 取（单一真源）——prob1 原版把这两个键塞在 P 里是因为它
# 自带了物性；此后物性归 common.props，P 只留"工况参数"，避免两处硬编码漂移。
P1 = dict(
    R=0.02, L=0.25, rho=820.0, cp=2600.0, k=0.36,
    h=25.0, hm=8.0e-7, T0=28.0, C0=2.55, t_end=1800.0,
    D0=props_mod.APP2["D0"], Da=props_mod.APP2["Da"],
)


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-300)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--air", required=True, help="附件1.xlsx 路径")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    if not os.path.exists(args.air):
        print(f"[FAIL] 找不到附件1：{args.air}")
        sys.exit(2)

    _hdr, t, Ta, Ca = fvm.load_air_table(args.air)
    air = fvm.AirDriver(t, Ta, Ca)
    pr = props_mod.props_app2

    fails, notes = [], []

    # ---------------- 主算例（生产配置 N=20, dt=0.2）----------------
    res = fvm.solve_case(20, 0.2, out_every=1.0, air=air, props=pr, P=P1,
                         record_all=True)
    T_end, C_end = res["T"][-1], res["C"][-1]

    checks = [
        ("T(r=0)", T_end[0], BASE_N20_T[0], TOL_ABS_STATE),
        ("T(r=1.0cm)", T_end[10], BASE_N20_T[1], TOL_ABS_STATE),
        ("T(r=2.0cm)", T_end[20], BASE_N20_T[2], TOL_ABS_STATE),
        ("C(r=0)", C_end[0], BASE_N20_C[0], TOL_ABS_STATE),
        ("C(r=1.0cm)", C_end[10], BASE_N20_C[1], TOL_ABS_STATE),
        ("C(r=2.0cm)", C_end[20], BASE_N20_C[2], TOL_ABS_STATE),
        ("E_absorbed", res["E_end"] - res["E0"], BASE["E_absorbed"], TOL_ABS_ENERGY),
    ]

    print("=" * 66)
    print("公共内核等价性自检（common.fvm + props_app2  vs  prob1 基线）")
    print("=" * 66)
    print(f"\n[主算例 N=20 dt=0.2 t_end=1800s]  Picard 最大迭代 {res['picard_max']}")
    for name, got, want, tol in checks:
        ok = abs(got - want) <= tol
        print(f"  {'[OK]' if ok else '[FAIL]'} {name:18s} got={got:.10g}  want={want:.10g}  |Δ|={abs(got-want):.3g}")
        if not ok:
            fails.append(name)

    # ---------------- V1 守恒（累积对账）----------------
    e_rel, m_rel, e_eq_rel = fvm.verify_conservation(N=20, dt=0.05, air=air, props=pr, P=P1)
    print(f"\n[V1 守恒 dt=0.05]")
    # [WARN] 判据必须用**方程级** e_eq_rel 对齐基线，不能用 (ρcpV·T) 差分口径：
    #    后者要把两个 ~1e5 量级的数相减才得到 ~0.8 的单步能量变化，**灾难性抵消**
    #    把 1e-16 的浮点噪声放大成 ~1e-11，纯属记账伪影。
    #    （问题1 的 4.75e-12 正是方程级口径的值。）
    for name, got, want in (("energy_eq_rel", e_eq_rel, BASE["v1_energy_rel"]),
                            ("moisture_rel", m_rel, BASE["v1_moisture_rel"])):
        ok = got < 1e-9 and 1e-3 < (got / want) < 1e3
        print(f"  {'[OK]' if ok else '[FAIL]'} {name:18s} got={got:.4e}  base={want:.4e}  阈值<1e-9")
        if not ok:
            fails.append(f"v1_{name}")
    # 差分口径仅作参考展示（同为 <1e-9，量级一致），不参与判 FAIL
    print(f"  ℹ  {'energy_rel(参考)':16s} got={e_rel:.4e}  "
          f"（差分口径，含浮点抵消伪影，仅供对照）")

    # ---------------- V4 BDF 交叉 ----------------
    r, T_bdf, C_bdf, tend, ok_bdf = fvm.verify_scipy_bdf(N=20, air=air, P=P1, props=pr)
    dT = float(np.max(np.abs(T_bdf - T_end)))
    dC = float(np.max(np.abs(C_bdf - C_end)))
    print(f"\n[V4 scipy BDF 交叉]  success={ok_bdf} t_end={tend:.1f}")
    for name, got, want in (("T_max_abs_diff", dT, BASE["v4_T_max_abs_diff"]),
                            ("C_max_abs_diff", dC, BASE["v4_C_max_abs_diff"])):
        ok = got < 1e-3 and 1e-3 < (got / want) < 1e3
        print(f"  {'[OK]' if ok else '[FAIL]'} {name:18s} got={got:.4e}  base={want:.4e}  阈值<1e-3")
        if not ok:
            fails.append(f"v4_{name}")

    # ---------------- V5 解析级数解（常系数退化）----------------
    # [WARN] 必须照 prob1 原版做：**N=80 + 常数 D + 常数 C_air + BDF vs 级数解**。
    # 拿主算例（N=20、C_air 随时间变、CN）去比级数解是错的——级数解的前提就是常系数，
    # 比出来的差异里混了"变 C_air"和"CN 时间离散"两种误差，不是实现误差。
    from scipy.integrate import solve_ivp

    D_const = float(P1["D0"] * math.exp(-P1["Da"] / P1["C0"]))
    Ca_const = float(Ca[0])
    Ca_drv = fvm.AirDriver(np.array([0.0, 1e9]),
                           np.array([P1["T0"], P1["T0"]]),
                           np.array([Ca_const, Ca_const]))
    dr5, r5, Af5, AR5, V5_ = fvm.make_grid(80, P1["R"])

    def f5(tau, y):
        return fvm.rhs_semi_discrete(y[:81], y[81:], tau, Ca_drv, 80, dr5, r5,
                                     Af5, AR5, V5_, P1, pr, const_D=D_const)

    y0c = np.concatenate([np.full(81, P1["T0"]), np.full(81, P1["C0"])])
    sol5 = solve_ivp(f5, (0.0, P1["t_end"]), y0c, method="BDF",
                     rtol=1e-11, atol=1e-13, max_step=10.0)
    C_num5 = sol5.y[81:, -1]
    C_ana5, _lam = fvm.analytic_cylinder_series(
        r5, P1["t_end"], D_const, P1["hm"], P1["C0"], Ca_const, P1["R"], n_terms=120)
    v5 = float(np.max(np.abs(C_num5 - C_ana5)))
    print(f"\n[V5 解析级数解]  N=80, D={D_const:.4e} m^2/s(常数), C_air={Ca_const:.5f}, "
          f"Bi_m={P1['hm'] * P1['R'] / D_const:.4f}, BDF success={sol5.success}")
    ok = (v5 < 5e-4) and (1e-3 < (v5 / BASE["v5_max_abs_diff"]) < 1e3)
    print(f"  {'[OK]' if ok else '[FAIL]'} max_abs_diff      got={v5:.4e}  base={BASE['v5_max_abs_diff']:.4e}  阈值<5e-4")
    if not ok:
        fails.append("v5_max_abs_diff")

    # ---------------- V7 stop_when 判停一致性----------------
    # 断言：用 stop_when 在 t=900 s 提前停，其末态必须与"跑满 1800 s 再取 t=900 s
    # 那一帧"**逐位一致**。若不一致 → 判停逻辑改坏了推进路径。
    res_full_s = fvm.solve_case(20, 0.2, out_every=0.2, air=air, props=pr, P=P1,
                                record_all=True)
    j900 = int(round(900.0 / 0.2))
    res_stop = fvm.solve_case(20, 0.2, out_every=0.2, air=air, props=pr, P=P1,
                              record_all=True,
                              stop_when=lambda tau, _T, _C: tau >= 900.0)
    dT7 = float(np.max(np.abs(res_stop["T"][-1] - res_full_s["T"][j900])))
    dC7 = float(np.max(np.abs(res_stop["C"][-1] - res_full_s["C"][j900])))
    print(f"\n[V7 stop_when 判停]  t_final={res_stop['t_final']:.2f}s "
          f"(停止={res_stop['stopped_early']})  末帧 t={res_stop['times'][-1]:.2f}s")
    v7 = dict(dT=dT7, dC=dC7,
              t_ok=bool(abs(res_stop["t_final"] - 900.0) < 1e-9),
              stopped=bool(res_stop["stopped_early"]),
              frame_ok=bool(abs(res_stop["times"][-1] - 900.0) < 1e-9))
    for name, got, tol in (("ΔT(判停vs跑满)", dT7, 1e-12),
                           ("ΔC(判停vs跑满)", dC7, 1e-12)):
        ok7 = got <= tol
        print(f"  {'[OK]' if ok7 else '[FAIL]'} {name:18s} got={got:.3g}  阈值<={tol:g}")
        if not ok7:
            fails.append(f"v7_{name}")
    ok7b = v7["t_ok"] and v7["stopped"] and v7["frame_ok"]
    print(f"  {'[OK]' if ok7b else '[FAIL]'} 停止时刻/末帧标记  "
          f"t_final={res_stop['t_final']:.2f}  stopped={res_stop['stopped_early']}  "
          f"末帧t={res_stop['times'][-1]:.2f}")
    if not ok7b:
        fails.append("v7_meta")

    # ---------------- V8 网格收敛----------------
    # 历史教训：verify_grid_convergence 里不同 N 的节点数不同（N=20 → 21 点、
    # N=80 → 81 点），写 `s["T"][-1] - ref["T"][-1]` 会广播崩溃（(21,) vs (81,)）。
    # 一致性比对最初只覆盖 V1/V4/V5/V6 → 这个 bug 一直藏到 prob2 才炸。补上守卫。
    v8 = fvm.verify_grid_convergence(air, pr, P1, Ns=(20, 40, 80), dt=0.2,
                                     t_end=1800.0)
    print(f"\n[V8 网格收敛 @1800 s]  N=20 vs N=80:  "
          f"ΔT={v8['T_fine_vs_coarse']:.3e} °C，ΔC={v8['C_fine_vs_coarse']:.3e}"
          f"  → {'[OK]' if v8['passed'] else '[FAIL]'}")
    if not v8["passed"]:
        fails.append("v8_grid_convergence")

    # ---------------- 常数一致性 ----------------
    bi = P1["h"] * P1["R"] / P1["k"]
    ok = abs(bi - BASE["Bi_heat"]) < 1e-9
    print(f"\n[常数自检]  Bi_heat = {bi:.6f}  (base {BASE['Bi_heat']:.6f})  {'[OK]' if ok else '[FAIL]'}")
    if not ok:
        fails.append("Bi_heat")

    # ---------------- V6 物理合理性（照 prob1 原版判据，便于逐项对齐）----------------
    # 注：common.fvm.verify_physics 是**加强版**（查全时间历史 + 更严的 C 下界），
    # 留给 prob2/3/4 用；这里为了"等价性证明"必须复刻原判据，否则比的是两套标准。
    Tend, Cend = res["T"][-1], res["C"][-1]
    Ta_max = float(np.max(Ta))
    Ca_min = float(np.min(Ca))
    v6 = dict(
        center_T_le_surface=bool(Tend[0] <= Tend[20] + 1e-9),
        center_C_ge_surface=bool(Cend[0] >= Cend[20] - 1e-9),
        T_center_monotone=bool(np.all(np.diff(res["T"][:, 0]) >= -1e-12)),
        C_center_monotone=bool(np.all(np.diff(res["C"][:, 0]) <= 1e-12)),
        T_bounds=bool(Tend.min() >= P1["T0"] - 1e-9 and Tend.max() <= Ta_max + 1e-9),
        C_bounds=bool(Cend.max() <= P1["C0"] + 1e-9 and Cend.min() >= Ca_min - 1e-9),
    )
    v6["passed"] = bool(all(v6.values()))
    print(f"\n[V6 物理合理性] {json.dumps(v6, ensure_ascii=False)}")
    if not v6["passed"]:
        fails.append("V6")

    summary = dict(
        passed=not fails, fails=fails,
        T_center_1800s=float(T_end[0]), T_surface_1800s=float(T_end[-1]),
        C_center_1800s=float(C_end[0]), C_surface_1800s=float(C_end[-1]),
        E_absorbed=float(res["E_end"] - res["E0"]),
        v1_energy_rel=e_rel, v1_moisture_rel=m_rel, v1_energy_eq_rel=e_eq_rel,
        v4_T_max_abs_diff=dT, v4_C_max_abs_diff=dC, v5_max_abs_diff=v5,
        picard_max=int(res["picard_max"]),
        v7_dT=dT7, v7_dC=dC7, v7_stopped_early=bool(res_stop["stopped_early"]),
    )
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print("\n" + "=" * 66)
    if fails:
        print(f"[FAIL] 等价性自检 FAIL（{len(fails)} 项）：{', '.join(fails)}")
        print("   → 重构改变了行为，必须定位后再继续。**不要放宽容差**。")
        sys.exit(1)
    print("[OK] 等价性自检 PASS —— common/ 与 prob1 原实现行为一致。")
    print("=" * 66)


if __name__ == "__main__":
    main()
