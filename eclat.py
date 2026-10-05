"""Eclat 实现（纯 Python）。

1. VerticalIndex：一次性构建垂直格式索引（只保留支持度 >= 下界的项），
   之后可用任意阈值重复 filter，避免支持度扫描中重复支付 O(|D|) 级构建成本；
2. 支持度 = 集合交的大小：sup(X ∪ Y) = |t(X) ∩ t(Y)|；
3. 位图（Python 大整数）表示 tidset：交集 = 按位与，支持度 = popcount；
4. 支持预算中断：超时 / 超内存时返回已发现的部分结果。
"""
from __future__ import annotations

import sys
import time

__all__ = ["VerticalIndex", "eclat", "eclat_search", "build_vertical", "support_of"]

_CHECK_MASK = 1023         # 每 1024 次交集检查一次预算


def _popcount(x):
    try:
        return x.bit_count()          # Python >= 3.10
    except AttributeError:
        return bin(x).count("1")


def support_of(tidset, representation="bitset"):
    return _popcount(tidset) if representation == "bitset" else len(tidset)


class VerticalIndex:
    """垂直格式索引：一次构建、多档复用。

    floor_min_sup 应取支持度扫描阶梯中的最小绝对支持度；
    低于该值的项在构建阶段即被丢弃。
    """

    def __init__(self, transactions, floor_min_sup=1, representation="bitset"):
        self.representation = representation
        self.n_transactions = len(transactions)

        buckets = {}
        for tid, trans in enumerate(transactions):
            for item in trans:
                bucket = buckets.get(item)
                if bucket is None:
                    buckets[item] = [tid]
                else:
                    bucket.append(tid)

        n_bytes = (self.n_transactions + 7) // 8
        # 缓存 (item, tidset, support)，避免每次 filter 重复计算 popcount
        self.items = []
        for item, bucket in buckets.items():
            support = len(bucket)
            if support < floor_min_sup:
                continue
            if representation == "bitset":
                buf = bytearray(n_bytes)
                for tid in bucket:
                    buf[tid >> 3] |= 1 << (tid & 7)
                tidset = int.from_bytes(buf, "little")
            else:
                tidset = frozenset(bucket)
            self.items.append((item, tidset, support))

        self.memory_mb = sum(sys.getsizeof(ts) for _, ts, _ in self.items) / 2 ** 20

    def filter(self, min_sup):
        """取出支持度 >= min_sup 的项，按支持度升序排列。"""
        kept = [entry for entry in self.items if entry[2] >= min_sup]
        kept.sort(key=lambda entry: entry[2])
        return [(item, tidset) for item, tidset, _ in kept]


class _Stopped(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def eclat_search(vertical, min_sup, representation="bitset", budget=None):
    """在垂直格式上执行前缀等价类 DFS。返回 (freq, stats)。"""
    sup = _popcount if representation == "bitset" else len
    freq = {}
    stats = {"num_nodes": 0, "num_intersections": 0, "status": "ok"}
    t_start = time.perf_counter()
    counter = 0

    def dfs(prefix, items):
        nonlocal counter
        for i in range(len(items)):
            item, tid_i = items[i]
            key = tuple(sorted(prefix + (item,)))     # 规范键：按项 id 升序
            freq[key] = sup(tid_i)
            stats["num_nodes"] += 1

            suffix = []
            for j in range(i + 1, len(items)):
                inter = tid_i & items[j][1]
                counter += 1
                stats["num_intersections"] += 1
                if budget is not None and (counter & _CHECK_MASK) == 0:
                    reason = budget.expired()
                    if reason:
                        raise _Stopped(reason)
                if sup(inter) >= min_sup:
                    suffix.append((items[j][0], inter))
            if suffix:
                dfs(key, suffix)

    try:
        dfs((), vertical)
    except _Stopped as stop:
        stats["status"] = stop.reason

    stats["seconds"] = time.perf_counter() - t_start
    return freq, stats


def eclat(transactions, min_sup, representation="bitset", budget=None):
    """便捷入口（单阈值，含一次性构建）。返回 (freq, stats)。"""
    t0 = time.perf_counter()
    index = VerticalIndex(transactions, min_sup, representation)
    vertical = index.filter(min_sup)
    t1 = time.perf_counter()
    freq, stats = eclat_search(vertical, min_sup, representation, budget)
    t2 = time.perf_counter()

    stats["tidset_build_s"] = t1 - t0
    stats["search_s"] = t2 - t1
    stats["seconds"] = t2 - t0
    return freq, stats


def build_vertical(transactions, min_sup, representation="bitset"):
    """兼容旧接口：返回某一阈值下的垂直视图。"""
    return VerticalIndex(transactions, min_sup, representation).filter(min_sup)
