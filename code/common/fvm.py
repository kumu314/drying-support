#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fvm.py —— 一维轴对称径向热/湿耦合问题的公共数值内核

从 `prob1/solve.py` 提炼（2026-09-11 ）。目标：一份代码通吃问题1/2/3/4。

与 prob1 原版的**唯一实质差异**
--------------------------------
原版把物性当 `PARAMS` 里的**标量常数**（rho=820/cp=2600/k=0.36），只在装配前取一次。
本版把物性改为**可注入的回调** `props(C, T_K) -> dict(rho, cp, k, D)`：

* 问题1 传 `props_app2`（返回常数组）→ 行为与重构前**逐位一致**
* 问题2/3 传 `props_app3`、问题4 传 `props_app4`（返回逐节点数组）→ 变物性

因此热方程的矩阵**每步重装**（原版只在循环外装一次）。常物性下重装得到的是
同一组浮点数，结果不变；变物性下这是必须的。

三个不能"简化"掉的坑
------------------------------------------
1. **xlsx 模板首行不含 t=0**：result1/2 从 1 起、result3/4 从 60 起 → `write_result_xlsx` 内跳过 `t<=0`
2. **CN 边界节点右端项含 `-A_R·h·T_N`**：漏掉会让表面温度**虚假偏高 ~22 °C**，
而网格/时间步收敛检验**仍显示正常** —— 只有守恒对账 + 解析解比对能抓到
3. **守恒必须用累积对账** `Σ|δE_num−δE_exp| / Σ|δE_exp|`，不能用单步相对误差
（t=0 处 T_air=T0 使分母趋零，会把浮点噪声放大成假异常）
"""

from __future__ import annotations

import math

import numpy as np

# ==========================================================================
# 常量（输出网格；表抽样列）
# ==========================================================================
OUT_CM = np.round(np.arange(0.0, 2.0 + 1e-9, 0.1), 10)          # 0,0.1,...,2.0 → 21 点
TAB_CM = [0.0, 0.5, 1.0, 1.5, 2.0]                              # 表1–表5 距离列


# ==========================================================================
# 线性代数 / 环境驱动 / 网格
# ==========================================================================
def thomas(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> np.ndarray:
    """三对角线性方程组求解（Thomas 追赶法）。

    a 下对角（a[0] 未用）、b 对角、c 上对角（c[-1] 未用）、d 右端。
    """
    n = b.size
    cp_ = np.empty(n)
    dp_ = np.empty(n)
    cp_[0] = c[0] / b[0]
    dp_[0] = d[0] / b[0]
    for i in range(1, n):
        m = b[i] - a[i] * cp_[i - 1]
        cp_[i] = (c[i] / m) if i < n - 1 else 0.0
        dp_[i] = (d[i] - a[i] * dp_[i - 1]) / m
    x = np.empty(n)
    x[-1] = dp_[-1]
    for i in range(n - 2, -1, -1):
        x[i] = dp_[i] - cp_[i] * x[i + 1]
    return x


def load_air_table(path: str):
    """读附件1：时间[s] / 温度[°C] / 水分浓度[kg/kg]。返回 (header, t, Ta, Ca)。"""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = [r for r in ws.iter_rows(values_only=True) if r and r[0] is not None]
    header = rows[0]
    body = rows[1:]
    t = np.array([float(r[0]) for r in body], dtype=float)
    Ta = np.array([float(r[1]) for r in body], dtype=float)
    Ca = np.array([float(r[2]) for r in body], dtype=float)
    idx = np.argsort(t)
    return header, t[idx], Ta[idx], Ca[idx]


class AirDriver:
    """烘房环境驱动量 T_air(t), C_air(t)：附件1 离散点上的**线性插值**。

    线性插值是最保守、最不可被质疑的选择（不引入样条过冲）。
    **超出数据范围时取端点值（不外推）** —— 这正是附件1 时序的末端处理口径：
    附件1 只到 14400 s，之后 T/C_air 恒定冻结在末值。
    """

    def __init__(self, t, Ta, Ca):
        self.t, self.Ta, self.Ca = t, Ta, Ca
        self.t_min, self.t_max = float(t[0]), float(t[-1])

    def __call__(self, tau: float):
        tt = min(max(tau, self.t_min), self.t_max)
        return float(np.interp(tt, self.t, self.Ta)), float(np.interp(tt, self.t, self.Ca))


class ConstDriver:
    """恒温阶段驱动（附件1 末段渐近值：50 °C / 0.05 kg/kg）。

    用法：`StagedDriver(air, t_switch, 50.0, 0.05)` —— t < t_switch 走附件1 插值，
    之后切常数。之所以写成独立类而不是改 AirDriver，是为了让"何时切"这件事
    在调用处显式可见（口径要能被看见，不能被埋进默认值）。
    """

    def __init__(self, T_air: float, C_air: float):
        self.T_air = float(T_air)
        self.C_air = float(C_air)

    def __call__(self, tau: float):
        return self.T_air, self.C_air


class StagedDriver:
    """分段驱动：t < t_switch 用 `first`，否则用 `second`。"""

    def __init__(self, first, t_switch: float, second):
        self.first, self.t_switch, self.second = first, float(t_switch), second

    def __call__(self, tau: float):
        return self.first(tau) if tau < self.t_switch else self.second(tau)


def make_grid(N: int, R: float):
    """柱坐标 FVM 网格：节点 r_i = i·dr (i=0..N)，两端半控制体。

    返回 (dr, r_nodes, A_face, A_R, V_cell)
      A_face[i] : 节点 i 与 i+1 之间内部面的面积（2πr_{i+1/2}）
      A_R       : 外表面（侧面）面积 2πR
      V_cell[i] : 节点 i 的控制体体积
    """
    dr = R / N
    r_nodes = np.arange(N + 1) * dr
    A_face = 2.0 * np.pi * (np.arange(N) + 0.5) * dr      # i = 0..N-1
    A_R = 2.0 * np.pi * R
    V = np.empty(N + 1)
    V[0] = np.pi * (0.5 * dr) ** 2
    V[1:N] = np.pi * 2.0 * np.arange(1, N) * dr ** 2
    V[N] = np.pi * (N ** 2 - (N - 0.5) ** 2) * dr ** 2
    return dr, r_nodes, A_face, A_R, V


# ==========================================================================
# 主求解器（常物性 / 变物性通用）
# ==========================================================================
def solve_case(N: int, dt: float, out_every: float, air, props, P,
               t_end=None, record_all: bool = False,
               max_picard: int = 30, tol_heat: float = 1.0e-8,
               tol_C: float = 1.0e-11, R_fn=None, stop_when=None):
    """跑一个算例。

    参数
    ----
    N          : 径向网格数（节点数 N+1）
    dt         : 时间步长 [s]
    out_every  : 每隔多少秒记录一次（必须是 dt 的整数倍）
    air        : 环境驱动，可调用 `air(tau) -> (T_air[°C], C_air[kg/kg])`
    props      : 物性回调 `props(C, T_K) -> dict(rho, cp, k, D)`（见 props.py）
    P          : 参数 dict，需含 R, h, hm, T0, C0, t_end
    R_fn       : 可选，`R_fn(t) -> 当前半径[m]`。**仅 prob4 用**；None 表示半径恒定。
                 注意：本函数按**空间坐标**求解，半径变化通过"外部逐段重启动"处理，
                 材料坐标（含对流项）的方案见 prob4/solve.py。
    stop_when  : 可选，`stop_when(t, T, C) -> bool`。一旦返回 True **立即停止**，
                 并把该时刻记为末态（prob2/3 的烘干完成判据、prob4 的消融都用它）。
                 **默认 None = 跑满 t_end，行为与抽取前基线逐位一致**
                 （`parity_check.py` 是这条的回归守卫；切勿在无回归的情况下改默认路径）。

    返回 dict：times / T / C / 守恒对账量 / picard_max / **t_final / stopped_early** 等。
    """
    t_end = P["t_end"] if t_end is None else t_end
    R = P["R"]
    dr, r, A_face, A_R, V = make_grid(N, R)
    n = N + 1

    T = np.full(n, P["T0"], dtype=float)
    C = np.full(n, P["C0"], dtype=float)

    nsteps = int(round(t_end / dt))
    out_stride = int(round(out_every / dt))
    if abs(out_stride * dt - out_every) > 1e-9:
        raise ValueError("out_every 必须是 dt 的整数倍")

    n_out = nsteps // out_stride
    times = np.empty(n_out + 1)
    T_hist = np.empty((n_out + 1, n))
    C_hist = np.empty((n_out + 1, n))
    times[0] = 0.0
    T_hist[0] = T
    C_hist[0] = C
    j_last = 0            # 最后一个**已写入**的历史槽位（提前停时用于截断）
    t_final = t_end
    stopped_early = False
    steps_done = 0

    # ---- 守恒对账累加器（口径见模块 docstring 坑 3）----
    def _energy(Tv, props_v):
        return float(np.sum(props_v["rho"] * props_v["cp"] * V * Tv))

    pr0 = props(C, T + 273.15)
    E0 = _energy(T, pr0)
    M0 = float(np.sum(V * C))
    Ta0, Ca0 = air(0.0)
    Q_prev = A_R * P["h"] * (Ta0 - T[N])
    Qm_prev = A_R * P["hm"] * (Ca0 - C[N])
    E_prev, M_prev = E0, M0
    cumE_defect = cumE_expect = 0.0
    cumM_defect = cumM_expect = 0.0
    # 方程级对账（**变物性下唯一严格的口径**）：
    #   Σ ρcp V ΔT  vs  ∫Q dt   —— 用该步 CN 方程的 LHS 物性，而非 (ρcp·T) 的差分。
    #   ρcp 随 C 变时，(ρcp T)_new − (ρcp T)_prev 里混进了 T·Δ(ρcp) 项（纯物性变化，
    #   不是能量不平衡），会把缺陷率抬高几个量级。常物性下 rc 恒定 → 两者恒等，
    #   故 prob1 基线与 parity_check 不受任何影响。
    cumE_eq_defect = cumE_eq_expect = 0.0
    stepE_max = stepE_scale = 0.0
    stepM_max = stepM_scale = 0.0
    k_picard_max = 0
    picard_sum = 0          # 外迭代平均次数统计（纯计数，不影响数值）
    picard_steps = 0

    for s in range(1, nsteps + 1):
        tn = s * dt
        tnm = tn - dt
        Ta_n, Ca_n = air(tnm)
        Ta_np, Ca_np = air(tn)

        # ---------------- Picard 迭代（热/湿块顺序，不扩大方程组）----------------
        T_k = T.copy()
        C_k = C.copy()
        T_new = T
        C_new = C
        n_pic = 0
        for it in range(max_picard):
            # 中点状态线性化：物性缓变时二阶精度，且恒物性下退化为原格式
            C_mid = 0.5 * (C + C_k)
            T_mid = 0.5 * (T + T_k)
            pr = props(C_mid, T_mid + 273.15)

            rc = pr["rho"] * pr["cp"]                      # 逐节点
            k_face = 0.5 * (pr["k"][0:N] + pr["k"][1:N + 1])
            beta = k_face * A_face / dr                    # i = 0..N-1

            # ---- 热：CN ----
            aH = np.zeros(n); bH = np.zeros(n); cH = np.zeros(n)
            bH[0] = rc[0] * V[0] / dt + 0.5 * beta[0]
            cH[0] = -0.5 * beta[0]
            for i in range(1, N):
                bH[i] = rc[i] * V[i] / dt + 0.5 * (beta[i - 1] + beta[i])
                aH[i] = -0.5 * beta[i - 1]
                cH[i] = -0.5 * beta[i]
            # ⚠️ 坑 2：边界右端项必须含 A_R*h*T_N，漏了表面温度虚高 ~22 °C
            bH[N] = rc[N] * V[N] / dt + 0.5 * A_R * P["h"] + 0.5 * beta[N - 1]
            aH[N] = -0.5 * beta[N - 1]

            rhs = rc * V / dt * T
            rhs[0] += 0.5 * beta[0] * (T[1] - T[0])
            rhs[1:N] += 0.5 * (beta[1:N] * (T[2:N + 1] - T[1:N])
                               - beta[0:N - 1] * (T[1:N] - T[0:N - 1]))
            rhs[N] += (0.5 * A_R * P["h"] * (Ta_n + Ta_np - T[N])
                       - 0.5 * beta[N - 1] * (T[N] - T[N - 1]))
            T_new = thomas(aH, bH, cH, rhs)

            # ---- 湿：CN ----
            D = pr["D"]
            Dface = 0.5 * (D[0:N] + D[1:N + 1])
            d_face = Dface * A_face / dr

            am = np.zeros(n); bmm = np.zeros(n); cm = np.zeros(n)
            bmm[0] = V[0] / dt + 0.5 * d_face[0]
            cm[0] = -0.5 * d_face[0]
            for i in range(1, N):
                bmm[i] = V[i] / dt + 0.5 * (d_face[i - 1] + d_face[i])
                am[i] = -0.5 * d_face[i - 1]
                cm[i] = -0.5 * d_face[i]
            bmm[N] = V[N] / dt + 0.5 * A_R * P["hm"] + 0.5 * d_face[N - 1]
            am[N] = -0.5 * d_face[N - 1]

            rhsm = V / dt * C
            rhsm[0] += 0.5 * d_face[0] * (C[1] - C[0])
            rhsm[1:N] += 0.5 * (d_face[1:N] * (C[2:N + 1] - C[1:N])
                                - d_face[0:N - 1] * (C[1:N] - C[0:N - 1]))
            rhsm[N] += (0.5 * A_R * P["hm"] * (Ca_n + Ca_np - C[N])
                        - 0.5 * d_face[N - 1] * (C[N] - C[N - 1]))
            C_new = thomas(am, bmm, cm, rhsm)

            n_pic = it + 1
            conv = (np.max(np.abs(T_new - T_k)) < tol_heat
                    and np.max(np.abs(C_new - C_k)) < tol_C)
            T_k, C_k = T_new, C_new
            if conv:
                break
        k_picard_max = max(k_picard_max, n_pic)
        picard_sum += n_pic
        picard_steps += 1

        # ---- 守恒对账（必须用与格式一致的梯形积分）----
        pr_new = props(C_new, T_new + 273.15)
        Q_now = A_R * P["h"] * (Ta_np - T_new[N])
        Qm_now = A_R * P["hm"] * (Ca_np - C_new[N])
        E_now = _energy(T_new, pr_new)
        M_now = float(np.sum(V * C_new))

        dE = E_now - E_prev
        dE_exp = 0.5 * dt * (Q_prev + Q_now)
        cumE_defect += abs(dE - dE_exp)
        cumE_expect += abs(dE_exp)
        stepE_max = max(stepE_max, abs(dE - dE_exp))
        stepE_scale = max(stepE_scale, abs(dE_exp))

        # 方程级（rc 取本轮 Picard 收敛时的物性，即 CN 方程真正用的系数）
        dE_eq = float(np.sum(rc * V * (T_new - T)))
        cumE_eq_defect += abs(dE_eq - dE_exp)
        cumE_eq_expect += abs(dE_exp)

        dM = M_now - M_prev
        dM_exp = 0.5 * dt * (Qm_prev + Qm_now)
        cumM_defect += abs(dM - dM_exp)
        cumM_expect += abs(dM_exp)
        stepM_max = max(stepM_max, abs(dM - dM_exp))
        stepM_scale = max(stepM_scale, abs(dM_exp))

        T, C = T_new, C_new
        E_prev, M_prev = E_now, M_now
        Q_prev, Qm_prev = Q_now, Qm_now

        steps_done = s
        if s % out_stride == 0:
            j = s // out_stride
            times[j] = tn
            T_hist[j] = T
            C_hist[j] = C
            j_last = j
        if stop_when is not None and stop_when(tn, T, C):
            stopped_early = True
            t_final = tn
            if s % out_stride != 0:
                # 停止时刻不落在记录点上 → 追加一帧末态，别丢最后的判据时刻
                times = np.append(times[:j_last + 1], tn)
                T_hist = np.vstack([T_hist[:j_last + 1], T])
                C_hist = np.vstack([C_hist[:j_last + 1], C])
                j_last += 1
            break

    if not record_all:
        keep = -1 if not stopped_early else j_last
        T_hist = T_hist[[0, keep]]
        C_hist = C_hist[[0, keep]]
        times = times[[0, keep]]
    else:
        # 提前停时预分配数组尾部是未赋值的垃圾，必须截断
        times = times[:j_last + 1]
        T_hist = T_hist[:j_last + 1]
        C_hist = C_hist[:j_last + 1]

    return dict(
        N=N, dt=dt, dr=dr, r=r, times=times, T=T_hist, C=C_hist,
        t_final=t_final, stopped_early=stopped_early, steps=steps_done,
        max_consE_rel=cumE_defect / max(cumE_expect, 1.0e-30),
        max_consM_rel=cumM_defect / max(cumM_expect, 1.0e-30),
        max_consE_eq_rel=cumE_eq_defect / max(cumE_eq_expect, 1.0e-30),
        cumE_eq_defect=cumE_eq_defect, cumE_eq_expect=cumE_eq_expect,
        stepE_rel=stepE_max / max(stepE_scale, 1.0e-30),
        stepM_rel=stepM_max / max(stepM_scale, 1.0e-30),
        E0=E0, E_end=E_prev, M0=M0, M_end=M_prev,
        cumE_defect=cumE_defect, cumE_expect=cumE_expect,
        cumM_defect=cumM_defect, cumM_expect=cumM_expect,
        picard_max=k_picard_max,
        picard_mean=(picard_sum / max(picard_steps, 1)),
    )


# ==========================================================================
# 验证件（V1 守恒 / V4 BDF 交叉 / V5 解析级数解）
# ==========================================================================
def verify_conservation(N=20, dt=0.05, air=None, props=None, P=None,
                        t_end=None):
    """V1：跑一小段做逐时间步累积对账。

    返回 `(energy_rel, moisture_rel, energy_eq_rel)`：
    · 前两个 = `Σ|Δ(ρcpV·T) − ∫Qdt| / Σ|∫Qdt|`（prob1 基线口径）
    · 第三个 = **方程级** `Σ|ΣρcpV·ΔT − ∫Qdt| / Σ|∫Qdt|`（变物性下唯一严格；
      常物性下与前两个中的 energy_rel **恒等**）
    """
    t_end = P["t_end"] if t_end is None else t_end
    res = solve_case(N, dt, out_every=dt * 100, air=air, props=props, P=P,
                     t_end=t_end, record_all=False)
    return (res["max_consE_rel"], res["max_consM_rel"], res["max_consE_eq_rel"])


def rhs_semi_discrete(T, C, tau, air, N, dr, r, A_face, A_R, V, P, props,
                      const_D=None):
    """FVM 半离散右端：返回 dT/dt, dC/dt（供 scipy 自适应积分使用）。

    与主求解器**共用同一空间离散**，但时间积分交给完全不同的算法，
    因此可交叉验证时间推进实现的正确性。
    """
    n = N + 1
    Ta, Ca = air(tau)
    pr = props(C, T + 273.15)
    rc = pr["rho"] * pr["cp"]
    k_face = 0.5 * (pr["k"][0:N] + pr["k"][1:N + 1])
    beta = k_face * A_face / dr

    L = np.empty(n)
    L[0] = beta[0] * (T[1] - T[0])
    L[1:N] = beta[1:N] * (T[2:N + 1] - T[1:N]) - beta[0:N - 1] * (T[1:N] - T[0:N - 1])
    L[N] = A_R * P["h"] * (Ta - T[N]) - beta[N - 1] * (T[N] - T[N - 1])
    dT = L / (rc * V)

    Dv = pr["D"] if const_D is None else np.full(n, float(const_D))
    Dface = 0.5 * (Dv[0:N] + Dv[1:N + 1])
    dm = Dface * A_face / dr
    Lm = np.empty(n)
    Lm[0] = dm[0] * (C[1] - C[0])
    Lm[1:N] = dm[1:N] * (C[2:N + 1] - C[1:N]) - dm[0:N - 1] * (C[1:N] - C[0:N - 1])
    Lm[N] = A_R * P["hm"] * (Ca - C[N]) - dm[N - 1] * (C[N] - C[N - 1])
    dC = Lm / V

    return np.concatenate([dT, dC])


def verify_scipy_bdf(N=20, t_end=None, air=None, P=None, props=None):
    """V4：用 scipy 的 BDF（自适应、变阶）积分同一半离散系统，与 CN 结果比对。"""
    from scipy.integrate import solve_ivp

    t_end = P["t_end"] if t_end is None else t_end
    dr, r, A_face, A_R, V = make_grid(N, P["R"])
    y0 = np.concatenate([np.full(N + 1, P["T0"]), np.full(N + 1, P["C0"])])

    def f(tau, y):
        return rhs_semi_discrete(y[:N + 1], y[N + 1:], tau, air, N, dr, r,
                                 A_face, A_R, V, P, props)

    sol = solve_ivp(f, (0.0, t_end), y0, method="BDF", rtol=1e-10, atol=1e-12,
                    dense_output=False, max_step=5.0)
    yend = sol.y[:, -1]
    return r, yend[:N + 1], yend[N + 1:], float(sol.t[-1]), bool(sol.success)


def analytic_cylinder_series(r, t, D, hm, C0, C_air, R, n_terms=60):
    """V5：无限圆柱常系数扩散问题的分离变量级数解。

    dC/dt = D·(1/r)·d/dr(r·dC/dr),  dC/dr|_r=0 = 0,  -D·dC/dr|_R = hm·(C_R - C_air)
    u = C - C_air 满足同一方程且边界齐次化后:
        u(r,t) = Σ_n A_n · J0(λ_n·r/R) · exp(-D·λ_n²·t/R²)
        λ_n : λ·J1(λ) = Bi·J0(λ),  Bi = hm·R/D
        A_n = 2·U0·J1(λ_n) / (λ_n·(J0(λ_n)² + J1(λ_n)²))
    """
    from scipy.special import j0, j1
    from scipy.optimize import brentq

    Bi = hm * R / D
    lam = []

    def f(x):
        return x * j1(x) - Bi * j0(x)

    x0 = 1.0e-6
    step = 0.05
    x = x0
    prev = f(x)
    while len(lam) < n_terms and x < 2000.0:
        x_next = x + step
        cur = f(x_next)
        if prev == 0.0 or prev * cur < 0:
            try:
                root = brentq(f, x, x_next, xtol=1e-14, rtol=1e-15)
                if root > 1e-8:
                    lam.append(root)
            except ValueError:
                pass
        x, prev = x_next, cur
    lam = np.array(lam[:n_terms])

    U0 = C0 - C_air
    An = 2.0 * U0 * j1(lam) / (lam * (j0(lam) ** 2 + j1(lam) ** 2))
    rr = np.asarray(r, dtype=float)
    Fo = D * t / R ** 2
    u = np.zeros_like(rr)
    for ln, an in zip(lam, An):
        u += an * j0(ln * rr / R) * math.exp(-ln ** 2 * Fo)
    return C_air + u, lam


# ==========================================================================
# 收敛性 / 物理合理性验证（V2 / V3 / V6）—— 原为 main 内联，抽取后独立成函数
# ==========================================================================
def verify_grid_convergence(air, props, P, Ns=(20, 40, 80), dt=0.2, t_end=None,
                            out_idx=(0, -1)):
    """V2：网格收敛。以最密网格为参考，报告各网格末态偏差与 2 阶斜率。

    ⚠️ 不同 N 的**节点个数与位置都不同**（N=20 → 21 点，N=80 → 81 点），
    直接写 `s["T"][-1] - ref["T"][-1]` 会广播失败（ValueError: shapes (21,) (81,)）。
    必须先把各网格解**插值到参考网格节点**上再比。
    """
    t_end = P["t_end"] if t_end is None else t_end
    sols = {}
    for N in Ns:
        res = solve_case(N, dt, out_every=dt, air=air, props=props, P=P,
                         t_end=t_end, record_all=True)
        sols[N] = res
    ref = sols[Ns[-1]]
    r_ref = ref["r"]
    rows = []
    for N in Ns:
        s = sols[N]
        T_on = np.interp(r_ref, s["r"], s["T"][-1])
        C_on = np.interp(r_ref, s["r"], s["C"][-1])
        rows.append(dict(
            N=N, dr_mm=P["R"] / N * 1000.0,
            # 三个代表位置统一用 r = 0 / R/2 / R 取值（插值到物理位置，跨网格可比）
            T=[float(np.interp(0.0, s["r"], s["T"][-1])),
               float(np.interp(P["R"] / 2.0, s["r"], s["T"][-1])),
               float(s["T"][-1][-1])],
            C=[float(np.interp(0.0, s["r"], s["C"][-1])),
               float(np.interp(P["R"] / 2.0, s["r"], s["C"][-1])),
               float(s["C"][-1][-1])],
            max_dT_vs_ref=float(np.max(np.abs(T_on - ref["T"][-1]))),
            max_dC_vs_ref=float(np.max(np.abs(C_on - ref["C"][-1]))),
        ))
    # 与最密网比对（单列别名，兼容旧报告字段名）
    for r_ in rows:
        r_["max_dT_vs_N80"] = r_["max_dT_vs_ref"]
        r_["max_dC_vs_N80"] = r_["max_dC_vs_ref"]
    return dict(rows=rows, ref_N=Ns[-1],
                T_fine_vs_coarse=rows[0]["max_dT_vs_ref"],
                C_fine_vs_coarse=rows[0]["max_dC_vs_ref"],
                passed=rows[0]["max_dT_vs_ref"] < 0.01 and rows[0]["max_dC_vs_ref"] < 0.01)


def verify_dt_convergence(air, props, P, dts=(0.2, 0.1, 0.05), N=20, t_end=None):
    """V3：时间步收敛。以最小步长为参考。"""
    t_end = P["t_end"] if t_end is None else t_end
    sols = {}
    for dt in dts:
        sols[dt] = solve_case(N, dt, out_every=dt, air=air, props=props, P=P,
                              t_end=t_end, record_all=True)
    ref = sols[dts[-1]]
    rows = []
    for dt in dts:
        s = sols[dt]
        rows.append(dict(
            dt=dt,
            T=[float(v) for v in s["T"][-1]],
            C=[float(v) for v in s["C"][-1]],
            max_dT_vs_min=float(np.max(np.abs(s["T"][-1] - ref["T"][-1]))),
            max_dC_vs_min=float(np.max(np.abs(s["C"][-1] - ref["C"][-1]))),
        ))
    for r_ in rows:
        r_["max_dT_vs_dt005"] = r_["max_dT_vs_min"]
        r_["max_dC_vs_dt005"] = r_["max_dC_vs_min"]
    return dict(rows=rows, ref_dt=dts[-1],
                T_coarse_vs_fine=rows[0]["max_dT_vs_min"],
                C_coarse_vs_fine=rows[0]["max_dC_vs_min"],
                passed=rows[0]["max_dT_vs_min"] < 0.01 and rows[0]["max_dC_vs_min"] < 0.01)


def verify_physics(times, r_cm, T_hist, C_hist, P, Ta_hist=None, Ca_hist=None):
    """V6：物理合理性 —— 最大值原理、外干内湿、水分单调。

    ⚠️ 判据必须是**时变边界下也成立**的不变量。附件1 的 T_air 先升到 50.165 °C
    再回落到 50 °C（实测段终点冻结），药温**必然**跟着先升后降，于是在 prob1（T_air 单调升）
    里成立的两条判据在 prob2 里必然假报错：
      · 「`T ≤ 末态最高温`」→ 历史最大值 > 末态值（差 ~0.1 °C）；
      · 「中心温度单调不降」→ 降温段中心温度是**降**的。
    故上界改用环境包络 `[min(T0,Ta_min), max(T0,Ta_max)]`（导热方程的最大值原理），
    并把单调性判据只保留在**水分**上（水分全程单调不增，无此问题）。
    """
    T0, C0 = P["T0"], P["C0"]
    T_end, C_end = T_hist[-1], C_hist[-1]
    Ta_hi = float(np.max(Ta_hist)) if Ta_hist is not None else float(T_end.max())
    Ta_lo = float(np.min(Ta_hist)) if Ta_hist is not None else T0
    Ca_lo = float(np.min(Ca_hist)) if Ca_hist is not None else 0.0

    center_colder = bool(np.all(T_end[0] <= T_end[-1] + 1e-9))   # 末态：外热内冷
    center_wetter = bool(np.all(C_end[0] >= C_end[-1] - 1e-9))   # 末态：外干内湿
    Cc = C_hist[:, 0]
    C_mono = bool(np.all(np.diff(Cc) <= 1e-12))                  # 中心水分单调不增
    T_lo_env, T_hi_env = min(T0, Ta_lo), max(T0, Ta_hi)
    T_bounds = bool(np.all(T_hist >= T_lo_env - 1e-9)
                    and np.all(T_hist <= T_hi_env + 1e-6))
    C_bounds = bool(np.all(C_hist <= C0 + 1e-9)
                    and np.all(C_hist >= Ca_lo - 1e-9))
    return dict(center_T_le_surface_end=center_colder,
                center_C_ge_surface_end=center_wetter,
                C_center_monotone=C_mono,
                T_bounds=T_bounds, C_bounds=C_bounds,
                T_env_envelope=[T_lo_env, T_hi_env],
                passed=all([center_colder, center_wetter, C_mono,
                            T_bounds, C_bounds]))


# ==========================================================================
# 输出
# ==========================================================================
def write_result_xlsx(path, times, r, T_hist, C_hist, out_cm=OUT_CM,
                      R_at=None, R_ref=None, sheets=("温度", "水分浓度"),
                      hists=None, fast: bool = False, last_col=None):
    """按附件3 模板写 resultN.xlsx。

    模板结构（实测附件3）：sheet「温度」「水分浓度」，A1 = '时间\\到药材中心的距离'，
    B.. 为距离(cm)，A2 起为时间(s)。**四个模板首行都不含 t=0**：
    result1/2 从 1 起（"每隔 1 s"），result3/4 从 60 起（"每隔 60 s"）。
    故本函数同样**不输出 t=0 行**，严格对齐模板。

    动边界支持（末列取当时半径的动态口径）
    ---------------------------
    `R_at` 给定时（长度 = times.size，每行当前半径[m]），解网格按 `r·(R_at[i]/R_ref)`
    缩放到该行的**物理半径**，再插值到固定 `out_cm` 网格。
    超过当前半径的格子写 **None（留空）**，绝不填数——填了就是把空气当药材。

    动态末列 `last_col`
    ------------------
    `last_col=(表头, 逐行取值)` 时，在固定网格之后**再追加一列**（长度须等于 times.size，
    与 times 逐行对齐，t<=0 的行不写）。用于收缩工况：固定网格只能到 r=1.9 cm，
    真正的表面在 r=R(t) 处并且**随时间内移**，模板里这一列的表头就叫「药材表面」。
    ⚠️ 注意不能靠"把末列表头改个名"来充当表面列 —— 固定网格上的 r=2.0 恒大于 R(t)，
    按留空规则整列都会是空的（这正是 result4.xlsx 曾经表面列全空的原因）。

    `fast=True` 走 openpyxl 的 **write_only 流式**模式（无样式、逐行 append）：
    prob2 的 20 万行 × 21 列 × 2 表在普通模式下需要几 GB 内存（每个 cell 都是
    一个 Python 对象），实测会 OOM；流式模式实测 ~70 s / ~47 MB 落盘。
    默认 False 保持 prob1 的样式化路径，**行为不变**。
    """
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    # ⚠️ `hists` 指定"每个 sheet 用哪张历史表"。默认 (T_hist, C_hist) 与旧行为完全一致。
    # 不加这个参数时，只想写一张表的调用方（result3/result4 是**水分单表**）会被
    # `zip(sheets, (T_hist, C_hist))` 截断，从而**把温度表写到水分 sheet 里**——
    # 这是个静默错误（文件能打开、数字也像，只是物理量错了）。
    _hists = (T_hist, C_hist) if hists is None else hists
    if len(_hists) != len(sheets):
        raise ValueError(f"sheets 与 hists 长度不一致：{len(sheets)} vs {len(_hists)}")

    # 动态末列：表头 + 逐行取值（与 times 逐行对齐）
    _lc_hdr, _lc_val = None, None
    if last_col is not None:
        _lc_hdr = str(last_col[0])
        _lc_val = np.asarray(last_col[1], dtype=float).ravel()
        if _lc_val.size != times.size:
            raise ValueError(
                f"last_col 取值长度 {_lc_val.size} 与 times 长度 {times.size} 不一致")

    if fast:
        wb = openpyxl.Workbook(write_only=True)
        for name, hist in zip(sheets, _hists):
            ws = wb.create_sheet(title=name)
            ws.append(["时间\\到药材中心的距离"]
                      + [float(round(d, 1)) for d in out_cm]
                      + ([_lc_hdr] if _lc_hdr else []))
            for i in range(times.size):
                t = float(times[i])
                if t <= 0:
                    continue
                vals = []
                if R_at is None:
                    assert r.size == out_cm.size, "网格节点数必须等于输出距离数"
                    vals = [float(round(hist[i, j], 4)) for j in range(out_cm.size)]
                else:
                    scale = float(R_at[i]) / float(R_ref)
                    r_row = np.asarray(r, dtype=float) * scale
                    R_cur = float(R_at[i])
                    for d in out_cm:
                        rp = float(d) * 0.01
                        if rp > R_cur + 1e-12:
                            vals.append(None)                 # ← 超界留空
                        else:
                            vals.append(float(round(
                                float(np.interp(rp, r_row, hist[i, :])), 4)))
                if _lc_val is not None:
                    v = _lc_val[i]
                    vals.append(None if not np.isfinite(v) else float(round(v, 4)))
                ws.append([int(round(t))] + vals)
        wb.save(path)
        return

    wb = openpyxl.Workbook()
    hdr_font = Font(bold=True)
    hdr_fill = PatternFill("solid", fgColor="DDEBF7")
    ctr = Alignment(horizontal="center", vertical="center")

    for si, (name, hist) in enumerate(zip(sheets, _hists)):
        ws = wb.active if si == 0 else wb.create_sheet(name)
        ws.title = name
        c = ws.cell(row=1, column=1, value="时间\\到药材中心的距离")
        c.font = hdr_font; c.fill = hdr_fill; c.alignment = ctr
        for j, d in enumerate(out_cm, start=2):
            c = ws.cell(row=1, column=j, value=float(round(d, 1)))
            c.font = hdr_font; c.fill = hdr_fill; c.alignment = ctr
        if _lc_hdr is not None:
            c = ws.cell(row=1, column=out_cm.size + 2, value=_lc_hdr)
            c.font = hdr_font; c.fill = hdr_fill; c.alignment = ctr

        row_out = 2
        for i in range(times.size):
            t = float(times[i])
            if t <= 0:
                continue                                   # 模板不含 t=0

            vals = []
            if R_at is None:
                assert r.size == out_cm.size, "网格节点数必须等于输出距离数"
                vals = [float(round(hist[i, j], 4)) for j in range(out_cm.size)]
            else:
                scale = float(R_at[i]) / float(R_ref)
                r_row = np.asarray(r, dtype=float) * scale      # 该行物理半径 [m]
                R_cur = float(R_at[i])
                for d in out_cm:
                    rp = float(d) * 0.01                        # cm -> m
                    if rp > R_cur + 1e-12:
                        vals.append(None)                       # ← 超界留空
                    else:
                        vals.append(float(round(
                            float(np.interp(rp, r_row, hist[i, :])), 4)))

            ws.cell(row=row_out, column=1, value=int(round(t)))
            for j, v in enumerate(vals):
                if v is not None:
                    ws.cell(row=row_out, column=2 + j, value=v)
            if _lc_val is not None:
                v = _lc_val[i]
                if np.isfinite(v):
                    ws.cell(row=row_out, column=out_cm.size + 2,
                            value=float(round(v, 4)))
            row_out += 1

        ws.column_dimensions["A"].width = 24
        _ncol = out_cm.size + (1 if _lc_hdr is not None else 0) + 2
        for j in range(2, _ncol):
            ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = 9
    wb.save(path)


def sample_table(times, hist, out_cm, tab_times, tab_cm=TAB_CM):
    """按给定时间/距离抽取表格值。"""
    out = {}
    for t in tab_times:
        i = int(np.argmin(np.abs(times - t)))
        row = {}
        for d in tab_cm:
            j = int(np.argmin(np.abs(out_cm - d)))
            row[f"{d:g}"] = float(round(hist[i, j], 4))
        out[f"{t:g}"] = row
    return out


def fmt_table(title, data, tab_times, tab_cm=TAB_CM):
    lines = [f"**{title}**", ""]
    lines.append("| 时间 | " + " | ".join(f"{d:g}" for d in tab_cm) + " |")
    lines.append("|" + "---|" * (len(tab_cm) + 1))
    for t in tab_times:
        key = f"{t:g}"
        if key not in data:
            continue
        row = data[key]
        lines.append(f"| {t:g} | " + " | ".join(f"{row[f'{d:g}']:.4f}" for d in tab_cm) + " |")
    return "\n".join(lines)
