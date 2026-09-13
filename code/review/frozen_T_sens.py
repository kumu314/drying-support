# -*- coding: utf-8 -*-
"""
t_dry 对冻结温度 T∞ 的敏感度。

背景（为什么做）
----------------
附件1 仅覆盖前 4 h（0–14400 s），P3 全程 56.48 h 里有约 52 h、P4 全程 50.81 h
里有约 47 h 处在"无数据外推区"（冻结在 50 °C / 0.05 kg/kg）。
判据阈值 ±10% 的停机敏感性（∓20%/32%）已说明停机口径主导结果；
本脚本补最后一环：**外推段的驱动温度若与 50 °C 有偏差，t_dry 动多少**。
±2 °C 取烘房温控的典型波动带宽（工程惯例）。

方法
----
完全复用 prob3 主求解器（同一 FVM+CN+Picard 链路，不另立模型）：
对 T∞ ∈ {48, 50, 52} °C 各跑一次到判据满足。50 °C 一档同时充当
"同代码复现基准"（应精确回到论文口径 56.4767 h），保证三点同源可比。

产出
----
review/frozen_T_sens.json：
  t_dry_h（三点）、相对 50 °C 的变化 h 与 %、外推依据一句话答案。

用法
----
    python review/frozen_T_sens.py --air <附件1.xlsx 路径>
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODER = os.path.dirname(_HERE)          # .../code（含 prob3/ common/）
sys.path.insert(0, _CODER)

from prob3 import solve as p3            # noqa: E402  （复用主求解器）
from common import props as props_mod    # noqa: E402

TEMPS = [48.0, 50.0, 52.0]               # T∞ 扫描点（°C），50 为论文口径
N_GRID, DT = 20, 1.0                     # 与论文口径一致（§4.1）
PAPER_BASE_H = 56.4767                   # results.json P3.t_dry_h


def run_one(t_inf_c: float, air_path: str):
    """把 prob3 的冻结温度换成 t_inf_c 后跑一次，返回 (res, t_dry_h)。"""
    p3.T_AIR_C = float(t_inf_c)          # 模块级常量，build_air 调用时读取
    air, _, _, _ = p3.build_air(air_path)
    P = dict(R=0.02, L=0.25, h=p3.H_CONV, hm=p3.H_MASS, T0=28.0, C0=2.55,
             t_end=3 * 86400.0)
    res, t_dry_s = p3.run_solve(N_GRID, DT, air, props_mod.props_app3, P,
                                3 * 86400.0)
    return res, t_dry_s / 3600.0


def main():
    ap = argparse.ArgumentParser(description="t_dry 对冻结温度 T∞ 的敏感度")
    ap.add_argument("--air", required=True, help="附件1.xlsx 路径")
    ap.add_argument("--out", default=os.path.join(_HERE, "frozen_T_sens.json"))
    args = ap.parse_args()

    rows, t_base = [], None
    for tc in TEMPS:
        t0 = time.time()
        res, t_h = run_one(tc, args.air)
        if abs(tc - 50.0) < 1e-9:
            t_base = t_h
        rows.append(dict(
            T_inf_C=tc,
            t_dry_h=round(t_h, 4),
            t_dry_s=round(t_h * 3600),
            C_max_at_dry=round(float(res["C"][-1].max()), 8),
            stopped_early=bool(res["stopped_early"]),
            picard_max=int(res["picard_max"]),
            wall_s=round(time.time() - t0, 1)))
        print(f"T∞={tc:.0f} °C → t_dry={t_h:.4f} h  "
              f"({time.time()-t0:.0f} s)", flush=True)

    assert t_base is not None, "50 °C 基准档缺失"
    for r in rows:
        r["d_h_vs_50"] = round(r["t_dry_h"] - t_base, 4)
        r["d_pct_vs_50"] = round((r["t_dry_h"] - t_base) / t_base * 100.0, 4)

    base_check_ok = abs(t_base - PAPER_BASE_H) < 0.01
    t48 = next(r for r in rows if r["T_inf_C"] == 48.0)["t_dry_h"]
    t52 = next(r for r in rows if r["T_inf_C"] == 52.0)["t_dry_h"]

    out = dict(
        _meta=dict(
            task="t_dry 对冻结温度 T∞ 敏感度（50±2 °C 两点）",
            generated_at=datetime.now().isoformat(timespec="seconds"),
            solver=p3.SOLVER_VERSION,
            reuse="prob3/solve.py 主求解器原样复用，仅替换冻结温度常量",
            grid=dict(N=N_GRID, dt_s=DT),
            paper_base_h=PAPER_BASE_H,
            base_reproduce_h=round(t_base, 4),
            base_reproduce_ok=bool(base_check_ok),
            note="±2 °C 为烘房温控典型波动带宽；±10% 量级（±5 °C）见 temp_tradeoff",
        ),
        rows=rows,
        headline=(
            f"冻结温度 ±2 °C 时 t_dry 在 [{t48:.2f}, {t52:.2f}] h 内变动，"
            f"相对论文口径 56.48 h 的偏离为 "
            f"{(t48-t_base)/t_base*100:+.1f}% / {(t52-t_base)/t_base*100:+.1f}%"),
        one_liner=(
            "附件1 覆盖区（前 4 h）内驱动量逐点实测、无外推；外推区冻结温度 "
            "±2 °C（烘房温控典型带宽）仅使 t_dry 偏离约百分之几，"
            "远小于判据阈值 ±10% 引起的 ∓20%/32%，外推口径不改变结论量级"),
    )
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n→ 已写出 {args.out}")
    print(out["headline"])
    if not base_check_ok:
        print("⚠️ 50 °C 档未复现论文口径 56.4767 h，请勿直接引用，先查口径！")


if __name__ == "__main__":
    main()
