import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type {
  RepoDiscoveryGroup,
  RepoDiscoveryResult,
} from "@/types/api";

export interface PolicyChipsProps {
  fileTypes: string[];
  excludeDirs: string[];
  onChange: (next: { file_types: string[]; exclude_dirs: string[] }) => void;
}

function ChipRow({
  label,
  items,
  onRemove,
  onAdd,
  addPlaceholder,
  addAriaLabel,
}: {
  label: string;
  items: string[];
  onRemove: (item: string) => void;
  onAdd: (item: string) => void;
  addPlaceholder: string;
  addAriaLabel: string;
}) {
  const [draft, setDraft] = useState("");
  const submit = () => {
    const v = draft.trim();
    if (!v) return;
    onAdd(v.startsWith(".") || !v.includes("/") ? v.toLowerCase() : v);
    setDraft("");
  };
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        {items.map((t) => (
          <span
            key={t}
            className="inline-flex items-center gap-1 rounded-md border bg-muted/40 px-1.5 py-0.5 text-xs"
          >
            {t}
            <button
              type="button"
              aria-label={`移除 ${t}`}
              className="text-muted-foreground hover:text-foreground"
              onClick={() => onRemove(t)}
            >
              ×
            </button>
          </span>
        ))}
        {items.length === 0 && (
          <span className="text-xs text-muted-foreground">无</span>
        )}
      </div>
      <Input
        value={draft}
        aria-label={addAriaLabel}
        placeholder={addPlaceholder}
        className="h-8 w-56 text-xs"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            submit();
          }
        }}
        onBlur={submit}
      />
    </div>
  );
}

/**
 * #16 Simple Mode:已采用策略的可视化微调(chips 直接绑定表单的
 * file_types / exclude_dirs 两个字段,与高级选项的原始输入同源)。
 * 仅做增删——不重判知识价值;技术安全边界在同步灌入时仍由后端强制。
 */
export function PolicyChips({ fileTypes, excludeDirs, onChange }: PolicyChipsProps) {
  if (fileTypes.length === 0 && excludeDirs.length === 0) return null;
  return (
    <div className="space-y-2 rounded-md border bg-muted/20 p-3">
      <p className="text-xs font-medium">已应用的纳入策略(可直接增删)</p>
      <ChipRow
        label="文件类型"
        items={fileTypes}
        addPlaceholder="添加文件类型,如 .csv"
        addAriaLabel="添加文件类型"
        onRemove={(t) =>
          onChange({ file_types: fileTypes.filter((x) => x !== t), exclude_dirs: excludeDirs })
        }
        onAdd={(t) =>
          !fileTypes.includes(t) &&
          onChange({ file_types: [...fileTypes, t], exclude_dirs: excludeDirs })
        }
      />
      <ChipRow
        label="排除目录"
        items={excludeDirs}
        addPlaceholder="添加排除目录,如 examples"
        addAriaLabel="添加排除目录"
        onRemove={(t) =>
          onChange({ file_types: fileTypes, exclude_dirs: excludeDirs.filter((x) => x !== t) })
        }
        onAdd={(t) =>
          !excludeDirs.includes(t) &&
          onChange({ file_types: fileTypes, exclude_dirs: [...excludeDirs, t] })
        }
      />
    </div>
  );
}

export interface RepoDiscoveryPanelProps {
  result: RepoDiscoveryResult;
  /** 采用推荐策略(后端编译产物原样上送表单,前端不二次推导)。 */
  onApply: (config: { file_types: string[]; exclude_dirs: string[] }) => void;
  /** #22 会话内组决策(键 = 组键);与 onDecide 成对提供。 */
  decisions?: Record<string, DiscoveryDecision>;
  /** #22 组决策:纳入/排除/恢复推荐(null = 清除决策)。 */
  onDecide?: (groupKey: string, decision: DiscoveryDecision | null) => void;
}

export type DiscoveryDecision = "include" | "exclude";

/**
 * #22:推荐基线 ⊕ 会话组决策 → 生效策略字段(纯函数,可单测)。
 *
 * 单一权威仍是表单的 file_types/exclude_dirs(sync 唯一消费源);决策
 * 只是「 sugar」:include = 该组技术安全成员的扩展名并入白名单 + 目录
 * 移出排除;exclude = 目录进排除(connector 语义:exclude_dirs 胜过
 * 白名单,少数派机械不进范围)。恢复推荐 = 删除决策后按基线重算。
 */
