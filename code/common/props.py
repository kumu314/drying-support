#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
props.py —— 物性函数族（附录 2 / 附录 3 / 附录 4 的机器可读镜像）

公式来源：题目附录2/3/4。改公式即改口径，须同步核对全部子问题。

设计约定
--------
所有物性函数统一签名 `f(C, T_K) -> dict(rho, cp, k, D)`，其中

* `C`   : 逐节点干基含水率 [kg/kg]，shape (N+1,) 或标量
* `T_K` : 逐节点温度 [K]（**注意是开尔文**，附录3/4 的 D 公式用 K），同形
* 返回  : 四个**同形数组**（标量输入也返回数组，便于统一调用）

为什么统一成"数组进、数组出"：问题1 是常物性（标量），问题2/3/4 是变物性（逐节点）。
统一形状后，`fvm.solve_case` 一份代码通吃，不必为常/变物性写两套装配。

⚠️ 两个易错点（已在代码里防守，勿"简化"掉）
------------------------------------------------
1. **附录3/4 的 D 是双指数，且 T 用开尔文**：
   `D = A · exp(-b/C) · exp(-3850/T)`。漏掉 `exp(-3850/T)` 会**错两个量级**。
2. **`exp(-b/C)` 的 C 在分母**：C → 0 时该因子 → 0（物理上"越干扩散越慢"，即表面硬化的数学体现）。
   为防 C 恰好为 0 时除零，统一取 `C_safe = max(C, 1e-12)`。
"""

from __future__ import annotations

import numpy as np
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

# ==========================================================================
# 附录 2 —— 问题1（常物性）
# ==========================================================================
APP2 = dict(
    rho=820.0,     # 密度 [kg/m^3]
    cp=2600.0,     # 比热容 [J/(kg·K)]
    k=0.36,        # 热传导系数 [W/(m·K)]
    D0=7.0e-9,     # D 前因子 [m^2/s]
    Da=0.89,       # D = D0 · exp(-Da/C)
)

# ==========================================================================
# 附录 3 —— 问题2 / 问题3（变物性）
#   rho = 650 + 128C
#   cp  = 1450 + 2736·C/(C+1)
#   k   = 0.21 + 0.38·C/(C+1)
#   D   = 2.4e-3 · exp(-0.45/C) · exp(-3850/T)     [T 单位 K]
# ==========================================================================
APP3 = dict(
    rho_a=650.0, rho_b=128.0,
    cp_a=1450.0, cp_b=2736.0,
    k_a=0.21, k_b=0.38,
    D_A=2.4e-3, D_b=0.45, D_E=3850.0,
)

# ==========================================================================
# 附录 4 —— 问题4（变物性，材质与附录3 不同）
#   rho = 760 + 90C
#   cp  = 1850 + 2150·C/(C+1)
#   k   = 0.12 + 0.20·C/(C+1)
#   D   = 4.2e-4 · exp(-0.30/C) · exp(-3850/T)     [T 单位 K]
# ==========================================================================
APP4 = dict(
    rho_a=760.0, rho_b=90.0,
    cp_a=1850.0, cp_b=2150.0,
    k_a=0.12, k_b=0.20,
    D_A=4.2e-4, D_b=0.30, D_E=3850.0,
)

_C_FLOOR = 1.0e-12


def _as_arrays(C, T_K):
    C = np.asarray(C, dtype=float)
    T = np.asarray(T_K, dtype=float)
    return C, T, np.maximum(C, _C_FLOOR)


def props_app2(C, T_K):
    """附录2 常物性。D 仍随 C 变（附录2 的 D 公式就是 C 的函数）。"""
    C, T, Cs = _as_arrays(C, T_K)
    with np.errstate(under="ignore"):
        D = APP2["D0"] * np.exp(-APP2["Da"] / Cs)
    return dict(
        rho=np.full_like(C, APP2["rho"]),
        cp=np.full_like(C, APP2["cp"]),
        k=np.full_like(C, APP2["k"]),
        D=D,
    )


def _props_variable(C, T_K, A):
    """附录3/4 公用的变物性装配（区别只在系数 A）。"""
    C, T, Cs = _as_arrays(C, T_K)
    frac = C / (C + 1.0)
    with np.errstate(under="ignore"):
        # 双指数：漏掉 exp(-3850/T) 会错两个量级
        D = A["D_A"] * np.exp(-A["D_b"] / Cs) * np.exp(-A["D_E"] / T)
    return dict(
        rho=A["rho_a"] + A["rho_b"] * C,
        cp=A["cp_a"] + A["cp_b"] * frac,
        k=A["k_a"] + A["k_b"] * frac,
        D=D,
    )


def props_app3(C, T_K):
    """附录3 变物性（问题2/3）。"""
    return _props_variable(C, T_K, APP3)


def props_app4(C, T_K):
    """附录4 变物性（问题4，材质不同）。"""
    return _props_variable(C, T_K, APP4)


PROPS = {
    "app2": props_app2,
    "app3": props_app3,
    "app4": props_app4,
}


# ==========================================================================
# 量级自检工具 —— 开跑前打印，确认没写错公式（附 README 教训：收敛性检验
# 不能替代量级检查）
# ==========================================================================
def sanity_table(C_list=(2.55, 1.0, 0.15), T_C=50.0):
    """在给定含水率/温度下打印三套物性，供人工核对量级。"""
    T_K = T_C + 273.15
    rows = []
    for C in C_list:
        r = {"C": C, "T_C": T_C}
        for name, f in PROPS.items():
            p = f(np.array([C]), np.array([T_K]))
            r[f"{name}:rho"] = float(p["rho"][0])
            r[f"{name}:cp"] = float(p["cp"][0])
            r[f"{name}:k"] = float(p["k"][0])
            r[f"{name}:D"] = float(p["D"][0])
        rows.append(r)
    return rows


if __name__ == "__main__":
    hdr = ["C", "T_C"]
    for name in PROPS:
        hdr += [f"{name}:rho", f"{name}:cp", f"{name}:k", f"{name}:D"]
    print("\t".join(hdr))
    for r in sanity_table():
        print("\t".join(f"{r[h]:.6g}" for h in hdr))
