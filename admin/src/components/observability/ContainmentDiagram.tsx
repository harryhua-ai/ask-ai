/** 信号关系图示(诊断异常 ⊃ 真实失败;降级恢复为独立信号,不嵌套)。

语义依据(合同 OBS-03/§10,与 backend tech.py _classify_trace 同源):
- 诊断异常 = 超性能阈值或含错误证据,包含真实失败;
- 真实失败 = generation_error(用户收到失败文案);
- 降级恢复 = 性能降级但用户仍获回答,与异常/失败正交。
 */
export default function ContainmentDiagram({
  anomaly,
  fail,
  recovered,
}: {
  anomaly: number;
  fail: number;
  recovered: number;
}) {
  return (
    <div data-containment className="grid grid-cols-2 gap-3">
      <div
        data-level="anomaly"
        className="rounded border-2 p-2"
        style={{ borderColor: "var(--warn)" }}
      >
        <div className="text-[11px] text-[var(--t2)]">
          诊断异常 {anomaly}
          <span className="text-[var(--t3)] ml-1">(信号,≠失败)</span>
        </div>
        <div
          data-level="fail"
          className="rounded border-2 p-2 mt-1.5"
          style={{ borderColor: "var(--err)" }}
        >
          <div className="text-[11px] text-[var(--t2)]">真实失败 {fail}</div>
        </div>
      </div>
      <div
        data-level="recovered"
        className="rounded border-2 p-2 self-start"
        style={{ borderColor: "var(--acc)" }}
      >
        <div className="text-[11px] text-[var(--t2)]">
          降级恢复 {recovered}
        </div>
        <div className="text-[10px] text-[var(--t3)] mt-1">
          降级但已恢复,用户仍获回答
        </div>
      </div>
    </div>
  );
}
