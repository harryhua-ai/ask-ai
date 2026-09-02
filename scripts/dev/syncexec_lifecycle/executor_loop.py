"""执行面替身(stdlib):等价 sync-executor 容器职责(scripts/sync_executor_loop.py)。

轮询 /plane/requests/*.json(生产对应 sync_requests pending 行),
领用(原子改名 = FOR UPDATE SKIP LOCKED 的文件版)后以**子进程**运行
sync_runner.py(生产对应 scripts/sync.py),等待退出并写结果
/plane/results/result-<id>.json。
"""

import json
import subprocess
import sys
import time
from pathlib import Path

REQ = Path("/plane/requests")
RES = Path("/plane/results")
RUN = Path("/plane/running")


def main() -> None:
    for d in (REQ, RES, RUN):
        d.mkdir(parents=True, exist_ok=True)
    print("[executor] plane up", flush=True)
    while True:
        for f in sorted(REQ.glob("req-*.json")):
            claimed = f.with_suffix(f.suffix + ".claimed")
            try:
                f.rename(claimed)  # 原子领用
            except FileNotFoundError:
                continue  # 已被其他副本领走
            req = json.loads(claimed.read_text())
            rid = req["id"]
            print(f"[executor] claimed req {rid}; spawning runner", flush=True)
            marker = RUN / f"run-{rid}.log"
            proc = subprocess.Popen(
                [sys.executable, "/plane/sync_runner.py", str(rid), str(marker)]
            )
            rc = proc.wait()
            (RES / f"result-{rid}.json").write_text(
                json.dumps({"id": rid, "exit_code": rc})
            )
            print(f"[executor] req {rid} finished exit={rc}", flush=True)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
