"""Apriori 基线实现（纯 Python）。

1. 逐层搜索：由 L(k-1) 自连接生成 C(k)，按反单调性剪枝，每层重扫数据库；
2. 计数在「事务子集枚举」与「逐候选匹配」之间按估算代价自动择优选；
3. 支持预算中断：超时 / 超内存时返回已完成的部分结果，并在 stats 中标注原因。
"""
from __future__ import annotations

import time
from collections import defaultdict
from itertools import combinations
from math import comb

__all__ = ["apriori"]

_LOOP_OVERHEAD = 2.0
_CHECK_MASK = 255          # 每 256 次迭代检查一次预算（兼顾精度与开销）


def _num_items(transactions):
    n = 0
    for trans in transactions:
        if trans and trans[-1] + 1 > n:
            n = trans[-1] + 1
    return n


def apriori(transactions, min_sup, budget=None):
    """挖掘频繁项集。返回 (freq, stats)。

    stats["status"] ∈ {"ok", "timeout", "memory_limit"}；
    中断时 freq 中保留已完成层的结果。
    """
    t_start = time.perf_counter()
    freq = {}
    stats = {
        "num_db_scans": 0, "num_candidates": 0,
        "num_subset_checks": 0, "num_candidate_checks": 0,
        "num_levels": 0, "status": "ok",
    }

    def finish(status="ok"):
        stats["status"] = status
        stats["seconds"] = time.perf_counter() - t_start
        return freq, stats

    # ---------------- 第 1 层 ----------------
    counts = [0] * _num_items(transactions)
    for idx, trans in enumerate(transactions):
        if budget is not None and (idx & _CHECK_MASK) == 0:
            reason = budget.expired()
            if reason:
                return finish(reason)
        for item in trans:
            counts[item] += 1
    stats["num_db_scans"] += 1

    prev = [(item,) for item, c in enumerate(counts) if c >= min_sup]
    prev_set = set(prev)
    for key in prev:
        freq[key] = counts[key[0]]
    stats["num_candidates"] += len(prev)
    stats["num_levels"] += 1
    if not prev:
        return finish()

    length_hist = defaultdict(int)
    for trans in transactions:
        length_hist[len(trans)] += 1

    k = 2
    while prev:
        if budget is not None:
            reason = budget.expired()
            if reason:
                return finish(reason)

        # ---------- 候选生成（自连接 + 反单调性剪枝） ----------
        groups = defaultdict(list)
        for key in prev:
            groups[key[:-1]].append(key)
        candidates = []
        for keys in groups.values():
            for i in range(len(keys)):
                ki = keys[i]
                for j in range(i + 1, len(keys)):
                    cand = ki + (keys[j][-1],)
                    if all(cand[:t] + cand[t + 1:] in prev_set for t in range(k)):
                        candidates.append(cand)
        stats["num_candidates"] += len(candidates)
        if not candidates:
            break

        # ---------- 支持度计数 ----------
        index = {cand: pos for pos, cand in enumerate(candidates)}
        counts_k = [0] * len(candidates)
        cost_subset = sum(n * comb(L, k) for L, n in length_hist.items() if L >= k)
        cost_loop = len(transactions) * len(candidates) * _LOOP_OVERHEAD

        if cost_subset <= cost_loop:
            for idx, trans in enumerate(transactions):
                if budget is not None and (idx & _CHECK_MASK) == 0:
                    reason = budget.expired()
                    if reason:
                        stats["aborted_level"] = k
                        return finish(reason)
                if len(trans) < k:
                    continue
                for sub in combinations(trans, k):
                    pos = index.get(sub)
                    if pos is not None:
                        counts_k[pos] += 1
            stats["num_subset_checks"] += cost_subset
        else:
            cand_frozen = [frozenset(c) for c in candidates]
            for idx, trans in enumerate(transactions):
                if budget is not None and (idx & _CHECK_MASK) == 0:
                    reason = budget.expired()
                    if reason:
                        stats["aborted_level"] = k
                        return finish(reason)
                tset = set(trans)
                for pos, cand in enumerate(cand_frozen):
                    if cand <= tset:
                        counts_k[pos] += 1
            stats["num_candidate_checks"] += len(transactions) * len(candidates)

        stats["num_db_scans"] += 1
        prev = []
        for cand, cnt in zip(candidates, counts_k):
            if cnt >= min_sup:
                freq[cand] = cnt
                prev.append(cand)
        prev.sort()
        prev_set = set(prev)
        stats["num_levels"] += 1
        k += 1

    return finish()
