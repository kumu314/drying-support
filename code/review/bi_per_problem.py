"""V6 分问传热 Biot 数复核
· 口径：Bi = h·R / k_ref，h = 25 W/(m²·K)（题面附录2），R = 0.02 m
·   Q1  : k₁ = 0.36 W/(m·K)（附录2 常物性）
·   Q2/Q3: k(C₀=2.55, T₀=301.15K)，props_app3（附录3 双指数）
·   Q4  : k(C₀=2.55, T₀=301.15K)，props_app4（附录4 材质）
· 说明：Bi 只用于"内部梯度是否可忽略"的量级判断（>0.1 不可集总），
·   Q2–Q4 变物性下 k 随 C/T 演化，取初始态参考值即与论文 §4.4 V6 的叙述口径一致。
"""
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # 包根
from common import props as props_mod          # noqa: E402

h = 25.0          # W/(m^2 K)
R = 0.02          # m
C0, T0 = 2.55, 301.15

out = {"meta": {
    "name": "V6 分问传热 Biot 数复核",
    "formula": "Bi = h*R/k_ref",
    "h_W_m2K": h, "R_m": R,
    "ref_state": {"C0_kgkg": C0, "T0_K": T0},
    "criterion": "Bi > 0.1 => 内部梯度不可忽略，一维径向离散必要",
}, "per_problem": {},
    "note_Q4": "论文 §4.4 取约 1.90；本表按附录4 物性式在初始态精算 "
                "k = 0.263662（Bi = 1.8964），圆整即 1.90。",}

# Q1：附录2 常物性
k1 = 0.36
out["per_problem"]["Q1"] = {"k_source": "附录2 常物性", "k_ref": k1,
                            "Bi": round(h * R / k1, 4)}

# Q2/Q3：附录3 在初始态
pr3 = props_mod.props_app3(np.array([C0]), np.array([T0]))
k3 = float(pr3["k"][0])
out["per_problem"]["Q2"] = out["per_problem"]["Q3"] = None  # 占位，下面统一写
out["per_problem"]["Q2"] = {"k_source": "附录3 props_app3 @ (C0, T0)", "k_ref": round(k3, 6),
                            "Bi": round(h * R / k3, 4)}
out["per_problem"]["Q3"] = dict(out["per_problem"]["Q2"])

# Q4：附录4 在初始态
pr4 = props_mod.props_app4(np.array([C0]), np.array([T0]))
k4 = float(pr4["k"][0])
out["per_problem"]["Q4"] = {"k_source": "附录4 props_app4 @ (C0, T0)", "k_ref": round(k4, 6),
                            "Bi": round(h * R / k4, 4)}

out["paper_claim"] = {"P1.Bi_heat": 1.3889, "Q2_Q3_approx": 1.04, "Q4_approx": 1.90}
out["verdict"] = {
    "P1": "match" if abs(out["per_problem"]["Q1"]["Bi"] - 1.3889) < 5e-4 else "MISMATCH",
    "Q2_Q3": "match" if abs(out["per_problem"]["Q2"]["Bi"] - 1.04) < 5e-3 else "MISMATCH",
    "Q4": "match" if abs(out["per_problem"]["Q4"]["Bi"] - 1.90) < 5e-3 else "MISMATCH",
    "all_gt_0.1": all(v["Bi"] > 0.1 for v in out["per_problem"].values()),
}

print(json.dumps(out["per_problem"], ensure_ascii=False, indent=2))
print("verdict:", json.dumps(out["verdict"], ensure_ascii=False))
(HERE / "bi_per_problem.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"written: {HERE / 'bi_per_problem.json'}")
