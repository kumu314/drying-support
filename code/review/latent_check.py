# -*- coding: utf-8 -*-
"""
潜热误差量级估计（论文 5.2 节 H6 量化）——纯后处理，不求解。

原理：模型的传质边界 J = h_m (C_R - C_air) 是严格的，表面蒸发带走潜热
Q_lat = J * L_v；模型能量方程却把全部对流入热 Q_sens = h (T_air - T_R)
都当成显热计入。若计入潜热汇，进入药材的净显热将按 Q_lat 减少——
因此 E_lat / E_sens（全程累计之比）就是"忽略潜热"对升温速率影响的
上界估计。

口径：复用 param_sensitivity.py 导出的基准全程时程 base_profile.npz
（问题3 生产口径，56.4767 h）。L_v 取 2.40e6 J/kg（45~55 °C 水的
汽化潜热 2.39~2.38 MJ/kg，取整略保守）。

自检两道：
  1) 质量守恒：边界通量积分的蒸发量 M_flux 与域内水分存量下降
     M_inv = (C_mean(0) - C_mean(end)) * V 应一致（模型内恰为同一守恒律）；
  2) 能量对账：E_sens = A_s * ∫ q_sens dt 应与控温扫描 50 °C 点的
     energy_J 同量级（口径交叉核对）。

产出 review/latent_check.json，结论句可直接供论文 5.2 节引用。
"""
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

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))

H_CONV = 25.0        # 表面对流换热系数
H_MASS = 8.0e-7      # 传质系数
R = 0.02             # m
L = 0.25             # m
LV = 2.40e6          # J/kg，45~55 °C 汽化潜热取整
A_SIDE = 2.0 * np.pi * R * L        # 侧面积（一维模型的全部换热面）
V_CYL = np.pi * R * R * L           # 柱体积
T_SCAN_50C_ENERGY_J = 88152.60850560566   # probQ temp_scan 50 °C 点（口径交叉核对）


def main():
    d = np.load(os.path.join(_HERE, "base_profile.npz"))
    t = d["times"]                     # s
    C_s = d["C_surface"]               # kg/kg
    C_m = d["C_mean"]
    T_s = d["T_surface"]               # °C
    T_a = d["t_air"]
    C_a = d["c_air"]

    # 单位面积通量（W/m2）
    q_lat = H_MASS * (C_s - C_a) * LV
    q_sens = H_CONV * (T_a - T_s)

    # 负值保护（理论上 q_lat>=0；末段 C_s->C_air 时趋 0）
    q_lat = np.clip(q_lat, 0.0, None)

    # 时间积分（输出间隔 60 s，末格梯形）
    E_lat = float(np.trapezoid(q_lat, t))          # J/m2
    E_sens = float(np.trapezoid(q_sens, t))        # J/m2
    ratio_total = E_lat / E_sens

    # 强脱水段窗口（前 24 h，该段累计蒸发占全程的绝大部分）
    m24 = t <= 24 * 3600.0
    E_lat_24 = float(np.trapezoid(q_lat[m24], t[m24]))
    E_sens_24 = float(np.trapezoid(q_sens[m24], t[m24]))
    ratio_24 = E_lat_24 / E_sens_24

    # 通量比的稳健统计（仅在 q_sens 显著处统计，避免预热初期 0/0）
    m_sig = q_sens > 1.0                            # W/m2 以上
    ratio_t = np.where(m_sig, q_lat / np.maximum(q_sens, 1e-12), np.nan)
    ratio_peak = float(np.nanmax(ratio_t))
    ratio_mean = float(np.nanmean(ratio_t))

    # 自检 1：质量守恒
    M_flux = H_MASS * A_SIDE * float(np.trapezoid(C_s - C_a, t))   # kg
    M_inv = (float(C_m[0]) - float(C_m[-1])) * V_CYL               # kg
    mass_rel = abs(M_flux - M_inv) / M_inv

    # 自检 2：E_sens 与控温扫描 50 °C 点对账
    E_sens_abs = E_sens * A_SIDE
    scan_rel = abs(E_sens_abs - T_SCAN_50C_ENERGY_J) / T_SCAN_50C_ENERGY_J

    out = dict(
        meta=dict(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            purpose="论文 5.2 节 H6 量化：能量方程忽略蒸发潜热的误差上界",
            method="q_lat = h_m (C_R - C_air) L_v 与 q_sens = h (T_air - T_R) "
                   "的全程累计之比；时程来自基准算例（56.4767 h）",
            L_v_J_kg=LV,
            window_24h="前 24 h（强脱水段）",
        ),
        energy=dict(
            E_lat_J_m2=round(E_lat, 1),
            E_sens_J_m2=round(E_sens, 1),
            ratio_total_pct=round(ratio_total * 100.0, 3),
            ratio_24h_pct=round(ratio_24 * 100.0, 3),
            flux_ratio_mean_pct=round(ratio_mean * 100.0, 3),
            flux_ratio_peak_pct=round(ratio_peak * 100.0, 3),
        ),
        mass_check=dict(
            M_flux_kg=round(M_flux, 8),
            M_inv_kg=round(M_inv, 8),
            rel_diff_pct=round(mass_rel * 100.0, 4),
            passed=bool(mass_rel < 0.02),
        ),
        energy_crosscheck=dict(
            E_sens_abs_J=round(E_sens_abs, 1),
            temp_scan_50C_J=T_SCAN_50C_ENERGY_J,
            rel_diff_pct=round(scan_rel * 100.0, 3),
            note="扫描点与生产口径的 t_dry 略有差异（56.38 vs 56.48 h），"
                 "故只要求同量级（<5%）",
            passed=bool(scan_rel < 0.05),
        ),
        conclusion_zh=(
            "在题给传质系数（h_m = 8×10^-7 m/s）下，全程蒸发潜热累计仅为对流入热"
            "的 {rt:.2f}%（强脱水段前 24 h 为 {r24:.2f}%），显著通量处的时间平均比"
            " {rm:.2f}%、峰值 {rp:.2f}%。即：若在能量方程计入潜热汇，进入药材的"
            "净显热至多减少约 {rt:.1f}%，升温速率的被高估量不超过同一量级，"
            "不改变任何主结论的定性判断。").format(
                rt=ratio_total * 100.0, r24=ratio_24 * 100.0,
                rm=ratio_mean * 100.0, rp=ratio_peak * 100.0),
    )
    out_path = os.path.join(_HERE, "latent_check.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("→", out_path)
    print(out["conclusion_zh"])
    print("mass_check:", out["mass_check"])
    print("energy_crosscheck:", out["energy_crosscheck"])
    if not out["mass_check"]["passed"]:
        print("!! 质量守恒自检未过（>2%），结果不可信，须排查")
        sys.exit(1)


if __name__ == "__main__":
    main()
