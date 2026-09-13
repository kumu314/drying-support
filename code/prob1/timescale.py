#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间尺度分离分析（传质与传热特征时间之比的量级洞察）

用于说明
「水分扩散的特征时间远大于导热的特征时间」，键值**必须代码实算**（
数字必须代码产出，且**比值随 C、T 变 → 不写死单一数**）。

定义（径向特征时间）
--------------------
    τ_heat = R^2 / α ,   α = k / (ρ · c_p)          [热扩散特征时间, s]
    τ_mass = R^2 / D                                 [质扩散特征时间, s]
    tau_ratio = τ_mass / τ_heat = α / D             [无量纲]

基准点取**问题一初态**（附录2 常物性，C₀ = 2.55 kg/kg，T₀ = 28 °C），
基准比值 τ_mass/τ_heat = 34.20（结果写入 `timescale.json`）。

[WARN] 为什么必须给曲线而不是一个数
------------------------------
* `ratio ∝ 1/D`。附录2 的 D = D₀·exp(-Da/C) 随 C **单调增**，附录3/4 还乘了
  exp(-3850/T)（**T 用开尔文**）—— 故 C↓ 或 T↓ 都会把比值推向更大。
* 问题一过程中表面含水率从 2.55 降到 1.512（1800 s），比值随之从 34 升到 43；
  若只报一个数，等于把一条 26% 的变化压成一个点。

用法
----
    python prob1/timescale.py
    python prob1/timescale.py --no-fig
