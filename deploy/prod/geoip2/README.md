# 受信国家信号(Nginx + 本地 GeoIP2 Country)—— 阶段 E 候选工件

- **Issue**: harryhua-ai/ask-ai#114(唯一 Contract 载体;阶段 P 为 A-owned 生产门)
- **状态**: 默认关闭(默认 off)。本目录全部为**离线可审查**工件:配置示例、
  更新/回滚脚本、部署预检、离线安全测试。**不构成生产启用,不宣告 #114 DONE。**
- **日期**: 2026-10-15(R2 修正 2026-10-17,见 §8)
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
| `mmdb_validate.py` | MMDB **硬结构校验**(stdlib:完整 metadata 解码 + 字段语义 + 走树越界门;更新脚本与预检共用) | AC4 |
| `precheck_checks.py` | 预检机械门纯函数库(CIDR=网关 /32 精确相等、nginx -T 生效配置覆盖链、发布端口绑定) | AC1/AC5 |
| `update-geolite2.sh` | MMDB 合法下载/硬校验/原子替换/失败恢复/常备回滚(凭据**零 argv**,只进 0600 curl 配置文件) | AC4 |
| `precheck-geoip2.sh` | fail-closed 上线预检(`--expect off\|on` 两态门检 + G8 发布端口边界;全程类别化输出) | AC1/AC5 |
| `../../tests/api/test_geoip2_ingress_contract_offline.py` | AC3 离线安全矩阵(15 用例;TEST_DATABASE_URL fail-closed) | AC3 |
| `../../../tests/deploy/test_geoip2_candidate_static.py` | 默认关闭/凭据红线/机械门负向 fixture/DSN 守卫(49 用例) | AC2/AC4/AC5 |

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
| P5 | API 入口拓扑与 #144 一致:唯一代理 vhost(wiki-data 域名,A 记录直连、无 CDN)→ `proxy_pass http://<宿主IP>:18000` → backend 容器;nginx 转发流量的应用直连 peer = compose 网桥网关 | `grep proxy_pass /etc/nginx/sites-enabled/*`;`docker network inspect tesla-t4_default` | **R2 修正解读**:「直连 peer = 网关」只对 *经 nginx 转发* 的流量成立;见 U8 —— 0.0.0.0 端口发布下其它流量经 DNAT 后同样表现为网关 peer |
| P6 | `nginx -t` 基线通过(当前配置零 geo 指令 = 默认关闭态健康) | `nginx -t` | 启用/回退的语法门可用 |
| P7 | 宿主具备更新脚本全部运行依赖:`curl`/`gzip`/`tar`/`python3` 在位(`mmdblookup`/`python3-geoip2` 缺省 → 校验用 python3 stdlib 硬解析兜底,合成样本正/负实测) | `which curl gzip tar python3` | update-geolite2.sh + mmdb_validate.py 无新增安装依赖 |
| P8 | 后端四道门代码接线在生产 SHA 在位(#144 RCA E1/E11),静态面本候选再次核验:`geo_country.py` 仅 ingress 单一路径,信任门未放宽 | 仓库结构断言(`test_backend_resolver_trust_gate_not_relaxed`) | 不需要任何 backend 代码改动 |

### 1.2 UNKNOWN / owner 前置(任一不满足 ⇒ 保持 off,fail-closed)

| # | 未知项 | 为什么读不到/未定 | 补齐方式(阶段 P 前置) |
|---|---|---|---|
| U1 | **GeoLite2 许可接受与 license key**(MMDB 使用权) | MaxMind 账户/许可接受是 owner 法律行为,B 无权代办(契约 forbidden 项) | owner 在 maxmind.com 接受 GeoLite2 EULA、开户、把 key 写入宿主 `/etc/ask-ai-geoip/geolite2-license.key`(0600) |
| U2 | **MMDB 文件本身** | 宿主全盘探针无任何 `.mmdb`(库从未安装) | U1 之后经 `update-geolite2.sh` 首次下载+硬校验 |
| U3 | **GeoLite2 数据对真实访客 IP 的命中质量/国家级准确率** | 不对生产 /ask(契约禁项);无真实流量样本可离线度量 | 阶段 P 受控验证:上线后按 §5 观测 `country_source='ingress'` 占比与 Admin 分布,Unknown 比例异常即回退 |
| U4 | **端到端(nginx→backend)真实头可达性** | 同上,禁生产探针;离线矩阵(AC3)已证明 backend 语义,nginx→backend 一跳属运行态 | 阶段 P 单请求受控验证(见 §4 清单第 9 步) |
| U5 | **性能影响数字(p95 等)** | 不虚构实测生产 p95(契约明令);本地微基准不代表生产 GPU 机型负载 | §6 性能验收方法(方法而非数字) |
| U6 | **nginx 1.18.0-6ubuntu14.6 → 14.21 升级后的模块行为** | 当前已装 14.6 与模块同源;14.21 未实装 | 可选:阶段 P 同窗升级 nginx+模块包(同源包 ABI 一致),升级后先 `nginx -t` 再 reload |
| U7 | **生产 .env 是否存在其他覆盖通道** | #144 E3/E10 已证三键零注入;本候选不变更 .env | 阶段 P 装配时按 `geoip2.env.example` 注入并 `precheck --expect on` 复核 |
| U8 | **发布端口边界(受信跳可达性)—— R2 新增** | 既有 compose `backend.ports: ["18000:8000"]` **无 loopback 绑定**:Docker 标准端口发布接受任意来源流量,DNAT 后源地址表现为网桥网关 peer,与 nginx 转发流量在门 3 处**不可区分** ⇒ 「网关 /32 授信 = 只有 Nginx 能供 geo-country」在现发布形态下**不成立**。收口(loopback 绑定或等效防火墙)属生产网络面变更,B 无权在本离线候选执行 | **另行授权的收口变更**(§2.4)+ `precheck-geoip2.sh` G8 机械复验;G8 未过 = 保持 off |

---

## 2. AC2:设计(默认关闭、可运维审查)

### 2.1 信任链(与 #144 三断层逐一闭合;UNTRUSTED_PEER 为条件性闭合)

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
- **UNTRUSTED_PEER 条件性闭合**: `GEO_TRUSTED_PROXY_CIDRS=<网桥网关>/32`
  是最小化单地址授信(拒绝整网段,预检 G6b 机械强制**精确相等**);但它
  **必要非充分** —— 只有当发布端口边界收口(U8/§2.4/G8)后,「网关 peer」
  才等价于「来自 nginx 的转发」。收口前 G8 FAIL = 保持 off。

### 2.2 明确不作真值的输入(契约禁止项)

Accept-Language / 时区 / 用户输入 / LLM 推断一律不读取;**不配置 real_ip_\***
(X-Forwarded-For 可伪造,不得提升为 `$remote_addr`)。结构断言
`test_nginx_example_does_not_promote_xff_to_remote_addr` 固化。

### 2.3 Unknown 语义与失败模式(R2 修正:失败模式不再假称良性)

| nginx 侧情形 | 下发头 | 后端四门结果 | 持久化 |
|---|---|---|---|
| MMDB 无此 IP/内网/保留段 | 头不下发 | 门4 前短路 | NULL/NULL |
| 库命中 XX(保留占位) | 不下发(map XX→"") | 门4 拒 | NULL/NULL |
| 库命中合法 ISO(如 US) | `geo-country: US` | 四门全过(**且发布端口边界已收口,§2.4**) | US/'ingress' |
| MMDB 缺失/损坏(更新失败窗口) | **未证实为自动抑制**:geoip2 引用不可读/损坏库可致 `nginx -t` 失败、reload 拒绝或 auto_reload 周期报错(错误日志暴露),而非静默降级为「头不下发」 | — | — |
| 客户端自带 `geo-country: US` 直打后端 | (不经 nginx) | 门3 拒 —— **仅在发布端口边界收口后成立**(U8);0.0.0.0 发布下远程直打 `:18000` 经 DNAT 同样表现为网关 peer,门3 不拒 | — |

> **失败模式处置(fail-closed 而非假安全)**:MMDB 不可读 ⇒ `nginx -t`/reload
> 失败即 **hard-stop**(不 reload、保持旧运行面),按 §4.1 回退(含
> `update-geolite2.sh --rollback` 恢复上一个已验证库);**不得假设** geoip2
> 会自动抑制 header。上两行「未证实」语义同样适用于门3 的直连旁路:在 G8
> 通过之前,本表一切「门3 拒」的断言不构成安全声明。

### 2.4 发布端口边界与需另行授权的网络变更(R1 修正,唯一 P1)

**威胁模型更正**:既有 `deploy/prod/docker-compose.yml` 以
`ports: ["18000:8000"]`(等价 `0.0.0.0:18000`)发布 backend。Docker 标准端口
发布下:(a) 任意外部宿主可直连 `<宿主>:18000`;(b) 同网桥网段任一容器可经
hairpin-NAT 直连 `<宿主>:18000`。两者经 DNAT/SNAT 后源地址都表现为**网桥网关
peer**,与 nginx 转发的直连 peer 在门 3 完全不可区分 ⇒ `网关/32` 授信可被
旁路,「只有 Nginx 能供 geo-country」不成立。README §2.1/§2.3/§7(c) 的相应
断言已按此更正(未证实直至 G8 通过)。

**收口变更(需 owner/受权操作者另行授权;本候选零执行、零触碰)**,二选一:

1. **loopback 绑定**(推荐,compose 语义收口):
   `deploy/prod/docker-compose.yml` backend ports 改为
   `"127.0.0.1:18000:8000"` + `docker compose up -d backend`;
   同窗将 nginx vhost `proxy_pass` 目标改为 `http://127.0.0.1:18000`
   (片段 B 注释已注明;否则 nginx 转发会被绑定拒绝)。
2. **等效防火墙**(不改 compose):宿主防火墙仅允许本机/nginx 来源访问
   18000/tcp,显式拒绝外部与网桥网段其余地址。

**验证**: `sudo deploy/prod/geoip2/precheck-geoip2.sh --expect on` 的
G8(docker inspect HostIp 必须 loopback)+ G8b(宿主 `ss` 监听交叉核验)
双门 PASS;离线结构断言 `check_publish_binding` 固化判定语义。

**回滚**: 恢复原 `ports: ["18000:8000"]` + 原 `proxy_pass` 目标后
`docker compose up -d backend`;nginx 侧同窗还原并 `nginx -t && reload`。
回滚后系统行为与 #144 现状一致(本候选默认 off,resolver 恒 Unknown)。

---

## 3. AC3:离线验证矩阵(零生产 /ask)

全部在本地:真实 ASGI app + **显式专用测试库** + 真实 resolver + 真实持久化;
RAG 用确定性假流替换;地址全为 loopback/RFC5737 合成值。
`tests/api/test_geoip2_ingress_contract_offline.py`:

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

**DSN 纪律(R2 修正)**:测试 DSN 必须经 `TEST_DATABASE_URL` 显式提供且库名含
`test`;缺失/非测试库/APP_MODE=prod 在**收集期拒绝**,绝不回落配置默认 DSN
(默认库名 `ask_ai` 与生产同名)。守卫以子进程导入测试固化于
`tests/deploy/test_geoip2_candidate_static.py`(`test_contract_*` 4 用例:
缺 URL 拒 / 非测试库名拒 / prod 拒 / 显式测试库过)。站点种子/清理只
管理本组合成 site_id 行,不无差别清理共享表。

既有回归(未改动,继续通过):`tests/services/test_geo_country.py`(信任边界 12 用例)、
`tests/api/test_routes_country_persistence.py`(DB 持久化 3 用例)、
`tests/db/test_country_truth_migration.py`。结构红线与机械门负向 fixture
49 用例见 `tests/deploy/test_geoip2_candidate_static.py`。

---

## 4. AC5:单次受控上线预检清单(阶段 P,A-owned;按序逐项勾选)

前置声明:本清单的执行主体是**受权生产操作者**;第 0-8 步不产生用户可见变化,
第 9 步起进入受控验证。任何一步失败 ⇒ 停止并回退(§4.1),不得带病推进。

0. **授权确认**:User 对「模块/数据来源、变更窗口、回滚、生产验证」的精确授权在案;
   `#138 RELEASE NO-GO` 状态复核(本 Issue 独立于 release,但不得借道发布通道)。
1. **owner 许可**(U1):MaxMind GeoLite2 EULA 已接受;license key 已写入
   `/etc/ask-ai-geoip/geolite2-license.key`,权限 0600。
2. **MMDB 首装**(U2):`sudo deploy/prod/geoip2/update-geolite2.sh`
   → 输出「硬结构校验通过」;`sudo .../update-geolite2.sh --verify` 复核。
3. **发布端口边界收口**(U8,§2.4,**需单独授权**):loopback 绑定(或等效
   防火墙)+ nginx `proxy_pass` 目标同步;**在 G8 通过前,后续一切启用步骤
   禁止执行**。
4. **预检(expect off)**:`sudo deploy/prod/geoip2/precheck-geoip2.sh --expect off`
   → 确认起点 = #144 基线健康。G8 在未收口时 FAIL 属预期(fail-closed:
   启用被阻断);第 3 步完成后 G8 必须转 PASS。
