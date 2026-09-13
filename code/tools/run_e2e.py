# -*- coding: utf-8 -*-
"""
端到端可运行性验证（官方红线自检）：在干净目录按附录 7.1 顺序
完整复跑求解链 prob1 -> prob2 -> prob3 -> prob4 -> probQ -> tools，
记录运行时长、产物哈希，并与论文口径数字逐位比对。

干净目录定义：仅含版本库内的源码与文档，不含任何开发残留
（__pycache__、*.npz 求解缓存、已生成的 result*.xlsx / results.json）。
附件（附件1/附件2.xlsx）留在仓库外的原始路径，按交付口径以命令行传入。

用法：
    python tools/run_e2e.py --air <附件1.xlsx> --radius <附件2.xlsx>
产出：review/e2e_reproduce.md
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

# ---- 控制台可移植性兜底-----------------------------------
# 默认中文 Windows 控制台是 cp936；stdout 遇不可编码字符会抛 UnicodeEncodeError
# 并中断。errors="replace" 降级为 '?'; **不改变 stdout 编码**。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (ValueError, OSError):
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(_HERE)                      # 求解器包根（本包根目录）
PY = sys.executable

# 论文口径的预期数字（与 results.json / 正文引用数字同源）
EXPECTED = {
    "P1.T_center_1800s": 33.5752,
    "P1.T_surface_1800s": 36.7853,
    "P3.t_dry_h": 56.4767,
    "P4.t_dry_h": 50.8097,
    "P5.Q_mean_30h": 0.23520516774184458,
}

STEPS = [
    ("prob1", "prob1/solve.py", "--air"),
    ("prob2", "prob2/solve.py", "--air"),
    ("prob3", "prob3/solve.py", "--air"),
    ("prob4", "prob4/solve.py", "--air", "--radius"),
    ("probQ", "probQ/solve.py", "--air"),
    ("probQ_fig", "probQ/make_fig.py", None),
    ("tools_results", "tools/make_results.py", None),
    ("tools_figs", "tools/make_figs.py", None),
    ("tools_appendix", "tools/make_appendix.py", None),
]

IGNORE = shutil.ignore_patterns(
    "__pycache__*", "*.npz", "*.pyc", "result*.xlsx",
    "results.json", "results_fragment.json", "sec7_appendix.md",
)


def md5(path, block=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


def get(d, dotted):
    for k in dotted.split("."):
        d = d[k]
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--air", required=True)
    ap.add_argument("--radius", required=True)
    ap.add_argument("--keep", action="store_true",
                    help="保留干净目录（默认结束后删除）")
    a = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    clean = os.path.join(os.path.dirname(PKG), f"_e2e_clean_{stamp}")
    if os.path.exists(clean):
        shutil.rmtree(clean)
    shutil.copytree(PKG, clean, ignore=IGNORE)
    print(f"[e2e] clean dir: {clean}")

    env_air_args = {"prob1": ["--air", a.air],
                    "prob2": ["--air", a.air, "--cache",
                              os.path.join("review", "p2_traj_cache.npz")],
                    "prob3": ["--air", a.air],
                    "prob4": ["--air", a.air, "--radius", a.radius],
                    "probQ": ["--air", a.air]}

    rows, t_all = [], time.time()
    for name, rel, *_ in STEPS:
        cmd = [PY, os.path.join(clean, rel)] + env_air_args.get(name, [])
        t0 = time.time()
        r = subprocess.run(cmd, cwd=clean, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        dt = time.time() - t0
        ok = r.returncode == 0
        rows.append((name, rel,
                     dt, ok, (r.stdout or "")[-200:], (r.stderr or "")[-300:]))
        print(f"[e2e] {name:14s} {'OK ' if ok else 'FAIL'} {dt:7.1f}s")
        if not ok:
            print((r.stderr or "")[-800:])
            break
    total = time.time() - t_all

    # 产物哈希 + 论文口径逐位比对
    hashes = {}
    for rel in ("prob1/result1.xlsx", "prob2/result2.xlsx",
                "prob3/result3.xlsx", "prob4/result4.xlsx"):
        p = os.path.join(clean, rel)
        if os.path.exists(p):
            hashes[rel] = md5(p)
    diffs = []
    rj = os.path.join(clean, "results.json")
    if os.path.exists(rj):
        hashes["results.json"] = md5(rj)
        res = json.load(open(rj, encoding="utf-8"))
        for key, exp in EXPECTED.items():
            try:
                got = float(get(res, key))
            except Exception as e:
                diffs.append((key, exp, f"missing ({e})"))
                continue
            if got != exp:
                diffs.append((key, exp, got))

    ok_all = all(x[3] for x in rows) and not diffs
    lines = [
        "# 端到端可运行性验证（e2e reproduce）", "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 干净目录：`_e2e_clean_{stamp}`（仅库内源码，无缓存/旧产物，"
        "结束后" + ("保留" if a.keep else "已删除") + "）",
        f"- 顺序：prob1 → prob2 → prob3 → prob4 → probQ → tools 三件",
        f"- 总时长：**{total/60:.1f} min**（Python {sys.version.split()[0]}）",
        f"- 结论：**{'[OK] 全部通过' if ok_all else '[FAIL] 存在失败/不一致'}**", "",
        "## 各步运行记录", "",
        "| 步骤 | 命令（包根相对） | 时长 s | 结果 |", "|---|---|---|---|",
    ]
    for name, cmd, dt, ok, _, _err in rows:
        lines.append(f"| {name} | `{cmd}` | {dt:.1f} | {'OK' if ok else 'FAIL'} |")
    lines += ["", "## 产物哈希（md5）", ""]
    lines += [f"- `{k}` = `{v}`" for k, v in hashes.items()]
    lines += ["", "## 与论文口径数字比对（要求逐位一致）", ""]
    if diffs:
        lines += ["| 键 | 论文口径 | 干净复跑 | ", "|---|---|---|"]
        lines += [f"| {k} | {e} | {g} |" for k, e, g in diffs]
    else:
        lines.append("5/5 键逐位一致（" +
                     ", ".join(f"{k}={v}" for k, v in EXPECTED.items()) + "）")
    lines.append("")

    os.makedirs(os.path.join(PKG, "review"), exist_ok=True)
    out_md = os.path.join(PKG, "review", "e2e_reproduce.md")
    with open(out_md, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print("[e2e] report ->", out_md)
    if not a.keep:
        shutil.rmtree(clean, ignore_errors=True)
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
