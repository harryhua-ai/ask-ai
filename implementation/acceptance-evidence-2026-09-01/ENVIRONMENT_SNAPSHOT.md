# 验收环境快照(2026-09-01)

## 基线核验
- 主仓: /Users/harryhua/Documents/GitHub/ask-ai, branch=main, HEAD=76b2199ff334194a4e145c80ab844726d7e50293
- 合同 BASELINE_COMMIT=76b2199 → 一致 ✓
- 工作树差异: 仅 `.gitignore`(先存本地改动:+.playwright-cli/ +gui-test-screenshots/,非本任务产物,未提交未回滚)
- 运行代码对齐: 本地后端进程(pid 76761)2026-08-31 20:00:02 启动 > 末次提交 16:35:47,backend/**/*.py 无晚于进程启动的 mtime → 本地运行代码=76b2199

## 生产(主验收目标) wiki-data.camthink.ai
- 运行提交: 76d75e7(PRODUCT_STATE 2026-08-31 记载)
- 76d75e7→76b2199 diff(git 实证): backend 仅 admin 3 文件 + main.py(28 行)+ Dockerfile/CI + widget 前端(T29 徽标);**问答管线(routes/services/prompt)零变更** → 生产 /api/ask 行为 ≡ 基线代码行为
- 知识面: 15 源(10 github + 2 filesystem + 1 woocommerce + 1 官网爬取 + 1 测试),PRODUCT_STATE 记 15/15 全绿
- SSE 实测事件契约: sources → token×N → done(conversation_id);declined 拒答事件;无 complete/intent 字段外露(客户端契约本来如此)

## 本地(对照) localhost:8000
- 代码=76b2199(上述已证);postgres+weaviate 本地 docker
- 本地 data_sources 表仅 1 源: website-*(web_crawl, enabled);weaviate Document=3666 chunks(全为 website-camthink/*)
- → 本地知识面 ≈ 官网爬取单源,与生产 15 源严重不对称;本地对照仅用于(1)代码差异行为验证(2)知识面不对称的实证

## channel 决策
- 主跑 channel=admin(产品语义:管理员测试通道,与真实访客 widget 数据池隔离,保护"零真实访客"干净状态)
- widget 通道跑等价性对照 6 题 × 双通道 + 附件 4 场景(附件为 widget 访客真实路径,session_id 归属校验)
- channel 在管线中只影响:Customization 绑定 / 落库归属 / widget 附件归属校验;不影响检索可见性

## 本任务对运行状态的副作用(如实记录,未做任何修复/清理)
- 生产 conversations 表新增 ~107 条 admin/widget 测试对话 + 对应 trace 行;生产 data/attachments 新增 4 个测试附件文件(30 天自动清理策略内)
- 本地 conversations 表新增 6 条对照对话
- 未改任何:代码/测试/prompt/意图规则/检索参数/知识配置/索引/LLM 配置/环境配置;未部署;未重索引
