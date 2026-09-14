/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track F**(证据聚合)
 * Wave 1 专属 —— 侧板 meta 计数区(data-panel-stats)+ 相关数据源卡区
 * (data-panel-sources)。
 *
 * Wave 1 实现(track-f-contract U-17/U-18;matrix-TI TI-27/TI-33):
 * - meta 行三项计数并排:相关提问 · 受影响回答 · 涉及用户。「涉及用户」
 *   = 后端权威聚合(GET /tech/answer-gaps/{id}/users,伪匿名会话去重,
 *   聚合窗=IF-7 所选分析窗);unavailable 态诚实呈现(身份真值不足 →
 *   「涉及用户 证据不可用」,不编造计数)。零前端估算。
 * - 相关数据源卡:后端权威归因投影(GET /tech/answer-gaps/{id}/sources,
 *   证据规则 conversation_citation_identity_match);外链深链
 *   /data-sources/:id 真实跳转;无归因证据 → 诚实空态,零猜测。
 * 数据经 useQuery 自取(同 GapPanel convQuery 模式;Integration 壳零编辑)。
 * window prop = IF-7 接线点:Integration 合并时由壳传入共享分析窗;
 * 独立运行默认 "all"(与既有 meta 计数的 gap 全证据跨度一致)。
 * v1.6.3 既有两项计数+最近发生呈现逐字保留。
 */

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { AnswerGapItem } from "@/lib/api/techInsight";
import {
  fetchGapSources,
  fetchGapUsers,
  type EvidenceWindowValue,
} from "@/lib/api/techEvidence";
import { relTime } from "./relTime";

export interface PanelStatsProps {
  gap: AnswerGapItem;
  /** U-17 聚合窗(IF-7 词表);Integration 接线点,默认 all。 */
  window?: EvidenceWindowValue;
  /** 显式起止窗(Integration 接线:壳 window=range:from/to 时由壳传入;
   * 提供时后端以 from/to 为权威评估窗,preset 仅作参数形态)。 */
  from?: string;
  to?: string;
}

/** 外链图标(参考 PNG 源卡外链 icon 呈现)。 */
function ExternalLinkIcon() {
  return (
    <svg
      data-source-external
      aria-hidden
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}

export function PanelStats({ gap, window = "all", from, to }: PanelStatsProps) {
  const usersQuery = useQuery({
    queryKey: ["gap-users", gap.id, window, from ?? null, to ?? null],
    queryFn: () => fetchGapUsers(gap.id, window, from, to),
    retry: false,
  });
  const sourcesQuery = useQuery({
    queryKey: ["gap-sources", gap.id],
    queryFn: () => fetchGapSources(gap.id),
    retry: false,
  });

  const users = usersQuery.data;
  // U-17 诚实三态:权威计数 / 证据不可用(身份真值不足或投影读取失败)/ 加载中。
  let usersFragment: string;
  if (usersQuery.isPending) {
    usersFragment = "涉及用户 …";
  } else if (users && users.users_available && users.users !== null) {
    usersFragment = `涉及 ${users.users} 个用户`;
  } else {
    usersFragment = "涉及用户 证据不可用";
  }

  const sourceItems = sourcesQuery.data?.items ?? [];
  const unmatched = sourcesQuery.data?.unmatched_citations ?? [];

  return (
    <div data-panel-stats className="mt-2 text-[12px] text-[var(--t2)]">
      <div>
        {gap.question_count} 次相关提问 · {gap.impacted_answer_count} 次受影响回答 ·{" "}
        <span data-panel-users>{usersFragment}</span>
      </div>
      <div className="mt-0.5 text-[var(--t3)]">最近发生:{relTime(gap.last_seen_at)}</div>

      <div className="mt-3" data-panel-sources>
        <h3 className="mb-1 text-[13px] font-medium text-[var(--t1)]">相关数据源</h3>
        {sourcesQuery.isLoading ? (
          <div className="text-[12px] text-[var(--t3)]">加载中...</div>
        ) : sourcesQuery.isError ? (
          <div className="text-[12px] text-[var(--t3)]">证据不可用:归因投影读取失败</div>
        ) : sourceItems.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {sourceItems.map((s) => (
              <Link
                key={s.source_id}
                to={`/data-sources/${s.source_id}`}
                data-source-card
                data-source-id={s.source_id}
                title={`证据规则:${s.evidence_rule};${s.citing_conversations} 条归属会话引用了该源身份`}
                className="flex items-center gap-1.5 rounded-md border px-2 py-1 text-[12px] text-[var(--t1)] hover:bg-black/5"
                style={{ borderColor: "var(--bd)" }}
              >
                <span
                  aria-hidden
                  className="flex h-4 w-6 items-center justify-center rounded-sm text-[9px] font-semibold uppercase"
                  style={{ background: "color-mix(in srgb, var(--acc) 12%, transparent)", color: "var(--acc)" }}
                >
                  {s.source_type.slice(0, 2)}
                </span>
                <span className="capitalize">{s.source_type}</span>
                <span className="text-[var(--t3)]">/</span>
                <span>{s.product}</span>
                <span className="text-[var(--t3)]">
                  <ExternalLinkIcon />
                </span>
              </Link>
            ))}
          </div>
        ) : sourcesQuery.data &&
          sourcesQuery.data.citing_conversations_total === 0 ? (
          <div className="text-[12px] text-[var(--t3)]" data-sources-unavailable>
            无归因证据:归属会话无引用来源记录,系统不做猜测
          </div>
        ) : (
          <div className="text-[12px] text-[var(--t3)]" data-sources-unavailable>
            无归因证据:归属会话引用未命中现存数据源身份,系统不做猜测
            {unmatched.length > 0 &&
              `(${unmatched.length} 类引用无对应数据源行)`}
          </div>
        )}
      </div>
    </div>
  );
}
