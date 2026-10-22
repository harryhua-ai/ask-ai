> **ⓘ 状态更新(2026-10-22,通道适配 A 裁决)**:带外采锚与
> PREFLIGHT_TRUST_ANCHOR_B64 写 secret 流程不再是发布前置;目标身份事实已
> 冻结入仓(deploy/prod/production-identity.json,随镜像分发)。本文的
> 只读采集命令与探测面注意事项仍可作为审计复核手段使用。

# v1.6.4-r3｜G2 生产信任锚只读采集清单(Role B 交 A,2026-10-22)

授权边界:本清单全程**只读**(docker inspect/exec 只读命令 + backend /health);
不得修改任何生产状态。锚值本身为非秘密标识(字段语义见
`.github/workflows/deploy-production.yml` 锚注释)。

## 采集命令(单 SSH 会话;B 已于 2026-10-22T02:48:51Z 实测一轮)

| 字段 | 命令(生产宿主) | 2026-10-22 实测值 |
|---|---|---|
| pg_system_id | `docker exec tesla-t4-postgres-1 psql -U ask_ai -d ask_ai -tA -c "SELECT system_identifier FROM pg_control_system();"` | `7670132346517975075` |
| weaviate_cluster_hostname | `docker exec tesla-t4-weaviate-1 printenv CLUSTER_HOSTNAME` | `7adc06acc397` |
| weaviate_image_digest | `docker inspect tesla-t4-weaviate-1 --format '{{.Image}}'` + `--format '{{.Config.Image}}'` | `sha256:b06b9711246633ce1f83d21394ced5a9c18aadfff32c273ae8e25ca06b27f4d2`(`cr.weaviate.io/semitechnologies/weaviate:1.28.0`) |
| weaviate_volume_name | `docker inspect tesla-t4-weaviate-1 --format '{{range .Mounts}}{{if eq .Destination "/var/lib/weaviate"}}{{.Source}}{{end}}{{end}}'` | `tesla-t4_weaviate_data`(卷路径形 `/var/lib/docker/volumes/<名>/_data`) |
| weaviate_volume_manifest_sha256 | `docker exec -i tesla-t4-weaviate-1 sh -s /var/lib/weaviate < scripts/weaviate_volume_manifest_scan.sh` | **须在停写窗口内采集**(见漂移分析文档);R5 时点值 `61675d79…`(581 文件)与 2026-10-22 值 `eb8d940b…`(637 文件)均为活卷漂移采样,不作现行等值断言 |

锚 JSON 组装(version 2 封闭词表,顺序不影响校验):

```json
{"version":2,"pg_system_id":"<SID>","weaviate_cluster_hostname":"<hostname>",
 "weaviate_image_digest":"sha256:<64hex>","weaviate_volume_name":"<卷名>",
 "weaviate_volume_manifest_sha256":"<64hex>"}
```

## 写 secret(A 动作)

```bash
B64=$(printf '%s' "$(cat anchor.json)" | base64)   # macOS: base64 -i anchor.json
gh secret set PREFLIGHT_TRUST_ANCHOR_B64 --env production --body "$B64"
```

部署预检对该 secret fail-closed:缺失/不可读/字段不符/manifest 不一致一律中止。

## 探测面注意(坑)

- 生产 weaviate 容器 **hostname 探测面勿用容器 hostname**(那是 docker 随机名,
  与锚无关);锚绑定的是 compose 注入的 `CLUSTER_HOSTNAME` env 与 `/v1/meta`
  自述,后者受 `_BIND_SHAPE_META_HOSTS` 词表处理。
- 卷扫描必须用 R5 官方脚本 stdin 模式;GNU `find -printf` 在 BusyBox 下
  产出空清单假哈希 `e3b0c442…`,禁止。