5. **候选工件就位**:nginx 片段 A/B 按 `.example` 注释指引展开到宿主
   (此刻仍不 reload);backend `.env` 三键按 `geoip2.env.example` 装配
   (CIDR = `<DOCKER_BRIDGE_GATEWAY>/32`,仍注释态)。
6. **启用边缘**:去掉片段 A/B 注释 → `sudo nginx -t` 通过 → `sudo systemctl reload nginx`。
   (nginx 先行:此窗口内后端仍 off,头被下发但 resolver 短路 ⇒ 零行为变化。)
7. **启用后端**:注释去掉 → `docker compose -f deploy/prod/docker-compose.yml up -d backend`
   → 容器 healthy。
8. **预检(expect on)**:`sudo precheck-geoip2.sh --expect on` → **全 PASS**
   (模块/库/MMDB 硬校验/凭据/peer 推导/CIDR=网关 /32 精确相等/三元组/
   nginx -T 生效配置覆盖链/发布端口边界逐门复验;任一 FAIL ⇒ 保持 off)。
9. **受控端到端**(U4,一次性):受权操作者以自身办公网 IP 经 wiki-data 域名发
   **一条**真实 widget 提问 ⇒ psql 只读复核该行 `country=预期ISO ∧ country_source='ingress'`;
   再以 `curl -H 'geo-country: US'`(伪造头)发一条 ⇒ 落 NULL。
   (此两步为生产 /ask,仅限本清单窗口、操作者自担、各一条。)
