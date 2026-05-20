"""同步知识库文件到写作应用的知识目录。

从 knowledge_base/泰拉拾遗录/ 复制所有 .md 文件
（排除以下划线开头的文件）到 knowledge/ 目录。
"""

import os
import shutil
import sys


def sync_knowledge():
    source_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "knowledge_base", "泰拉拾遗录")
    )
    target_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "knowledge")
    )

    if not os.path.isdir(source_dir):
        print(f"[错误] 源目录不存在：{source_dir}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(target_dir, exist_ok=True)

    copied = 0
    skipped = 0

    for root, dirs, files in os.walk(source_dir):
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            if fname.startswith("_"):
                skipped += 1
                print(f"  [跳过] {fname} (以下划线开头)")
                continue

            src_path = os.path.join(root, fname)
            dst_path = os.path.join(target_dir, fname)

            shutil.copy2(src_path, dst_path)
            copied += 1
            print(f"  [复制] {fname}")

    print(f"\n完成。共复制 {copied} 个文件，跳过 {skipped} 个（以下划线开头）。")


if __name__ == "__main__":
    sync_knowledge()
