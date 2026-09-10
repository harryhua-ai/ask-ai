# V1.4.0 Production Runtime + Real-World Acceptance Report

- 状态:**FINAL PASS**(本报告即守卫契约 `deployments/acceptance/1.4.0.json` 的 `report_path` 证据文件)
- 冻结发布:tag `v1.4.0` / release SHA `41278f07eb4abbf4f3420b2d7b65db28c7fdcbb1`
- 生产部署:workflow run `34467038970`,authoritative Deployment `6369778394`(success)
- 观察窗口:2026-09-10 10:45–11:35Z;模式:READ-ONLY / NATURAL PRODUCTION ACCEPTANCE
  (零部署动作、零容器操作、零 DB/配置变异;仅正常用户可见请求 + 只读探查)
- 执行方式:真实 Chromium(In-app Browser,桌面 1440×900 / 移动 390×844)访问真实生产站点;
  页面内 150ms 采样器 + console/error/fetch hook 结构化实录;执行侧证据工件(11 张截图 + 全量记录)
  存于执行机 `~/Documents/ask-ai-acceptance/v140-runtime-20260910/`(含 ACCEPTANCE-EVIDENCE.md),不入库

## 生产路径

真实生产站点 `https://www.camthink.ai`(site_id=camthink-website)hydration 后加载
`wiki-data.camthink.ai` 的 `/widget/widget.js`、`/widget/ask-ai-widget.css`、
`/api/widget/site-config?site_id=camthink-website` —— 被测对象即生产运行时。

## 门结论

1. **Runtime identity / stability:PASS** —— `/health` 两次核验 `200 {ok,1.4.0,41278f07…,production}`;
   三容器镜像 `ghcr.io/harryhua-ai/ask-ai:v1.4.0`,StartedAt=部署 rollout 窗口,RestartCount=0;
   Deployment 6369778394=success 无漂移;schema `launcher_presentation` varchar(10) nullable。
2. **Widget delivery:PASS** —— 真实站点加载生产 widget 资源;Origin fail-closed 实证
   (未授权 origin→403「站点未授权或来源不受信任」,无 Origin→403);launcher 首帧即最终形态(#33)。
3. **Real LLM streaming:PASS**(本发布此前唯一未决项)—— 真实提问后实测:
   `✦ Preparing an answer…` 等待态 → 首个真实 token 原位替换(t≈+13.4s,len 0→2)→
   19 个渐进增长采样点(len→2022,内联引用 0→7)→ 完成(反馈行现、输入再启用)→
   追问同链再证(会话延续)。无三点/伪进度 UI;无独立 Sources 区块(内联引用为验收面)。
   API 直测:SSE = sources → 234×token → done,answer 4,656 字符,sources 返回
   wiki.camthink.ai 文档链接 ×2,均 HTTP 200。
4. **I-UX-001 窄对比:PASS** —— #33 首帧一致;#38 生产 Admin SPA bundle 实测含
   Entry & Engagement / Appearance / Authorized Websites / Preview 四分区,三域 API 在用,
   未认证 401;#39 桌面 mini→面板生长叙事实测,移动端(清洁会话)B nudge 呈现、
   mini/面板绝不自动展开,Trusted Actions 全站 published=0(≤2);
   **#36(Admin 预览品牌)、#37(Preview/Test 主题不落盘)、#40 reduced-motion = UNPROVEN**
   (需 Admin 登录——执行凭证不入转写;reduced-motion 自动化不可达;冻结代码/单测契约佐证)。
5. **Core business smoke:PASS** —— 两次真实 widget 问答 + 一次授权 Origin 的 API 问答探针全部成功;
   证据链接可用(200);Admin 生产在用;Widget 完成后可用。
6. **Observability:PASS** —— backend 自部署起 ERROR/Traceback=0;无 UndefinedColumnError /
   ModuleNotFoundError / TEST_DATABASE_URL 迁移错误;容器 RestartCount=0。
   已知非回归项:sync-cron 10:41Z 2 篇 website 文档 embed 失败(`text exceeds max_length=1024`),
   属同步 ingest 内容类(对应 follow-up #45),非本发布回归,不并入闭环。

## 透明披露

- 验收窗口内,生产三站 `launcher_presentation` 由运营者本人经已认证 Admin 会话
  (`PUT /api/admin/widget-experience/{camthink-store,camthink-wiki}`,200)从 NULL 置为 `pill`。
  本验收由此在真实生产同时行使了两种语义:NULL → legacy 圆形图标 FAB、`pill` → 品牌胶囊
  「✦ Ask AI」(DOM `button.ask-ai-launcher-pill`,textContent `✦Ask AI`),两态渲染均正确,
  运行身份全程无漂移 —— "Launcher presentation becomes site-configurable" 获生产级实证。
- WebM 录制 API 两次产物为空(录制器局限),以 PNG 帧序列(11 帧)+ in-page 结构化时间线替代。

## 证据局限声明

上述 UNPROVEN 三项为本报告全部未直接观测项;其余结论均来自真实生产路径的直接观察。
本报告不含任何 secret / .env 内容 / 私钥材料。
