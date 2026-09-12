/**
 * 数据源编辑器纯模型(类型/schema/映射;v1.6.3 B1 从 DataSources.tsx 抽出,
 * 供列表页与详情页共用的 SourceEditorDrawer 消费;行为与原实现逐字等价)。
 */

import { z } from "zod";
import type { DataSource } from "@/types/api";

// 决策 2A:github 为唯一 git 源类型(local_git 降为实现细节,不再暴露给用户)
// Task 4:woocommerce 进数据源类型枚举
// C8B:web_crawl 进枚举(C8 后端 connector 已交付),关闭"未知类型归一 github"对爬站源的编辑陷阱
export const SOURCE_TYPES = ["github", "filesystem", "woocommerce", "web_crawl"] as const;
export type SourceType = (typeof SOURCE_TYPES)[number];

export const formSchema = z
  .object({
    id: z.string().optional(),
    type: z.enum(["github", "filesystem", "woocommerce", "web_crawl"]),
    product: z.string().min(1, "产品线必填"),
    enabled: z.boolean(),
    sync_interval: z.string().regex(/^\d+[hm]$/, "格式如 24h 或 30m"),
    repo_url: z.string().optional(),
    clone_path: z.string().optional(),
    root_path: z.string().optional(),
    upload_mode: z.boolean().optional(),
    branches: z.string().optional(),
    file_types: z.string().optional(),
    include_dirs: z.string().optional(),
    exclude_dirs: z.string().optional(),
    exclude_regex: z.string().optional(),
    max_file_size: z.string().optional(),
    store_url: z.string().optional(),
    consumer_key: z.string().optional(),
    consumer_secret: z.string().optional(),
    base_url: z.string().optional(),
    sitemap_url: z.string().optional(),
    exclude_patterns: z.string().optional(),
    crawl_delay_ms: z.string().optional(),
    // #22 持久发现策略(治理记忆):组/家族决定落此键,随 config 保存,
    // 后续发现自动继承;非表单输入字段,由组决策控件维护。
    discovery_rules: z
      .array(
        z.object({
          pattern: z.string(),
          decision: z.enum(["include", "exclude"]),
          kind: z.string().nullable().optional(),
          origin: z.string().nullable().optional(),
          decided_at: z.string().nullable().optional(),
          note: z.string().nullable().optional(),
        }),
      )
      .optional(),
  })
  .superRefine((v, ctx) => {
    if (v.type === "web_crawl" && !(v.base_url ?? "").trim()) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["base_url"], message: "站点地址必填" });
    }
  });

export type FormValues = z.infer<typeof formSchema>;

export const EMPTY_FORM: FormValues = {
  id: "",
  type: "github",
  product: "",
  enabled: true,
  sync_interval: "24h",
  repo_url: "",
  clone_path: "",
  root_path: "",
  upload_mode: false,
  branches: "",
  file_types: "",
  include_dirs: "",
  exclude_dirs: "",
  exclude_regex: "",
  max_file_size: "",
  store_url: "",
  consumer_key: "",
  consumer_secret: "",
  base_url: "",
  sitemap_url: "",
  exclude_patterns: "",
  crawl_delay_ms: "",
  discovery_rules: [],
};

// Task 3:类型中文可读名映射(未知值降级原始 key)
// #50 B1:详情工作面复用本映射(单一出处,不复制第二份)
export const TYPE_LABELS: Record<string, string> = {
  github: "代码仓库",
  local_git: "代码仓库",
  filesystem: "文件目录",
  woocommerce: "商城",
  web_crawl: "网站爬取",
};

