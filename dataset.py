"""数据集读取与统计。"""
from __future__ import annotations

__all__ = ["load_fimi", "dataset_summary"]


def load_fimi(path):
    """读取 FIMI 格式数据集。

    每行一条事务，项之间以空格分隔。为加速后续运算，项被映射为整数 id。

    返回
    ----
    transactions : list[tuple[int, ...]]
        已去重并升序排列的事务；每条事务是项 id 的升序元组。
    id2name : list[str]
        id -> 原始项名。
    """
    name2id = {}
    id2name = []
    transactions = []

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ids = set()
            for token in line.split():
                idx = name2id.get(token)
                if idx is None:
                    idx = len(id2name)
                    name2id[token] = idx
                    id2name.append(token)
                ids.add(idx)
            transactions.append(tuple(sorted(ids)))

    return transactions, id2name


def dataset_summary(transactions, id2name, name=""):
    """返回数据集的基本统计量（用于报告"稀疏/稠密"）。"""
    n = len(transactions)
    n_items = len(id2name)
    total = sum(len(t) for t in transactions)
    return {
        "dataset": name,
        "num_transactions": n,
        "num_items": n_items,
        "total_item_occurrences": total,
        "avg_transaction_length": (total / n) if n else 0.0,
        "max_transaction_length": max((len(t) for t in transactions), default=0),
        # 密度 = 实际出现的（项, 事务）对 / 全部可能组合
        "density": (total / (n * n_items)) if (n and n_items) else 0.0,
    }

