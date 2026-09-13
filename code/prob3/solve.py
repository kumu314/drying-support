#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 题 · 问题 3 —— 确定药材烘干所需时间

物理设定（与问题2 **完全同一套模型**，同属一个模型族）
------------------------------------------------------------------
· 物性：附录 3（ρ(C)、c_p(C)、k(C)、D(C,T) 双指数，T 用 K）
· 环境：0–14400 s 用附件1 实测；其后冻结在 50 °C / 0.05 kg/kg
· 半径：恒定 R = 2 cm（H7：尺寸变化只在问题 4 处理）
· 判据：各处水分浓度 < 0.15 kg/kg → 反解烘干时长 t_dry

与问题 2 的唯一差别是**输出规格**（两问共用同一模型 => t_dry 必须是同一个数）：

| 输出 | 内容 | 规格 |
|------|------|------|
| 表 5 | 水分浓度 | 每隔 6 h × 距离每隔 0.5 cm；**末行 = 烘干结束时间** |
| `result3.xlsx` | 水分浓度（单表） | 每隔 **60 s** × 距离每隔 0.1 cm；**首行不含 t = 0** |

[WARN] 输出表模板的陷阱：`result3.xlsx` 的 A 列从 **60** 起，不是 0。`write_result_xlsx`
   内部已跳过 `t ≤ 0`，此处只需保证 `out_every = 60`。
[WARN] 单表写盘的坑：容器名必须是 **`Sheet1`**（模板实测），且必须传 `hists=(C_h,)`，
   否则 `zip(sheets, (T_hist, C_hist))` 会静默把温度表写进这个 sheet。
   两者都在下方调用处写明（2026-09-11 复审修正，见 PR 评论）。

用法
----
    python prob3/solve.py --air "<附件1.xlsx 路径>"
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
SOLVER_VERSION = "p3-fvm-cn-varprops-v1"

TAB5_CM = [0.0, 0.5, 1.0, 1.5, 2.0]     # 表5 距离列（cm）
OUT_CM = np.array([round(i * 0.1, 1) for i in range(21)])   # 0…2 cm，21 列


def build_air(path):
    """与 prob2 完全一致：附件1 实测 → 14400 s 后冻结。"""
    _hdr, t, Ta, Ca = fvm.load_air_table(path)
    drv = fvm.StagedDriver(fvm.AirDriver(t, Ta, Ca), T_SWITCH,
                           fvm.ConstDriver(T_AIR_C, C_AIR_C))
    return drv, t, Ta, Ca


def run_solve(N, dt, air, props, P, cap):
    """跑一次到判据满足，返回 (res, t_dry_s)。"""
    res = fvm.solve_case(
        N, dt, out_every=60.0, air=air, props=props, P=P,
        record_all=True,
        stop_when=lambda tau, _T, C_: bool(np.max(C_) < C_DRY))
    return res, float(res["t_final"])