export function splitComma(s: string | undefined): string[] {
  if (!s) return [];
  return s
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/** config 取字符串字段(非字符串/缺失返回空串)。 */
export function cfgStr(cfg: Record<string, unknown>, key: string): string {
  const v = cfg[key];
  return typeof v === "string" ? v : "";
}

/**
 * github/local_git 源的仓库 URL:优先 config.repo_url;
 * 历史 local_git 源 DB 里只有 repo_path(本地 clone 路径),按 camthink-ai 约定
 * 由 repo_path 末段重建 repo_url(与 dsToForm 编辑回填同规则),不裸显本地路径。
 */
export function githubRepoUrl(ds: DataSource): string {
  const cfg = ds.config || {};
  const explicit = cfgStr(cfg, "repo_url");
  if (explicit) return explicit;
  const repoPath = cfgStr(cfg, "repo_path");
  if (!repoPath) return "";
  const repoName = repoPath.split("/").filter(Boolean).pop() ?? "";
  return repoName ? `https://github.com/camthink-ai/${repoName}.git` : "";
}

/**
 * 按数据源类型取"来源地址"副标题:
 * github/local_git → githubRepoUrl(由 repo_path 重建,不裸显本地路径),
 * filesystem → root_path,woocommerce → store_url。
 * href 非 null 表示是可点击 URL(http 开头)。
 * #50 B1:详情工作面复用本函数(单一出处,不复制第二份)。
 */
export function sourceLocation(ds: DataSource): { text: string; href: string | null } {
  const cfg = ds.config || {};
  let text = "";
  switch (ds.type) {
    case "github":
    case "local_git":
      text = githubRepoUrl(ds);
      break;
    case "filesystem":
      text = cfgStr(cfg, "root_path");
      break;
    case "woocommerce":
      text = cfgStr(cfg, "store_url");
      break;
    case "web_crawl":
      text = cfgStr(cfg, "base_url");
      break;
  }
  return { text, href: text.startsWith("http") ? text : null };
}

/**
 * #22:组决策 → config.discovery_rules 治理记忆(同 pattern+kind 先删后插;
 * decision=null 表示恢复推荐 = 删除该规则)。decided_at 记录决策时间。
 */
export function upsertDiscoveryRule(
  rules: NonNullable<FormValues["discovery_rules"]>,
  kind: "github" | "web_crawl",
  pattern: string,
  decision: "include" | "exclude" | null,
): NonNullable<FormValues["discovery_rules"]> {
  const rest = rules.filter((r) => !(r.pattern === pattern && (r.kind ?? null) === kind));
  if (!decision) return rest;
  return [
    ...rest,
    {
      pattern,
      decision,
      kind,
      origin: "admin",
      decided_at: new Date().toISOString(),
      note: null,
    },
  ];
}

/** 把表单值组装成后端 config dict(按 type 分发)。 */
export function buildConfig(v: FormValues): Record<string, unknown> {
  switch (v.type) {
    case "github":
      return {
        repo_url: v.repo_url || "",
        clone_path: v.clone_path || "",
        branches: splitComma(v.branches),
        file_types: splitComma(v.file_types),
        exclude_dirs: splitComma(v.exclude_dirs),
        exclude_regex: v.exclude_regex || "",
        max_file_size: v.max_file_size ? Number(v.max_file_size) : undefined,
        ...(v.discovery_rules?.length ? { discovery_rules: v.discovery_rules } : {}),
      };
    case "filesystem":
      return {
        root_path: v.upload_mode ? "" : v.root_path || "",
        upload_mode: v.type === "filesystem" ? v.upload_mode : false,
        file_types: splitComma(v.file_types),
        include_dirs: splitComma(v.include_dirs),
        exclude_dirs: splitComma(v.exclude_dirs),
        exclude_regex: v.exclude_regex || "",
        max_file_size: v.max_file_size ? Number(v.max_file_size) : undefined,
      };
    case "woocommerce":
      return {
        store_url: v.store_url || "",
        consumer_key: v.consumer_key || "",
        consumer_secret: v.consumer_secret || "",
      };
    case "web_crawl": {
      // 与 connectors/web_crawl.py 约定一致:可选键留空即不写 config。
      // #17:sitemap_url 缺省 = 自动发现(robots 指令 → 通用回退),不再
      // 钉死 {base_url}/sitemap_index.xml;exclude_patterns 提供时替换默认
      // 排除清单(自动发现后由推荐清单回填,保证「预览=同步视野」)。
      const delay = Number(v.crawl_delay_ms);
      return {
        base_url: (v.base_url || "").trim(),
        ...(v.sitemap_url?.trim() ? { sitemap_url: v.sitemap_url.trim() } : {}),
        ...(splitComma(v.exclude_patterns).length > 0
          ? { exclude_patterns: splitComma(v.exclude_patterns) }
          : {}),
        ...(v.crawl_delay_ms && Number.isFinite(delay) ? { crawl_delay_ms: delay } : {}),
        ...(v.discovery_rules?.length ? { discovery_rules: v.discovery_rules } : {}),
      };
    }
    default:
      return {};
  }
}

/** 从 DataSource 反解出表单值(用于编辑预填)。 */
export function dsToForm(ds: DataSource): FormValues {
  const cfg = ds.config || {};
  const toStr = (v: unknown): string => {
    if (Array.isArray(v)) return (v as string[]).join(", ");
    return typeof v === "string" || typeof v === "number" ? String(v) : "";
  };
  const known = (SOURCE_TYPES as readonly string[]).includes(ds.type)
    ? (ds.type as SourceType)
    : "github";
  // 历史 local_git 源在 DB 中 config 仍为 repo_path 结构;
  // 编辑时归一为 github 表单,同时把 repo_path 等价转换为
  // repo_url + clone_path(与 scripts/migrate_github_source_schema.py
  // build_github_config 同规则),避免"类型变了但配置字段丢了"。
  const repoPath = toStr(cfg.repo_path);
  return {
    ...EMPTY_FORM,
    id: ds.id,
    type: known,
    product: ds.product,
    enabled: ds.enabled,
    sync_interval: ds.sync_interval,
    repo_url: githubRepoUrl(ds),
    clone_path: toStr(cfg.clone_path) || repoPath,
    root_path: toStr(cfg.root_path),
    upload_mode: cfg.upload_mode === true,
    branches: toStr(cfg.branches),
    file_types: toStr(cfg.file_types),
    include_dirs: toStr(cfg.include_dirs),
    exclude_dirs: toStr(cfg.exclude_dirs),
    exclude_regex: toStr(cfg.exclude_regex),
    max_file_size: cfg.max_file_size != null ? String(cfg.max_file_size) : "",
    store_url: toStr(cfg.store_url),
    consumer_key: toStr(cfg.consumer_key),
    consumer_secret: toStr(cfg.consumer_secret),
    base_url: toStr(cfg.base_url),
    sitemap_url: toStr(cfg.sitemap_url),
    exclude_patterns: toStr(cfg.exclude_patterns),
    crawl_delay_ms: cfg.crawl_delay_ms != null ? String(cfg.crawl_delay_ms) : "",
    discovery_rules: Array.isArray(cfg.discovery_rules)
      ? (cfg.discovery_rules as FormValues["discovery_rules"])
      : [],
  };
}

/** ISO 时间 → 本地可读时间(如 "07-31 14:30")，非法/空输入返回 "—"。 */
export function formatSyncTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 上传落盘根目录(与后端 _upload_root 同语义)。 */
export const uploadRootOf = (sourceId: string) => `data/uploads/data-sources/${sourceId}`;

// #17 Website Simple Mode:发现方式与推荐结论的展示文案(后端冻结语义)
export const DISCOVERY_MODE_LABELS: Record<string, string> = {
  explicit: "已使用手动指定的 Sitemap",
  robots: "已自动检测 Sitemap(robots.txt 声明)",
  generic: "已自动检测 Sitemap(标准地址)",
  none: "未检测到 Sitemap",
};

export const REC_META: Record<string, { label: string; className: string }> = {
  include: { label: "建议纳入", className: "text-green-600" },
  exclude: { label: "排除", className: "text-destructive" },
  review: { label: "待确认", className: "text-amber-600" },
};

/** repo_url → {owner, repo}(与后端 _REPO_URL_RE 一致),用于"拉取分支"预览。 */
export function parseRepoUrl(url: string): { owner: string; repo: string } | null {
  const m = url.match(/github\.com\/([^/]+)\/([^/]+?)(?:\.git)?\/?$/i);
  return m ? { owner: m[1], repo: m[2] } : null;
}