"""

from __future__ import annotations

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

from datetime import datetime

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))          # 公共模块目录
from common import props as props_mod               # noqa: E402

# ---------------- 口径常量（与 prob1 一致；不另立一套）----------------
R_M = 0.02          # 药材半径 m
C0 = 2.55           # 初始含水率 kg/kg
T0_C = 28.0         # 初始温度 °C
C_DRY = 0.15        # 烘干完成判据阈值 kg/kg
T_AIR_C = 50.0      # 恒温段风温 °C
SOLVER_VERSION = "p1-timescale-v1"


def taus(props_fn, C, T_C):
    """返回 (tau_heat_s, tau_mass_s, ratio)。C / T_C 可为标量或数组（广播）。"""
    C_arr = np.atleast_1d(np.asarray(C, dtype=float))
    T_K = np.atleast_1d(np.asarray(T_C, dtype=float)) + 273.15
    p = props_fn(C_arr, T_K)
    alpha = p["k"] / (p["rho"] * p["cp"])
    tau_heat = R_M ** 2 / alpha
    tau_mass = R_M ** 2 / p["D"]
    return tau_heat, tau_mass, tau_mass / tau_heat


def _f(x):
    x = np.atleast_1d(x)
    return float(x[0])


def main():
    ap = argparse.ArgumentParser(description="A题 时间尺度分离（τ_mass/τ_heat）")
    ap.add_argument("--out-dir", default=_HERE)
    ap.add_argument("--no-fig", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    print("=" * 74)
    print("A 题 · 时间尺度分离  τ_heat = R^2/α ,  τ_mass = R^2/D ,  ratio = α/D")
    print("=" * 74)

    # ---------------- ① 基准点：问题一初态（附录2）----------------
    th0, tm0, r0 = taus(props_mod.props_app2, C0, T0_C)
    th0, tm0, ratio0 = _f(th0), _f(tm0), _f(r0)
    print(f"\n[基准] 问题一初态（附录2, C={C0}, T={T0_C} °C）")
    print(f"  τ_heat = {th0:,.1f} s ;  τ_mass = {tm0:,.1f} s  →  ratio = {ratio0:.2f}")

    # ---------------- ② 三套物性 × 两个温度（对照）----------------
    cross = {}
    for tag, fn in (("app2", props_mod.props_app2),
                    ("app3", props_mod.props_app3),
                    ("app4", props_mod.props_app4)):
        for T_C in (T0_C, T_AIR_C):
            th, tm, rr = taus(fn, C0, T_C)
            cross[f"{tag}_T{int(T_C)}"] = dict(
                tau_heat_s=round(_f(th), 2),
                tau_mass_s=round(_f(tm), 2),
                ratio=round(_f(rr), 3),
            )
    print("\n[对照] 同一初态含水率 C=2.55，三套物性 × 两个温度：")
    for k, v in cross.items():
        print(f"  {k:12s}  τ_heat={v['tau_heat_s']:>10,.1f} s  "
              f"τ_mass={v['tau_mass_s']:>12,.1f} s  ratio={v['ratio']:>8.3f}")

    # ---------------- ③ 曲线：ratio vs 含水率 C（随含水率变化的曲线）----------------
    # C 从初值 2.55 扫到判据 0.15；用对数分布，兼顾两端量级跨度
    C_grid = np.round(np.geomspace(C_DRY, C0, 41), 4)
    curves = {}
    for tag, fn in (("app2", props_mod.props_app2),
                    ("app3", props_mod.props_app3),
                    ("app4", props_mod.props_app4)):
        _, _, rr = taus(fn, C_grid, T0_C)
        curves[f"{tag}_T{int(T0_C)}"] = [round(float(x), 4) for x in rr]
    # 附录3 再给一条 50 °C（说明 T 的影响方向）
    _, _, rr50 = taus(props_mod.props_app3, C_grid, T_AIR_C)
    curves[f"app3_T{int(T_AIR_C)}"] = [round(float(x), 4) for x in rr50]

    r_C0 = _f(taus(props_mod.props_app2, C0, T0_C)[2])
    r_Cend = _f(taus(props_mod.props_app2, 1.512, T0_C)[2])
    r_dry = _f(taus(props_mod.props_app2, C_DRY, T0_C)[2])
    print(f"\n[曲线] 问题一实际 C 变化范围 2.55 → 1.512（表面，1800 s）：")
    print(f"  ratio: {r_C0:.2f} → {r_Cend:.2f}   （+{(r_Cend/r_C0-1)*100:.1f}%）")
    print(f"  若一路降到判据 {C_DRY}：ratio = {r_dry:.2f}")

    # ---------------- ④ 出图 ----------------
    fig_path = None
    if not args.no_fig:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei",
                                           "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        figs_dir = os.path.join(os.path.dirname(_HERE), "figs")
        os.makedirs(figs_dir, exist_ok=True)
        fig_path = os.path.join(figs_dir, "fig_p1_timescale.png")

        fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=150)
        style = {
            f"app2_T{int(T0_C)}": ("附录2（问题一）T=28 °C", "#1f77b4", "-", 1.9),
            f"app3_T{int(T0_C)}": ("附录3（问题二/三）T=28 °C", "#ff7f0e", "-", 1.9),
            f"app3_T{int(T_AIR_C)}": ("附录3 T=50 °C", "#ff7f0e", "--", 1.5),
            f"app4_T{int(T0_C)}": ("附录4（问题四）T=28 °C", "#2ca02c", "-", 1.9),
        }
        for k, (lab, col, ls, lw) in style.items():
            ax.semilogy(C_grid, curves[k], ls, color=col, lw=lw, label=lab)
        ax.axvline(1.512, color="#999999", lw=0.9, ls=":")
        ax.text(1.512, ax.get_ylim()[1] * 0.7, " 问题一 1800 s 表面 C", rotation=90,
                va="top", ha="right", fontsize=8, color="#666666")
        ax.plot([C0], [r_C0], "o", color="#1f77b4", ms=5, mec="k", mew=0.5, zorder=5)
        ax.annotate(f"基准 {r_C0:.1f}", xy=(C0, r_C0), xytext=(-8, 12),
                    textcoords="offset points", fontsize=9, color="#1f77b4")
        ax.set_xlabel("干基含水率 C (kg/kg)")
        ax.set_ylabel("时间尺度比 τ_mass / τ_heat  （对数轴）")
        ax.set_title("传质/传热特征时间之比随含水率的变化", fontsize=11)
        ax.grid(True, which="both", ls=":", lw=0.4, alpha=0.6)
        ax.legend(fontsize=8.5, framealpha=0.95)
        fig.tight_layout()
        fig.savefig(fig_path)
        plt.close(fig)
        print(f"\n→ 图已写出：{fig_path}")

    # ---------------- ⑤ fragment ----------------
    frag = dict(
        meta=dict(generated_at=datetime.now().isoformat(timespec="seconds"),
                  seed=0, solver_version=SOLVER_VERSION, reproducible=True,
                  props_source="题目附录2/3/4",
                  note="τ 为径向特征时间 R²/α 与 R²/D；比值 = α/D，随 C、T 变"),
        P1_timescale=dict(
            tau_heat_s=round(th0, 2),
            tau_mass_s=round(tm0, 2),
            **{"tau_ratio": round(ratio0, 3)},
            at=dict(C=C0, T_C=T0_C, props="附录2", R_m=R_M),
            range_problem1=dict(
                C_from=C0, C_to=1.512, tau_ratio_from=round(r_C0, 3),
                tau_ratio_to=round(r_Cend, 3),
                change_pct=round((r_Cend / r_C0 - 1.0) * 100.0, 2)),
            tau_ratio_if_dry=round(r_dry, 3),
        ),
        cross_props=cross,
        curve=dict(
            C=C_grid.tolist(),
            ratio=curves,
            note="T 为 °C；D 公式内含 exp(−3850/T_K)，**T 用开尔文**；"
                 "纵轴为对数刻度（跨约 2.4 个量级）"),
        figure=dict(
            id="fig_p1_timescale",
            file="figs/fig_p1_timescale.png",
            caption="图：传质/传热特征时间之比随含水率的变化（三套物性与两个温度）",
            scope="支撑材料/§3.1 可选插图"),
    )
    out = os.path.join(args.out_dir, "timescale.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(frag, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"→ fragment 已写出：{out}")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
