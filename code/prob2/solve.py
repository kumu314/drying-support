#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 题 · 问题 2 —— 整个烘干过程的温度场与水分浓度场（变物性，附录 3）

物理设定
--------
· 0 – 14400 s：烘房按**附件1 实测** T_air(t) / C_air(t) 变化（28 → 50.165 °C，0.01963 → 0.04986）
· t > 14400 s：附件1 结束 → 按附件1 末段渐近值冻结在恒温恒湿条件（50 °C / 0.05 kg/kg）
  （T_air = 50 °C、C_air = 0.05）。题面原句「预热平衡与恒温干燥阶段的参数有所不同」。
· 物性：**附录3**（ρ(C)、c_p(C)、k(C)、D(C,T)）→ 热/湿方程**耦合**，按块顺序 Picard 迭代
· 半径恒定 R = 2 cm（**H7**：尺寸变化只在问题 4 处理）

终止条件
--------
题面「烘干过程一般持续 2–3 天」。本文件按**烘干完成判据**（各处水分浓度 < 0.15 kg/kg）判停 ——
即 **P2 的模拟区间 = 烘干过程**，与 P3 反解出的 t_dry 是同一时刻（两问共用同一模型，
P3 只是把判据显式写出来）。若在 `--t-end-cap` 之前仍未达标则**按上限截断并报警**，
绝不悄悄改判据。

[WARN] 变物性下的守恒对账只用**方程级**口径（`max_consE_eq_rel`）
    `Σ ρcpV·ΔT  vs  ∫Q dt`，不用 `Δ(ρcpV·T)` 差分 —— 后者要把两个 ~1e5 的数相减才得到
    ~1 的单步变化，**灾难性抵消**会把 1e-16 浮点噪声放大成 1e-11 的假缺陷。

用法
----
    python prob2/solve.py --air "<附件1.xlsx 路径>"
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
T_AIR_C = 50.0         # Q2/Q3 恒温段烘房温度
C_AIR_C = 0.05         # Q2/Q3 恒温段烘房水分浓度
H_CONV = 25.0          # Q2–Q4 沿用 h = 25 W/(m^2·K)
H_MASS = 8.0e-7        # 传质系数（附录2 唯一给出的值）
C_DRY = 0.15           # 烘干完成判据阈值
SOLVER_VERSION = "p2-fvm-cn-varprops-v1"

TAB3_T = [1800.0, 3600.0, 5400.0, 7200.0, 9000.0, 10800.0]   # 0.5…3.0 h
TAB3_CM = [0.0, 0.5, 1.0, 1.5, 2.0]


def build_air(path):
    """构造 Q2 的环境驱动：附件1 实测 → 14400 s 后冻结。"""
    _hdr, t, Ta, Ca = fvm.load_air_table(path)
    drv = fvm.StagedDriver(fvm.AirDriver(t, Ta, Ca), T_SWITCH,
                           fvm.ConstDriver(T_AIR_C, C_AIR_C))
    return drv, t, Ta, Ca


# ---------------- 主求解缓存----------------
_SCALARS = ("t_final", "stopped_early", "steps", "picard_max",
            "max_consE_rel", "max_consM_rel", "max_consE_eq_rel",
            "stepE_rel", "stepM_rel", "E0", "E_end", "M0", "M_end")


def cache_save(path, res, N, dt, cap):
    np.savez(path, times=res["times"], T=res["T"], C=res["C"], r=res["r"],
             _N=N, _dt=dt, _cap=cap,
             **{k: res[k] for k in _SCALARS})


def cache_load(path, N, dt, cap):
    """读缓存；参数不一致则返回 None（绝不拿错参数的解当结果）。"""
    try:
        z = np.load(path)
    except Exception:
        return None
    if (int(z["_N"]) != N or float(z["_dt"]) != dt
            or abs(float(z["_cap"]) - cap) > 1e-9):
        print(f"  [WARN] 缓存参数不一致（N={int(z['_N'])} dt={float(z['_dt'])} "
              f"cap={float(z['_cap'])}），忽略并重算")
        return None
    res = {k: z[k] for k in ("times", "T", "C", "r")}
    for k in _SCALARS:
        res[k] = z[k].item() if z[k].ndim == 0 else z[k]
    return res


