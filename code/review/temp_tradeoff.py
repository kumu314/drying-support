# -*- coding: utf-8 -*-
"""
恒温口径 T_air ∈ {45, 50, 55, 60} °C 四点权衡（论文摘要/§6 的
「温度—品质—时长」数据支点）。

口径与 probQ 控温扫描完全同款（ConstDriver 恒温、C_air=0.05、判据 max C<0.15、
N=20、dt=1 s），Qbar 用 probQ 的 integrate_Q/qbar_curve 同一实现：
review/temp_tradeoff.json
figs/fig_pareto.png —— 共享图区

用法：
python temp_tradeoff.py --air 附件1.xlsx路径
"""
import argparse
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

import time
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))          # 上级目录（common 包）

from common import fvm                              # noqa: E402
from common import props as props_mod               # noqa: E402
from prob3.solve import C_DRY                       # noqa: E402
from probQ.solve import (EA_J_MOL, K_REF_PER_H,     # noqa: E402
                         integrate_Q, qbar_curve)

FIGS = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "figs")
TEMPS = [45.0, 50.0, 55.0, 60.0]


def main():
    ap = argparse.ArgumentParser(description="恒温四点权衡")
    ap.add_argument("--air", required=True)
    ap.add_argument("--N", type=int, default=20)
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--t-end-cap", type=float, default=5 * 86400.0)
    args = ap.parse_args()

    P0 = dict(R=0.02, L=0.25, h=25.0, hm=8.0e-7, T0=28.0, C0=2.55,
              t_end=args.t_end_cap)
    V = fvm.make_grid(args.N, P0["R"])[4]      # 控制体体积数组（与求解网格一致）

    rows = []
    wall0 = time.time()
    for Tc in TEMPS:
        tw = time.time()
        a2 = fvm.ConstDriver(Tc, 0.05)
        r2 = fvm.solve_case(args.N, args.dt, out_every=args.dt,
                            air=a2, props=props_mod.props_app3, P=P0,
                            record_all=True,
                            stop_when=lambda tau, _T, C_: bool(np.max(C_) < C_DRY))
        td = float(r2["t_final"])
        t2 = np.asarray(r2["times"], float)
        Qs = integrate_Q(t2, np.asarray(r2["T"], float), EA_J_MOL, K_REF_PER_H)
        qb = qbar_curve(Qs, V)
        j = int(np.argmin(np.abs(t2 - td)))
        rows.append(dict(
            T_air_C=Tc, t_dry_s=round(td, 1), t_dry_h=round(td / 3600.0, 4),
            qbar_at_dry=float(qb[j]),
            qbar_at_30h=float(qb[int(np.argmin(np.abs(t2 - 30 * 3600.0)))]),
            energy_J=float(r2["cumE_eq_expect"]),
            stopped_early=bool(r2["stopped_early"]),
            solve_s=round(time.time() - tw, 1)))
        print(f"[{Tc:g} °C] t_dry={td/3600.0:.4f} h  Qbar(t_dry)={qb[j]:.4f}"
              f"（{rows[-1]['solve_s']} s）", flush=True)

    # ---- 图：恒温四点权衡（共享区） ----
    td = [r["t_dry_h"] for r in rows]
    qd = [max(r["qbar_at_dry"], 1e-6) for r in rows]
    colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(rows)))
    fig, ax = plt.subplots(figsize=(6.4, 3.8), dpi=110)
    ax.semilogy(td, qd, "-o", color="#5c8a4e", lw=1.4, ms=5)
    for x, y, tc, c in zip(td, qd, TEMPS, colors):
        ax.scatter([x], [y], s=100, color=[c], zorder=3,
                   edgecolor="white", lw=0.8)
        ax.annotate(f"{tc:g} °C", (x, y), textcoords="offset points",
                    xytext=(8, 5), fontsize=9, color="0.25")
    i50 = TEMPS.index(50.0)
    ax.scatter([td[i50]], [qd[i50]], s=170, facecolor="none",
               edgecolor="#d0603a", lw=1.6, zorder=4)
    ax.set_xlabel("烘干时间 t_dry (h)", fontsize=9.5)
    ax.set_ylabel(r"判定时刻平均保留率 $\bar{Q}(t_{dry})$", fontsize=9.5)
    ax.set_title("恒温工艺扫描：时长—品质权衡（红圈 = 题设 50 °C，纵轴对数）",
                 fontsize=10.5)
    ax.grid(lw=0.4, alpha=0.5, which="both")
    fig.tight_layout()
    os.makedirs(FIGS, exist_ok=True)
    fig_path = os.path.join(FIGS, "fig_pareto.png")
    fig.savefig(fig_path)
    plt.close(fig)

    # ---- 结论句 ----
    r45, r50, r60 = rows[0], rows[1], rows[3]
    concl = (
        "恒温口径四点（45/50/55/60 °C）：烘干时间 {t45:.1f} → {t60:.1f} h，"
        "判定时刻平均保留率 {q45:.3f} → {q60:.4f}。相对题设 50 °C：降温 5 °C "
        "多用 {d45:.1f} h（+{p45:.0f}%）换取保留率 ×{g45:.2f}；提温 10 °C 缩短 "
        "{d60:.1f} h（−{p60:.0f}%）但保留率相对下降 {l60:.0f}%。"
        "「低温长烘换品质、高温快烘换时间」在该四点上定量成立，且品质对温度的"
        "弹性远大于时长对温度的弹性。").format(
            t45=r45["t_dry_h"], t60=r60["t_dry_h"],
            q45=r45["qbar_at_dry"], q60=r60["qbar_at_dry"],
            d45=r45["t_dry_h"] - r50["t_dry_h"],
            p45=(r45["t_dry_h"] / r50["t_dry_h"] - 1) * 100.0,
            g45=r45["qbar_at_dry"] / r50["qbar_at_dry"],
            d60=r50["t_dry_h"] - r60["t_dry_h"],
            p60=(1 - r60["t_dry_h"] / r50["t_dry_h"]) * 100.0,
            l60=(1 - r60["qbar_at_dry"] / r50["qbar_at_dry"]) * 100.0)

    out = dict(
        meta=dict(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            purpose="摘要「温度—品质—时长权衡」取舍声明的数据支点",
            framework="恒温 ConstDriver(Tc, C_air=0.05)，prob3 口径 N=20/dt=1 s，"
                      "Q̄ 用 probQ integrate_qbar 同一实现",
            caliber_note="energy_J 为对账累计口径，只作参考；与 probQ temp_scan "
                         "50 °C 点口径一致可互检",
        ),
        rows=rows,
        conclusion_zh=concl,
    )
    out_path = os.path.join(_HERE, "temp_tradeoff.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("\n→", out_path)
    print("→", fig_path)
    print("\n" + concl)
    print("总用时 %.0f s" % (time.time() - wall0))


if __name__ == "__main__":
    main()
