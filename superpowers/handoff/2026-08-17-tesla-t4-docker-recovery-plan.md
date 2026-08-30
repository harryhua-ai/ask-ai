# tesla-t4 Docker 全量恢复预案

> 2026-08-17 事故:overlay2 层全部物理消失(126/126 layerdb 记录指向空目录),14 个容器靠 mmap 残活。
> 数据卷/宿主 bind mount 全部完好。本预案目标:**14 容器全部恢复,数据零丢失**。
> 预计停机:60-90 分钟(公共镜像 pull 15-30min + 3 个本地镜像 rebuild)。

## 已就绪的准备(停机前完成,无损)

| 材料 | 位置 |
|---|---|
| 容器配置快照(config.v2.json + hostconfig.json,62M) | `tesla-t4:~/docker-recovery/containers-config/` |
| 恢复清单(14 容器全参数 JSON) | `tesla-t4:~/docker-recovery/recovery-manifest.json` |
| 网络子网记录 | 见下表 |
| 数据卷 | `/var/lib/docker/volumes/`(**全程只读不动**) |

原网络子网(重置后会漂移,如有外部依赖需按原值重建):

| 网络 | 子网 |
|---|---|
| tesla-t4_default | 172.24.0.0/16 |
| model-portal_default | 172.23.0.0/16 |
| camthink-analytics_default | 172.21.0.0/16 |
| locate-anything-service_default | 172.20.0.0/16 |
| aitoolstack_default | 172.19.0.0/16 |

已确认无子网外部依赖:nginx 反代走 `127.0.0.1:18000` 端口映射;umami airgap 规则已清。

## 阶段 A:停机 + 重置(约 10 分钟)

```bash
# A1. 前置:owners 已确认窗口
# A2. 收拢备份(root 下的快照挪到 ubuntu 家目录)
sudo cp -a /root/docker-recovery/containers-config /home/ubuntu/docker-recovery/ 2>/dev/null

# A3. 停 daemon(全部容器终止,含别人服务)
sudo systemctl stop docker docker.socket
pgrep -x dockerd && echo "还在,等待" || echo "已停"

# A4. 重置数据目录(白名单 mv,保留 volumes;old-state 留作回退/取证)
sudo mkdir -p /home/ubuntu/docker-recovery/old-state
cd /var/lib/docker
for d in containers image overlay2 buildkit containerd network runtimes plugins swarm tmp; do
  [ -e "$d" ] && sudo mv "$d" /home/ubuntu/docker-recovery/old-state/
done
ls /var/lib/docker/   # 应只剩 volumes/ 等

# A5. 配国内镜像加速(docker.io 直连不可靠;腾讯云内网 mirror)
sudo tee /etc/docker/daemon.json <<'EOF'
{ "registry-mirrors": ["https://mirror.ccs.tencentyun.com"] }
EOF

# A6. 起 daemon = 全新状态
sudo systemctl start docker
docker info | head -5 && docker volume ls   # 卷应显示 6 个
```

## 阶段 B:公共镜像 + ask-ai 优先恢复

```bash
# B1. 拉镜像(顺序即优先级;ask-ai 9.55G 最久,先发起)
docker pull ghcr.io/harryhua-ai/ask-ai:latest &
docker pull postgres:16-alpine mysql:8.4 cr.weaviate.io/semitechnologies/weaviate:1.28.0 nginx:alpine ossrs/srs:5 eclipse-mosquitto:2.0
wait

# B2. ask-ai 全栈(external 卷自动接上;weaviate CLUSTER_HOSTNAME 已在 compose 固定)
cd ~/ask-ai/deploy/prod && docker compose up -d
# 验证:backend healthy;curl -s localhost:18000/health
# 冒烟:curl -sN -X POST https://wiki-data.camthink.ai/api/ask -H 'Content-Type: application/json' -d '{"message":"NE301 参数"}' | head -c 300

# B3. 手动容器 ×3(配置全在宿主 bind,机械重建)
docker run -d --name hls-server --restart unless-stopped \
  -p 18080:80 \
  -v /home/ubuntu/srs/htdocs:/usr/share/nginx/html:ro \
  -v /home/ubuntu/srs/nginx-hls.conf:/etc/nginx/conf.d/default.conf:ro \
  nginx:alpine

docker run -d --name srs --restart unless-stopped \
  -p 11935:1935 -p 18085:1985 \
  -v /home/ubuntu/srs/srs.conf:/usr/local/srs/conf/docker.conf \
  -v /home/ubuntu/srs/htdocs:/usr/local/srs/htdocs \
  -v /home/ubuntu/srs/logs:/usr/local/srs/logs \
  ossrs/srs:5

docker run -d --name camthink-mosquitto --restart always \
  -p 1883:1883 \
  -v /home/AIToolStack/mosquitto/data:/mosquitto/data \
  -v /home/AIToolStack/mosquitto/log:/mosquitto/log \
  -v /home/AIToolStack/mosquitto/config:/mosquitto/config \
  eclipse-mosquitto:2.0

# B4. 别人的数据层(本地镜像 build 完再起 app)
cd ~/model-portal && docker compose up -d db
cd /opt/zhenglp-app/camthink-analytics/deploy && docker compose up -d mysql
```

