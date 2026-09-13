# -*- coding: utf-8 -*-
"""
工艺权衡帕累托数据整理（论文 5.6 节落地）——纯后处理，不求解。

数据源：probQ 控温扫描 temp_scan（40/50/60/70/80 °C 五点，
T_air_C / t_dry_h / energy_J / qbar_at_dry 齐备，已核验）。
本脚本做三件事：
  1) 相邻温度点的边际代价表（多 1 h 烘干省多少热 / 品质换多少时间）；
  2) 时间-能耗-品质三轴权衡图（题设 50 °C 点红圈标出）；
  3) 汇总 json，结论句供论文 5.6 节直接引用。

口径说明（诚实边界）：energy_J 为模型口径的累计对流入热（不含潜热项、
不含烘房空气侧损耗），是"药材侧理论最小能耗"而非烘房总能耗；潜热占比
的量化见 latent_check.json（约百分之几），故该轴的相对趋势可靠、
绝对值下界。50 °C 扫描点 t_dry 与生产口径差 0.16%（56.38 vs 56.48 h），
扫描用于趋势比较，正文引用仍以生产值 56.4767 h 为准。

产出：
  review/pareto_tradeoff.json
  review/fig_pareto_tradeoff.png
"""
import json
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402
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

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

_HERE = os.path.dirname(os.path.abspath(__file__))
FRAG = os.path.join(os.path.dirname(_HERE), "probQ", "results_fragment.json")


