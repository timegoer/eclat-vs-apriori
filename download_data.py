#!/usr/bin/env python3
"""下载实验所需的公开数据集（FIMI 格式：一行一条事务，项以空格分隔）。

背景
----
FIMI 官方站点 fimi.uantwerpen.be 的 HTTPS 证书已过期，标准下载会报
`CERTIFICATE_VERIFY_FAILED`。本脚本按下列顺序尝试多种途径，并对结果做内容校验：

  1. 官方 HTTPS 直链（正常校验证书）
  2. 证书校验失败时 —— 自动降级为跳过证书验证重试（终端会打印警告）
  3. 官方 HTTP 直链
  4. Wayback Machine 历史快照（返回原始文件）
  5. 仍失败则打印手动下载指引（含 wget / curl / 浏览器三种方式）

用法
----
python download_data.py                  # 下载默认数据集
python download_data.py --list            # 查看数据集清单
python download_data.py --datasets mushroom T10I4D100K
python download_data.py --force           # 强制重新下载
python download_data.py --strict-ssl      # 禁止跳过证书验证（更安全，但当前可能失败）
python download_data.py --mirror https://your-mirror.example.com/data/
"""
from __future__ import annotations

import argparse
import os
import ssl
import sys
import urllib.error
import urllib.request

USER_AGENT = "Mozilla/5.0 (eclat-vs-apriori benchmark; academic use)"
FIMI_HOST = "fimi.uantwerpen.be"
FIMI_HTTPS = "https://%s/data/" % FIMI_HOST
FIMI_HTTP = "http://%s/data/" % FIMI_HOST

DATASETS = {
    "mushroom": {
        "file": "mushroom.dat",
        "min_lines": 8124,
        "desc": "稠密：8124 条事务 / 119 个项 / 平均事务长度约 23",
    },
    "T10I4D100K": {
        "file": "T10I4D100K.dat",
        "min_lines": 100000,
        "desc": "稀疏·大规模：100000 条事务 / 870 个项 / 平均事务长度约 10",
    },
    "retail": {
        "file": "retail.dat",
        "min_lines": 88162,
        "desc": "稀疏·零售场景：88162 条事务 / 16470 个项 / 平均事务长度约 10",
    },
    "groceries": {
        "file": "groceries.txt",
        "min_lines": 9835,
        "desc": "稠密·零售场景：9835 条事务 / 169 个项",
        "manual": "https://www.philippe-fournier-viger.com/spmf/index.php?link=datasets.php",
    },
}

DEFAULT_DATASETS = ["mushroom", "T10I4D100K", "retail"]


# ---------------------------------------------------------------- URL 候选
def candidate_urls(filename, mirror=None):
    urls = []
    if mirror:
        urls.append(mirror.rstrip("/") + "/" + filename)
    urls += [
        FIMI_HTTPS + filename,
        FIMI_HTTP + filename,
        "https://web.archive.org/web/2024id_/" + FIMI_HTTPS + filename,
        "https://web.archive.org/web/2022id_/" + FIMI_HTTPS + filename,
        "https://web.archive.org/web/2019id_/" + FIMI_HTTPS + filename,
    ]
    return urls


# ---------------------------------------------------------------- 网络
def _read(url, insecure=False, timeout=180):
    context = None
    if insecure:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=context) as resp:
        return resp.read()


def fetch(url, allow_insecure=True, timeout=180):
    """下载指定 URL，返回 (data, note)。

    若报证书错误且 allow_insecure 为真，则跳过证书验证重试一次，
    此时 note 为 "insecure"。
    """
    try:
        return _read(url, timeout=timeout), ""
    except (urllib.error.URLError, ssl.SSLError) as exc:
        message = str(getattr(exc, "reason", exc))
        if not allow_insecure or "certificate" not in message.lower():
            raise
        print("      证书校验失败，改为跳过证书验证重试……")
        print("      （数据为公开学术数据集；但该连接未经认证，请注意风险）")
        return _read(url, insecure=True, timeout=timeout), "insecure"


