"""同步 runner 替身(stdlib):等价 scripts/sync.py 的长跑重型行程。

受控长跑 ~20s:向 marker 文件每秒追加一行心跳(时间戳),供宿主侧
验证「backend 容器重启期间 runner 仍在推进」。生产对应 scripts/sync.py
的真实 fetch/embed/ingest。
"""

import sys
import time
from pathlib import Path

marker = Path(sys.argv[2])
deadline = time.time() + 20
with marker.open("a") as fh:
    while time.time() < deadline:
        fh.write(f"{time.time()}\n")
        fh.flush()
        time.sleep(1)
