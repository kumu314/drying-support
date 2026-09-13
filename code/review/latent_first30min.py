# -*- coding: utf-8 -*-
"""
潜热对问题一预热段（0-1800 s）影响的一阶估计 —— 纯后处理，不求解。

背景：外部讨论聚焦「第一问前期（前半小时）潜热影响是否显著」。
本文按 latent_check.py 同一口径（base_profile.npz，问题3 生产时程）
取前 1800 s 分窗，给出两个层次的数：
  1) 占比层：E_lat / E_sens（前 30 min）——注意预热初期 T_air≈T_s
     时 q_sens 分母趋零，占比峰值高是分母效应，不等于绝对影响大；
  2) 绝对层：若计入潜热汇，问题一 1800 s 末药材整体温升的高估量
     ΔT1 ≈ E_lat(0-1800s) / (rho·cp·V/A)。取附2 常物性
     rho=820 kg/m3, cp=2600 J/(kg·K)；V/A = R/2 = 0.01 m（一维径向的
     单位面积对应热容层）。另按问题二变物性（rho=650+128C,
     cp=1450+2736C/(C+1)）在 C∈[1.5,2.55] 范围给出区间。

口径与铁规：模型层面不引入潜热（H6）；本估计为求解后的能量账本
核对，供论文 5.2 节与答辩问答引用。

产出 review/latent_first30min.json。
"""
import json
import os
from datetime import datetime

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))

H_CONV = 25.0        # 对流换热系数（h = 25 W/(m^2·K)）
H_MASS = 8.0e-7      # 传质系数
R = 0.02             # m
L = 0.25             # m
LV = 2.40e6          # J/kg
A_SIDE = 2.0 * np.pi * R * L
V_CYL = np.pi * R * R * L
RHO2_CP_CONST = 820.0 * 2600.0      # 附2 常物性体积热容 J/(m3·K)


def main():
    d = np.load(os.path.join(_HERE, "base_profile.npz"))
    t = d["times"]
    C_s = d["C_surface"]
    T_s = d["T_surface"]
    T_a = d["t_air"]
    C_a = d["c_air"]

    q_lat = np.clip(H_MASS * (C_s - C_a) * LV, 0.0, None)
    q_sens = H_CONV * (T_a - T_s)

    # 问题一窗口：0-1800 s（预热段；驱动仍在按附件1 升温）
    m = t <= 1800.0
    tw, ql, qs = t[m], q_lat[m], q_sens[m]
    E_lat = float(np.trapezoid(ql, tw))            # J/m2
    E_sens = float(np.trapezoid(qs, tw))
    ratio = 100.0 * E_lat / E_sens if E_sens > 0 else float("nan")

    # 窗口内的瞬时占比峰值（分母效应的实证）
    with np.errstate(divide="ignore", invalid="ignore"):
        inst = np.where(qs > 1e-9, 100.0 * ql / qs, np.nan)
    peak = float(np.nanmax(inst)) if np.any(np.isfinite(inst)) else float("nan")
    peak_t = float(tw[np.nanargmax(inst)]) if np.any(np.isfinite(inst)) else float("nan")

    # 绝对温升高估（问题一口径：附2 常物性，单位面积热容层 V/A=R/2）
    vol_per_area = R / 2.0                          # m
    dT1_const = E_lat / (RHO2_CP_CONST * vol_per_area)
    # 变物性区间（附3，C 取 1800 s 内表面-平均范围的代表区间）
    dts = []
    for c_rep in (2.55, 2.0, 1.5):
        rho = 650.0 + 128.0 * c_rep
        cp = 1450.0 + 2736.0 * c_rep / (c_rep + 1.0)
        dts.append(dT1_const * RHO2_CP_CONST / (rho * cp))
    dT1_var = (min(dts), max(dts))

    # 一阶修正后的问题一中心温度读数（仅量级示意，非重解）
    out = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "purpose": "回应「第一问前 30 min 潜热影响」之争：占比层 + 绝对层",
            "source": "base_profile.npz 前 1800 s 窗（问题3 生产口径）",
            "constants": dict(h=H_CONV, h_m=H_MASS, L_v=LV,
                              rho_cp_const=RHO2_CP_CONST, vol_per_area=vol_per_area),
        },
        "window_1800s": {
            "E_lat_J_m2": round(E_lat, 1),
            "E_sens_J_m2": round(E_sens, 1),
            "ratio_pct": round(ratio, 2),
            "flux_ratio_peak_pct": round(peak, 1),
            "flux_ratio_peak_at_s": peak_t,
        },
        "absolute_dT_overestimate_C": {
            "formula": "E_lat / (rho*cp*(R/2))，一阶集中热容估计",
            "const_props": round(float(dT1_const), 3),
            "var_props_range": [round(dT1_var[0], 3), round(dT1_var[1], 3)],
            "note": "问题一整体升温约 5.6~8.8 °C；此为上界式估计（假设潜热汇全部"
                    "作用于整体热容，未计入径向梯度集中表面效应——真实表面局部"
                    "温降更大、中心影响更小）",
        },
        "conclusion_zh": (
            "前 30 min 潜热/对流入热占比峰值 {:.0f}%（出现在 t≈{:.0f} s、"
            "T_air≈T_s 使对流入热分母趋零之时，属分母效应）；同窗累计占比 "
            "{:.1f}%。折算绝对量级：即使计入潜热，1800 s 末药材温升的高估"
            "至多约 {:.2f} °C（常物性上界），相对问题一 ~6-9 °C 的升温为 "
            "个位数百分比——「占比高」与「影响大」不是一回事，绝对温升才是"
            "判据。模型不引入潜热（H6），量级上界 8.72% 见 latent_check。"
        ).format(peak, peak_t, ratio, float(dT1_const)),
    }
    with open(os.path.join(_HERE, "latent_first30min.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(out["conclusion_zh"])
    print("window_1800s:", json.dumps(out["window_1800s"], ensure_ascii=False))
    print("dT_const =", round(float(dT1_const), 3), "°C")


if __name__ == "__main__":
    main()
