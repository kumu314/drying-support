# -*- coding: utf-8 -*-
"""落地：机理示意图与求解流程图。

产出（figs/ 为图件目录）：
../figs/fig_mechanism.png -> 正文 §3.1（图3-1）物理机理与热湿耦合示意
../figs/fig_flowchart.png -> 正文 §3.3 末（图3-2）数值求解流程

风格与 make_figs.py 一致（Microsoft YaHei、dpi 110）。纯示意图形，
不依赖任何数值结果；题注的权威源在 make_results.py 的 FIGURES。
"""
import os
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch
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

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 110

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "figs")

# ---------------------------------------------------------------- 机理图
def make_mechanism():
    fig = plt.figure(figsize=(10.8, 5.4))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1.0], wspace=0.10,
                          left=0.02, right=0.98, top=0.86, bottom=0.04)

    # ---- (a) 圆柱横截面：几何、通量与收缩动边界
    ax = fig.add_subplot(gs[0, 0])
    ax.set_aspect("equal"); ax.axis("off")
    cx, cy = 0.15, -0.05
    R0, R1 = 1.00, 0.78

    ax.add_patch(Circle((cx, cy), R0, fill=False, ls=(0, (4, 3)),
                        lw=1.4, ec="0.55"))
    ax.add_patch(Circle((cx, cy), R1, facecolor="#fdf3e3",
                        edgecolor="#8c5a2b", lw=1.8))
    for rr in (0.60, 0.42, 0.25):
        ax.add_patch(Circle((cx, cy), R1 * rr, fill=False,
                            lw=0.8, ec="#c98d4b", alpha=0.35))

    # 轴线与半径
    ax.plot([cx - 0.055, cx + 0.055], [cy, cy], color="k", lw=1.2)
    ax.text(cx + 0.08, cy - 0.10, "r = 0（轴线）", fontsize=8.5, color="0.25")
    ax.add_patch(FancyArrowPatch((cx, cy), (cx + 0.42, cy + 0.42),
                                 arrowstyle="-|>", mutation_scale=11,
                                 color="k", lw=1.1))
    ax.text(cx + 0.30, cy + 0.50, "r", fontsize=11, style="italic")

    # 收缩标注：从 R0 圆到 R1 圆的箭头（左上 45°），文字放外侧
    a = math.radians(133)
    p0 = (cx + R0 * math.cos(a), cy + R0 * math.sin(a))
    p1 = (cx + R1 * math.cos(a), cy + R1 * math.sin(a))
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=10,
                                 color="0.45", lw=1.1))
    ax.text(cx - 1.42, cy + 1.06, "初始边界 R$_0$（虚线）", fontsize=8.8,
            color="0.35")
    ax.text(cx - 0.30, cy + 1.13, "收缩动边界 R(t)：表面随干燥内移",
            fontsize=8.8, color="#8c5a2b")
    ax.add_patch(FancyArrowPatch((cx + 0.10, cy + 1.08), (cx + 0.62, cy + 0.80),
                                 arrowstyle="-", color="0.45", lw=0.7))

    # 热风箭头（左侧水平三道）+ 标注放箭头下方
    for y in (-0.45, 0.05, 0.55):
        ax.add_patch(FancyArrowPatch((-1.72, cy + y), (-1.25, cy + y),
                                     arrowstyle="-|>", mutation_scale=13,
                                     color="#d0603a", lw=1.6))
    ax.text(-1.78, cy - 0.80, "热风 T$_g$、流速 v", fontsize=9, color="#d0603a")

    # 对流供热（红，向内）与蒸发（蓝，向外）
    for ang in (35, 145, 215, 325):
        a1 = math.radians(ang)
        x0, y0 = cx + (R0 + 0.18) * math.cos(a1), cy + (R0 + 0.18) * math.sin(a1)
        x1, y1 = cx + (R1 + 0.05) * math.cos(a1), cy + (R1 + 0.05) * math.sin(a1)
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>",
                                     mutation_scale=12, color="#d0603a", lw=1.6))
        a2 = math.radians(ang - 14)
        x2, y2 = cx + (R1 - 0.16) * math.cos(a2), cy + (R1 - 0.16) * math.sin(a2)
        x3, y3 = cx + (R0 + 0.12) * math.cos(a2), cy + (R0 + 0.12) * math.sin(a2)
        ax.add_patch(FancyArrowPatch((x2, y2), (x3, y3), arrowstyle="-|>",
                                     mutation_scale=12, color="#2f6fb4", lw=1.6))

    ax.text(1.28, cy - 0.62, "对流供热 h(T$_g$−T$_s$)", fontsize=9, color="#d0603a")
    ax.text(1.28, cy - 0.84, "表面蒸发（水汽逸出）", fontsize=9, color="#2f6fb4")
    ax.text(1.28, cy - 1.06, "内部：导热与水分扩散", fontsize=9, color="0.25")
    ax.text(1.28, cy - 1.28, "（梯度驱动，耦合物性）", fontsize=8.2, color="0.40")

    ax.set_xlim(-2.00, 2.90); ax.set_ylim(-1.75, 1.35)
    ax.set_title("(a) 圆柱药材横截面：通量与收缩动边界", fontsize=10.5, pad=4)

    # ---- (b) 热湿耦合回路（菱形布局，标签居中避让）
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.axis("off")

    def box(x, y, w, h, text, fc, ec, fs=9.3):
        ax2.add_patch(FancyBboxPatch((x, y), w, h,
                                     boxstyle="round,pad=0.02,rounding_size=0.04",
                                     facecolor=fc, edgecolor=ec, lw=1.4))
        ax2.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                 fontsize=fs, color="0.10")

    # T 上、C 下、R 左、Q 右（菱形）
    box(0.34, 0.78, 0.32, 0.14, "温度场 T(r, t)", "#fbe9e4", "#d0603a")
    box(0.34, 0.08, 0.32, 0.14, "水分场 C(r, t)", "#e4eefb", "#2f6fb4")
    box(0.00, 0.43, 0.20, 0.14, "收缩边界\nR(t)", "#f3ede2", "#8c5a2b", fs=8.8)
    box(0.82, 0.43, 0.22, 0.14, "品质变化\n动力学 Q", "#eef3ea", "#5c8a4e", fs=8.8)

    ar = dict(arrowstyle="-|>", mutation_scale=12, lw=1.5)
    # T <-> C 两侧大弧
    ax2.add_patch(FancyArrowPatch((0.70, 0.80), (0.70, 0.20),
                                  connectionstyle="arc3,rad=-0.32",
                                  color="#8c5a2b", **ar))
    ax2.add_patch(FancyArrowPatch((0.30, 0.20), (0.30, 0.80),
                                  connectionstyle="arc3,rad=-0.32",
                                  color="#8c5a2b", **ar))
    # 耦合标签放环内居中（避开弧线与侧框）
    ax2.text(0.51, 0.60, "升温强化扩散\n（D 随 T 增大）", fontsize=8.4,
             color="#8c5a2b", ha="center", va="center")
    ax2.text(0.51, 0.38, "蒸发吸热降温\n（物性随 C 变）", fontsize=8.4,
             color="#8c5a2b", ha="center", va="center")
    # R -> T / R -> C
    ax2.add_patch(FancyArrowPatch((0.20, 0.55), (0.36, 0.78), **ar))
    ax2.add_patch(FancyArrowPatch((0.20, 0.45), (0.36, 0.22), **ar))
    ax2.text(0.235, 0.71, "边界内移", fontsize=7.8, color="#8c5a2b")
    ax2.text(0.235, 0.27, "边界内移", fontsize=7.8, color="#8c5a2b")
    # T -> Q 单向下馈（事后积分）
    ax2.add_patch(FancyArrowPatch((0.66, 0.86), (0.88, 0.57),
                                  connectionstyle="arc3,rad=0.28",
                                  color="#5c8a4e", **ar))
    ax2.text(0.93, 0.80, "温度历史\n事后积分\n（单向下馈）", fontsize=7.8,
             color="#5c8a4e", ha="center")

    ax2.set_xlim(-0.04, 1.10); ax2.set_ylim(0.0, 1.00)
    ax2.set_title("(b) 热—湿耦合回路与品质单向下馈", fontsize=10.5, pad=4)

    fig.suptitle("物理机理示意", fontsize=12, y=0.965)
    fig.savefig(os.path.join(OUT, "fig_mechanism.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("ok fig_mechanism.png")

# ---------------------------------------------------------------- 流程图
def _fbox(ax, x, y, w, h, text, fc, ec, fs=9.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0.012,rounding_size=0.03",
                                facecolor=fc, edgecolor=ec, lw=1.4))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color="0.10")