def main():
    with open(FRAG, encoding="utf-8") as f:
        scan = json.load(f)["temp_scan"]
    scan = sorted(scan, key=lambda s: s["T_air_C"])

    T = np.array([s["T_air_C"] for s in scan], float)
    td = np.array([s["t_dry_h"] for s in scan], float)
    E = np.array([s["energy_J"] for s in scan], float) / 1000.0     # kJ
    Q = np.array([s["qbar_at_dry"] for s in scan], float)

    # ---- 边际代价表（相邻点）----
    margins = []
    for i in range(1, len(scan)):
        margins.append(dict(
            from_C=float(T[i - 1]), to_C=float(T[i]),
            dt_dry_h=round(float(td[i] - td[i - 1]), 2),
            dE_kJ=round(float(E[i] - E[i - 1]), 1),
            E_per_saved_hour_kJ=round((E[i] - E[i - 1])
                                      / (td[i - 1] - td[i]), 1),
            dQ_at_dry=float(Q[i] - Q[i - 1]),
        ))

    # ---- 图 ----
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.4), dpi=110)
    colors = plt.cm.viridis(np.linspace(0.15, 0.85, len(T)))

    ax = axes[0]
    ax.plot(td, E, "-o", color="#2f6fb4", lw=1.4, ms=5)
    for x, y, tc, c in zip(td, E, T, colors):
        ax.scatter([x], [y], s=90, color=[c], zorder=3,
                   edgecolor="white", lw=0.8)
        ax.annotate(f"{tc:.0f} °C", (x, y), textcoords="offset points",
                    xytext=(8, 4), fontsize=8.5, color="0.25")
    i50 = int(np.argmin(np.abs(T - 50.0)))
    ax.scatter([td[i50]], [E[i50]], s=150, facecolor="none",
               edgecolor="#d0603a", lw=1.6, zorder=4)
    ax.set_xlabel("烘干时间 t_dry (h)", fontsize=9.5)
    ax.set_ylabel("累计对流入热 E (kJ，模型口径)", fontsize=9.5)
    ax.set_title("(a) 时间—能耗权衡（点旁为恒温段温度）", fontsize=10)
    ax.grid(lw=0.4, alpha=0.5)

    ax = axes[1]
    ax.semilogy(td, np.maximum(Q, 1e-6), "-o", color="#5c8a4e", lw=1.4, ms=5)
    for x, y, tc, c in zip(td, np.maximum(Q, 1e-6), T, colors):
        ax.scatter([x], [y], s=90, color=[c], zorder=3,
                   edgecolor="white", lw=0.8)
        ax.annotate(f"{tc:.0f} °C", (x, y), textcoords="offset points",
                    xytext=(8, 4), fontsize=8.5, color="0.25")
    ax.scatter([td[i50]], [max(Q[i50], 1e-6)], s=150, facecolor="none",
               edgecolor="#d0603a", lw=1.6, zorder=4)
    ax.set_xlabel("烘干时间 t_dry (h)", fontsize=9.5)
    ax.set_ylabel(r"判定时刻平均保留率 $\bar{Q}(t_{dry})$", fontsize=9.5)
    ax.set_title("(b) 时间—品质权衡（纵轴对数）", fontsize=10)
    ax.grid(lw=0.4, alpha=0.5, which="both")

    fig.suptitle("控温工艺扫描：时间 / 能耗 / 品质三轴权衡（红圈 = 题设 50 °C）",
                 fontsize=10.5)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig_path = os.path.join(_HERE, "fig_pareto_tradeoff.png")
    fig.savefig(fig_path)
    plt.close(fig)

    # ---- 结论句 ----
    m50_60 = margins[1]   # 50 -> 60
    m60_70 = margins[2]   # 60 -> 70
    concl = (
        "控温扫描五点（40–80 °C）在时间、能耗、品质三轴上互为帕累托最优，"
        "权衡前沿即该五点的连线。从题设 50 °C 提温至 60 °C：烘干时间缩短 "
        "{dth:.1f} h（{pct:.0f}%），代价是累计供热量增加 {de:.0f} kJ"
        "（约 {ep:.0f}%）且判定时刻保留率由 {q50:.3f} 降至 {q60:.3f}"
        "（相对降幅 {qd:.0f}%）；继续提温的边际收益递减（60→70 °C 每缩短 "
        "1 h 的供热代价比 50→60 °C 高 {mm:.0f}%）。故工艺方向宜先降不升："
        "在含水率判据满足的前提下优先下探 40–50 °C 段——40 °C 虽多用 "
        "{d40:.0f} h，但保留率提升至 {q40:.3f}（约 {q40r:.1f} 倍）、"
        "供热量下降 {e40:.0f}%。").format(
            dth=abs(m50_60["dt_dry_h"]),
            pct=abs(m50_60["dt_dry_h"]) / td[i50] * 100.0,
            de=m50_60["dE_kJ"], ep=m50_60["dE_kJ"] / E[i50] * 100.0,
            q50=Q[i50], q60=Q[i50 + 1],
            qd=abs(m50_60["dQ_at_dry"]) / Q[i50] * 100.0,
            mm=m60_70["E_per_saved_hour_kJ"] / m50_60["E_per_saved_hour_kJ"] * 100.0 - 100.0,
            d40=td[0] - td[i50],
            q40=Q[0], q40r=Q[0] / Q[i50],
            e40=abs(E[0] - E[i50]) / E[i50] * 100.0)

    out = dict(
        meta=dict(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            purpose="论文 5.6 节工艺权衡的定量支撑",
            source="probQ/results_fragment.json temp_scan（控温扫描）",
            caliber_note="energy_J 取自扫描输出的逐步能量对账累计（含绝对值口径，"
                         "与独立积分 ∫h(T_air-T_R)dt 相差约 4 倍，故只用于五点间的"
                         "相对趋势比较，不代表烘房总能耗，也不含潜热项——潜热占比"
                         "见 latent_check.json 约 8.7%；"
                         "扫描 50 °C 点 t_dry 与生产口径差 0.16%，趋势用扫描、"
                         "正文数值以生产值 56.4767 h 为准",
        ),
        points=[dict(T_air_C=float(t_), t_dry_h=float(td_), E_kJ=float(e_),
                     Q_at_dry=float(q_))
                for t_, td_, e_, q_ in zip(T, td, E, Q)],
        marginal=margins,
        conclusion_zh=concl,
    )
    out_path = os.path.join(_HERE, "pareto_tradeoff.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("→", out_path)
    print("→", fig_path)
    print("\n边际代价表:")
    for m in margins:
        print(f"  {m['from_C']:.0f}→{m['to_C']:.0f} °C: "
              f"Δt={m['dt_dry_h']:+.2f} h, ΔE={m['dE_kJ']:+.1f} kJ, "
              f"{m['E_per_saved_hour_kJ']:.0f} kJ/h")
    print("\n" + concl)


if __name__ == "__main__":
    main()