## 阶段 C:本地镜像 rebuild(与 B 并行;磁盘 16G,逐个来,每个后 `docker builder prune -f`)

```bash
# C1. model-portal(源码+Dockerfile 在 ~/model-portal)
cd ~/model-portal && docker compose build app && docker compose up -d

# C2. locate-anything(GPU 容器!compose 在 ~/locate-anything-service)
#    等效手动命令(若 compose 无 gpus 配置时用):
#    docker run -d --name locate-anything --restart unless-stopped \
#      --runtime nvidia --gpus all -p 9380:9380 \
#      -e HF_HOME=/models/huggingface -e LOCATE_ANYTHING_MODEL=nvidia/LocateAnything-3B \
#      -v locate-models:/root/.cache/huggingface locate-anything-service
cd ~/locate-anything-service && docker compose up -d --build

# C3. camthink-analytics(zhenglp 源码,git 完整;migrate/api/web 三个镜像都要 build)
cd /opt/zhenglp-app/camthink-analytics/deploy && docker compose build && docker compose up -d
```

## 阶段 D:验证清单

| 服务 | 验证 |
|---|---|
| ask-ai backend | `curl -s localhost:18000/health` → ok;公网 /api/ask SSE 出 sources |
| ask-ai sync | `docker logs tesla-t4-sync-cron-1` 下一轮无 fork 错误 |
| ask-ai pg/weaviate | 端到端 ask 验证即覆盖;`docker ps` 两容器 Up |
| model-portal | `curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:8000/` 非 000 |
| camthink | web `127.0.0.1:3006`;mysql `docker exec camthink-analytics-mysql-1 mysqladmin ping` |
| srs | `curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:8080/` = 415 |
| hls | `curl -s 127.0.0.1:18080/` 响应 |
| mosquitto | `nc -z 127.0.0.1 1883` 通 |
| locate-anything | `curl 127.0.0.1:9380` 响应 + `nvidia-smi` 见进程 |

## 回退与不可逆点

- **数据零风险**:`volumes/` 与所有宿主 bind mount 全程不触碰,任何步骤失败数据都在。
- 阶段 A4 的 `mv` 完全可逆(mv 回 + 重启 daemon 即回到当前状态——虽无意义,但保底)。
- **唯一硬前提**:执行前 owners(zhenglp、AIToolStack、model-portal/locate-anything 使用方)已收到停机通知。

## 风险登记

1. **磁盘 16G**:镜像 pull ~3G + 逐个 build。每步 `df -h /` 检查,build 间 `docker builder prune -f`;不够就先清 `/home/ubuntu/docker-recovery/old-state`(取证完成后)。
2. **docker.io 拉取慢/失败**:A5 已配腾讯云内网 mirror;仍失败备选 docker.1ms.run 等公共 mirror。
3. **postgres/mysql 小版本漂移**(tag 拉 latest 小版本):16.x/8.4.x 数据目录兼容,风险极低。
4. **mysql init 脚本**:init-shadow.sql 只在空库执行,现有卷数据直接用,不会重跑。
5. **rebuild 失败**(依赖缺/网络):逐个隔离,失败不阻塞其他服务;owner 后备。
6. **sync-cron ~21:45 下一轮可能挂**:`|| true` 兜底,无碍;停机窗口本来就覆盖。
7. root 常驻 python(9380 之外的宿主 :9380 服务)与 llama-server 是宿主进程,不受影响。

## 收尾(恢复完成后)

- `old-state/` 保留一周取证后删除
- 加磁盘监控:`df` > 90% 告警(cron 脚本)
- 更新 memory(ask-ai-image-corrupt-layer)与 tesla-t4 skill env.md
- 复盘记录:磁盘余量管理是根因,长期 91-96% 不可再犯

## 停机窗口协调清单(执行前用户确认)

- [ ] zhenglp(camthink-analytics,mysql/web/api 中断)
- [ ] model-portal 使用方(app+db 中断)
- [ ] locate-anything 使用方(9380 中断)
- [ ] AIToolStack / 流媒体使用方(mosquitto/srs/hls 中断)
- [ ] ask-ai(自家,wiki-data.camthink.ai 短暂不可用)
