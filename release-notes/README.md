# Release Notes 惯例(Issue #10 版本与发布治理)

## 权威关系

- **仓库内 `release-notes/vX.Y.Z.md` = 发布说明的事实源**(本目录);
- **GitHub Release = 仓库发布说明的公开可发现镜像**,不是运行时权威;
- **运行时版本权威 = 镜像内 `RELEASE.json`**(CI 构建期生成,
  见 `scripts/generate_release_manifest.sh` 与 `backend/release.py`)。

## 流程

1. Final RC Assembly 完成后,按模板撰写 `release-notes/vX.Y.Z.md`(各节必填);
2. CI 构建 tag `vX.Y.Z` 镜像(自动内嵌 RELEASE.json 并断言一致);
3. **显式**人工操作:以 `release-notes/vX.Y.Z.md` 为源创建 GitHub Release
   (CI 不会自动创建);
4. 生产部署/回滚:`deploy/prod/update.sh vX.Y.Z`(禁止 latest,三应用服务同 tag)。

## 命名

- 一文件一版本:`vX.Y.Z.md`,与 git tag 字面一致;
- 模板:`TEMPLATE.md`(复制后填写;各节不得删除,无内容写「无」)。
