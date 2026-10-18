"""流水线最后一步：把最终发布到日报、精选与 AI 栏目的事件写进 30 天记忆。

单独一步而不是塞在 rank.py 里，是因为 rank 之后还有一次降级筛选。
按 rank 的结果记忆会让降级条目被永久扣分沉底。
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rank import SECTIONS, load_memory, save_memory

TZ = timezone(timedelta(hours=8))


def main():
    digest_path = sys.argv[1] if len(sys.argv) > 1 else "data/digest.json"
    mem_path = sys.argv[2] if len(sys.argv) > 2 else "data/memory.json"

    with open(digest_path, encoding="utf-8") as handle:
        digest = json.load(handle)
    now = datetime.now(timezone.utc).astimezone(TZ)
    memory = load_memory(mem_path, now)

    if digest.get("preview") or digest.get("offline"):
        print("[OK] 试刊/离线检查不写入正式发布记忆")
        return
    sections = SECTIONS if digest.get("schema_version") == 3 else ("lead", "relevant", "threads")
    published = [event for section in sections for event in digest.get(section, [])]
    save_memory(mem_path, memory, published, digest["date"])
    print(f"[OK] 记忆已更新：本次记入 {len(published)} 条，库内共 {len(memory)} 条")


if __name__ == "__main__":
    main()
