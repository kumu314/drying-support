#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probQ 出图 —— fig_p5_quality.png（品质模块 Q 的正式插图）

数据源（**只读已产出的结果，不重算、不手抄**）：
    probQ/results_fragment.json
      · P5.qbar_curve_h        Qbar(t) 时程（0/6/…/54 h）
      · P5.Q_profile_at_dry    t = t_dry 时刻的 Q 径向剖面（21 点，与表列 0.1 cm 对齐）
      · P5.isothermal_check    等温 50 °C 的解析参考 exp(-k_ref·t)
      · sensitivity            Ea × k_ref 网格上的 Qbar(30 h)（热图）
      · temp_scan              控温扫描：T_air → t_dry 与 Qbar(30 h)

为什么单独一个脚本：Q 的数据在 JSON 片段里（不在 result*.xlsx 中），
与 `tools/make_figs.py`「从 xlsx 读场」的取数方式不同 —— 分开更内聚，也避免互相牵动。

用法
----
    python probQ/make_fig.py
"""

from __future__ import annotations

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


import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 110

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
FIGS = os.path.join(os.path.dirname(PKG), "figs")   # 图目录与源码目录同级
FRAG = os.path.join(HERE, "results_fragment.json")


def _edges(v):
    """由格心数组构造格边界（首尾外扩半个间隔）—— 供 pcolormesh 使用。

    [WARN] 不能用 imshow + extent：imshow 假定网格是**均匀**的，而本题
    Ea = 25/40/55/73/90 与 k_ref = 0.005…0.2（对数后同样不均匀）都**不是**均匀网格，
    用 imshow 会静默错位映射格子（刻度与格心对不上）。
    """
    v = np.asarray(v, float)
    e = np.empty(v.size + 1)
    e[1:-1] = 0.5 * (v[:-1] + v[1:])
    e[0] = v[0] - 0.5 * (v[1] - v[0])
    e[-1] = v[-1] + 0.5 * (v[-1] - v[-2])
    return e


def main():
    with open(FRAG, encoding="utf-8") as f:
        frag = json.load(f)

    P5 = frag["P5"]
    sen = frag["sensitivity"]
    scan = frag["temp_scan"]
    t_dry = float(P5["t_dry_h"])

    # --- (a) Qbar(t) 时程 ---
    curve = {float(k): float(v) for k, v in P5["qbar_curve_h"].items()}
    tk = np.array(sorted(curve))
    qk = np.array([curve[t] for t in tk])

    # --- (b) Ea × k_ref 敏感性面 ---
    ea = np.asarray(sen["ea_grid_kJ_mol"], float)
    kref = np.asarray(sen["kref_grid_per_h"], float)
    Z = np.asarray(sen["qbar_at_30h"], float)          # (n_ea, n_kref)

    # --- (c) t_dry 时刻的 Q 径向剖面 ---
    prof = np.asarray(P5["Q_profile_at_dry"], float)
    r_cm = np.arange(prof.size) * 0.1                  # 0 … 2.0 cm，21 点

    # --- (d) 控温扫描 ---
    T_air = np.array([s["T_air_C"] for s in scan], float)
    td = np.array([s["t_dry_h"] for s in scan], float)
    q30 = np.array([s["qbar_at_30h"] for s in scan], float)

    fig, ax = plt.subplots(2, 2, figsize=(11.6, 8.2))
    fig.suptitle("品质变化动力学：有效成分保留率 Q 的演化、分解与工艺敏感性",
                 fontsize=13, y=0.985)

    # (a) Qbar(t)
    a = ax[0, 0]
    a.plot(tk, qk, "o-", color="#1f77b4", lw=1.9, ms=5, label="体积平均保留率 $\\bar{Q}(t)$")
    q_iso = float(P5["isothermal_check"]["exp_minus_kt"])
    a.axhline(q_iso, color="#d62728", ls="--", lw=1.3,
              label="恒温 50 °C 解析 $e^{-k_{\\rm ref}t}$(30 h)=%.4f" % q_iso)
    a.axvline(t_dry, color="#7f7f7f", ls=":", lw=1.2)
    a.annotate("$t_{dry}$=%.2f h" % t_dry, xy=(t_dry, 0.5), xytext=(6, 0),
               textcoords="offset points", fontsize=9, color="#555555")
    a.set_xlabel("烘干时间 t (h)")
    a.set_ylabel("$\\bar{Q}$（体积平均保留率）")
    a.set_title("(a) 保留率时程与等温解析对照", fontsize=10.5)
    a.grid(True, ls=":", lw=0.4, alpha=0.6)
    a.legend(fontsize=8.5, loc="upper right")

    # (b) 敏感性面
    b = ax[0, 1]
    lx = np.log10(kref)
    xe, ye = _edges(lx), _edges(ea)
    im = b.pcolormesh(xe, ye, Z, cmap="viridis", shading="flat")
    b.set_xticks(lx)
    b.set_xticklabels([f"{v:g}" for v in kref])
    b.set_yticks(ea)
    b.set_yticklabels([f"{v:g}" for v in ea])
    b.set_xlabel("参考速率常数 $k_{\\rm ref}$ (h$^{-1}$，对数刻度)")
    b.set_ylabel("活化能 $E_a$ (kJ/mol)")
    b.set_title("(b) $\\bar{Q}$(30 h) 对 $E_a\\times k_{\\rm ref}$ 的敏感性", fontsize=10.5)
    for i in range(Z.shape[0]):
        for j in range(Z.shape[1]):
            b.text(lx[j], ea[i], f"{Z[i, j]:.3f}", ha="center", va="center",
                   fontsize=6.4, color="white" if Z[i, j] < 0.45 else "black")
    i0, j0 = int(np.argmin(np.abs(ea - 73.0))), int(np.argmin(np.abs(kref - 0.05)))
    b.plot(lx[j0], ea[i0], "o", ms=9, mfc="none", mec="#ff2d2d", mew=1.8)
    b.annotate("基准", xy=(lx[j0], ea[i0]), xytext=(0, -26),
               textcoords="offset points", ha="center", fontsize=8.5, color="#ff2d2d",
               bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8))
    fig.colorbar(im, ax=b, fraction=0.046, pad=0.03).set_label("$\\bar{Q}$(30 h)", fontsize=8.5)

    # (c) 径向剖面
    c = ax[1, 0]
    c.plot(r_cm, prof, "s-", color="#2ca02c", lw=1.8, ms=4.5)
    c.axhline(float(P5["Q_min_at_dry"]), color="#999999", ls=":", lw=1.1)
    c.set_xlabel("径向坐标 r (cm)")
    c.set_ylabel("$Q(r,\\,t_{dry})$")
    c.set_title("(c) $t_{dry}$ 时刻 Q 的径向剖面（中心与表面相差仅 "
                "%.2f%%）" % ((prof[0]/prof[-1]-1)*100), fontsize=10.5)
    c.grid(True, ls=":", lw=0.4, alpha=0.6)
    c.text(0.02, 0.06,
           f"中心 {prof[0]:.5f} ｜ 表面 {prof[-1]:.5f}\n"
           f"（近似等温，剖面极平，温度梯度对 Q 影响很小）",
           transform=c.transAxes, fontsize=8.2, color="#444444", va="bottom")

    # (d) 控温扫描
    d = ax[1, 1]
    l1, = d.plot(T_air, td, "o-", color="#ff7f0e", lw=1.8, ms=5, label="$t_{dry}$ (h)")
    d.set_xlabel("恒温段热风温度 $T_{air}$ (°C)")
    d.set_ylabel("$t_{dry}$ (h)", color="#ff7f0e")
    d.tick_params(axis="y", labelcolor="#ff7f0e")
    d.grid(True, ls=":", lw=0.4, alpha=0.6)
    d2 = d.twinx()
    l2, = d2.plot(T_air, q30, "s--", color="#9467bd", lw=1.8, ms=5,
                  label="$\\bar{Q}$(30 h)")
    d2.set_ylabel("$\\bar{Q}$(30 h)", color="#9467bd")
    d2.tick_params(axis="y", labelcolor="#9467bd")
    d.set_title("(d) 控温工艺扫描：烘干时长 vs 保留率（权衡）", fontsize=10.5)
    d.legend(handles=[l1, l2], fontsize=8.5, loc="center right")

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    os.makedirs(FIGS, exist_ok=True)
    out = os.path.join(FIGS, "fig_p5_quality.png")
    fig.savefig(out)
    plt.close(fig)

    print(f"→ 已生成 {out}  ({os.path.getsize(out)/1024:.0f} KB)")
    print(f"   Qbar(30 h) = {P5['Q_mean_30h']:.4f} ｜ Qbar(t_dry) = {P5['Q_mean_at_dry']:.4f} "
          f"｜ t_dry = {t_dry:.4f} h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
