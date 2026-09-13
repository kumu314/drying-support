# -*- coding: utf-8 -*-
"""
C-2 出图工具：fig_p2_* / fig_p3_* / fig_p4_*

数据来源（全部为磁盘上已产出的真实结果，不重算、不编造）：
  - prob2/result2.xlsx   问题2 全场时序（每 1 s，抽稀取每 60 s）
  - prob3/result3.xlsx   问题3 烘干过程（每 60 s）
  - prob4/result4.xlsx   问题4 动边界（每 60 s，超界留空）
  - 附件2.xlsx                           半径收缩曲线 R(t)

图名严格遵守 fig_p<N>_<内容>.png 的前缀纪律。

题注（caption）**不由本脚本写回** —— 题注的唯一权威源是
`tools/make_results.py` 的 `FIGURES`（它用 {t3}/{t4} 变量标记从各问碎片现场取值，
与 results.json 的数值同源）。`--update-results` 保留为「出图完成后给出提示」，
不再改动 results.json，避免两个写入方互相覆盖导致正文题注漂移。
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


import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 110

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
FIGS = os.path.join(os.path.dirname(PKG), "figs")   # 图目录与源码目录同级
CACHE = os.path.join(PKG, "review", "p2_traj_cache.npz")

C_DRY = 0.15          # 烘干完成判据阈值（kg/kg，干基）
C0 = 2.55             # 初始水分浓度
T0 = 28.0             # 初始温度

# ----------------------------------------------------------------------------
# 读取
# ----------------------------------------------------------------------------
def read_xlsx_sheet(path, sheet=0, stride=1, verbose=True):
    """读一个工作表：第 1 行为表头（第 1 格是角标），第 1 列为时间。"""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[sheet] if isinstance(sheet, int) else wb[sheet]
    it = ws.iter_rows(values_only=True)
    hdr = list(next(it))
    nr = len(hdr) - 1
    ts, data = [], []
    for i, row in enumerate(it):
        if row is None or row[0] is None:
            break
        if i % stride:
            continue
        ts.append(float(row[0]))
        data.append([np.nan if v is None else float(v) for v in row[1:1 + nr]])
    wb.close()
    if verbose:
        print(f"  读取 {os.path.basename(path)}[{ws.title}] -> {len(ts)} 行 x {nr} 列",
              file=sys.stderr)
    return hdr[1:], np.asarray(ts, float), np.asarray(data, float)


# P2 三张图画的是 0–56 h 全程（含 t_dry 判据点）。现存的 result2.xlsx
# 按最终口径只出前 3 h —— 若拿它出图，图能画出来、看着也正常，
# 但相态/演化结论全是错的。所以宁可报错退出，绝不静默退化。
P2_MIN_HOURS = 40.0

_HOWTO = (
    "  先跑一次全程求解（写出可复用的 npz 缓存，约 6 分钟）：\n"
    "    python prob2/solve.py --air 附件1.xlsx"
    " --cache review/p2_traj_cache.npz\n"
    "  或把全程版 result2.xlsx 放回 prob2/ 后重跑本脚本。"
)


def _check_p2_span(t, src):
    """时长守卫：不足 40 h 直接退出，禁止静默出退化图。"""
    if t is None or np.asarray(t).size == 0:
        sys.exit("\n[make_figs] P2 数据为空：%s\n  %s" % (src, _HOWTO))
    t = np.asarray(t, float)
    span_h = float(t[-1] - t[0]) / 3600.0
    if span_h < P2_MIN_HOURS:
        sys.exit(
            "\n[make_figs] P2 数据时长不足：%.2f h < %.0f h（来源：%s）\n"
            "  result2.xlsx 现按约定口径只出前 3 h，不足以画全程图。\n"
            "  请先生成全程数据：\n%s\n" % (span_h, P2_MIN_HOURS, src, _HOWTO))
    print("  P2 数据时长守卫通过：%.2f h（来源：%s）" % (span_h, os.path.basename(str(src))),
          file=sys.stderr)
    return span_h


def load_p2(stride=60):
    """问题2 的温度/水分时序（带缓存，避免重复解析 25 MB xlsx）。

    缓存兼容两种来源（键名不同，勿混）：
      A. 本脚本自己存过的出图缓存：cols / t / T / C（已按 stride 抽稀）
      B. prob2/solve.py --cache 写的主求解缓存：times / T / C / r（全量，需抽稀）
    B 是推荐路径：result2.xlsx 现在只出 3 h，只有 npz 才有全程数据。
    """
    p = os.path.join(PKG, "prob2", "result2.xlsx")
    if os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        keys = set(z.files)
        if {"cols", "t", "T", "C"} <= keys:
            print("  命中出图缓存 p2_traj_cache.npz", file=sys.stderr)
            cols, t, T, C = list(z["cols"]), z["t"], z["T"], z["C"]
            _check_p2_span(t, CACHE)
            return cols, t, T, C
        if {"times", "T", "C", "r"} <= keys:
            print("  命中主求解缓存 p2_traj_cache.npz（全量，按 %d 步抽稀）" % stride,
                  file=sys.stderr)
            # 求解器内部用 SI（m），出图口径与 result2.xlsx 表头一致用 cm
            cols = ["%g" % (x * 100.0) for x in np.asarray(z["r"], float)]
            t = np.asarray(z["times"], float)[::stride]
            T = np.asarray(z["T"], float)[::stride]
            C = np.asarray(z["C"], float)[::stride]
            _check_p2_span(t, CACHE)
            return cols, t, T, C
        sys.exit("\n[make_figs] 无法识别的缓存格式 %s：键为 %s\n"
                 "  期望 A(cols/t/T/C) 或 B(times/T/C/r)。删掉该文件后重跑即可。\n"
                 % (CACHE, sorted(keys)))
    print("  解析 result2.xlsx（25 MB，约需数分钟，仅首次）...", file=sys.stderr)
    cols, t1, T = read_xlsx_sheet(p, 0, stride)
    # 先查时长再读第二个表，免得白等几分钟才报错
    _check_p2_span(t1, p)
    try:
        _, t2, C = read_xlsx_sheet(p, 1, stride)
    except IndexError:
        sys.exit("\n[make_figs] %s 只有 1 个工作表，缺水分场（应为温度+水分两表）。\n  %s"
                 % (p, _HOWTO))
    n = min(len(t1), len(t2))
    t, T, C = t1[:n], T[:n], C[:n]
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    np.savez(CACHE, cols=np.asarray(cols, dtype=object), t=t, T=T, C=C)
    return cols, t, T, C


# ----------------------------------------------------------------------------
# 图 P2
# ----------------------------------------------------------------------------
def fig_p2_evolution(cols, t, T, C, air=None):
    """问题2：温度场与水分场的时空演化（2x2）。

    air = (t_s, T_air) 附件1 实测热风温度；0–14400 s 按实测升温，之后恒为 50 °C（恒温段风温、实测段终点）。
    """
    th = t / 3600.0
    r = np.asarray([float(c) for c in cols], float)      # cm
    tend = th[-1]

    fig, ax = plt.subplots(2, 2, figsize=(12.5, 8.6))

    # (a) 温度径向剖面（升温阶段）
    axa = ax[0, 0]
    for tt, ls in [(0.25, "-"), (0.5, "-"), (1.0, "-"), (2.0, "-"), (3.0, "-"), (6.0, "-")]:
        k = int(np.argmin(np.abs(th - tt)))
        axa.plot(r, T[k], lw=1.6, label=f"{th[k]:.2f} h")
    axa.set_xlabel("到药材中心的距离 r (cm)")
    axa.set_ylabel("温度 T (°C)")
    axa.set_title("(a) 温度径向剖面（升温阶段）")
    axa.grid(alpha=.3); axa.legend(fontsize=8, ncol=2)

    # (b) 水分径向剖面（全时程）
    axb = ax[0, 1]
    for tt in [1.0, 6.0, 12.0, 24.0, 36.0, 48.0, tend]:
        k = int(np.argmin(np.abs(th - tt)))
        axb.plot(r, C[k], lw=1.6, label=f"{th[k]:.2f} h")
    axb.axhline(C_DRY, color="crimson", ls="--", lw=1.2, label="判据 0.15 kg/kg")
    axb.set_xlabel("到药材中心的距离 r (cm)")
    axb.set_ylabel("水分浓度 C (kg/kg)")
    axb.set_title("(b) 水分浓度径向剖面（全时程）")
    axb.grid(alpha=.3); axb.legend(fontsize=8, ncol=2)

    # (c) 中心/表面温度时程
    axc = ax[1, 0]
    m = th <= 6.0
    if air is not None:
        ta_s, ta_T = air
        ta_h = ta_s / 3600.0
        axc.plot(ta_h, ta_T, lw=2.0, color="crimson", label="烘房热风温度（附件1）")
        axc.plot([ta_h[-1], 6.0], [50.0, 50.0],
                 lw=2.0, color="crimson", ls=":")
    axc.plot(th[m], T[m, 0], lw=1.8, label="中心 r=0")
    axc.plot(th[m], T[m, -1], lw=1.8, label="表面 r=2 cm")
    axc.set_xlabel("时间 t (h)")
    axc.set_ylabel("温度 T (°C)")
    axc.set_title("(c) 中心、表面与热风温度时程（前 6 h）")
    axc.grid(alpha=.3); axc.legend(fontsize=8)

    # (d) 中心/表面水分时程（全时程 + 判据）
    axd = ax[1, 1]
    axd.plot(th, C[:, 0], lw=1.8, label="中心 r=0")
    axd.plot(th, C[:, -1], lw=1.8, label="表面 r=2 cm")
    axd.axhline(C_DRY, color="crimson", ls="--", lw=1.3, label="判据阈值 0.15 kg/kg")
    axd.axvline(tend, color="navy", ls=":", lw=1.3,
                label=f"判停 t={tend:.2f} h")
    axd.set_xlabel("时间 t (h)")
    axd.set_ylabel("水分浓度 C (kg/kg)")
    axd.set_title("(d) 中心与表面水分时程（全时程）")
    axd.grid(alpha=.3); axd.legend(fontsize=8)

    fig.suptitle(f"问题2 药材内部热湿耦合场的时空演化（终止 {tend:.2f} h）",
                 fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    out = os.path.join(FIGS, "fig_p2_evolution.png")
    fig.savefig(out, dpi=170); plt.close(fig)
    return out


def fig_p2_verification(p2ver):
    """问题2：数值方案验证（网格收敛 / 时间步收敛 / 守恒性）。"""
    fig, ax = plt.subplots(1, 3, figsize=(13.6, 4.3))

    def _conv(axis, x, dT, dC, xlabel, ylabel, title, ref_x):
        dTp = np.where(np.asarray(dT, float) > 0, dT, np.nan)
        dCp = np.where(np.asarray(dC, float) > 0, dC, np.nan)
        axis.semilogy(x, dTp, "-o", lw=1.8, label="温度最大偏差 (°C)")
        axis.semilogy(x, dCp, "-s", lw=1.8, label="水分浓度最大偏差 (kg/kg)")
        axis.axvline(ref_x, color="0.6", ls=":", lw=1.3)
        axis.text(ref_x, 0.30, " 参考解", fontsize=8, color="0.4", va="top")
        axis.axhline(0.05, color="crimson", ls="--", lw=1.2, label="判据 0.05")
        axis.set_xlabel(xlabel); axis.set_ylabel(ylabel); axis.set_title(title)
        axis.set_ylim(1e-8, 1.2)
        axis.grid(alpha=.3, which="both"); axis.legend(fontsize=8, loc="lower left")

    # (a) 网格收敛
    rows = p2ver["v2"]["rows"]
    _conv(ax[0],
          [r["N"] for r in rows],
          [r["max_dT_vs_ref"] for r in rows],
          [r["max_dC_vs_ref"] for r in rows],
          "径向网格数 N", "相对参考解的最大偏差", "(a) 网格收敛性",
          p2ver["v2"]["ref_N"])

    # (b) 时间步收敛
    rows = p2ver["v3"]["rows"]
    _conv(ax[1],
          [r["dt"] for r in rows],
          [r["max_dT_vs_min"] for r in rows],
          [r["max_dC_vs_min"] for r in rows],
          "时间步长 Δt (s)", "相对最细步长的最大偏差", "(b) 时间步收敛性",
          p2ver["v3"]["ref_dt"])
    ax[1].invert_xaxis()

    # (c) 守恒性
    axc = ax[2]
    v1 = p2ver["v1"]
    names = ["能量（守恒形式）", "水分（守恒形式）"]
    vals = [max(v1["energy_eq_rel"], 1e-18), max(v1["moisture_rel"], 1e-18)]
    bars = axc.bar(names, vals, color=["#7fb3d5", "#a9cce3"], edgecolor="0.3", width=.5)
    axc.set_yscale("log")
    axc.axhline(v1["tol"], color="crimson", ls="--", lw=1.4,
                label=f"容差 {v1['tol']:.0e}")
    for b, v in zip(bars, vals):
        axc.text(b.get_x() + b.get_width() / 2, v * 1.6, f"{v:.1e}",
                 ha="center", fontsize=9.5)
    axc.set_ylabel("相对守恒残差")
    axc.set_ylim(1e-14, 1e-4)
    axc.set_title("(c) 离散守恒性")
    axc.grid(alpha=.3, axis="y"); axc.legend(fontsize=8)

    fig.suptitle("问题2 数值方案的收敛性与守恒性验证", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = os.path.join(FIGS, "fig_p2_verification.png")
    fig.savefig(out, dpi=170); plt.close(fig)
    return out


def fig_p2_phase(cols, t, T, C):
    """问题2：热湿耦合过程（温度—含水率相图与干燥速率）。"""
    th = t / 3600.0
    r = np.asarray([float(c) for c in cols], float)
    fig, ax = plt.subplots(1, 2, figsize=(12.2, 4.6))

    # (a) C–T 轨迹（不同半径）
    axa = ax[0]
    picks = [0.0, 0.5, 1.0, 1.5, 2.0]
    idx = [int(np.argmin(np.abs(r - x))) for x in picks]
    cmap = plt.get_cmap("viridis")
    for i, j in enumerate(idx):
        m = th <= 12.0
        sc = axa.scatter(T[m, j], C[m, j], c=th[m], cmap="viridis", s=3.2,
                         vmin=0, vmax=12, alpha=.85)
        axa.plot(T[m, j][:1], C[m, j][:1], "o", ms=6,
                 color=cmap(i / max(1, len(idx) - 1)), mec="k",
                 label=f"r = {r[j]:g} cm")
    cb = fig.colorbar(sc, ax=axa)
    cb.set_label("时间 t (h)")
    axa.set_xlabel("温度 T (°C)")
    axa.set_ylabel("水分浓度 C (kg/kg)")
    axa.set_title("(a) 温度—含水率耦合轨迹（前 12 h）")
    axa.grid(alpha=.3); axa.legend(fontsize=8, loc="upper right")

    # (b) 总体干燥速率曲线（节点径向加权的体积平均含水率，与品质 Q̄(t) 同口径）
    axb = ax[1]
    dr = np.gradient(r)
    w = r * dr
    Cavg = (C * w).sum(axis=1) / w.sum()
    rate = -np.gradient(Cavg, t) * 3600.0               # kg/(kg·h)
    axb.plot(Cavg, rate, lw=2.2, color="darkgreen", label="体积平均干燥速率")
    axb.plot([Cavg[-1]], [rate[-1]], "o", color="navy", ms=6,
             label=f"判停时刻（平均含水率 {Cavg[-1]:.3f}）")
    axb.annotate("全程单调递减，无恒速段",
                 xy=(Cavg[len(Cavg)//2], rate[len(rate)//2]),
                 xytext=(1.05, 0.78), fontsize=9, color="0.25",
                 arrowprops=dict(arrowstyle="->", color="0.5", lw=1.1))
    axb.set_xlabel("体积平均含水率 $\\bar{C}$(t)（kg/kg）")
    axb.set_ylabel("总体干燥速率 −dC/dt (kg/(kg·h))")
    axb.set_xlim(0, 2.6); axb.set_ylim(bottom=0)
    axb.set_title("(b) 总体干燥速率曲线（全程单段降速）")
    axb.grid(alpha=.3); axb.legend(fontsize=8)

    fig.suptitle("问题2 热湿耦合路径与干燥速率特征", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    out = os.path.join(FIGS, "fig_p2_phase.png")
    fig.savefig(out, dpi=170); plt.close(fig)
    return out


# ----------------------------------------------------------------------------
# 图 P3
# ----------------------------------------------------------------------------
def fig_p3_drying(cols3, t3, C3, t_dry_h):
    """问题3：烘干时间反解（2x2，含判据穿越与时空热力图）。"""
    th = t3 / 3600.0
    r = np.asarray([float(c) for c in cols3], float)
    Cmax = np.nanmax(C3, axis=1)          # 判据量：max_r C(r,t)

    fig, ax = plt.subplots(2, 2, figsize=(12.5, 8.6))

    # (a) C_max(t) 全时程 + 判据
    axa = ax[0, 0]
    axa.plot(th, Cmax, lw=1.8, color="darkgreen", label="全场最大水分浓度 C_max(t)")
    axa.axhline(C_DRY, color="crimson", ls="--", lw=1.4, label="判据阈值 0.15 kg/kg")
    axa.axvline(t_dry_h, color="navy", ls=":", lw=1.4,
                label=f"t_dry = {t_dry_h:.4f} h（{t_dry_h/24:.3f} d）")
    axa.plot([t_dry_h], [C_DRY], "o", color="navy", ms=5)
    axa.set_xlabel("时间 t (h)")
    axa.set_ylabel("水分浓度 C (kg/kg)")
    axa.set_title("(a) 判据量演化与烘干时刻")
    axa.grid(alpha=.3); axa.legend(fontsize=8)

    # (b) 时空热力图
    axb = ax[0, 1]
    TT, RR = np.meshgrid(th, r)
    pc = axb.pcolormesh(TT, RR, C3.T, cmap="YlGnBu", shading="auto",
                        vmin=0.0, vmax=C0)
    cs = axb.contour(TT, RR, C3.T, levels=[C_DRY], colors="crimson", linewidths=1.6)
    axb.clabel(cs, inline=True, fontsize=8, fmt="0.15")
    axb.axvline(t_dry_h, color="navy", ls=":", lw=1.4)
    cb = fig.colorbar(pc, ax=axb)
    cb.set_label("水分浓度 C (kg/kg)")
    axb.set_xlabel("时间 t (h)")
    axb.set_ylabel("到药材中心的距离 r (cm)")
    axb.set_title("(b) 水分浓度时空分布与 0.15 等值线")

    # (c) 判据穿越放大
    axc = ax[1, 0]
    m = th >= t_dry_h - 6.0
    axc.plot(th[m], Cmax[m], lw=2.0, color="darkgreen")
    axc.axhline(C_DRY, color="crimson", ls="--", lw=1.4, label="判据 0.15 kg/kg")
    axc.axvline(t_dry_h, color="navy", ls=":", lw=1.4, label=f"t_dry={t_dry_h:.4f} h")
    axc.set_xlabel("时间 t (h)")
    axc.set_ylabel("C_max (kg/kg)")
    axc.set_title("(c) 判据穿越段放大（末 6 h）")
    axc.grid(alpha=.3); axc.legend(fontsize=8)

    # (d) 不同深度的 C(t)
    axd = ax[1, 1]
    for j, rc in enumerate(r):
        if rc not in (0.0, 0.5, 1.0, 1.5, 2.0):
            continue
        axd.plot(th, C3[:, j], lw=1.6, label=f"r = {rc:g} cm")
    axd.axhline(C_DRY, color="crimson", ls="--", lw=1.2, label="判据 0.15 kg/kg")
    axd.axvline(t_dry_h, color="navy", ls=":", lw=1.2)
    axd.set_xlabel("时间 t (h)")
    axd.set_ylabel("水分浓度 C (kg/kg)")
    axd.set_title("(d) 不同深度处的水分浓度时程")
    axd.grid(alpha=.3); axd.legend(fontsize=8)

    fig.suptitle("问题3 烘干时间的反解（判据：全场 C < 0.15 kg/kg）",
                 fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    out = os.path.join(FIGS, "fig_p3_drying.png")
    fig.savefig(out, dpi=170); plt.close(fig)
    return out


# ----------------------------------------------------------------------------
# 图 P4
# ----------------------------------------------------------------------------
def fig_p4_compare(cols3, t3, C3, t3_dry,
                   cols4, t4, C4, t4_dry,
                   R_t, abl):
    """问题4：考虑收缩后的对比与消融（2x2）。"""
    th3, th4 = t3 / 3600.0, t4 / 3600.0
    r3 = np.asarray([float(c) for c in cols3], float)
    Cmax3 = np.nanmax(C3, axis=1)
    Cmax4 = np.nanmax(C4, axis=1)

    fig, ax = plt.subplots(2, 2, figsize=(12.5, 8.6))

    # (a) Q3 vs Q4 的判据量
    axa = ax[0, 0]
    axa.plot(th3, Cmax3, lw=1.8, color="darkgreen", label=f"问题3（定半径 R=2 cm）")
    axa.plot(th4, Cmax4, lw=1.8, color="darkorange", label="问题4（考虑收缩 R(t)）")
    axa.axhline(C_DRY, color="crimson", ls="--", lw=1.4, label="判据阈值 0.15 kg/kg")
    axa.axvline(t3_dry, color="darkgreen", ls=":", lw=1.3,
                label=f"t_dry(Q3) = {t3_dry:.4f} h")
    axa.axvline(t4_dry, color="darkorange", ls=":", lw=1.3,
                label=f"t_dry(Q4) = {t4_dry:.4f} h")
    axa.set_xlabel("时间 t (h)")
    axa.set_ylabel("C_max (kg/kg)")
    axa.set_ylim(0, 2.8)
    axa.set_title("(a) 定半径 vs 动边界：判据量演化")
    axa.grid(alpha=.3); axa.legend(fontsize=7.5)

    # (b) 半径收缩曲线 R(t)
    axb = ax[0, 1]
    axb.plot(R_t[0] / 3600.0, R_t[1], lw=2.0, color="sienna",
             label="附件2 实测半径 R(t)")
    axb.axhline(2.0, color="0.5", ls=":", lw=1.2, label="初始 R0 = 2 cm")
    axb.axvline(t4_dry, color="darkorange", ls="--", lw=1.3,
                label=f"t_dry(Q4) = {t4_dry:.2f} h")
    axb.set_xlabel("时间 t (h)")
    axb.set_ylabel("药材半径 R (cm)")
    axb.set_title("(b) 药材半径收缩曲线")
    axb.grid(alpha=.3); axb.legend(fontsize=8)

    # (c) A/B/C 三组消融
    axc = ax[1, 0]
    names = ["A\n附录3+定R", "B\n附录4+定R", "C\n附录4+动R"]
    vals = [abl.get("A_app3_fixedR_h"), abl.get("B_app4_fixedR_h"),
            abl.get("C_app4_movingR_h")]
    colors = ["#7fb3d5", "#c39bd3", "#f0a06a"]
    bars = axc.bar(names, vals, color=colors, edgecolor="0.3", width=.55)
    for b, v in zip(bars, vals):
        axc.text(b.get_x() + b.get_width() / 2, v + 2.5, f"{v:.2f} h",
                 ha="center", fontsize=9.5)
    axc.set_ylabel("烘干时长 (h)")
    axc.set_ylim(0, max(vals) * 1.18)
    axc.set_title("(c) 消融：材质效应与收缩效应")
    axc.grid(alpha=.3, axis="y")
    d_mat = abl.get("材质效应_B_minus_A_h", 0.0)
    d_shr = abl.get("收缩效应_C_minus_B_h", 0.0)
    axc.text(0.02, 0.95,
             f"材质效应 B−A = {d_mat:+.2f} h\n收缩效应 C−B = {d_shr:+.2f} h",
             transform=axc.transAxes, va="top", fontsize=9,
             bbox=dict(boxstyle="round,pad=0.4", fc="#fffbe6", ec="0.6"))

    # (d) 中心与表面含水率时程对比（Q3 vs Q4）
    axd = ax[1, 1]
    axd.plot(th3, C3[:, 0], lw=1.6, color="darkgreen", ls="-", label="问题3 中心 r=0")
    axd.plot(th3, C3[:, -1], lw=1.6, color="darkgreen", ls="--", label="问题3 表面 r=2 cm")
    axd.plot(th4, C4[:, 0], lw=1.6, color="darkorange", ls="-", label="问题4 中心 ξ=0")
    axd.plot(th4, C4[:, -1], lw=1.6, color="darkorange", ls="--", label="问题4 表面 ξ=1")
    axd.axhline(C_DRY, color="crimson", ls="--", lw=1.2, label="判据 0.15 kg/kg")
    axd.set_xlabel("时间 t (h)")
    axd.set_ylabel("水分浓度 C (kg/kg)")
    axd.set_title("(d) 中心与表面的水分浓度时程（Q3 vs Q4）")
    axd.grid(alpha=.3); axd.legend(fontsize=7.5)

    fig.suptitle("问题4 考虑尺寸收缩后的烘干过程与效应分解", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    out = os.path.join(FIGS, "fig_p4_compare.png")
    fig.savefig(out, dpi=170); plt.close(fig)
    return out


def fig_p4_profiles(cols4, t4, C4, t4_dry, R_t):
    """问题4：动边界下的水分剖面（材料坐标 vs 物理坐标）。"""
    th4 = t4 / 3600.0
    r_fixed = np.asarray(
        [float(c) if isinstance(c, (int, float)) else np.nan for c in cols4], float)
    surf_idx = [j for j, c in enumerate(cols4) if not isinstance(c, (int, float))]

    fig, ax = plt.subplots(1, 2, figsize=(12.2, 4.6))
    axa, axb = ax[0], ax[1]
    times = [6.0, 12.0, 24.0, 36.0, t4_dry]
    cmap = plt.get_cmap("plasma")

    for i, tt in enumerate(times):
        k = int(np.argmin(np.abs(th4 - tt)))
        Rk = float(np.interp(t4[k], R_t[0], R_t[1]))
        row = C4[k]
        m = ~np.isnan(row)
        if m.sum() == 0:
            continue
        xs = r_fixed[m].copy()
        if surf_idx:
            xs[np.isnan(xs)] = Rk
        col = cmap(i / max(1, len(times) - 1))
        axb.plot(xs / Rk, row[m], "-o", ms=3.0, lw=1.6, color=col,
                 label=f"{th4[k]:.2f} h（R={Rk:.2f} cm）")
        axa.plot(xs, row[m], "-o", ms=3.0, lw=1.6, color=col, label=f"{th4[k]:.2f} h")
        axa.plot([xs[-1]], [row[m][-1]], "o", ms=9, mfc="none", mec=col, mew=1.6)

    # (a) 物理坐标：标出烘干末段已收缩掉的几何区域
    R_end = float(np.interp(t4[-1], R_t[0], R_t[1]))
    axa.axvspan(R_end, 2.0, color="0.88", zorder=0)
    axa.text(R_end + 0.02, 1.62,
             f"末段已收缩区域\nR: 2.00 → {R_end:.2f} cm",
             fontsize=8, color="0.35")
    axa.axhline(C_DRY, color="crimson", ls="--", lw=1.2, label="判据 0.15 kg/kg")
    axa.plot([], [], "o", ms=9, mfc="none", mec="0.35", mew=1.6, label="○ 当时的表面 R(t)")
    axa.set_xlabel("到药材中心的距离 r (cm)")
    axa.set_ylabel("水分浓度 C (kg/kg)")
    axa.set_xlim(0, 2.05)
    axa.set_title("(a) 物理坐标下的水分剖面（边界随 R(t) 内移）")
    axa.grid(alpha=.3); axa.legend(fontsize=7.5, loc="lower left", ncol=2)

    axb.axhline(C_DRY, color="crimson", ls="--", lw=1.2, label="判据 0.15 kg/kg")
    axb.set_xlabel("无量纲材料坐标 ξ = r / R(t)")
    axb.set_ylabel("水分浓度 C (kg/kg)")
    axb.set_xlim(0, 1.02)
    axb.set_title("(b) 材料坐标下的水分剖面")
    axb.grid(alpha=.3); axb.legend(fontsize=7.5, loc="lower left")

    fig.suptitle("问题4 动边界水分剖面：材料坐标与物理坐标", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    out = os.path.join(FIGS, "fig_p4_profiles.png")
    fig.savefig(out, dpi=170); plt.close(fig)
    return out


# ----------------------------------------------------------------------------
# 附件1 热风边界 / 附件2 半径曲线
# ----------------------------------------------------------------------------
def load_air(path):
    """附件1：热风温度时序（0–14400 s）。"""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    ts, Ta = [], []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        ts.append(float(row[0])); Ta.append(float(row[1]))
    wb.close()
    return np.asarray(ts, float), np.asarray(Ta, float)



def load_radius(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    ts, rs = [], []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        ts.append(float(row[0])); rs.append(float(row[1]))
    wb.close()
    return np.asarray(ts, float), np.asarray(rs, float)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--air", default="附件/附件1.xlsx")
    ap.add_argument("--radius", default="附件/附件2.xlsx")
    ap.add_argument("--update-results", action="store_true",
                    help="把图题注写回 results.json 的 figures 字段")
    ap.add_argument("--skip-p2", action="store_true", help="跳过 25 MB 的 result2 解析")
    args = ap.parse_args()

    os.makedirs(FIGS, exist_ok=True)
    outs = []

    p3 = json.load(open(os.path.join(PKG, "prob3", "results_fragment.json"),
                        encoding="utf-8"))
    p4 = json.load(open(os.path.join(PKG, "prob4", "results_fragment.json"),
                        encoding="utf-8"))
    t3_dry = float(p3["P3"]["t_dry_h"])
    t4_dry = float(p4["P4"]["t_dry_h"])

    print("[1/3] 问题3 结果", file=sys.stderr)
    cols3, tt3, C3 = read_xlsx_sheet(os.path.join(PKG, "prob3", "result3.xlsx"), 0, 1)

    print("[2/3] 问题4 结果", file=sys.stderr)
    cols4, tt4, C4 = read_xlsx_sheet(os.path.join(PKG, "prob4", "result4.xlsx"), 0, 1)

    print("[3/3] 附件2 半径曲线", file=sys.stderr)
    rt, rr = load_radius(args.radius)
    R_t = (rt, rr)

    if not args.skip_p2:
        print("[+] 问题2 结果（首次解析较慢）", file=sys.stderr)
        cols2, t2, T2, C2 = load_p2(stride=60)
        p2 = json.load(open(os.path.join(PKG, "prob2", "results_fragment.json"),
                            encoding="utf-8"))
        outs.append(fig_p2_evolution(cols2, t2, T2, C2, load_air(args.air)))
        outs.append(fig_p2_verification(p2["verification"]))
        outs.append(fig_p2_phase(cols2, t2, T2, C2))

    outs.append(fig_p3_drying(cols3, tt3, C3, t3_dry))
    outs.append(fig_p4_compare(cols3, tt3, C3, t3_dry,
                               cols4, tt4, C4, t4_dry, R_t,
                               p4["ablation"]))
    outs.append(fig_p4_profiles(cols4, tt4, C4, t4_dry, R_t))

    print("\n=== 已生成 ===")
    for o in outs:
        print(f"  {o}  ({os.path.getsize(o)/1024:.0f} KB)")

    if args.update_results:
        # 题注**不再由本脚本写回**：唯一权威源是 tools/make_results.py 的 FIGURES。
        # 原因：过去本处与 make_results.py 各写一份题注文字，两者已漂移
        # （一处写「判据阈值」、一处带判据代号字样），谁后跑谁覆盖 —— 正文从
        # results.json 复制题注时会得到不确定的结果。故删除本处写入。
        print("\n[提示] 未改动 results.json —— 题注现由 tools/make_results.py 统一产出。")
        print("       请接着运行求解器包内的 tools/make_results.py")
        print("       （题注里的 t_dry 等数字由它从各问碎片现场取值，与结果数值同源。）")


if __name__ == "__main__":
    main()