export function applyRepoDecisions(
  result: RepoDiscoveryResult,
  decisions: Record<string, DiscoveryDecision> = {},
): { file_types: string[]; exclude_dirs: string[] } {
  const fileTypes = new Set(result.recommended_config.file_types ?? []);
  const excludeDirs = new Set(result.recommended_config.exclude_dirs ?? []);
  for (const [key, decision] of Object.entries(decisions)) {
    if (decision === "include") {
      for (const c of result.candidates) {
        if (groupOf(c.path) !== key || !c.technical_safe) continue;
        const lastDot = c.path.lastIndexOf(".");
        if (lastDot > -1 && lastDot > c.path.lastIndexOf("/")) {
          fileTypes.add(c.path.slice(lastDot).toLowerCase());
        }
      }
      excludeDirs.delete(key);
    } else if (decision === "exclude") {
      excludeDirs.add(key);
    }
  }
  return { file_types: [...fileTypes].sort(), exclude_dirs: [...excludeDirs].sort() };
}

const REC_META: Record<
  string,
  { label: string; variant: "success" | "secondary" | "warning" }
> = {
  include: { label: "建议纳入", variant: "success" },
  exclude: { label: "建议排除", variant: "secondary" },
  review: { label: "待人工确认", variant: "warning" },
};

/** 与后端 top_level_group 同规则:嵌套取首段,根文件归“(根目录)”。 */
function groupOf(path: string): string {
  return path.includes("/") ? path.split("/", 1)[0] : "(根目录)";
}

/** 分组 → 组内去重人读理由(最多 2 条;后端冻结文案原样呈现)。 */
function groupReasons(result: RepoDiscoveryResult, key: string): string[] {
  const reasons: string[] = [];
  for (const c of result.candidates) {
    if (groupOf(c.path) !== key) continue;
    if (!reasons.includes(c.reason)) reasons.push(c.reason);
    if (reasons.length >= 2) break;
  }
  return reasons;
}

