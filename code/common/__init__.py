#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common —— A 题《药材的烘干问题》公共数值内核

问题1/2/3/4 共用。产物（2026-09-11）。

from common import fvm, props
from common.fvm import solve_case, AirDriver, ConstDriver, StagedDriver
from common.props import props_app2, props_app3, props_app4

分层
----
* `props` —— 物性函数族（题目附录2/3/4 的机器可读镜像）
* `fvm` —— 数值内核（网格 / Thomas / CN 推进 / 守恒对账 / 验证件 / 写盘）
* `quality` —— 品质变化动力学 Q（单向被动，唯一集中创新）

⚠️ 本包被多个子问题共享，**只在公共模块抽取阶段写过**。此后视为只读：
内核改动请统一在公共模块内进行，不要在各问的求解脚本里就地修改。
"""

from . import fvm, props  # noqa: F401

from .fvm import (  # noqa: F401
    OUT_CM,
    TAB_CM,
    AirDriver,
    ConstDriver,
    StagedDriver,
    analytic_cylinder_series,
    fmt_table,
    load_air_table,
    make_grid,
    rhs_semi_discrete,
    sample_table,
    solve_case,
    thomas,
    verify_conservation,
    verify_dt_convergence,
    verify_grid_convergence,
    verify_physics,
    verify_scipy_bdf,
    write_result_xlsx,
)

from .props import PROPS, props_app2, props_app3, props_app4, sanity_table  # noqa: F401

__all__ = [
    "fvm", "props",
    "solve_case", "thomas", "make_grid",
    "AirDriver", "ConstDriver", "StagedDriver", "load_air_table",
    "write_result_xlsx", "sample_table", "fmt_table",
    "verify_conservation", "verify_grid_convergence", "verify_dt_convergence",
    "verify_physics", "verify_scipy_bdf", "analytic_cylinder_series",
    "rhs_semi_discrete", "OUT_CM", "TAB_CM",
    "props_app2", "props_app3", "props_app4", "PROPS", "sanity_table",
]