10. **观测窗**(≥24h):§7 健康观测各项正常且 §7(c) 边界语义成立(已收口)。
11. **收尾**:观测窗通过 ⇒ 保留 cron 周更新;观测窗失败 ⇒ §4.1 回退 + RCA。

### 4.1 回退 off(任何一步可执行;各步独立,前一步失败不得中止后步)

```bash
# 1) 断边缘(秒级,零后端影响;真禁用 = 移出 conf.d 的 *.conf include 通配)
sudo mv /etc/nginx/conf.d/ask-ai-geoip2.conf /etc/nginx/conf.d/ask-ai-geoip2.conf.disabled
# (或:vhost 内注释片段 B 行 —— 二者做其一即可断链,建议先只做此步)
sudo nginx -t && sudo systemctl reload nginx \
  || { sudo mv /etc/nginx/conf.d/ask-ai-geoip2.conf.disabled /etc/nginx/conf.d/ask-ai-geoip2.conf; \
       echo "nginx -t 失败,已恢复原片段配置;继续执行第 2 步"; }
# 2) 断后端(独立执行,恢复 #144 基线语义:恒 Unknown)
#   .env 三键重新注释 → docker compose -f deploy/prod/docker-compose.yml up -d backend
# 3) MMDB 异常时:deploy/prod/geoip2/update-geolite2.sh --rollback
#   (成功更新后 .bak 恒保留 = 上一个已验证有效库;--rollback 校验后原子换回)
```

