/** AFP-002/008:无权限显式状态(区别于空数据)。 */
export default function NoPermission() {
  return (
    <div
      data-no-permission
      className="rounded-lg border p-8 text-center"
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
    >
      <div className="text-[15px] font-medium text-[var(--t1)]">无访问权限</div>
      <div className="mt-1 text-[13px] text-[var(--t2)]">
        当前账号角色为只读(viewer),无法查看或操作此页面。请联系管理员调整角色。
      </div>
    </div>
  );
}
