# -*- coding: utf-8 -*-
"""
灵敏度全参定量表 + 共享区龙卷风图。

在 param_sensitivity.py（h/h_m/k/判据阈值）与 d_sensitivity.py（D）基础上，
补跑 rho / c_p ±10% 两组（问题3 口径，基线自检同款），合并产出：
review/sensitivity_matrix.json —— 全参数一张表（行格式与 d_sensitivity 一致）
figs/fig_tornado.png —— 共享图区龙卷风图

用法：
python sensitivity_matrix.py --air 附件1.xlsx路径
"""
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

from common import props as props_mod               # noqa: E402
from prob3.solve import build_air, run_solve        # noqa: E402

FIGS = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "figs")
PARAM_JSON = os.path.join(_HERE, "param_sensitivity.json")
D_JSON = os.path.join(_HERE, "d_sensitivity.json")


def scaled_props(channel, scale):
    """把附录3 物性回调的指定通道整体缩放，其余原样透传。"""
    def f(C, T_K):
        d = props_mod.props_app3(C, T_K)
        d[channel] = d[channel] * scale
        return d
    return f


def main():
    ap = argparse.ArgumentParser(description="rho/c_p ±10% 补跑 + 全参数合并表")
    ap.add_argument("--air", required=True)
    ap.add_argument("--N", type=int, default=20)
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--t-end-cap", type=float, default=5 * 86400.0)
    args = ap.parse_args()

    air, _t, _Ta, _Ca = build_air(args.air)
    P = dict(R=0.02, L=0.25, h=25.0, hm=8.0e-7, T0=28.0, C0=2.55,
             t_end=args.t_end_cap)

    rows = []
    wall0 = time.time()

    # 基线自检（生产路径）
    _res, t_base = run_solve(args.N, args.dt, air, props_mod.props_app3,
                             P, args.t_end_cap)
    ref = json.load(open(
        os.path.join(os.path.dirname(_HERE), "prob3", "results_fragment.json"),
        encoding="utf-8"))["P3"]["t_dry_h"]
    ok = abs(t_base / 3600.0 - ref) < 1e-3
    print(f"[base] t_dry={t_base/3600.0:.4f} h，复现 {ref}：{ok}", flush=True)
    assert ok, "基线未复现 56.4767 h，停止（口径被污染）"
    rows.append(dict(case="base", scale=1.00, t_dry_s=round(t_base, 1),
                     t_dry_h=round(t_base / 3600.0, 4)))

    # 只补 rho / c_p 两组四向（h/h_m/k/C_th/D 已有结果，直接引用）
    for tag, ch, sc in [("rho_plus10", "rho", 1.10), ("rho_minus10", "rho", 0.90),
                        ("cp_plus10", "cp", 1.10), ("cp_minus10", "cp", 0.90)]:
        w0 = time.time()
        _res, td = run_solve(args.N, args.dt, air, scaled_props(ch, sc),
                             P, args.t_end_cap)
        rows.append(dict(case=tag, scale=sc, t_dry_s=round(td, 1),
                         t_dry_h=round(td / 3600.0, 4),
                         delta_pct=round((td - t_base) / t_base * 100.0, 4),
                         wall_s=round(time.time() - w0, 1)))
        print(f"[{tag:>12}] t_dry={td/3600.0:.4f} h"
              f"（delta {rows[-1]['delta_pct']:+.3f}%）", flush=True)

    # ---- 合并三源 ----
    pj = json.load(open(PARAM_JSON, encoding="utf-8"))
    dj = json.load(open(D_JSON, encoding="utf-8"))
    dmap = {r["case"]: r for r in dj["rows"]}

    def entry(name, plus_case, minus_case, plus, minus, src):
        return dict(param=name, plus_case=plus_case, minus_case=minus_case,
                    plus10_pct=plus, minus10_pct=minus, source=src)

    def from_pj(case):
        r = next(x for x in pj["rows"] if x["case"] == case)
        return r["delta_pct"]

    matrix = [
        entry("判据阈值 C_crit", "thr_plus10", "thr_minus10",
              from_pj("thr_plus10"), from_pj("thr_minus10"),
              "review/param_sensitivity.json"),
        entry("水分扩散系数 D", "D_plus10", "D_minus10",
              dmap["D_plus10"]["delta_pct"], dmap["D_minus10"]["delta_pct"],
              "review/d_sensitivity.json"),
        entry("密度 rho", "rho_plus10", "rho_minus10",
              rows[1]["delta_pct"], rows[2]["delta_pct"], "本次补跑"),
        entry("比热 c_p", "cp_plus10", "cp_minus10",
              rows[3]["delta_pct"], rows[4]["delta_pct"], "本次补跑"),
        entry("对流传质系数 h_m", "hm_plus10", "hm_minus10",
              from_pj("hm_plus10"), from_pj("hm_minus10"),
              "review/param_sensitivity.json"),
        entry("对流换热系数 h", "h_plus10", "h_minus10",
              from_pj("h_plus10"), from_pj("h_minus10"),
              "review/param_sensitivity.json"),
        entry("导热系数 k", "k_plus10", "k_minus10",
              from_pj("k_plus10"), from_pj("k_minus10"),
              "review/param_sensitivity.json"),
    ]
    matrix.sort(key=lambda x: max(abs(x["plus10_pct"]),
                                  abs(x["minus10_pct"])), reverse=True)

    # ---- 共享区龙卷风图 ----
    fig, ax = plt.subplots(figsize=(7.4, 3.8), dpi=110)
    ypos = np.arange(len(matrix))[::-1]
    for y, m in zip(ypos, matrix):
        lo, hi = min(m["plus10_pct"], m["minus10_pct"]), \
            max(m["plus10_pct"], m["minus10_pct"])
        ax.barh(y, hi - lo, left=lo, height=0.55, color="#aec7e8",
                edgecolor="#2f6fb4", lw=0.8)
        ax.text(hi + 1.2, y + 0.18, f"{m['plus10_pct']:+.2f}%",
                va="center", fontsize=8.2)
        ax.text(hi + 1.2, y - 0.22, f"{m['minus10_pct']:+.2f}%",
                va="center", fontsize=8.2, color="0.35")
    ax.set_yticks(ypos)
    ax.set_yticklabels([m["param"] for m in matrix], fontsize=9.5)
    ax.axvline(0.0, color="0.3", lw=1.0)
    ax.set_xlim(-42, 62)
    ax.set_xlabel("烘干时间 t_dry 的相对变化（%）", fontsize=9.5)
    ax.set_title("烘干时间对单参数 ±10% 扰动的灵敏度"
                 "（上栏：+10% / 下栏：−10%）", fontsize=10)
    ax.grid(axis="x", lw=0.4, alpha=0.5)
    fig.tight_layout()
    os.makedirs(FIGS, exist_ok=True)
    fig.savefig(os.path.join(FIGS, "fig_tornado.png"))
    plt.close(fig)

    out = dict(
        meta=dict(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            purpose="灵敏度全参定量表（D/h_m/h/k/rho/c_p/判据阈值 各 ±10%）",
            framework="问题3 口径：fvm.solve_case + 完成判据(max C<0.15)，"
                      "N=20, dt=1.0 s；基线逐位复现 56.4767 h",
            air_source=os.path.basename(args.air),
            rho_cp_rows=rows,
        ),
        rows=matrix,
        order=[m["param"] for m in matrix],
        conclusion_zh=(
            "七参数 ±10% 扫描的层级排序：判据阈值（−19.7%/+31.9%）≫ 扩散系数 D"
            "（−7.9%/+9.7%）≫ 对流传质 h_m（−1.1%/+1.4%）≫ 密度、比热、对流换热 h、"
            "导热 k（|Δ| ≤ 0.03%）。热物性 rho/c_p/k 与换热 h 几乎不影响烘干时间——"
            "它们只改变升温快慢，而烘干进程由水分扩散与停机判据主导；全部参数"
            "响应方向不对称，t_dry 对扰动呈非线性，报告时应按方向分别给出。"),
    )
    out_path = os.path.join(_HERE, "sensitivity_matrix.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("\n→", out_path)
    print("→", os.path.join(FIGS, "fig_tornado.png"))
    for m in matrix:
        print(f"  {m['param']:<18s} +10%: {m['plus10_pct']:+8.3f}%   "
              f"-10%: {m['minus10_pct']:+8.3f}%")
    print("总用时 %.0f s" % (time.time() - wall0))


if __name__ == "__main__":
    main()