> ⚠️ `cp -a xxx.conf{,.disabled}` **不是禁用**(原文件仍在 include 内)——
> 必须用 `mv` 移出通配。`nginx -t` 失败只回滚本步的片段变更并继续第 2 步,
> 不得中断后端断链。回退后系统行为与 #144 现状完全一致(resolver 第一门短路,
> 恒 Unknown)。

---

## 5. 模块/主机兼容性矩阵(AC1/AC5 汇总)

| 组件 | 要求 | 状态 |
|---|---|---|
| 宿主 nginx | ≥1.11(geoip2 指令集) | **已证 1.18.0-6ubuntu14.6**(P1) |
| geoip2 动态模块 | 与 nginx 同源 ABI + `--with-compat` | **已证已装已挂载**(P2) |
| libmaxminddb0 | ≥1.0.2 | **已证在位**(P4) |
| `auto_reload` | geoip2 模块支持 | **已证**(P3) |
| MMDB(GeoLite2-Country) | 许可合法 + 文件就位 + **硬结构校验通过** | **UNKNOWN → owner(U1/U2)** |
| license key 凭据管理 | 宿主 0600 文件,零 argv,不入仓库 | 机制已交付;key 在位性 **UNKNOWN(U1)** |
| 直连 peer | compose 网桥网关单地址(CIDR 精确相等) | 拓扑已证(P5);**边界未收口 = UNKNOWN(U8)** |
| 发布端口边界 | 发布端口仅 loopback(或等效防火墙) | **未收口(U8)→ 另行授权变更(§2.4)+ G8 复验** |
| 真实访客命中质量 | 国家级估计可用 | **UNKNOWN(U3/U4),阶段 P 验证** |
| 性能 p95 | 无回归 | **UNKNOWN(U5),按 §6 方法验收** |

