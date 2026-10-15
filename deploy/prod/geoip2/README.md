# 受信国家信号(Nginx + 本地 GeoIP2 Country)—— 阶段 E 候选工件

- **Issue**: harryhua-ai/ask-ai#114(唯一 Contract 载体;阶段 P 为 A-owned 生产门)
- **状态**: 默认关闭(默认 off)。本目录全部为**离线可审查**工件:配置示例、
  更新/回滚脚本、部署预检、离线安全测试。**不构成生产启用,不宣告 #114 DONE。**
- **日期**: 2026-10-15
- **依据**: #144 生产只读 RCA(CONFIG_OFF + MISSING_HEADER + UNTRUSTED_PEER 三断层)、
  `backend/services/geo_country.py` 四道门、User 选定方案(Nginx + 本地 GeoLite2 Country)
- **隐私红线**: 本目录与配套测试不含真实访客 IP、原始请求头、内网 CIDR、凭据、
  用户请求正文;`<DOCKER_BRIDGE_GATEWAY>` 等占位符由操作者在生产宿主现场推导填充。

---

## 0. 工件清单

| 文件 | 用途 | 对应 AC |
|---|---|---|
| `nginx-geoip2.conf.example` | 宿主 Nginx GeoIP2 边缘配置示例(全注释态;片段 A=http 级 geoip2+map,片段 B=vhost 覆盖同名头) | AC2 |
| `geoip2.env.example` | backend 三元组 env 装配示例(compose `env_file` 通道;全注释态) | AC2 |
| `update-geolite2.sh` | MMDB 合法下载/校验/原子替换/失败恢复/手动回滚(凭据只读宿主 0600 文件) | AC4 |
| `precheck-geoip2.sh` | fail-closed 上线预检(`--expect off\|on` 两态门检,零写面) | AC1/AC5 |
| `../../tests/api/test_geoip2_ingress_contract_offline.py` | AC3 离线安全矩阵(15 用例) | AC3 |
| `../../../tests/deploy/test_geoip2_candidate_static.py` | 默认关闭/凭据红线/原子替换结构断言(11 用例) | AC2/AC4 |

---

## 1. AC1:事实核验与检查方式(2026-10-15 只读 SSH 探针)

检查方式 = 对生产宿主的只读命令(nginx -V / ldconfig / apt-cache / docker inspect /
ls;零写面、零配置变更、零生产 /ask)。逐项结论:

### 1.1 已证(PROVEN)

