"""两个算法的结果一致性校验。

性能结论必须建立在"两个算法挖出的频繁项集完全相同"的前提上。
"""
from __future__ import annotations

__all__ = ["compare", "cross_check_mlxtend"]


def compare(freq_a, freq_b, min_sup, name="", verbose=True):
    """比较两个频繁项集集合。返回 (是否一致, 可打印的报告)。

    比较前先把键规范化为 frozenset，避免"同一项集、键的排列不同"
    被误判为结果不一致。
    """
    keys_a, keys_b = set(freq_a), set(freq_b)
    only_a_raw = keys_a - keys_b
    only_b_raw = keys_b - keys_a

    set_a = {frozenset(key): v for key, v in freq_a.items()}
    set_b = {frozenset(key): v for key, v in freq_b.items()}

    only_a = set(set_a) - set(set_b)
    only_b = set(set_b) - set(set_a)
    support_diff = [k for k in (set(set_a) & set(set_b)) if set_a[k] != set_b[k]]

    ok = not only_a and not only_b and not support_diff

    report = [
        "[一致性校验] %s  min_sup=%d" % (name, min_sup),
        "  Apriori: %d 个频繁项集" % len(set_a),
        "  Eclat  : %d 个频繁项集" % len(set_b),
        "  仅 Apriori 有 %d 个；仅 Eclat 有 %d 个；支持度不一致 %d 个"
        % (len(only_a), len(only_b), len(support_diff)),
        "  结论：%s" % ("一致 ✔" if ok else "不一致 ✘（请先排查实现问题）"),
    ]

    if ok and (only_a_raw or only_b_raw):
        report.append(
            "  说明：有 %d 个项集的原始键排列不同（如支持度序 vs 项 id 序），"
            "但项集内容与支持度完全一致。" % len(only_a_raw)
        )

    if not ok and verbose:
        for key in list(only_a)[:3]:
            report.append("  仅 Apriori 有：%s（支持度 %d）" % (sorted(key), set_a[key]))
        for key in list(only_b)[:3]:
            report.append("  仅 Eclat 有：%s（支持度 %d）" % (sorted(key), set_b[key]))

    return ok, "\n".join(report)



def cross_check_mlxtend(transactions, min_sup, id2name, verbose=True):
    """（可选）用 mlxtend 做第三方对拍。需先 pip install mlxtend。

    返回 None 表示未安装 mlxtend。
    """
    try:
        from mlxtend.frequent_patterns import apriori as mlx_apriori
        from mlxtend.preprocessing import TransactionEncoder
    except ImportError:
        if verbose:
            print("  [跳过] 未安装 mlxtend，无法进行第三方交叉验证。")
        return None

    import pandas as pd

    records = [[id2name[i] for i in t] for t in transactions]
    encoder = TransactionEncoder()
    matrix = encoder.fit(records).transform(records)
    df = pd.DataFrame(matrix, columns=encoder.columns_)
    freq_df = mlx_apriori(df, min_support=min_sup / len(transactions),
                          use_colnames=True)

    mlx = {frozenset(row): 0 for row in freq_df["itemsets"]}
    return mlx

