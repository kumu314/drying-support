# -*- coding: utf-8 -*-
"""
Picard 外迭代统计（论文 §4.2「迭代收敛性」论述的定量支撑）。

口径：
  prob2 口径 —— 生产同款（附件1 分段驱动，0–3 h 报告窗口）；
  prob3 口径 —— 全程跑到完成判据（t_dry ≈ 56.48 h）；
  prob4     —— 与 prob3 同一 Picard 机制（变物性迭代），仅材质参数族与动边界
               不同；其求解器为独立实现（solve_moving），生产日志已报告最大
               迭代数，不在此重复求解。

容差与生产一致：tol_heat=1e-8（温度块），tol_C=1e-11（水分块），max_picard=30。
统计量：平均 / 最大外迭代次数（每时间步计一次）。
产出：review/picard_stats.json

用法：python picard_stats.py --air 附件1.xlsx路径
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

import numpy as np                       # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))          # 上级目录（common 包）

from common import props as props_mod               # noqa: E402
from prob3.solve import build_air, run_solve        # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Picard 外迭代统计（prob2/prob3 口径）")
    ap.add_argument("--air", required=True)
    ap.add_argument("--N", type=int, default=20)
    ap.add_argument("--dt", type=float, default=1.0)
    args = ap.parse_args()

    air, _t, _Ta, _Ca = build_air(args.air)
    out = dict(meta=dict(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        purpose="Picard 外迭代统计（论文 §4.2 用）",
        tolerances=dict(tol_heat=1e-8, tol_C=1e-11, max_picard=30),
        note="每时间步计一次外迭代；恒物性问题一不解耦迭代，不统计",
    ), cases=[])

    # ---- prob2 口径：0–3 h 报告窗口 ----
    P2 = dict(R=0.02, L=0.25, h=25.0, hm=8.0e-7, T0=28.0, C0=2.55,
              t_end=3 * 3600.0)
    w0 = time.time()
    r2 = fvm_solve(args, air, props_mod.props_app3, P2)
    out["cases"].append(dict(
        case="prob2（报告窗口 0–3 h）", steps=int(round(3 * 3600.0 / args.dt)),
        picard_mean=round(r2["picard_mean"], 4),
        picard_max=int(r2["picard_max"]),
        wall_s=round(time.time() - w0, 1)))
    print(f"[prob2 窗口] mean={r2['picard_mean']:.3f} max={r2['picard_max']}"
          f"（{out['cases'][-1]['wall_s']} s）", flush=True)

    # ---- prob3 口径：全程到判据 ----
    P3 = dict(R=0.02, L=0.25, h=25.0, hm=8.0e-7, T0=28.0, C0=2.55,
              t_end=5 * 86400.0)
    w0 = time.time()
    r3, td = run_solve(args.N, args.dt, air, props_mod.props_app3, P3,
                       P3["t_end"])
    out["cases"].append(dict(
        case="prob3（全程到判据）", t_dry_h=round(td / 3600.0, 4),
        steps=int(round(td / args.dt)),
        picard_mean=round(r3["picard_mean"], 4),
        picard_max=int(r3["picard_max"]),
        wall_s=round(time.time() - w0, 1)))
    print(f"[prob3 全程] t_dry={td/3600.0:.4f} h mean={r3['picard_mean']:.3f} "
          f"max={r3['picard_max']}（{out['cases'][-1]['wall_s']} s）", flush=True)

    out["cases"].append(dict(
        case="prob4（说明）",
        note="与 prob3 同一 Picard 机制（附录4 材质 + 动边界独立实现 solve_moving），"
             "迭代次数量级与 prob3 相当；生产求解日志已报告其最大迭代数",
    ))

    out["conclusion_zh"] = (
        "外迭代代价极低：报告窗口内平均 {m2:.2f} 次/步、峰值 {x2} 次；全程平均 "
        "{m3:.2f} 次/步、峰值 {x3} 次（容差温度块 1e-8、水分块 1e-11）。"
        "变物性耦合收敛快，印证「顺序耦合 + Picard」在该问题上是低成本选择。"
    ).format(m2=out["cases"][0]["picard_mean"], x2=out["cases"][0]["picard_max"],
             m3=out["cases"][1]["picard_mean"], x3=out["cases"][1]["picard_max"])

    out_path = os.path.join(_HERE, "picard_stats.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("→", out_path)
    print(out["conclusion_zh"])


def fvm_solve(args, air, props, P):
    """prob2 口径的直接求解（带 Picard 统计）。"""
    from common import fvm
    return fvm.solve_case(args.N, args.dt, out_every=60.0, air=air,
                          props=props, P=P, record_all=False)


if __name__ == "__main__":
    main()