---

## 6. AC4:性能验收方法(方法,非数字)

不虚构生产 p95,亦不宣称组件级微秒数(R2 修正:原「单次微秒级」为未经实测
的口径,已删)。验收在阶段 P 观测窗内按以下口径执行:

1. **基线对照**:启用前 7 天 vs 启用后 7 天,同渠道(site=camthink-website/wiki/store)
   `conversations.response_time_ms` 的 p50/p95 对比(现成遥测,无新埋点)。
   判定:p95 劣化 >10% 且超绝对 200ms ⇒ 复查并考虑回退。
2. **nginx 侧成本口径**:geoip2 查询为进程内 mmap 读(数量级未实测,不宣称);
   验证方式 = 启用前后宿主 `nginx` worker CPU%(如 `pidstat -u -C nginx`)与
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
- **(c) 伪造污染哨兵(R2 修正:未证实前不构成防伪造证明)**:
  `country_source='ingress'` 行数与 nginx 访问日志量级交叉比对。**在发布端口
  边界收口(U8/§2.4)并经 G8 验证之前,'ingress' 行不排除 DNAT 旁路伪造
  通道,不得当作「无伪造通道」的证明;收口之后,'ingress' 出现才与受信
  链路产出相符,异常放量仍须先复核 G8 边界再排查数据。
- **(d) nginx 错误日志**:`grep -c geoip2 /var/log/nginx/error.log` 应恒 0;
  非 0 即模块/MMDB 层故障信号 ⇒ 按 §2.3 失败模式处置(hard-stop/回滚),
  不假设自动降级。

---

## 8. R2 修正记录(A 五项阻塞逐条处置)

| # | A 阻塞 | 处置 |
|---|---|---|
| 1 | 已发布 backend 旁路击穿信任边界(P1) | 威胁模型更正(§2.4 + U8 + §2.1/§2.3/§7c 条件化);预检新增 G8/G8b:发布端口必须仅 loopback,0.0.0.0/:: 绑定 FAIL=保持 off,收口变更(§2.4)明确记载为另行授权 + 验证 + 回滚;本候选零 compose/防火墙改动、不发明信任 CIDR、未测前不报生产 ingress 安全 |
| 2 | precheck 假 PASS(G6 整网段 / G7 源码 grep) | G6b 改为受信 CIDR 与网关 /32 **精确相等**(`precheck_checks.check_trusted_cidrs_exact`,整网段/多Entry/非网关必拒);G7 改为 `nginx -T` **生效配置**机械解析(geoip2+auto_reload+map 兜底+无条件同名头覆盖+location 继承语义+if/静态值拒绝);G5 全程类别化输出(真实网关/子网/CIDR 不回显);负向 fixture 固化于静态测试(整网段、注释指令、静态值、location 遮蔽、if 包裹必拒) |
| 3 | GeoLite2 key/MMDB 校验/回滚不安全 | 凭据**零 argv**(只进 0600 curl 配置文件 `-K`;stderr 经脱敏器抹 key/license_key 后输出;不 set -x);MMDB 校验 = `mmdb_validate.py` 硬结构解析(完整 metadata 解码+字段语义+布局一致+走树越界门,合成 MMDB 正/负样本单测);成功更新后 **保留 .bak**(--rollback 恒可用,旧实现成功即删);§4.1/示例回退改 `mv` 真禁用 + 各步独立/nginx -t 失败不中断;离线负测覆盖(成功替换后回滚可用、畸形 MMDB 拒、凭据不暴露、损坏配置回退序列) |
| 4 | 离线测试可能写非测试库 | `TEST_DATABASE_URL` 强制显式 + 库名含 `test` + APP_MODE=prod 拒绝,收集期 fail-closed(`_resolve_test_dsn` 先于任何 load_settings);种子/清理只作用本组合成 site_id 行;4 个子进程守卫测试证明缺 URL/非测试库/prod 均不可运行 |
| 5 | 文档准确性 | §2.3 失败模式改为「未证实为自动抑制,hard-stop/回滚处置」;§6 删除未实测微秒口径(方法保留、数字不宣称);§7(c) 改为「未证实直至边界收口+G8 验证」;§2.1/§5 同步条件化 |
