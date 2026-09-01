"""Phase-3 假设实验(机制验证,零代码改动):
before 检索 → 本地 weaviate 将 knowledge-* chunk 置 internal → after 检索 → 公开源控制组 → 还原。
"""
import sys
sys.path.insert(0, "/Users/harryhua/Documents/GitHub/ask-ai")
import weaviate

client = weaviate.connect_to_local()
coll = client.collections.get("Document")

KNOW_PREFIXES = ("knowledge-d341da15/", "knowledge-1db4e151/")
know = []
for o in coll.iterator(return_properties=["source_id", "channel_visibility"]):
    sid = o.properties.get("source_id", "")
    if sid.startswith(KNOW_PREFIXES):
        know.append((o.uuid, sid, tuple(o.properties.get("channel_visibility") or [])))
orig_vis = know[0][2] if know else ("widget", "api")
print(f"[setup] knowledge chunks={len(know)} original_visibility={orig_vis}", flush=True)

from backend.embedder.bge import BGEEmbedder
from backend.retrieval.search import HybridSearcher

embedder = BGEEmbedder(device="cpu", batch_size=8, max_length=8192)
searcher = HybridSearcher(client, embedder)

SIM_Q = "NE101 照片无法上传云端 蜂窝网络注册被拒 SIM 卡不匹配"
PUB_Q = "NE301 的工作温度范围是多少"

def probe():
    hits = searcher.search(query=SIM_Q, limit=20, channel="widget")
    know_hits = [r for r in hits if r.source_id.startswith(KNOW_PREFIXES)]
    bucket = searcher.search_bucket(query=SIM_Q, source_types=["filesystem"], limit=20, channel="widget")
    know_bucket = [r for r in bucket if r.source_id.startswith(KNOW_PREFIXES)]
    pub = searcher.search(query=PUB_Q, limit=5, channel="widget")
    return (len(hits), len(know_hits), len(know_bucket),
            (know_hits[0].source_id[:40] if know_hits else "-"),
            len(pub), (pub[0].source_id[:30] if pub else "-"))

print(f"[BEFORE] total={probe()}", flush=True)

# 置为 internal(仅本地实验,结束后还原)
for uuid, _, _ in know:
    coll.data.update(uuid=uuid, properties={"channel_visibility": ["internal"]})
print(f"[mutate] knowledge-* -> ['internal'] ({len(know)} objs)", flush=True)

print(f"[AFTER ] total={probe()}", flush=True)

# 还原
for uuid, _, _ in know:
    coll.data.update(uuid=uuid, properties={"channel_visibility": list(orig_vis)})
print(f"[restore] knowledge-* -> {list(orig_vis)} ({len(know)} objs)", flush=True)
client.close()