| # | 事实 | 证据(只读命令) | 对交付的意义 |
|---|---|---|---|
| P1 | 宿主 nginx **1.18.0-6ubuntu14.6**(Ubuntu 22.04 jammy),apt 候选 1.18.0-6ubuntu14.21 同源可升级 | `nginx -v`;`apt-cache policy nginx` | 版本/ABI 基线确定 |
| P2 | **ngx_http_geoip2 动态模块已安装且已挂载**:`/usr/lib/nginx/modules/ngx_http_geoip2_module.so` + `/etc/nginx/modules-enabled/50-mod-http-geoip2.conf`(`load_module`),`nginx -V` 含 `--add-dynamic-module=...http-geoip2`、`--with-compat`;同源包 `libnginx-mod-http-geoip2 1.18.0-6ubuntu14.6` 已装 | `ls /usr/lib/nginx/modules/`;`dpkg -s libnginx-mod-http-geoip2` | **无需编译/跨源装模块** —— #144 决策二(a) 的最大不确定项消除;模块与 nginx 同源包,升级时同步 ABI |
| P3 | geoip2 模块支持 `auto_reload`(.so 内含该指令字符串) | `strings .so \| grep auto_reload` | 原子替换 MMDB 后免 reload 生效 |
| P4 | `libmaxminddb.so.0` 在位(模块运行依赖满足) | `ldconfig -p \| grep maxmind` | 模块可加载 |
| P5 | API 入口拓扑与 #144 一致:唯一代理 vhost(wiki-data 域名,A 记录直连、无 CDN)→ `proxy_pass http://<宿主IP>:18000` → backend 容器;直连 peer = compose 网桥网关 | `grep proxy_pass /etc/nginx/sites-enabled/*`;`docker network inspect tesla-t4_default` | 头只能在 nginx 边缘生产;受信 peer = 网关单地址 |
| P6 | `nginx -t` 基线通过(当前配置零 geo 指令 = 默认关闭态健康) | `nginx -t` | 启用/回退的语法门可用 |
| P7 | 宿主具备更新脚本全部运行依赖:`curl`/`gzip`/`tar`/`python3` 在位(`mmdblookup`/`python3-geoip2` 缺省 → 校验用 python3 stdlib 兜底,已实测合成样本通过) | `which curl gzip tar python3` | update-geolite2.sh 无新增安装依赖 |
| P8 | 后端四道门代码接线在生产 SHA 在位(#144 RCA E1/E11),静态面本候选再次核验:`geo_country.py` 仅 ingress 单一路径,信任门未放宽 | 仓库结构断言(`test_backend_resolver_trust_gate_not_relaxed`) | 不需要任何 backend 代码改动 |

### 1.2 UNKNOWN / owner 前置(任一不满足 ⇒ 保持 off,fail-closed)

| # | 未知项 | 为什么读不到/未定 | 补齐方式(阶段 P 前置) |
|---|---|---|---|
| U1 | **GeoLite2 许可接受与 license key**(MMDB 使用权) | MaxMind 账户/许可接受是 owner 法律行为,B 无权代办(契约 forbidden 项) | owner 在 maxmind.com 接受 GeoLite2 EULA、开户、把 key 写入宿主 `/etc/ask-ai-geoip/geolite2-license.key`(0600) |
| U2 | **MMDB 文件本身** | 宿主全盘探针无任何 `.mmdb`(库从未安装) | U1 之后经 `update-geolite2.sh` 首次下载+校验 |
| U3 | **GeoLite2 数据对真实访客 IP 的命中质量/国家级准确率** | 不对生产 /ask(契约禁项);无真实流量样本可离线度量 | 阶段 P 受控验证:上线后按 §5 观测 `country_source='ingress'` 占比与 Admin 分布,Unknown 比例异常即回退 |
| U4 | **端到端(nginx→backend)真实头可达性** | 同上,禁生产探针;离线矩阵(AC3)已证明 backend 语义,nginx→backend 一跳属运行态 | 阶段 P 单请求受控验证(见 §4 清单第 8 步) |
| U5 | **性能影响数字(p95 等)** | 不虚构实测生产 p95(契约明令);本地微基准不代表生产 GPU 机型负载 | §6 性能验收方法(方法而非数字) |
| U6 | **nginx 1.18.0-6ubuntu14.6 → 14.21 升级后的模块行为** | 当前已装 14.6 与模块同源;14.21 未实装 | 可选:阶段 P 同窗升级 nginx+模块包(同源包 ABI 一致),升级后先 `nginx -t` 再 reload |
| U7 | **生产 .env 是否存在其他覆盖通道** | #144 E3/E10 已证三键零注入;本候选不变更 .env | 阶段 P 装配时按 `geoip2.env.example` 注入并 `precheck --expect on` 复核 |

---

## 2. AC2:设计(默认关闭、可运维审查)

### 2.1 信任链(与 #144 三断层逐一闭合)

```
访客真实 IP
  └─► 宿主 nginx(API vhost,直连无 CDN)
        geoip2 $remote_addr → GeoLite2-Country(本地 MMDB,auto_reload 5m)
        map: 无数据/XX → ""(空串)
  └─► proxy_set_header geo-country $ask_ai_geo_country
        · 无条件存在 ⇒ 客户端同名头恒被 nginx 计算值覆盖;
        · nginx 语义:值为空串 ⇒ 该头不下发 ⇒ 后端拿到 None
  └─► backend resolve_request_country() 四道门(零代码改动):
        mode=ingress(门1)∧ 头名显式配置(门2)∧ 直连 peer ∈ 网关/32(门3)
        ∧ ISO alpha-2 非 XX(门4) ⇒ (ISO,'ingress');否则 (None,None)
```

- **CONFIG_OFF 闭合**: 三键经 compose 既有 `env_file: ../../.env` 通道注入
  (compose 文件零改动,装配示例见 `geoip2.env.example`)。
- **MISSING_HEADER 闭合**: 片段 A 生产 geo 头、片段 B 下发覆盖头。
- **UNTRUSTED_PEER 闭合**: `GEO_TRUSTED_PROXY_CIDRS=<网桥网关>/32` —— 最小化
  单地址授信(不授信整个网桥网段,同网段其他容器无法伪造,符合 #144 决策三)。

### 2.2 明确不作真值的输入(契约禁止项)

Accept-Language / 时区 / 用户输入 / LLM 推断一律不读取;**不配置 real_ip_\***
(X-Forwarded-For 可伪造,不得提升为 `$remote_addr`)。结构断言
`test_nginx_example_does_not_promote_xff_to_remote_addr` 固化。

### 2.3 Unknown 语义全覆盖

| nginx 侧情形 | 下发头 | 后端四门结果 | 持久化 |
|---|---|---|---|
| MMDB 无此 IP/内网/保留段 | 头不下发 | 门4 前短路 | NULL/NULL |
| 库命中 XX(保留占位) | 不下发(map XX→"") | 门4 拒 | NULL/NULL |
| 库命中合法 ISO(如 US) | `geo-country: US` | 四门全过 | US/'ingress' |
| MMDB 缺失/损坏(更新失败窗口) | 头不下发(geoip2 打不开→查不到) | 短路 | NULL/NULL |
| 客户端自带 `geo-country: US` 直打后端 | (不经 nginx) | 门3 拒(非网关 peer) | NULL/NULL |

---

## 3. AC3:离线验证矩阵(零生产 /ask)

全部在本地:真实 ASGI app + 本地测试库 + 真实 resolver + 真实持久化;RAG 用确定性
假流替换;地址全为 loopback/RFC5737 合成值。`tests/api/test_geoip2_ingress_contract_offline.py`:

| 矩阵项 | 用例 | 结果 |
|---|---|---|
| 可信 country header 正常入库(正常路径) | `test_normal_path_trusted_ingress_country_persists` | PASS |
| 外部伪造同名头 + 直连后端攻击面 | `test_client_supplied_same_name_header_from_untrusted_peer_is_unknown` | PASS |
| 空/错误/保留码(XX/usa/U1/空白) | `test_invalid_and_reserved_codes_persist_unknown`(4 参数) | PASS |
| 不受信 peer → Unknown | 上两用例 + `test_budget_declined_path_untrusted_peer_stays_unknown` | PASS |
| proxy 身份头(XFF/X-Real-IP)变更不得绕信任门 | `test_proxy_identity_header_spoofing_cannot_bypass_trust_gate` + `test_hostile_proxy_identity_headers_do_not_degrade_trusted_value` | PASS |
| 三站点共享 API 路径(site_id×3 + legacy + admin) | `test_three_sites_share_api_path_country_resolution` | PASS |
| 正常及预算拒绝持久化路径不回退 | `test_budget_declined_path_persists_trusted_country` + 正常路径用例 | PASS |
| env 装配(默认 off / ingress 三键 / 非法 CIDR fail-closed / 头名大小写) | `test_env_assembly_*`(4 用例) | PASS |

既有回归(未改动,继续通过):`tests/services/test_geo_country.py`(信任边界 12 用例)、
`tests/api/test_routes_country_persistence.py`(DB 持久化 3 用例)、
`tests/db/test_country_truth_migration.py`。结构红线 11 用例见
`tests/deploy/test_geoip2_candidate_static.py`。

---

## 4. AC5:单次受控上线预检清单(阶段 P,A-owned;按序逐项勾选)

前置声明:本清单的执行主体是**受权生产操作者**;第 0-7 步不产生用户可见变化,
第 8 步起进入受控验证。任何一步失败 ⇒ 停止并回退(§4.1),不得带病推进。

0. **授权确认**:User 对「模块/数据来源、变更窗口、回滚、生产验证」的精确授权在案;
   `#138 RELEASE NO-GO` 状态复核(本 Issue 独立于 release,但不得借道发布通道)。
1. **owner 许可**(U1):MaxMind GeoLite2 EULA 已接受;license key 已写入
   `/etc/ask-ai-geoip/geolite2-license.key`,权限 0600。
2. **MMDB 首装**(U2):`sudo deploy/prod/geoip2/update-geolite2.sh`
   → 输出「校验通过」;`sudo .../update-geolite2.sh --verify` 复核。
3. **候选工件就位**:nginx 片段 A/B 按 `.example` 注释指引展开到宿主
   (此刻仍不 reload);backend `.env` 三键按 `geoip2.env.example` 装配(仍注释态)。
4. **预检(expect off)**:`sudo deploy/prod/geoip2/precheck-geoip2.sh --expect off`
   → 全 PASS(确认起点 = #144 基线健康)。
5. **启用边缘**:去掉片段 A/B 注释 → `sudo nginx -t` 通过 → `sudo systemctl reload nginx`。
   (nginx 先行:此窗口内后端仍 off,头被下发但 resolver 短路 ⇒ 零行为变化。)
6. **启用后端**:注释去掉 → `docker compose -f deploy/prod/docker-compose.yml up -d backend`
   → 容器 healthy。
7. **预检(expect on)**:`sudo precheck-geoip2.sh --expect on` → 全 PASS
   (模块/库/MMDB/凭据/peer 推导/CIDR 收敛/三元组/nginx 一致性逐门复验)。
8. **受控端到端**(U4,一次性):受权操作者以自身办公网 IP 经 wiki-data 域名发
   **一条**真实 widget 提问 ⇒ psql 只读复核该行 `country=预期ISO ∧ country_source='ingress'`;
   再以 `curl -H 'geo-country: US'`(伪造头)发一条 ⇒ 落 NULL。
   (此两步为生产 /ask,仅限本清单窗口、操作者自担、各一条。)
9. **观测窗**(≥24h):§7 健康观测三项全部正常;伪造头污染为零(§7c)。
10. **收尾**:观测窗通过 ⇒ 保留 cron 周更新;观测窗失败 ⇒ §4.1 回退 + RCA。

### 4.1 回退 off(任何一步可执行)

```bash
# 1) 断边缘(秒级,零后端影响)
sudo cp -a /etc/nginx/conf.d/ask-ai-geoip2.conf{,.disabled}   # 片段 A 移除
# 或注释 vhost 内片段 B 行
sudo nginx -t && sudo systemctl reload nginx
# 2) 断后端(恢复 #144 基线语义:恒 Unknown)
#   .env 三键重新注释 → docker compose -f deploy/prod/docker-compose.yml up -d backend
# 3) MMDB 异常时:deploy/prod/geoip2/update-geolite2.sh --rollback(或重跑更新)
```

回退后系统行为与 #144 现状完全一致(resolver 第一门短路,恒 Unknown)。

---

## 5. 模块/主机兼容性矩阵(AC1/AC5 汇总)

| 组件 | 要求 | 状态 |
|---|---|---|
| 宿主 nginx | ≥1.11(geoip2 指令集) | **已证 1.18.0-6ubuntu14.6**(P1) |
| geoip2 动态模块 | 与 nginx 同源 ABI + `--with-compat` | **已证已装已挂载**(P2) |
| libmaxminddb0 | ≥1.0.2 | **已证在位**(P4) |
| `auto_reload` | geoip2 模块支持 | **已证**(P3) |
| MMDB(GeoLite2-Country) | 许可合法 + 文件就位 | **UNKNOWN → owner(U1/U2)** |
| license key 凭据管理 | 宿主 0600 文件,不入仓库 | 机制已交付;key 在位性 **UNKNOWN(U1)** |
| 直连 peer | compose 网桥网关单地址 | 拓扑已证(P5);具体地址仅宿主现场推导(红线) |
| 真实访客命中质量 | 国家级估计可用 | **UNKNOWN(U3/U4),阶段 P 验证** |
| 性能 p95 | 无回归 | **UNKNOWN(U5),按 §6 方法验收** |

---

## 6. AC4:性能验收方法(方法,非数字)

不虚构生产 p95。验收在阶段 P 观测窗内按以下口径执行:

1. **基线对照**:启用前 7 天 vs 启用后 7 天,同渠道(site=camthink-website/wiki/store)
   `conversations.response_time_ms` 的 p50/p95 对比(现成遥测,无新埋点)。
   判定:p95 劣化 >10% 且超绝对 200ms ⇒ 复查并考虑回退。
2. **nginx 侧成本口径**:geoip2 查询为进程内 mmap 读,单次微秒级;验证方式 =
   启用前后宿主 `nginx` worker CPU%(如 `pidstat -u -C nginx`)与
   `/var/log/nginx/error.log` 零 geoip2 报错。
3. **MMDB 更新窗口成本**:更新脚本为 curl+gunzip+rename,IO 峰值 <10MB;
   cron 排在 04:17 低峰,失败自动保持旧库(无服务窗口)。

## 7. AC4:最小汇总健康观测(类别级,零 PII)

- **(a) 配置态可见性**:每次 backend 启动在日志输出生效三元组**类别**
  (mode / 头名是否配置 / 受信条目数)——不做生产改动,B 已在测试中锁定
  env 解析语义;该可见性若需产品化属阶段 P 可选增量(不阻塞本候选)。
- **(b) 归因产出**:每周 `SELECT country_source, count(*) FROM conversations
  WHERE created_at > now()-interval '7 days' GROUP BY 1`(只读计数)——
  `ingress` 从 0 变正即链路存活;再归 Unknown 占比异常(>50%)⇒ 检查 MMDB/拓扑。
- **(c) 伪造污染哨兵**:`country_source='ingress'` 行数与 nginx 访问日志量级
  交叉比对;伪造头在四道门下**不可能**产出 'ingress'(AC3 已证),故该值
  出现即代表受信链路产出,无伪造通道。
- **(d) nginx 错误日志**:`grep -c geoip2 /var/log/nginx/error.log` 恒 0
  (模块/MMDB 层故障即在此暴露)。
