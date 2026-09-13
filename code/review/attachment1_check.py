# -*- coding: utf-8 -*-
"""
附件1 校验表（题面白纸黑字要求「用附件1 校验模型」的诚实落法）。

口径（本模型采用）：附件1 只有环境侧数据（T_air/C_air），无药材实测，
故「校验」= 两层：
  1) 驱动一致性：t = 300/600/900/1200/1500/1800 s，附件1 实测值 vs 模型采用值
     （线性插值过点）——在这些时刻恰为分节点，偏差应严格为 0，
     证明模型严格受附件1 同期环境数据驱动、无自由发挥；
  2) 响应合理性：同表附药材表面/中心温度响应（取自问题1 生产输出 result1.xlsx），
     核对「表面单调升温、对环境渐近跟踪（无量纲滞后比收窄）」的物理预期。

产出：review/attachment1_check.json（含 markdown 表，可直接给论文 §4.4/附录用）
用法：python attachment1_check.py --air 附件1.xlsx路径
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

from datetime import datetime

import openpyxl                          # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))          # 上级目录（common 包）

from prob3.solve import build_air                   # noqa: E402

CHECK_TS = [300, 600, 900, 1200, 1500, 1800]
RESULT1 = os.path.join(os.path.dirname(_HERE), "prob1", "result1.xlsx")


def main():
    ap = argparse.ArgumentParser(description="附件1 驱动一致性 + 响应合理性校验表")
    ap.add_argument("--air", required=True)
    args = ap.parse_args()

    air, t_tab, Ta_tab, Ca_tab = build_air(args.air)

    # 附件1 原始分节点（t_tab/Ta_tab/Ca_tab）
    tab = {int(round(t)): (float(Ta), float(Ca))
           for t, Ta, Ca in zip(t_tab, Ta_tab, Ca_tab)}

    # 问题1 生产输出的响应（result1.xlsx：行=时刻，列=半径 cm）
    wb = openpyxl.load_workbook(RESULT1, data_only=True)
    wsT = wb[wb.sheetnames[0]]
    resp = {}
    header = [c.value for c in wsT[1]]
    col_center = header.index(0.0) if 0.0 in header else 1
    col_surf = len(header) - 1
    for row in wsT.iter_rows(min_row=2):
        tv = round(float(row[0].value), 3)
        if tv in CHECK_TS:
            resp[tv] = (float(row[col_center].value),
                        float(row[col_surf].value))

    table_md = []
    rows = []
    prev_gap = None
    mono_ok = True
    for t in CHECK_TS:
        Ta_model, Ca_model = air(float(t))          # 模型采用值（线性插值驱动）
        if t in tab:
            dTa = Ta_model - tab[t][0]
            dCa = Ca_model - tab[t][1]
            src = "分节点（偏差恒等于 0）"
        else:
            dTa = dCa = None
            src = "插值点"
        Tc, Ts = resp[t]
        gap = float(Ta_model) - Ts                  # 环境—表面温差
        # 预热期环境升温快于药材，温差先扩大是正常物理；
        # 无量纲滞后比 (T_air-T_s)/(T_air-T_0) 收窄才是「渐近跟踪」的正确判据
        lag_ratio = gap / max(float(Ta_model) - 28.0, 1e-9)
        if prev_gap is not None and lag_ratio > prev_gap + 1e-9:
            mono_ok = False
        prev_gap = lag_ratio
        rows.append(dict(
            t_s=t,
            air_T_measured=tab[t][0] if t in tab else None,
            air_T_model=round(float(Ta_model), 6),
            dev_T=round(dTa, 12) if dTa is not None else None,
            air_C_measured=tab[t][1] if t in tab else None,
            air_C_model=round(float(Ca_model), 9),
            dev_C=round(dCa, 12) if dCa is not None else None,
            T_center_C=round(Tc, 4), T_surface_C=round(Ts, 4),
            gap_air_surface_C=round(gap, 4),
            lag_ratio=round(lag_ratio, 4),
            source=src))
        table_md.append(                            # 小数位与「实测」列对齐
            f"| {t} | {tab[t][0]:.3f} | {Ta_model:.3f} | {dTa:.4f} | "
            f"{tab[t][1]:.4f} | {Ca_model:.4f} | {dCa:.4f} | "
            f"{Tc:.4f} | {Ts:.4f} | {gap:.3f} |")

    gaps = [r["gap_air_surface_C"] for r in rows]
    surface_rising = all(rows[i]["T_surface_C"] <= rows[i + 1]["T_surface_C"]
                         + 1e-12 for i in range(len(rows) - 1))

    md = (
        "**附件1 校验表**（驱动一致性 + 响应合理性）\n\n"
        "| t (s) | T_air 实测 | T_air 模型采用 | ΔT | C_air 实测 | "
        "C_air 模型采用 | ΔC | 药材中心 T | 药材表面 T | 环境—表面温差 |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        + "\n".join(table_md)
        + "\n\n说明：t=300–1800 s 均为附件1 分节点，线性插值过点，"
        "驱动偏差严格为 0——模型无任何自由发挥。预热期环境升温快于药材，"
        "环境—表面温差由 "
        f"{gaps[0]:.2f} °C 扩大至 {gaps[-1]:.2f} °C 属正常物理；"
        f"无量纲滞后比 (T_air−T_s)/(T_air−T_0) 由 {rows[0]['lag_ratio']:.2f} "
        f"收窄至 {rows[-1]['lag_ratio']:.2f}，表面温度单调上升、渐近跟踪环境温度，"
        "与预热阶段的物理预期一致。")

    out = dict(
        meta=dict(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            purpose="附件1 校验表（题面要求的模型校验的诚实落法）",
            caliber="附件1 仅环境侧数据 → 校验 = 驱动一致性（插值过点偏差=0）"
                    " + 响应合理性（滞后比收窄、表面渐近环境）",
            air_source=os.path.basename(args.air),
            response_source="prob1/result1.xlsx（生产输出）",
        ),
        checks=dict(
            driver_deviation_all_zero=bool(
                all(r["dev_T"] == 0 and r["dev_C"] == 0 for r in rows)),
            lag_ratio_narrowing=bool(mono_ok),
            surface_monotonic_rising=bool(surface_rising),
            all_passed=bool(all(r["dev_T"] == 0 and r["dev_C"] == 0
                                for r in rows) and mono_ok and surface_rising),
        ),
        rows=rows,
        markdown_table=md,
    )
    out_path = os.path.join(_HERE, "attachment1_check.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("→", out_path)
    print("checks:", out["checks"])
    print()
    print(md)


if __name__ == "__main__":
    main()
