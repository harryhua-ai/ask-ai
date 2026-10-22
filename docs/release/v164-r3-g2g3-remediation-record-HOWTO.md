> **ⓘ 状态更新(2026-10-22,通道适配 A 裁决)**:本 HOWTO 描述的 RSA 签发与
> 四项 PREFLIGHT_* Environment Secrets 发布依赖已按 A 正式授权退出发布链
> (User 无私钥/新增秘密配置通道)。本文件与其引用的工件/记录**保留为历史
> 审计记录,不篡改**;现行部署通道见 `.github/workflows/deploy-production.yml`
> 头注与 `deploy/prod/update.sh` [1.3/6] deployed-version 回滚守卫。

# v1.6.4-r3 整改记录签发 HOWTO(A 专属;B 无私钥、不代签)

物料(本目录,B 已备,均非秘密):

1. `v164-r3-g2g3-remediation-artifact.md` —— 实际证据工件,字节已冻结,
   SHA256 = `72ee99903274a0753a3e3236704251e131af2d79aa6be62a1a96d1f4464e62c9`
   (= 记录 `evidence_digest`;改动即失配)。
2. `v164-r3-g2g3-remediation-record.unsigned.json` —— v3 记录模板。

A 步骤:

1. Tag/Release 授权落定后,以 tag 目标 40-hex SHA 填 `release_sha`
   (评估器按 `[0-9a-f]{40}` 校验,并与部署 `--release-sha` 精确绑定);
2. 填 `not_after`(ISO8601;建议 = 签发时刻 +72h,须覆盖实际部署窗口);
3. `scripts/sign_remediation_approval.py --private-key <A 离线私钥> \\
   --record <填好的记录> --emit-public-key approval-pub.json`
   (纯 stdlib RSA-2048 PKCS#1 v1.5;私钥仅 A 受控路径,绝不进仓库/CI/容器);
4. 写 production Environment secrets(名称必须逐字符一致):
   - `PREFLIGHT_TRUST_ANCHOR_B64` ← G2 锚 JSON base64(停写窗口采集,见
     `v164-r3-g2-trust-anchor-runbook.md`);
   - `PREFLIGHT_REMEDIATION_EVIDENCE_B64` ← 签名后完整记录 JSON base64;
   - `PREFLIGHT_REMEDIATION_EVIDENCE_ARTIFACT_B64` ← 工件文件 base64(≤64KB 上限,本件 ~5KB);
   - `PREFLIGHT_REMEDIATION_APPROVAL_PUBKEY_B64` ← 公钥 JSON base64;
5. 同停写窗口内 dispatch 部署(预检对四 secret 全部 fail-closed;
   双因子 = 工件摘要一致 + RSA 签名有效,缺一即 BLOCKED)。

语义锚(git 057dd1d3):评估器 `scripts/release_preflight.py` v3 记录词表;
签发侧 `scripts/sign_remediation_approval.py`;gate 词源
`deploy/prod/compatibility.json → remediation_gate`。