def _arrow(ax, p0, p1, color="0.30", rad=0.0, lw=1.4):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=12,
                                 color=color, lw=lw,
                                 connectionstyle=f"arc3,rad={rad}"))

def make_flowchart():
    fig, ax = plt.subplots(figsize=(7.8, 9.6))
    ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    C_IN, C_PDE, C_NUM, C_CHK, C_OUT = ("#f5f5f5", "#fbe9e4", "#e4eefb",
                                        "#fdf3dd", "#eef3ea")
    E_IN, E_PDE, E_NUM, E_CHK, E_OUT = ("0.45", "#d0603a", "#2f6fb4",
                                        "#b08a2e", "#5c8a4e")

    # (高, 文本, 面色, 边色)——自上而下排布，先算好再画
    steps = [
        (0.062, "附件 1–3 数据读入\n物性 k(T,C)、D(T,C)、ρc 插值", C_IN, E_IN),
        (0.088, "建立控制方程\n柱坐标一维径向热湿耦合 PDE\n（对流边界 + 蒸发通量）", C_PDE, E_PDE),
        (0.088, "FVM 空间离散\nN 个控制体积、界面调和平均\n收缩段换算到材料坐标 ξ = r/R(t)", C_NUM, E_NUM),
        (0.088, "CN 半隐式时间推进\n三对角方程组逐层求解\nPicard 外迭代处理非线性物性", C_NUM, E_NUM),
        (0.062, "校验：网格收敛 / 时间步收敛\n离散守恒 / 浓度非负", C_CHK, E_CHK),
        (0.044, "判据：全域水分低于阈值 → 判停 t$_{dry}$", C_CHK, E_CHK),
        (0.044, "输出：resultN.xlsx、结果图、results.json", C_OUT, E_OUT),
    ]
    GAP = 0.038
    total = sum(s[0] for s in steps) + GAP * (len(steps) - 1)
    y_top = 0.985
    W, X = 0.58, 0.06

    boxes = []  # (bottom, h)
    y = y_top
    for h, _, _, _ in steps:
        boxes.append((y - h, h))
        y -= h + GAP

    for i, ((btm, h), (_, text, fc, ec)) in enumerate(zip(boxes, steps)):
        _fbox(ax, X, btm, W, h, text, fc, ec)
        if i:
            prev_btm = boxes[i - 1][0]
            _arrow(ax, (X + W / 2, prev_btm), (X + W / 2, btm + h))

    # 品质分支：输出框右侧引出，事后积分不回馈主求解
    out_btm, out_h = boxes[-1]
    bx, by, bw, bh = 0.70, out_btm - 0.045, 0.285, 0.135
    _fbox(ax, bx, by, bw, bh,
          "品质变化动力学 Q\n（温度场事后积分，\n不反馈主求解）", C_OUT, E_OUT, fs=8.4)
    _arrow(ax, (X + W, out_btm + out_h / 2), (bx, by + bh / 2),
           color=E_OUT, rad=-0.12)

    ax.set_title("数值求解流程", fontsize=12, pad=10)
    fig.savefig(os.path.join(OUT, "fig_flowchart.png"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("ok fig_flowchart.png")

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    make_mechanism()
    make_flowchart()
