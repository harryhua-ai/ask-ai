/**
 * Ownership(IF-6 附录,文件内区域互斥):本文件 = **Track E**(观察与导出)
 * Wave 1 专属 —— 历史记录 tab 内容(data-panel-history)。
 * Wave 1(track-e-contract「历史 Tab 渲染全部流转事件」U-15)在本文件内实现
 * 观察流转历史,不编辑 GapPanel/AnswerGapsTab(Integration 壳仅消费稳定
 * props=gap;面板内自取数据可循 GapPanel convQuery 的 useQuery 模式)。
 *
 * Track E 其余将来区域(本 Wave 均无实现,零占位控件/零观察语义):
 * - 导出卡(U-16):absent-by-contract,渲染挂载面由 Track E 在 Wave 1
 *   于本文件(或 E 新建导出面板文件)内落地,Integration 壳不预设;
 * - 队列工具栏观察态 filter:plan §3.2「观察态 filter=E」将来区域;
 *   Wave 1 若需接入队列查询状态,经 Integration 轨按 IF-6 仲裁接线。
 * v1.6.3 既有诚实呈现逐字保留:历史呈「证据不可用」,系统不做推断。
 */

import type { AnswerGapItem } from "@/lib/api/techInsight";

export interface PanelHistoryProps {
  /** 诊断侧板当前缺口(Wave 1 U-15 流转历史数据挂载面;本 Wave 未读取)。 */
  gap: AnswerGapItem;
}

export function PanelHistory(_props: PanelHistoryProps) {
  return (
    <section data-panel-history>
      <div className="text-[12px] leading-5 text-[var(--t3)]">
        证据不可用:v1.6.3 暂无该缺口的权威历史记录(观察/流转)数据,
        系统不做推断。
      </div>
    </section>
  );
}
