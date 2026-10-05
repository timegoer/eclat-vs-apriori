"""实验配置（v3，精简版）。

设计目标：用最少的变量验证"Eclat 相对 Apriori 的改进"。
- 只保留一个自变量：支持度阈值；
- 只保留三个度量：运行时间、峰值内存、频繁项集数量；
- 数据集只取两个：一个中等规模（mushroom）、一个大规模（T10I4D100K）。
"""

# 数据集名称 -> 文件名
FILES = {
    "mushroom": "mushroom.dat",
    "T10I4D100K": "T10I4D100K.dat",
    "retail": "retail.dat",          # 可选：不在默认列表中
    "groceries": "groceries.txt",    # 可选
}

# 默认参与实验的数据集（按此顺序执行）
DEFAULT_DATASETS = ["mushroom", "T10I4D100K"]

# 支持度阶梯（降序）。区间选取原则：保证两个算法都能完成、且能挖出多项目集。
EXPERIMENTS = {
    "mushroom": [0.40, 0.30, 0.20, 0.15, 0.10],
    "T10I4D100K": [0.010, 0.007, 0.005, 0.0035, 0.0025],
    "retail": [0.010, 0.007, 0.005, 0.0035, 0.0025],
    "groceries": [0.030, 0.020, 0.015, 0.010],
}

DEFAULT_SUPPORTS = [0.010, 0.007, 0.005]

# ---------------- 运行预算 ----------------
DEFAULT_TIMEOUT = 300.0        # 单次算法运行时限（秒），超时记为 timeout
DEFAULT_MEM_LIMIT_MB = 6000    # 进程常驻内存上限（MB），0 表示不限制
DEFAULT_REPEAT = 3             # 计时重复次数上限（自适应截断）
REPEAT_THRESHOLD_S = 1.0       # 单次运行超过该秒数即不再重复计时
MEM_TIMEOUT_S = 180.0          # 峰值内存测量的独立时限（秒）
MEM_SKIP_S = 120.0             # 单次运行超过该秒数则跳过内存测量
QUICK_LEVELS = 2               # --quick 时每个数据集只取前 N 档