def _fmt_block(title, data, tab_times, tab_cm):
    """渲染 Markdown 表。[WARN] `data` 的键是**秒**（sample_table 用秒做 key），
    显示时刻才换算成小时——两处若不一致会整表空白。"""
    lines = [f"**{title}**", "", "| 时间(h) | " + " | ".join(f"{d:g}" for d in tab_cm) + " |",
             "|" + "---|" * (len(tab_cm) + 1)]
    for t in tab_times:
        key = f"{t:g}"
        if key not in data:
            continue
        row = data[key]
        lines.append(f"| {t/3600:g} | "
                     + " | ".join(f"{row[f'{d:g}']:.4f}" for d in tab_cm) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="A题 问题2：整个烘干过程（变物性）")
    ap.add_argument("--air", required=True, help="附件1.xlsx 路径")
    ap.add_argument("--out-dir", default=_HERE)
    ap.add_argument("--N", type=int, default=20)
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--t-end-cap", type=float, default=3 * 86400.0)
    ap.add_argument("--no-xlsx", action="store_true")
    ap.add_argument("--xlsx-span-h", type=float, default=3.0,
                    help="result2.xlsx 覆盖的小时数（默认 3.0；0 = 全程，仅本地留档）")
    ap.add_argument("--skip-verify", action="store_true")
    ap.add_argument("--cache", default=None,
                    help="主求解缓存 .npz；存在且 N/dt/cap 一致则直接复用")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    wall0 = time.time()

    air, t_tab, Ta_tab, Ca_tab = build_air(args.air)
    P = dict(R=0.02, L=0.25, h=H_CONV, hm=H_MASS, T0=28.0, C0=2.55,
             t_end=args.t_end_cap)
    pr3 = props_mod.props_app3

    print("=" * 74)
    print("A 题 · 问题2 —— 整个烘干过程（变物性：附录3）")
    print("=" * 74)
    print(f"工况  0–{T_SWITCH:.0f} s 用附件1 实测驱动；其后冻结在 "
          f"T_air={T_AIR_C} °C / C_air={C_AIR_C}（恒温段风温/风含湿、实测段终点）")
    print(f"      附件1 实读：T_air {Ta_tab[0]:.3f}→{Ta_tab[-1]:.3f} °C，"
          f"C_air {Ca_tab[0]:.5f}→{Ca_tab[-1]:.5f}")
    print(f"物性  附录3（ρ(C)、c_p(C)、k(C)、D(C,T) 双指数）→ 块顺序 Picard")
    print(f"数值  N={args.N}（Δr={P['R']/args.N*1000:.2f} mm），dt={args.dt} s，"
          f"输出步长 {args.dt} s")
    print(f"判据  max_r C(r,t) < {C_DRY} kg/kg（首达即停）")
    print("-" * 74)

    # ---------------- 主求解（带缓存）----------------
    res = None
    if args.cache:
        res = cache_load(args.cache, args.N, args.dt, args.t_end_cap)
        if res is not None:
            print(f"→ 复用主求解缓存：{args.cache}")
    if res is None:
        res = fvm.solve_case(
            args.N, args.dt, out_every=args.dt, air=air, props=pr3, P=P,
            record_all=True,
            stop_when=lambda tau, _T, C_: bool(np.max(C_) < C_DRY))
        if args.cache:
            cache_save(args.cache, res, args.N, args.dt, args.t_end_cap)
            print(f"→ 主求解缓存已写出：{args.cache}")

    t_dry_s = float(res["t_final"])
    t_dry_h = t_dry_s / 3600.0
    hit_cap = not res["stopped_early"]
    T_h, C_h, ts = res["T"], res["C"], res["times"]
    r_cm = res["r"] * 100.0

    print(f"→ 主求解：t_final = {t_dry_s:.0f} s = {t_dry_h:.4f} h "
          f"= {t_dry_h/24:.3f} 天   stopped_early={res['stopped_early']}")
    print(f"  Picard 最大迭代 {res['picard_max']}，"
          f"记录 {ts.size} 帧，用时 {time.time()-wall0:.1f} s")
    if hit_cap:
        print(f"  [WARN] 到 {args.t_end_cap:.0f} s 上限仍未满足判据 —— "
              f"须人工复核，不得直接沿用！")
    Cmax_end = float(np.max(C_h[-1]))
    print(f"  末态：max C = {Cmax_end:.6f}（判据 <{C_DRY}），"
          f"C_center = {C_h[-1][0]:.6f}，T_center = {T_h[-1][0]:.3f} °C，"
          f"T_surface = {T_h[-1][-1]:.3f} °C")

    # ---------------- 表3/表4（0.5–3.0 h）----------------
    tab3 = fvm.sample_table(ts, T_h, r_cm, TAB3_T, TAB3_CM)
    tab4 = fvm.sample_table(ts, C_h, r_cm, TAB3_T, TAB3_CM)
    print("\n" + "=" * 74)
    print(_fmt_block("表3  3 小时内药材的温度（°C）", tab3, TAB3_T, TAB3_CM))
    print()
    print(_fmt_block("表4  3 小时内药材的水分浓度（kg/kg）", tab4, TAB3_T, TAB3_CM))

    # ---------------- result2.xlsx ----------------
    # [WARN] 输出范围：只覆盖**前 3 小时**。
    # 依据：① 题面表3/表4 只要「3h 内」的数据 → 出题人对 Q2 的关注域就是前 3h；
    #       ② Q3 的 result3（每 60 s、全程）才是覆盖烘干全程的那一份；
    #       ③ 全程每 1 s = 203316 行 ≈ 25.3 MB，**单文件即击穿**《全国大学生数学建模
    #          竞赛论文格式规范》第十一条「支撑材料压缩包 ≤ 20MB」（xlsx 本身是 zip，
    #          换 openpyxl/xlsxwriter 都无解，实测同为 ~47.5 MB/20 万行随机数据）。
    # 全程解**照常计算**（P2.t_end_h 需要它），此处只在**写盘时截取**。
    # `--xlsx-span-h 0` 可恢复全程输出（本地留档用，不入库）。
    xlsx_path = os.path.join(args.out_dir, "result2.xlsx")
    sel = (ts <= args.xlsx_span_h * 3600.0) if args.xlsx_span_h > 0 else np.ones(ts.size, bool)
    ts_x, T_x, C_x = ts[sel], T_h[sel], C_h[sel]
    if not args.no_xlsx:
        tw = time.time()
        fvm.write_result_xlsx(xlsx_path, ts_x, res["r"], T_x, C_x,
                              out_cm=np.asarray([round(i * 0.1, 1) for i in range(21)]),
                              fast=True)
        print(f"\n→ result2.xlsx 已写出：{ts_x.size - 1} 行 × 2 表 × 21 列"
              f"（t = {ts_x[1]:.0f}…{ts_x[-1]:.0f} s，"
              f"覆盖前 {args.xlsx_span_h:g} h；全程解共 {ts.size - 1} 行未截断保留在内存/缓存），"
              f"{os.path.getsize(xlsx_path)/1024/1024:.2f} MB，用时 {time.time()-tw:.1f} s")

    # ---------------- 验证 ----------------
    ver = {}
    # 浓度非负（终检补充验证）：全时刻全节点 C >= 0
    # 论坛坑：显式格式大步长会震荡出负值；本解 CN+隐式理应无此问题，
    # 此处对全程历史做显式断言固化，防止未来改格式/步长后回退。
    C_min_all = float(np.min(res["C"]))
    ver["cneg"] = dict(C_min=round(C_min_all, 10), tol=0.0,
                       passed=bool(C_min_all >= 0.0))
    print(f"[浓度非负]  全场 min C = {C_min_all:.6e}  → "
          f"{'[OK]' if ver['cneg']['passed'] else '[FAIL]'}")
    ver["v1"] = dict(
        energy_eq_rel=float(res["max_consE_eq_rel"]),
        energy_diff_rel=float(res["max_consE_rel"]),
        moisture_rel=float(res["max_consM_rel"]),
        step_energy_eq_rel=float(res["stepE_rel"]),
        step_moisture_rel=float(res["stepM_rel"]),
        tol=1e-6,
        passed=bool(res["max_consE_eq_rel"] < 1e-6 and res["max_consM_rel"] < 1e-6))
    ver["v6"] = fvm.verify_physics(
        ts, r_cm, T_h, C_h, P,
        Ta_hist=np.where(ts <= T_SWITCH, np.interp(ts, t_tab, Ta_tab), T_AIR_C),
        Ca_hist=np.where(ts <= T_SWITCH, np.interp(ts, t_tab, Ca_tab), C_AIR_C))

    if not args.skip_verify:
        print("\n" + "-" * 74)
        print("[V1 守恒（全程累积，方程级口径）]")
        print(f"  energy_eq_rel = {ver['v1']['energy_eq_rel']:.4e}  "
              f"(差分口径参考 {ver['v1']['energy_diff_rel']:.4e})")
        print(f"  moisture_rel  = {ver['v1']['moisture_rel']:.4e}   "
              f"阈值 <{ver['v1']['tol']:g}  → {'[OK]' if ver['v1']['passed'] else '[FAIL]'}")

        print("\n[V6 物理合理性]")
        print("  " + json.dumps(ver["v6"], ensure_ascii=False))
        print(f"  → {'[OK]' if ver['v6']['passed'] else '[FAIL]'}")

        # V2 网格收敛（短时域：3 h；N=80 跑到 56 h 代价过高）
        v2 = fvm.verify_grid_convergence(air, pr3, P, Ns=(20, 40, 80),
                                         dt=args.dt, t_end=10800.0)
        ver["v2"] = dict(rows=[{k: v for k, v in r_.items() if k != "T" and k != "C"}
                               for r_ in v2["rows"]],
                         ref_N=v2["ref_N"],
                         T_20_vs_80=v2["T_fine_vs_coarse"],
                         C_20_vs_80=v2["C_fine_vs_coarse"],
                         passed=v2["passed"], t_end_s=10800.0)
        print(f"\n[V2 网格收敛 @3h]  N=20 vs N=80:  ΔT={v2['T_fine_vs_coarse']:.3e} °C，"
              f"ΔC={v2['C_fine_vs_coarse']:.3e}  → {'[OK]' if v2['passed'] else '[FAIL]'}")

        # V3 步长收敛（短时域：3 h）
        v3 = fvm.verify_dt_convergence(air, pr3, P, dts=(2.0, 1.0, 0.5),
                                       N=args.N, t_end=10800.0)
        ver["v3"] = dict(rows=[{k: v for k, v in r_.items() if k != "T" and k != "C"}
                               for r_ in v3["rows"]],
                         ref_dt=v3["ref_dt"],
                         T_2_vs_05=v3["T_coarse_vs_fine"],
                         C_2_vs_05=v3["C_coarse_vs_fine"],
                         passed=v3["passed"], t_end_s=10800.0)
        print(f"[V3 步长收敛 @3h]  dt=2 vs dt=0.5:  ΔT={v3['T_coarse_vs_fine']:.3e} °C，"
              f"ΔC={v3['C_coarse_vs_fine']:.3e}  → {'[OK]' if v3['passed'] else '[FAIL]'}")

        # V4 BDF 交叉（变物性、同一空间离散、完全不同的时间积分器）
        r4, T4, C4, tend4, ok4 = fvm.verify_scipy_bdf(N=args.N, t_end=3600.0,
                                                      air=air, P=P, props=pr3)
        i4 = int(np.argmin(np.abs(ts - tend4)))
        dT4 = float(np.max(np.abs(T4 - T_h[i4])))
        dC4 = float(np.max(np.abs(C4 - C_h[i4])))
        ver["v4"] = dict(T_max_abs_diff=dT4, C_max_abs_diff=dC4,
                         converged=bool(ok4), t_end_s=tend4,
                         passed=bool(ok4 and dT4 < 0.05 and dC4 < 0.05))
        print(f"[V4 BDF 交叉 @1h]  ΔT={dT4:.3e} °C，ΔC={dC4:.3e}（收敛={ok4}）"
              f"  → {'[OK]' if ver['v4']['passed'] else '[FAIL]'}")

        # V5 与问题1 常物性同题对比 —— 这不是"误差校验"，而是**量化物性变化本身的贡献**。
        # 附录2 → 附录3：k: 0.36 → 0.483，ρcp: 2.132e6 → 3.334e6 => 热扩散率
        # α = k/(ρcp): 1.689e-7 → 1.449e-7（-14%），1800 s 内温度场差 ~1.4 °C 属正常物理量级。
        # 故判据只用来兜住"离谱错误"（差一个量级），不设紧容差。
        air_full = fvm.AirDriver(t_tab, Ta_tab, Ca_tab)
        P1800 = dict(P, t_end=1800.0)
        sc = fvm.solve_case(args.N, 0.2, out_every=1.0, air=air_full,
                            props=props_mod.props_app2, P=P1800, record_all=True)
        sv = fvm.solve_case(args.N, 0.2, out_every=1.0, air=air_full,
                            props=pr3, P=P1800, record_all=True)
        dT5 = float(np.max(np.abs(sv["T"][-1] - sc["T"][-1])))
        dC5 = float(np.max(np.abs(sv["C"][-1] - sc["C"][-1])))
        alpha_c = 0.36 / (820.0 * 2600.0)
        pr_c0 = props_mod.props_app3(np.array([2.55]), np.array([301.15]))
        alpha_v = float(pr_c0["k"][0] / (pr_c0["rho"][0] * pr_c0["cp"][0]))
        ver["v5"] = dict(
            dT_1800s=dT5, dC_1800s=dC5,
            alpha_const=alpha_c, alpha_var=alpha_v,
            alpha_delta_pct=(alpha_v / alpha_c - 1.0) * 100.0,
            T_center_const=float(sc["T"][-1][0]), T_center_var=float(sv["T"][-1][0]),
            C_surface_const=float(sc["C"][-1][-1]), C_surface_var=float(sv["C"][-1][-1]),
            note="物性差异的物理量级（非误差）；判据仅兜住量级级错误",
            passed=bool(dT5 < 3.0 and dC5 < 0.5))
        print(f"[V5 vs 问题1 常物性 @1800 s]  ΔT={dT5:.3f} °C，ΔC={dC5:.4f}  "
              f"（α: {alpha_c:.3e}→{alpha_v:.3e} m^2/s，"
              f"{ver['v5']['alpha_delta_pct']:+.1f}%）"
              f"  → {'[OK]' if ver['v5']['passed'] else '[FAIL]'}")

    # ---------------- fragment ----------------
    i3h = int(np.argmin(np.abs(ts - 10800.0)))
    frag = dict(
        meta=dict(generated_at=datetime.now().isoformat(timespec="seconds"),
                  seed=0, solver_version=SOLVER_VERSION, reproducible=True,
                  air_source=os.path.basename(args.air),
                  props="附录3", N_radial=args.N, dt_s=args.dt),
        P2=dict(
            # ---- 结果键----
            t_end_h=round(t_dry_h, 4),
            T_center_3h=round(float(T_h[i3h][0]), 4),
            T_surface_3h=round(float(T_h[i3h][-1]), 4),
            C_surface_3h=round(float(C_h[i3h][-1]), 4),
            # ---- 诊断（非结果键，供复核与讨论章引用）----
            C_center_3h=round(float(C_h[i3h][0]), 4),
            t_end_s=round(t_dry_s, 4),
            stopped_early=bool(res["stopped_early"]),
            stop_rule=f"烘干完成判据：max_r C < {C_DRY} kg/kg",
            T_center_at_dry=round(float(T_h[-1][0]), 4),
            T_surface_at_dry=round(float(T_h[-1][-1]), 4),
            C_center_at_dry=round(float(C_h[-1][0]), 8),
            C_max_at_dry=round(float(np.max(C_h[-1])), 8),
            C_max_at_dry_note="判据为首达 <0.15 的时刻，故此处必然略小于 0.15（Q3 精算）",
            R_m=0.02, T_air_const_C=T_AIR_C, C_air_const=C_AIR_C,
            h_W_m2K=H_CONV, hm_m_s=H_MASS,
            xlsx_span_h=args.xlsx_span_h,
            xlsx_span_note=("result2.xlsx 只覆盖前 3 h（题面表3/表4 同域）；"
                            "全程解仍算到 t_dry，见 t_end_s"),
        ),
        tables=dict(table3_temp=tab3, table4_moisture=tab4,
                    note="t 单位 s（0.5 h=1800 s…3.0 h=10800 s）；距离单位 cm"),
        verification=ver,
    )
    frag_path = os.path.join(args.out_dir, "results_fragment.json")
    with open(frag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(frag, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n→ fragment 已写出：{frag_path}")

    allpass = all(v.get("passed", True) for v in ver.values()) and not hit_cap
    print("\n" + "=" * 74)
    print(f"{'[OK] 问题2 全部检查通过' if allpass else '[FAIL] 有问题项未通过，见上'}"
          f"   总用时 {time.time()-wall0:.1f} s")
    print("=" * 74)
    return 0 if allpass else 1


if __name__ == "__main__":
    sys.exit(main())
