/** 包含关系图示(异常 ⊃ retry ⊃ 失败,带计数)。 */
export default function ContainmentDiagram({
  anomaly,
  retry,
  fail,
}: {
  anomaly: number;
  retry: number;
  fail: number;
}) {
  return (
    <div data-containment className="space-y-1.5">
      <div
        data-level="anomaly"
        className="rounded border-2 p-2"
        style={{ borderColor: "var(--warn)" }}
      >
        <div className="text-[11px] text-[var(--t2)]">异常 {anomaly}</div>
        <div
          data-level="retry"
          className="rounded border-2 p-2 mt-1.5"
          style={{ borderColor: "var(--acc)" }}
        >
          <div className="text-[11px] text-[var(--t2)]">重试 {retry}</div>
          <div
            data-level="fail"
            className="rounded border-2 p-2 mt-1.5"
            style={{ borderColor: "var(--err)" }}
          >
            <div className="text-[11px] text-[var(--t2)]">失败 {fail}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