function GroupSection({
  groups,
  result,
  decisions,
  onDecide,
}: {
  groups: RepoDiscoveryGroup[];
  result: RepoDiscoveryResult;
  decisions?: Record<string, DiscoveryDecision>;
  onDecide?: (groupKey: string, decision: DiscoveryDecision | null) => void;
}) {
  if (groups.length === 0) return null;
  return (
    <div className="space-y-1">
      {groups.map((g) => {
        const reasons = groupReasons(result, g.key);
        const decided = decisions?.[g.key];
        return (
          <div key={g.key} className="space-y-0.5 text-sm">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-medium">{g.key}</span>
              <span className="text-xs text-muted-foreground">{g.count} 个文件</span>
              {g.admin_decision && (
                <span
                  className="rounded-md border border-blue-200 bg-blue-50 px-1 text-xs text-blue-700"
                  title="来自已保存的发现策略,后续发现自动继承"
                >
                  已按策略
                </span>
              )}
              {g.recommendation === "include" && g.scope_confirmed === true && (
                <span
                  className="text-xs text-emerald-600"
                  title="该组全部建议纳入文件都在生效策略范围内"
                >
                  ✓ 范围已确认
                </span>
              )}
              {g.recommendation === "include" && g.scope_confirmed === false && (
                <span
                  className="text-xs text-amber-600"
                  role="alert"
                  title="该组有建议纳入文件不在生效策略范围内,请核对文件类型/排除清单"
                >
                  ⚠ 范围未确认
                </span>
              )}
              {(g.member_excluded ?? 0) > 0 && (
                <span className="text-xs text-muted-foreground">
                  {g.member_excluded} 个已排除
                </span>
              )}
              {(g.member_review ?? 0) > 0 && (
                <span
                  className="text-xs text-amber-600"
                  title="组内存在待人工确认成员;该部分不进入采用策略的生效范围,直至组被决定"
                >
                  {g.member_review} 个待确认
                </span>
              )}
              {reasons.map((r) => (
                <span key={r} className="text-xs text-muted-foreground">
                  {r}
                </span>
              ))}
            </div>
            {onDecide && (
              <div className="flex flex-wrap items-center gap-1">
                {decided ? (
                  <>
                    <span className="text-xs text-muted-foreground">
                      已决定:{decided === "include" ? "纳入" : "排除"}
                    </span>
                    <button
                      type="button"
                      className="text-xs text-muted-foreground underline hover:text-foreground"
                      onClick={() => onDecide(g.key, null)}
                    >
                      恢复推荐
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className="text-xs text-emerald-700 underline hover:text-emerald-900"
                      onClick={() => onDecide(g.key, "include")}
                    >
                      纳入
                    </button>
                    <button
                      type="button"
                      className="text-xs text-muted-foreground underline hover:text-foreground"
                      onClick={() => onDecide(g.key, "exclude")}
                    >
                      排除
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** #16 Simple Mode:仓库内容发现预览(S0 共享契约的呈现层)。

推荐/理由/能力边界全部为后端冻结产物,这里只分组直呈;「采用推荐策略」
把 recommended_config 原样写入表单的既有 config 字段,不创建第二套语义。
 */
export function RepoDiscoveryPanel({ result, onApply, decisions, onDecide }: RepoDiscoveryPanelProps) {
  const byRec = (rec: string) => result.groups.filter((g) => g.recommendation === rec);
  const includeGroups = byRec("include");
  const excludeGroups = byRec("exclude");
  const reviewGroups = byRec("review");
  const rec = result.recommended_config;
  const fileTypes = rec.file_types ?? [];
  const excludeDirs = rec.exclude_dirs ?? [];
  const inheritedRules = (result.target as { inherited_rules?: number }).inherited_rules ?? 0;

  return (
    <Card aria-label="仓库内容发现">
      <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
        <CardTitle className="text-base">仓库内容发现</CardTitle>
        <Badge variant="outline">{result.target.branch}</Badge>
      </CardHeader>
      <CardContent className="space-y-3 p-4 pt-0 text-sm">
        <p className="text-muted-foreground">
          共 {result.totals.files} 个文件 · 技术安全 {result.totals.safe_files} 个
          {result.totals.unsafe_files > 0
            ? ` · ${result.totals.unsafe_files} 个存在技术安全限制(密钥/二进制/超大),任何配置不可纳入`
            : ""}
        </p>

        {result.warnings.map((w) => (
          <p
            key={w}
            className="rounded-md border border-yellow-200 bg-yellow-50 p-2 text-xs text-yellow-800"
            role="alert"
          >
            {w}
          </p>
        ))}

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-2">
            <Badge variant={REC_META.include.variant}>{REC_META.include.label}</Badge>
            <GroupSection groups={includeGroups} result={result} decisions={decisions} onDecide={onDecide} />
          </div>
          <div className="space-y-2">
            <Badge variant={REC_META.exclude.variant}>{REC_META.exclude.label}</Badge>
            <GroupSection groups={excludeGroups} result={result} decisions={decisions} onDecide={onDecide} />
          </div>
          <div className="space-y-2">
            <Badge variant={REC_META.review.variant}>{REC_META.review.label}</Badge>
            <GroupSection groups={reviewGroups} result={result} decisions={decisions} onDecide={onDecide} />
            {reviewGroups.length > 0 && (
              <p className="text-xs text-muted-foreground">
                仅真正无法安全判定的组需要决定;决定一次后按策略保存,后续发现不再重复询问。
              </p>
            )}
            {reviewGroups.length === 0 && (
              <p className="text-xs text-muted-foreground">无待确认组(推荐可直接采用)</p>
            )}
          </div>
        </div>
        {inheritedRules > 0 && (
          <p className="text-xs text-blue-700">
            已继承 {inheritedRules} 条已保存的发现策略(带「已按策略」标记的组不再重复询问)。
          </p>
        )}

        <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
          <span>推荐纳入类型:</span>
          {fileTypes.length > 0 ? (
            fileTypes.map((t) => (
              <span key={t} className="rounded border px-1 font-mono">
                {t}
              </span>
            ))
          ) : (
            <span>无</span>
          )}
          <span className="ml-2">推荐排除目录:</span>
          {excludeDirs.length > 0 ? (
            excludeDirs.map((t) => (
              <span key={t} className="rounded border px-1 font-mono">
                {t}
              </span>
            ))
          ) : (
            <span>无</span>
          )}
        </div>

        {result.capability_notes.length > 0 && (
          <details className="rounded-md border p-2 text-xs text-muted-foreground">
            <summary className="cursor-pointer font-medium text-foreground">能力边界说明</summary>
            <ul className="mt-1 list-disc space-y-1 pl-4">
              {result.capability_notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </details>
        )}

        <Button
          type="button"
          size="sm"
          onClick={() => onApply(applyRepoDecisions(result, decisions))}
        >
          采用推荐策略
        </Button>
      </CardContent>
    </Card>
  );
}