def main():
    ap = argparse.ArgumentParser(description="A题 问题3：烘干所需时间（反解）")
    ap.add_argument("--air", required=True, help="附件1.xlsx 路径")
    ap.add_argument("--out-dir", default=_HERE)
    ap.add_argument("--N", type=int, default=20)
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--t-end-cap", type=float, default=3 * 86400.0)
    ap.add_argument("--dt2", type=float, default=2.0,
                    help="双 dt 复核的第二时间步（完成判据：两个 dt 的 t_dry 差 <1%）")
    ap.add_argument("--no-xlsx", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    wall0 = time.time()

    air, t_tab, Ta_tab, Ca_tab = build_air(args.air)
    P = dict(R=0.02, L=0.25, h=H_CONV, hm=H_MASS, T0=28.0, C0=2.55,
             t_end=args.t_end_cap)
    pr3 = props_mod.props_app3

    print("=" * 74)
    print("A 题 · 问题3 —— 烘干所需时间（判据：各处 C < 0.15 kg/kg）")
    print("=" * 74)
    print(f"模型  与问题2 同一套（附录3 变物性 + 恒温段风温/风含湿、实测段终点），R = 2 cm 恒定")
    print(f"数值  N={args.N}（Δr={P['R']/args.N*1000:.2f} mm），dt={args.dt} s，"
          f"输出步长 60 s")
    print("-" * 74)

    # ---------------- 主求解 ----------------
    res, t_dry_s = run_solve(args.N, args.dt, air, pr3, P, args.t_end_cap)
    t_dry_h = t_dry_s / 3600.0
    hit_cap = not res["stopped_early"]
    C_h, ts = res["C"], res["times"]
    r_cm = res["r"] * 100.0

    print(f"→ t_dry = {t_dry_s:.0f} s = {t_dry_h:.4f} h = {t_dry_h/24:.3f} 天   "
          f"stopped_early={res['stopped_early']}")
    print(f"  Picard 最大迭代 {res['picard_max']}，记录 {ts.size} 帧，"
          f"用时 {time.time()-wall0:.1f} s")
    if hit_cap:
        print(f"  [WARN] 到 {args.t_end_cap:.0f} s 上限仍未满足判据 —— 不得直接沿用！")

    Cmax_end = float(np.max(C_h[-1]))
    C_center_end = float(C_h[-1][0])
    print(f"  判据回验：末态 max C = {Cmax_end:.8f}（判据 <{C_DRY}）→ "
          f"{'[OK] 满足' if Cmax_end < C_DRY else '[FAIL] 不满足'}")
    print(f"          末态 C_center = {C_center_end:.8f}（中心最慢，通常即瓶颈）")

    # ---------------- 表 5（每隔 6 h + 末行烘干结束时间）----------------
    n6 = int(t_dry_s // 21600.0)
    tab5_t = [21600.0 * i for i in range(1, n6 + 1)] + [t_dry_s]
    tab5 = fvm.sample_table(ts, C_h, r_cm, tab5_t, TAB5_CM)
    print("\n" + "=" * 74)

    def _fmt_tab5():
        lines = ["**表5  药材烘干过程的水分浓度（kg/kg）**", "",
                 "| 时间(h) | " + " | ".join(f"{d:g}" for d in TAB5_CM) + " |",
                 "|" + "---|" * (len(TAB5_CM) + 1)]
        for t in tab5_t:
            key = f"{t:g}"
            if key not in tab5:
                continue
            row = tab5[key]
            label = (f"{t/3600:.4f}（烘干结束）" if abs(t - t_dry_s) < 1e-9
                     else f"{t/3600:g}")
            lines.append(f"| {label} | "
                         + " | ".join(f"{row[f'{d:g}']:.4f}" for d in TAB5_CM) + " |")
        return "\n".join(lines)
    print(_fmt_tab5())

    # ---------------- result3.xlsx ----------------
    xlsx_path = os.path.join(args.out_dir, "result3.xlsx")
    if not args.no_xlsx:
        tw = time.time()
        # ① 容器名：附件3 模板实测是 **`Sheet1`**，不是「水分浓度」
        #    （openpyxl.load_workbook('附件3/result3.xlsx').sheetnames → ['Sheet1']）
        # ② 用 `hists=(C_h,)` 显式声明"这一张表写水分"。不加它，函数内部
        #    `zip(sheets, (T_hist, C_hist))` 会把唯一的 sheet 配到 **T_hist** 上，
        #    静默写出温度值（文件能打开、数字也像样，但物理量是错的）。
        fvm.write_result_xlsx(xlsx_path, ts, res["r"], C_h, C_h,
                              out_cm=OUT_CM, sheets=("Sheet1",), hists=(C_h,))
        print(f"\n→ result3.xlsx 已写出：{ts.size - 1} 行 × 21 列，"
              f"{os.path.getsize(xlsx_path)/1024:.0f} KB，用时 {time.time()-tw:.1f} s")

    # ---------------- 验证 ----------------
    ver = {}
    ver["v1_conservation"] = dict(
        energy_eq_rel=float(res["max_consE_eq_rel"]),
        moisture_rel=float(res["max_consM_rel"]),
        tol=1e-6,
        passed=bool(res["max_consE_eq_rel"] < 1e-6 and res["max_consM_rel"] < 1e-6))
    print(f"\n[V1 守恒]  energy_eq_rel={ver['v1_conservation']['energy_eq_rel']:.4e}  "
          f"moisture_rel={ver['v1_conservation']['moisture_rel']:.4e}  "
          f"→ {'[OK]' if ver['v1_conservation']['passed'] else '[FAIL]'}")

    # 判据回验
    ver["j1_check"] = dict(C_max_at_dry=round(Cmax_end, 8),
                           C_center_at_dry=round(C_center_end, 8),
                           threshold=C_DRY,
                           passed=bool(Cmax_end < C_DRY))
    print(f"[判据回验]  max C = {Cmax_end:.8f} < {C_DRY}  → "
          f"{'[OK]' if ver['j1_check']['passed'] else '[FAIL]'}")

    # 浓度非负（终检补充验证）：全时刻全节点 C >= 0
    # 论坛坑：显式格式大步长会震荡出负值；本解 CN+隐式理应无此问题，
    # 此处对全程历史做显式断言固化，防止未来改格式/步长后回退。
    C_min_all = float(np.min(res["C"]))
    ver["cneg"] = dict(C_min=round(C_min_all, 10), tol=0.0,
                       passed=bool(C_min_all >= 0.0))
    print(f"[浓度非负]  全场 min C = {C_min_all:.6e}  → "
          f"{'[OK]' if ver['cneg']['passed'] else '[FAIL]'}")

    # 双 dt 复核（完成判据：差 <1%）
    _, t_dry2 = run_solve(args.N, args.dt2, air, pr3, P, args.t_end_cap)
    diff_pct = abs(t_dry2 - t_dry_s) / t_dry_s * 100.0
    ver["dt_dual"] = dict(dt1=args.dt, dt2=args.dt2,
                          t_dry1_s=round(t_dry_s, 1), t_dry2_s=round(t_dry2, 1),
                          t_dry1_h=round(t_dry_s / 3600.0, 4),
                          t_dry2_h=round(t_dry2 / 3600.0, 4),
                          diff_pct=round(diff_pct, 4),
                          passed=bool(diff_pct < 1.0))
    print(f"[双 dt 复核]  dt={args.dt} → {t_dry_s/3600:.4f} h；"
          f"dt={args.dt2} → {t_dry2/3600:.4f} h；"
          f"差 {diff_pct:.4f}%  → {'[OK]' if ver['dt_dual']['passed'] else '[FAIL]'}")

    # 与问题2 的一致性（两问共用同一模型 => t_dry 必须同一个数）
    p2_frag = os.path.join(os.path.dirname(_HERE), "prob2", "results_fragment.json")
    cross = None
    if os.path.exists(p2_frag):
        try:
            with open(p2_frag, encoding="utf-8") as f:
                p2 = json.load(f)["P2"]
            if p2.get("t_end_h") is not None:
                d = abs(p2["t_end_h"] - t_dry_h)
                cross = dict(prob2_t_dry_h=p2["t_end_h"], prob3_t_dry_h=round(t_dry_h, 4),
                             abs_diff_h=round(d, 6), passed=bool(d < 1e-3))
                print(f"[与问题2 交叉]  prob2 t_end={p2['t_end_h']} h vs "
                      f"prob3 t_dry={t_dry_h:.4f} h；差 {d:.6f} h  → "
                      f"{'[OK] 一致' if cross['passed'] else '[WARN] 不一致，须人工复核'}")
        except Exception as e:
            print(f"[与问题2 交叉]  读取失败：{e}")

    # ---------------- fragment ----------------
    frag = dict(
        meta=dict(generated_at=datetime.now().isoformat(timespec="seconds"),
                  seed=0, solver_version=SOLVER_VERSION, reproducible=True,
                  air_source=os.path.basename(args.air), props="附录3",
                  N_radial=args.N, dt_s=args.dt,
                  note="与问题2 同一物理模型，仅判据与输出规格不同"),
        P3=dict(
            # ---- 结果键----
            t_dry_h=round(t_dry_h, 4),
            C_max_at_dry=round(Cmax_end, 8),
            C_center_at_dry=round(C_center_end, 8),
            # ---- 诊断（非结果键）----
            t_dry_s=round(t_dry_s, 1),
            t_dry_day=round(t_dry_h / 24.0, 4),
            stopped_early=bool(res["stopped_early"]),
            stop_rule=f"烘干完成判据：max_r C < {C_DRY} kg/kg",
            R_m=0.02, T_air_const_C=T_AIR_C, C_air_const=C_AIR_C,
            h_W_m2K=H_CONV, hm_m_s=H_MASS,
        ),
        tables=dict(table5_moisture=tab5,
                    note="t 单位 s（6 h = 21600 s）；末行为烘干结束时刻；距离单位 cm"),
        verification=ver,
        cross_check_prob2=cross,
    )
    frag_path = os.path.join(args.out_dir, "results_fragment.json")
    with open(frag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(frag, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n→ fragment 已写出：{frag_path}")

    allpass = (all(v.get("passed", True) for v in ver.values())
               and not hit_cap
               and (cross is None or cross["passed"]))
    print("\n" + "=" * 74)
    print(f"{'[OK] 问题3 全部检查通过' if allpass else '[FAIL] 有问题项未通过，见上'}"
          f"   总用时 {time.time()-wall0:.1f} s")
    print("=" * 74)
    return 0 if allpass else 1


if __name__ == "__main__":
    sys.exit(main())
