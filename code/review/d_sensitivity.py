# -*- coding: utf-8 -*-
"""
D 直接灵敏度（补充验证）——「内阻控制型」结论的直接验证。

外部一致性核对给出结论：内阻控制型干燥，D±10% → t_dry 约 ∓9.8%。
我们此前只做过品质动力学的 Ea×k_ref 灵敏度面，未对 D 做过直接扰动实验。
本脚本用问题3 的现成框架（fvm.solve_case + 烘干完成判据 + 双 dt 同款口径）补这一组：

基线 D = props_app3(C, T) （自检：t_dry 必须复现 56.4767 h）
+10% D ×= 1.10 （扩散更快 → t_dry 应变短）
-10% D ×= 0.90 （扩散更慢 → t_dry 应变长）

其余口径（N、dt、驱动、判据、网格）与生产算例逐位一致，唯一变量是 D 的整体缩放。
成本 = 3 次求解。产出 review/d_sensitivity.json，数值以 t_dry_sens_* 字段写入 results.json
（口径文件由项目统一维护，本脚本不直接修改）。

用法：
python d_sensitivity.py --air 附件1.xlsx路径
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

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))                    # 上级目录（common 包）

from common import props as props_mod          # noqa: E402
from prob3.solve import build_air, run_solve   # noqa: E402

BASE_FRAG = os.path.join(os.path.dirname(_HERE), "prob3", "results_fragment.json")


def scaled_props(scale):
    """把附录3 物性回调的 D 通道整体缩放 scale，其余物性原样透传。"""
    def f(C, T_K):
        d = props_mod.props_app3(C, T_K)
        d["D"] = d["D"] * scale
        return d
    return f


def main():
    ap = argparse.ArgumentParser(description="D±10% 直接灵敏度（问题3 口径）")
    ap.add_argument("--air", required=True, help="附件1.xlsx 路径")
    ap.add_argument("--N", type=int, default=20)
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--t-end-cap", type=float, default=3 * 86400.0)
    args = ap.parse_args()

    air, _t, _Ta, _Ca = build_air(args.air)
    P = dict(R=0.02, L=0.25, h=25.0, hm=8.0e-7, T0=28.0, C0=2.55,
             t_end=args.t_end_cap)

    rows = []
    t0_wall = time.time()
    for tag, scale in [("base", 1.00), ("D_plus10", 1.10), ("D_minus10", 0.90)]:
        wall0 = time.time()
        _res, t_dry_s = run_solve(args.N, args.dt, air, scaled_props(scale), P,
                                  args.t_end_cap)
        rows.append(dict(
            case=tag, D_scale=scale,
            t_dry_s=round(t_dry_s, 1),
            t_dry_h=round(t_dry_s / 3600.0, 4),
            wall_s=round(time.time() - wall0, 1),
        ))
        print(f"[{tag:>10}]  D×{scale:.2f}  →  t_dry = {t_dry_s/3600.0:.4f} h"
              f"（{rows[-1]['wall_s']} s）", flush=True)

    base, up, dn = rows[0], rows[1], rows[2]
    for r, denom in [(up, base), (dn, base)]:
        r["delta_pct"] = round((r["t_dry_s"] - base["t_dry_s"])
                               / base["t_dry_s"] * 100.0, 4)
    sym = abs(abs(up["delta_pct"]) - abs(dn["delta_pct"]))
    asym_note = ("正负扰动响应幅值近似对称（|Δ+| 与 |Δ-| 差 <0.5 个百分点），"
                 "支持把 t_dry 对 D 的局部关系近似为幂律 / 线性响应。"
                 if sym < 0.5 else
                 "正负扰动响应幅值不对称（差 ≥0.5 个百分点），局部关系非线性，"
                 "宜按方向分别报告。")

    # 基线自检：与 prob3 生产 fragment 的 t_dry_h 对账（须逐位一致）
    base_check = None
    try:
        with open(BASE_FRAG, encoding="utf-8") as f:
            ref = json.load(f)["P3"]["t_dry_h"]
        base_check = dict(ref_t_dry_h=ref, got_t_dry_h=base["t_dry_h"],
                          match=bool(abs(ref - base["t_dry_h"]) < 1e-3))
    except Exception as e:
        base_check = dict(error=str(e))

    out = dict(
        meta=dict(generated_at=datetime.now().isoformat(timespec="seconds"),
                  purpose="D 直接灵敏度（补充验证）：验证「内阻控制型，"
                          "D±10% → t_dry ∓9.8%」的外部一致结论",
                  framework="prob3 口径：fvm.solve_case + 完成判据(max C<0.15)，"
                            "N=20, dt=1.0 s，唯一扰动量为 props 的 D 整体缩放",
                  air_source=os.path.basename(args.air), seed=0, reproducible=True,
                  base_check=base_check),
        rows=rows,
        conclusion=dict(
            D_plus10_delta_pct=up["delta_pct"],
            D_minus10_delta_pct=dn["delta_pct"],
            symmetry_gap_pct=round(sym, 4),
            note=asym_note,
        ),
    )
    out_path = os.path.join(_HERE, "d_sensitivity.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n→ {out_path}")
    print(f"结论：D+10% → t_dry {up['delta_pct']:+.2f}%；"
          f"D-10% → t_dry {dn['delta_pct']:+.2f}%。{asym_note}")
    print(f"总用时 {time.time() - t0_wall:.0f} s")


if __name__ == "__main__":
    main()
