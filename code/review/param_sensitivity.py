# -*- coding: utf-8 -*-
"""
全参数直接灵敏度（补充量化）：h、h_m、k、判据阈值 各 +/-10%，问题3 口径。
D 的结果已在 d_sensitivity.json（同口径），此处汇总引用、不重跑。

口径与生产算例逐位一致（N=20, dt=1.0 s, out_every=60 s, record_all=True），
唯一变量是被扰动的参数。基线自检两道：
  1) base 走生产路径 run_solve，t_dry 必须复现 56.4767 h；
  2) base2 走本脚本的直接 stop_when 路径（阈值 0.15），须与 base 逐位一致，
     以保证阈值扰动的对照有效性。

产出：
  review/param_sensitivity.json      —— 汇总表（含 D），供论文 5.3 节引用
  review/fig_sensitivity_tornado.png —— 龙卷风图
  review/base_profile.npz            —— base 全程时程（潜热核算复用，避免重复求解）

用法：
    python param_sensitivity.py --air 附件1.xlsx路径
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
sys.path.insert(0, os.path.dirname(_HERE))                    # 上级目录（common 包）

from common import props as props_mod          # noqa: E402
from common import fvm                         # noqa: E402
from prob3.solve import build_air, run_solve, C_DRY   # noqa: E402

BASE_FRAG = os.path.join(os.path.dirname(_HERE), "prob3", "results_fragment.json")
D_FRAG = os.path.join(_HERE, "d_sensitivity.json")


def k_scaled_props(scale):
    """把附录3 物性回调的导热系数 k 通道整体缩放，其余原样透传。"""
    def f(C, T_K):
        d = props_mod.props_app3(C, T_K)
        d["k"] = d["k"] * scale
        return d
    return f


def solve_thr(N, dt, air, props, P, thr):
    """与 run_solve 完全同口径，仅判据阈值可调。props 缺省用附录3 生产回调。"""
    if props is None:
        props = props_mod.props_app3
    res = fvm.solve_case(
        N, dt, out_every=60.0, air=air, props=props, P=P,
        record_all=True,
        stop_when=lambda tau, _T, C_: bool(np.max(C_) < thr))
    return res, float(res["t_final"])


def main():
    ap = argparse.ArgumentParser(description="全参数直接灵敏度（问题3 口径）")
    ap.add_argument("--air", required=True, help="附件1.xlsx 路径")
    ap.add_argument("--N", type=int, default=20)
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--t-end-cap", type=float, default=5 * 86400.0)
    args = ap.parse_args()

    air, _t, _Ta, _Ca = build_air(args.air)
    P = dict(R=0.02, L=0.25, h=25.0, hm=8.0e-7, T0=28.0, C0=2.55,
             t_end=args.t_end_cap)

    def run(tag, props, params, thr=C_DRY):
        wall0 = time.time()
        if params is None and props is None:
            # 生产路径基线
            _res, t_dry_s = run_solve(args.N, args.dt, air, props_mod.props_app3,
                                      P, args.t_end_cap)
        else:
            _res, t_dry_s = solve_thr(args.N, args.dt, air, props,
                                      params if params is not None else P, thr)
        print(f"[{tag:>10}]  t_dry = {t_dry_s/3600.0:.4f} h"
              f"（{time.time()-wall0:.0f} s）", flush=True)
        return t_dry_s

    rows = []
    t0 = time.time()

    # ---- 基线（两道自检）----
    t_base = run("base", None, None)                       # 生产路径
    t_base2 = run("base_check", props_mod.props_app3, P, C_DRY)  # 直接阈值路径
    check = dict(base_s=round(t_base, 1), base2_s=round(t_base2, 1),
                 identical=bool(abs(t_base - t_base2) < 1e-6))
    ref = None
    with open(BASE_FRAG, encoding="utf-8") as f:
        ref = json.load(f)["P3"]["t_dry_h"]
    check["ref_t_dry_h"] = ref
    check["match_ref"] = bool(abs(t_base / 3600.0 - ref) < 1e-3)
    print("自检:", check, flush=True)

    base = t_base2 if check["identical"] else t_base

    # ---- 四参数 × 两方向 ----
    cases = [
        ("h_plus10",    None,               {**P, "h":  P["h"] * 1.10},  C_DRY),
        ("h_minus10",   None,               {**P, "h":  P["h"] * 0.90},  C_DRY),
        ("hm_plus10",   None,               {**P, "hm": P["hm"] * 1.10}, C_DRY),
        ("hm_minus10",  None,               {**P, "hm": P["hm"] * 0.90}, C_DRY),
        ("k_plus10",    k_scaled_props(1.10), None,                     C_DRY),
        ("k_minus10",   k_scaled_props(0.90), None,                     C_DRY),
        ("thr_plus10",  None,               P,  C_DRY * 1.10),
        ("thr_minus10", None,               P,  C_DRY * 0.90),
    ]
    for tag, props, params, thr in cases:
        td = run(tag, props, params, thr)
        rows.append(dict(case=tag, t_dry_s=round(td, 1),
                         t_dry_h=round(td / 3600.0, 4),
                         delta_pct=round((td - base) / base * 100.0, 4)))

    # ---- D 行引用（不重跑）----
    d_rows = {}
    try:
        with open(D_FRAG, encoding="utf-8") as f:
            dj = json.load(f)
        for r in dj["rows"]:
            d_rows[r["case"]] = r
    except Exception as e:
        print("警告：D 结果引用失败", e)

    # ---- 基线全程时程导出（潜热核算复用）----
    res, _ = solve_thr(args.N, args.dt, air, props_mod.props_app3, P, C_DRY)
    ts = np.asarray(res["times"], float)
    C_h = np.asarray(res["C"], float)          # [time, radius]
    T_h = np.asarray(res["T"], float)
    np.savez_compressed(
        os.path.join(_HERE, "base_profile.npz"),
        times=ts, r=res["r"],
        C_surface=C_h[:, -1], C_mean=C_h.mean(axis=1),
        T_surface=T_h[:, -1], T_mean=T_h.mean(axis=1),
        t_air=np.array([air(x)[0] for x in ts]),
        c_air=np.array([air(x)[1] for x in ts]),
    )
    print("已导出 base_profile.npz（%d 个时刻）" % len(ts), flush=True)

    # ---- 龙卷风图 ----
    def dget(case):
        if case.startswith("D_"):
            return d_rows[case]["delta_pct"]
        return next(r["delta_pct"] for r in rows if r["case"] == case)

    items = [
        ("判据阈值 C_th ±10%", dget("thr_plus10"), dget("thr_minus10")),
        ("水分扩散系数 D ±10%", dget("D_plus10"), dget("D_minus10")),
        ("对流传质系数 h_m ±10%", dget("hm_plus10"), dget("hm_minus10")),
        ("对流换热系数 h ±10%", dget("h_plus10"), dget("h_minus10")),
        ("导热系数 k ±10%", dget("k_plus10"), dget("k_minus10")),
    ]
    items.sort(key=lambda x: max(abs(x[1]), abs(x[2])), reverse=True)

    fig, ax = plt.subplots(figsize=(7.4, 3.4), dpi=110)
    ypos = np.arange(len(items))[::-1]
    for y, (name, dplus, dminus) in zip(ypos, items):
        lo, hi = min(dplus, dminus), max(dplus, dminus)
        ax.barh(y, hi - lo, left=lo, height=0.55, color="#aec7e8",
                edgecolor="#2f6fb4", lw=0.8)
        ax.text(hi + 1.2, y + 0.18, f"{dplus:+.2f}%", va="center", fontsize=8.2)
        ax.text(hi + 1.2, y - 0.22, f"{dminus:+.2f}%", va="center",
                fontsize=8.2, color="0.35")
    ax.set_yticks(ypos)
    ax.set_yticklabels([x[0] for x in items], fontsize=9.5)
    ax.axvline(0.0, color="0.3", lw=1.0)
    ax.set_xlim(-42, 62)
    ax.set_xlabel("烘干时间 t_dry 的相对变化（%）", fontsize=9.5)
    ax.set_title("问题三 烘干时间对单参数 ±10% 扰动的灵敏度"
                 "（上栏：+10% / 下栏：−10%）", fontsize=10)
    ax.grid(axis="x", lw=0.4, alpha=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(_HERE, "fig_sensitivity_tornado.png"))
    plt.close(fig)

    # ---- 汇总 ----
    out = dict(
        meta=dict(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            purpose="论文 5.3 节全参数直接灵敏度量化：单参数 ±10% 扰动下 "
                    "t_dry 的相对变化，层级排序与方向不对称性",
            framework="问题3 口径：fvm.solve_case + 完成判据(max C<0.15)，"
                      "N=20, dt=1.0 s；D 行引用 d_sensitivity.json（同口径）",
            air_source=os.path.basename(args.air),
            base_check=check,
        ),
        rows=rows,
        tornado_order=[x[0] for x in items],
        tornado=[dict(param=n, plus10_pct=p, minus10_pct=m)
                 for n, p, m in items],
        D_reference=dict(
            D_plus10_delta_pct=d_rows.get("D_plus10", {}).get("delta_pct"),
            D_minus10_delta_pct=d_rows.get("D_minus10", {}).get("delta_pct"),
            source="review/d_sensitivity.json",
        ),
    )
    out_path = os.path.join(_HERE, "param_sensitivity.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("\n→ %s" % out_path)
    print("层级排序（|效应| 降序）:")
    for n, p, m in items:
        print(f"  {n:<22s} +10%: {p:+7.2f}%   -10%: {m:+7.2f}%")
    print("总用时 %.0f s" % (time.time() - t0))


if __name__ == "__main__":
    main()
