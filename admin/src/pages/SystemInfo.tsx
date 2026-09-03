import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import LoadError from "@/components/LoadError";
import { useReleaseInfo } from "@/hooks/useReleaseInfo";

/**
 * #10 系统信息页:发布身份直呈(值全部来自后端 /api/admin/system/release,
 * 前端零版本常量)。运行时权威 = 镜像内 RELEASE.json(进程启动加载,不可变)。
 *
 * 设计边界(Issue #7):本页是系统信息的承载页;硬件/系统可观测性后续在
 * 「版本 / 发布」节之后追加独立 section,**不改变 release identity 权威**,
 * 本组件不实现任何 #7 内容、不提供任何重启/进程控制。
 */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="text-sm">{children}</div>
    </div>
  );
}

export default function SystemInfo() {
  const { data: release, isLoading, isError, error, refetch } = useReleaseInfo();

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">系统信息</h1>

      <Card aria-label="版本与发布">
        <CardHeader className="flex-row items-center justify-between space-y-0 p-4">
          <CardTitle className="text-base">版本 / 发布</CardTitle>
          {release && (
            <Badge variant={release.source === "manifest" ? "success" : "secondary"}>
              {release.source === "manifest" ? "正式发布" : "开发态"}
            </Badge>
          )}
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {isLoading && (
            <p className="text-sm text-muted-foreground" aria-live="polite">
              正在加载发布信息…
            </p>
          )}
          {isError && <LoadError error={error} onRetry={() => refetch()} />}
          {release && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="ASK-AI 版本">
                <span className="font-mono text-base font-semibold">{release.version}</span>
              </Field>
              <Field label="运行环境">
                <span>{release.app_mode}</span>
              </Field>
              <Field label="Git SHA(完整)">
                <span className="break-all font-mono text-xs">{release.git_sha}</span>
              </Field>
              <Field label="构建时间">
                <span className="font-mono text-xs">{release.built_at ?? "—"}</span>
              </Field>
              <Field label="镜像 / Tag">
                <span className="break-all font-mono text-xs">{release.image ?? "—"}</span>
              </Field>
              <Field label="CI 构建">
                {release.ci_run_id ? (
                  <a
                    className="break-all font-mono text-xs underline underline-offset-2"
                    href={`https://github.com/harryhua-ai/ask-ai/actions/runs/${release.ci_run_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    run {release.ci_run_id}
                  </a>
                ) : (
                  <span className="text-muted-foreground">不可用</span>
                )}
              </Field>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