# ---------------------------------------------------------------- 校验
def validate_file(path, min_lines=None, tolerance=0.95):
    """校验下载内容是否为可用的 FIMI 文本。

    返回 (是否通过, 说明)。
    """
    with open(path, "rb") as f:
        head = f.read(8192).lower()
    if not head.strip():
        return False, "文件为空"
    for marker in (b"<html", b"<!doctype", b"<head", b"<title"):
        if marker in head:
            return False, "内容为 HTML（可能是错误页或证书告警页）"

    num_lines = 0
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for num_lines, _ in enumerate(f, 1):
            pass
    if num_lines < 2:
        return False, "没有有效数据行"
    if min_lines and num_lines < int(min_lines * tolerance):
        return False, "行数 %d，少于预期下限 %d" % (num_lines, int(min_lines * tolerance))
    return True, "共 %d 行" % num_lines


# ---------------------------------------------------------------- 主流程
def download_one(name, data_dir, force=False, allow_insecure=True, mirror=None):
    meta = DATASETS[name]
    dest = os.path.join(data_dir, meta["file"])

    if os.path.isfile(dest) and not force:
        ok, note = validate_file(dest, meta.get("min_lines"))
        if ok:
            print("  [已存在] %s（%s，如需重新下载请加 --force）" % (dest, note))
            return True
        print("  [已存在但校验不通过] %s（%s），将重新下载。" % (dest, note))

    if not candidate_urls(meta["file"], mirror) and "manual" in meta:
        pass  # groceries 走下面的手动分支

    urls = candidate_urls(meta["file"], mirror)
    if name == "groceries":
        urls = []          # 官方无稳定直链，只能手动

    for url in urls:
        print("  尝试 %s" % url)
        try:
            data, note = fetch(url, allow_insecure=allow_insecure)
        except Exception as exc:                       # noqa: BLE001
            print("    失败：%s" % exc)
            continue

        with open(dest, "wb") as f:
            f.write(data)

        ok, message = validate_file(dest, meta.get("min_lines"))
        if ok:
            size_mb = os.path.getsize(dest) / 2 ** 20
            flag = "（未经证书认证）" if note == "insecure" else ""
            print("    完成：%s（%.1f MB，%s）%s" % (dest, size_mb, message, flag))
            return True

        print("    下载内容校验不通过：%s，已丢弃。" % message)
        os.remove(dest)

    # ---------------- 全部失败：打印手动指引 ----------------
    print("  [失败] 所有自动途径均不可用。")
    print("  手动获取方式（任选其一）：")
    print("    ① 命令行绕过证书校验：")
    print("       wget --no-check-certificate -P %s %s" % (data_dir, FIMI_HTTPS + meta["file"]))
    print("       curl -kL -o %s %s" % (dest, FIMI_HTTPS + meta["file"]))
    print("    ② 浏览器打开（可手动忽略证书告警），另存为 %s：" % dest)
    print("       %s" % (FIMI_HTTPS + meta["file"]))
    print("       https://web.archive.org/web/2024/%s" % (FIMI_HTTPS + meta["file"]))
    if "manual" in meta:
        print("    ③ 从 SPMF 数据集页下载：%s" % meta["manual"])
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="下载 FIMI 公开数据集")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--datasets", nargs="*", default=None)
    parser.add_argument("--force", action="store_true", help="强制重新下载")
    parser.add_argument("--strict-ssl", action="store_true",
                        help="禁止跳过证书验证（当前 FIMI 站点证书已过期，可能全部失败）")
    parser.add_argument("--mirror", default=None,
                        help="自定义镜像前缀，例如 https://your-mirror/data/")
    parser.add_argument("--list", action="store_true", help="列出可用数据集")
    args = parser.parse_args(argv)

    if args.list:
        for name, meta in DATASETS.items():
            print("%-12s %s" % (name, meta["desc"]))
        return 0

    os.makedirs(args.data_dir, exist_ok=True)
    names = args.datasets or DEFAULT_DATASETS
    unknown = [n for n in names if n not in DATASETS]
    if unknown:
        sys.exit("未知数据集：%s（可用：%s）" % (unknown, ", ".join(DATASETS)))

    print("提示：FIMI 官方站点证书已过期，脚本会自动降级重试；"
          "如失败请按提示手动下载。\n")

    ok_count = 0
    for name in names:
        print("[%s] %s" % (name, DATASETS[name]["desc"]))
        if download_one(name, args.data_dir, args.force,
                        allow_insecure=not args.strict_ssl, mirror=args.mirror):
            ok_count += 1
        print()

    print("完成：%d/%d 个数据集已就绪于 %s/" % (ok_count, len(names), args.data_dir))
    if ok_count:
        print("下一步：python run_experiment.py --quick")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

