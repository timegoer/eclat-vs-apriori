#!/usr/bin/env python3
"""Eclat 与 Apriori 的对比实验（v3，精简版）。

独立变量只有一个：支持度阈值。
核心结论只需一张表 + 一张图：Eclat 在所有配置下更快，且支持度越低优势越大。

保留的工程保障
--------------
* 预算制：每次运行有时间和内存上限，超限安全中断并保留部分结果；
* 单调剪枝：某算法在某档超预算后，更低档直接标记 skipped；
* 自适应重复：单次运行超过 1 秒不再重复计时；
* 单行容错：某一行异常不影响整个实验；
* 正确性前置校验：先确认两算法结果完全一致，再比较性能。

用法
----
python download_data.py
python run_experiment.py --quick          # 冒烟测试
python run_experiment.py --plot           # 完整实验并出图
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
import tracemalloc

import config
from apriori import apriori
from dataset import dataset_summary, load_fimi
from eclat import VerticalIndex, eclat, eclat_search
from verify import compare

COLUMNS = [
    "dataset", "num_transactions", "num_items",
    "min_sup_rel", "min_sup_abs", "algorithm", "status",
    "time_min_s", "time_mean_s", "time_std_s",
    "peak_mem_mb", "num_freq_itemsets",
    "search_min_s", "tidset_build_s", "speedup_vs_apriori",
]


# ================================================================ 基础
def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rss_bytes():
    """当前进程常驻内存（字节）。Linux 读 /proc，其他平台退回 ru_maxrss。"""
    try:
        with open("/proc/self/statm", "r") as fh:
            pages = int(fh.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return usage if sys.platform == "darwin" else usage * 1024


class Budget:
    """时间 / 内存预算。expired() 返回 None 或中止原因。"""

    def __init__(self, seconds=None, mem_limit_mb=None, mem_check_interval=0.5):
        self.deadline = (time.perf_counter() + seconds) if seconds else None
        self.mem_limit = mem_limit_mb * 2 ** 20 if mem_limit_mb else None
        self._next_mem_check = 0.0
        self._mem_check_interval = mem_check_interval

    def expired(self):
        now = time.perf_counter()
        if self.deadline is not None and now >= self.deadline:
            return "timeout"
        if self.mem_limit is not None and now >= self._next_mem_check:
            self._next_mem_check = now + self._mem_check_interval
            if _rss_bytes() > self.mem_limit:
                return "memory_limit"
        return None


def safe_run(runner, budget):
    """执行 runner，把异常转成 stats["status"]，保证单行失败不中断整个实验。"""
    try:
        return runner(budget)
    except MemoryError:
        return {}, {"status": "memory_error"}
    except Exception as exc:                            # noqa: BLE001
        return {}, {"status": "error", "error": "%s: %s" % (type(exc).__name__, exc)}


# ================================================================ 测量
def measure(runner, args):
    """运行 runner(budget) -> (freq, stats)，收集时间与峰值内存。

    计时流程：
      * repeat > 0：预热 1 次 → 最多 repeat 次计时；
        预热样本若耗时超过阈值或运行失败，则直接作为唯一一次测量。
      * repeat <= 0（--quick）：不做预热，跑一次并直接作为测量。
    """
    out = {"status": "ok", "times": [], "freq": {}, "stats": {}, "peak_mem_mb": ""}
    best = None

    def record(elapsed, freq, stats):
        nonlocal best
        out["times"].append(elapsed)
        if best is None or elapsed < best:
            best = elapsed
            out["freq"], out["stats"] = freq, stats

    warmup = 0 if args.repeat <= 0 else 1
    runs = max(1, args.repeat)

    for i in range(warmup + runs):
        budget = Budget(args.timeout, args.mem_limit_mb)
        t0 = time.perf_counter()
        freq, stats = safe_run(runner, budget)
        elapsed = time.perf_counter() - t0
        status = stats.get("status", "ok")

        if i < warmup and status == "ok" and elapsed <= config.REPEAT_THRESHOLD_S:
            continue                      # 预热样本：快则丢弃，不计入统计

        record(elapsed, freq, stats)
        out["status"] = status
        if status != "ok" or elapsed > config.REPEAT_THRESHOLD_S:
            break

    if not out["times"]:
        out["status"] = "failed"

    # 峰值内存（单独一次运行，独立预算）
    fastest = min(out["times"]) if out["times"] else None
    if (args.no_memory or out["status"] != "ok"
            or (fastest is not None and fastest > config.MEM_SKIP_S)):
        out["peak_mem_mb"] = ""
    else:
        budget = Budget(min(config.MEM_TIMEOUT_S, args.timeout), args.mem_limit_mb)
        tracemalloc.start()
        try:
            _, stats = safe_run(runner, budget)
            _, peak = tracemalloc.get_traced_memory()
            if stats.get("status", "ok") == "ok":
                out["peak_mem_mb"] = peak / 2 ** 20
        finally:
            tracemalloc.stop()
    return out



# ================================================================ 记录
def _base(info, rel, abs_sup, algo):
    return {
        "dataset": info["dataset"],
        "num_transactions": info["num_transactions"],
        "num_items": info["num_items"],
        "min_sup_rel": rel,
        "min_sup_abs": abs_sup,
        "algorithm": algo,
    }


def build_record(info, rel, abs_sup, algo, res, build_s, timeout):
    times = res["times"]
    stats = res["stats"] or {}
    freq = res["freq"] or {}
    peak = res["peak_mem_mb"]
    offset = build_s if (algo == "eclat" and build_s) else 0.0

    rec = _base(info, rel, abs_sup, algo)
    rec.update({
        "status": res["status"],
        "time_min_s": round(min(times) + offset, 4) if times else "",
        "time_mean_s": round(statistics.mean(times) + offset, 4) if times else "",
        "time_std_s": (round(statistics.pstdev(times), 4) if len(times) > 1
                       else (0.0 if times else "")),
        "peak_mem_mb": round(peak, 1) if peak != "" else "",
        "num_freq_itemsets": len(freq),
        "search_min_s": round(min(times), 4) if (algo == "eclat" and times) else "",
        "tidset_build_s": round(build_s, 4) if algo == "eclat" else "",
        "budget_s": timeout,
    })
    if res["status"] != "ok" and stats.get("aborted_level"):
        rec["note"] = "中止于第 %d 层" % stats["aborted_level"]
    return rec


def skipped_record(info, rel, abs_sup, algo, failed_at, build_s):
    rec = _base(info, rel, abs_sup, algo)
    rec.update({
        "status": "skipped_after_failure",
        "note": "该算法在支持度 %.4f 处已超预算，按单调性跳过" % failed_at,
    })
    if algo == "eclat":
        rec["tidset_build_s"] = round(build_s, 4)
    return rec


def annotate_speedups(records, default_timeout):
    groups = {}
    for rec in records:
        groups.setdefault((rec["dataset"], rec["min_sup_rel"]), {})[rec["algorithm"]] = rec

    for group in groups.values():
        apr, ecl = group.get("apriori"), group.get("eclat")
        if not apr or not ecl:
            continue
        a_time = _num(apr.get("time_min_s"))
        e_time = _num(ecl.get("time_min_s"))
        if apr.get("status") == "ok" and ecl.get("status") == "ok" and a_time and e_time:
            speedup = round(a_time / e_time, 3)
            apr["speedup_vs_apriori"] = ecl["speedup_vs_apriori"] = speedup
        elif ecl.get("status") == "ok" and e_time and apr.get("status") != "ok":
            budget = _num(apr.get("budget_s"), default_timeout) or default_timeout
            lower = round(budget / e_time, 2)
            apr["speedup_lower_bound"] = ecl["speedup_lower_bound"] = lower


def format_result(rec):
    if rec["status"] != "ok":
        return "%s（已发现 %s 个项集）" % (rec["status"], rec["num_freq_itemsets"])
    mem = "%sMB" % rec["peak_mem_mb"] if rec["peak_mem_mb"] != "" else "n/a"
    return "t=%-9s mem=%-10s |freq|=%-8d" % (
        "%ss" % rec["time_min_s"], mem, rec["num_freq_itemsets"])


# ================================================================ 入口
def pick_file(data_dir, name):
    for cand in (config.FILES.get(name), name + ".dat", name + ".txt", name):
        if cand:
            path = os.path.join(data_dir, cand)
            if os.path.isfile(path):
                return path
    for fname in sorted(os.listdir(data_dir)):
        if name.lower() in fname.lower():
            return os.path.join(data_dir, fname)
    return None


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Eclat vs Apriori 对比实验（v3）")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--datasets", nargs="*", default=None,
                   help="默认 %s" % " ".join(config.DEFAULT_DATASETS))
    p.add_argument("--supports", nargs="*", type=float, default=None,
                   help="覆盖配置中的支持度阶梯")
    p.add_argument("--repeat", type=int, default=config.DEFAULT_REPEAT,
                   help="计时重复次数上限（自适应截断）")
    p.add_argument("--timeout", type=float, default=config.DEFAULT_TIMEOUT,
                   help="单次算法运行时限（秒）")
    p.add_argument("--mem-limit-mb", type=float, default=config.DEFAULT_MEM_LIMIT_MB,
                   help="进程内存上限（MB），0 表示不限制")
    p.add_argument("--no-memory", action="store_true", help="跳过峰值内存测量")
    p.add_argument("--quick", action="store_true", help="快速模式")
    p.add_argument("--resume", action="store_true", help="跳过已完成组合")
    p.add_argument("--plot", action="store_true", help="结束后自动出图")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.quick:
        args.repeat = 0
        args.no_memory = True
    if not os.path.isdir(args.data_dir):
        sys.exit("找不到 %s/，请先运行 python download_data.py" % args.data_dir)

    out_path = os.path.join(args.out_dir, "summary.csv")
    records, done = [], set()
    if args.resume and os.path.isfile(out_path):
        with open(out_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                records.append(row)
                done.add((row["dataset"], round(float(row["min_sup_rel"]), 6),
                          row["algorithm"]))

    names = args.datasets or [n for n in config.DEFAULT_DATASETS
                              if pick_file(args.data_dir, n)]
    if not names:
        sys.exit("data/ 下没有找到默认数据集，请先运行 python download_data.py")

    print("=" * 78)
    print("数据集：%s" % "、".join(names))
    print("预算：timeout=%.0fs  内存上限=%sMB" % (args.timeout, args.mem_limit_mb or "无"))
    print("=" * 78)

    for name in names:
        path = pick_file(args.data_dir, name)
        if path is None:
            print("\n[跳过] 未找到 %s" % name)
            continue

        transactions, id2name = load_fimi(path)
        info = dataset_summary(transactions, id2name, name)
        print("\n=== %s：%d 条事务 / %d 个项 ==="
              % (name, info["num_transactions"], info["num_items"]))

        supports = args.supports or config.EXPERIMENTS.get(name, config.DEFAULT_SUPPORTS)
        supports = sorted({round(float(s), 6) for s in supports}, reverse=True)
        if args.quick:
            supports = supports[:config.QUICK_LEVELS]

        # ---- 正确性前置校验 ----
        check_abs = max(1, int(round(supports[0] * info["num_transactions"])))
        f_apr, _ = apriori(transactions, check_abs)
        f_ecl, _ = eclat(transactions, check_abs, "bitset")
        ok, report = compare(f_apr, f_ecl, check_abs, name)
        print(report)

        # ---- 垂直索引：一次构建、多档复用 ----
        floor_abs = max(1, int(round(supports[-1] * info["num_transactions"])))
        t0 = time.perf_counter()
        index = VerticalIndex(transactions, floor_abs, "bitset")
        build_s = time.perf_counter() - t0
        print("垂直索引：%.3fs（一次性）  保留 %d 项" % (build_s, len(index.items)))

        # ---- 逐档测量 ----
        failed = {}
        for rel in supports:
            abs_sup = max(1, int(round(rel * info["num_transactions"])))
            print("  min_sup=%.4f（绝对 %d）" % (rel, abs_sup))
            for algo in ("apriori", "eclat"):
                if (name, rel, algo) in done:
                    print("      %-8s 已存在，跳过" % algo)
                    continue
                if algo in failed:
                    records.append(skipped_record(info, rel, abs_sup, algo,
                                                  failed[algo], build_s))
                    print("      %-8s skipped（在 %.4f 处已超预算）" % (algo, failed[algo]))
                    continue

                if algo == "apriori":
                    runner = (lambda sup: (lambda b: apriori(transactions, sup, b)))(abs_sup)
                else:
                    runner = (lambda sup: (lambda b: eclat_search(
                        index.filter(sup), sup, "bitset", b)))(abs_sup)

                res = measure(runner, args)
                rec = build_record(info, rel, abs_sup, algo, res, build_s, args.timeout)
                records.append(rec)
                print("      %-8s %s" % (algo, format_result(rec)))
                if rec["status"] != "ok":
                    failed[algo] = rel

    # ---------------- 输出（只保留核心列） ----------------
    annotate_speedups(records, args.timeout)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, restval="")
        writer.writeheader()
        for rec in records:
            writer.writerow({col: rec.get(col, "") for col in COLUMNS})

    print("\n" + "=" * 78)
    print("结果已写入：%s" % out_path)
    print("%-11s %8s %8s %10s %10s %12s %12s"
          % ("dataset", "min_sup", "algo", "time(s)", "mem(MB)", "|freq|", "speedup"))
    for rec in records:
        rel = _num(rec.get("min_sup_rel"), 0.0) * 100
        if rec.get("status") == "skipped_after_failure":
            print("%-11s %7.3f%% %8s %10s %10s %12s %12s"
                  % (rec["dataset"], rel, rec["algorithm"], "-", "-", "-", "skipped"))
            continue
        speedup = rec.get("speedup_vs_apriori") or rec.get("speedup_lower_bound") or "-"
        if rec.get("status") != "ok":
            speedup = "%s/%s" % (rec["status"], speedup)
        print("%-11s %7.3f%% %8s %10s %10s %12s %12s"
              % (rec["dataset"], rel, rec["algorithm"],
                 rec.get("time_min_s", "-"), rec.get("peak_mem_mb", "-"),
                 rec.get("num_freq_itemsets", "-"), speedup))
    print("=" * 78)

    if args.plot:
        import plot_results
        plot_results.main([])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
