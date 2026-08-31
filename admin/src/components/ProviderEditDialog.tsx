import { useState } from "react";
import { RefreshCw, Plus, X, Star } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useFetchModels } from "@/hooks/useLLMProviders";
import type { LLMProvider } from "@/types/api";

interface Props {
  provider: LLMProvider;
  onSave: (patch: {
    type?: string;
    enabled?: boolean;
    config: Record<string, unknown>;
  }) => void;
  onClose: () => void;
}

export function ProviderEditDialog({ provider, onSave, onClose }: Props) {
  const cfg = provider.config as Record<string, unknown>;
  const initialModels =
    (cfg.available_models as string[] | undefined) ??
    (cfg.model ? [cfg.model as string] : []);
  const [apiBase, setApiBase] = useState((cfg.api_base as string) ?? "");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState<string[]>(initialModels);
  const [fetchResult, setFetchResult] = useState<string[] | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [newModel, setNewModel] = useState("");
  const [saving, setSaving] = useState(false);
  const fetchModels = useFetchModels();

  const handleFetch = async () => {
    const res = await fetchModels.mutateAsync({
      id: provider.id,
      // T27:传表单当前值(未保存也生效);留空字段不传,后端回退 DB 凭证
      apiBase: apiBase.trim() || undefined,
      apiKey: apiKey.trim() || undefined,
    });
    if (res.error) {
      setFetchError(res.error);
      setFetchResult([]);
    } else {
      setFetchError(null);
      setFetchResult(res.models);
    }
  };

  const handleAddManual = () => {
    if (newModel && !models.includes(newModel)) {
      setModels([...models, newModel]);
      setNewModel("");
    }
  };

  const handleSetDefault = (m: string) => {
    setModels([m, ...models.filter((x) => x !== m)]);
  };

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const config: Record<string, unknown> = {
        ...cfg,
        api_base: apiBase,
        model: models[0] ?? cfg.model,
        available_models: models,
      };
      if (apiKey) config.api_key = apiKey;
      else delete config.api_key;
      await onSave({
        type: provider.type,
        enabled: provider.enabled,
        config,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>编辑供应商 · {provider.id}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="api-base">API Base</Label>
            <Input
              id="api-base"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              默认仅支持 deepseek / openai / anthropic 三家直连;其他供应商需在服务端
              .env 配置 LLM_ALLOWED_HOSTS 放行后才能保存与拉取
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="api-key">
              API Key <span className="text-xs text-muted-foreground">留空则保留当前密钥</span>
            </Label>
            <Input
              id="api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="留空则不修改"
            />
          </div>

          <div className="space-y-2">
            <Label>
              可用模型 <span className="text-xs text-muted-foreground">★ 第 1 个 = 默认</span>
            </Label>

            <div className="space-y-1">
              {models.map((m, i) => (
                <div
                  key={m}
                  className="flex items-center gap-2 rounded-md border px-2.5 py-1.5"
                >
                  <Star className="h-3 w-3 shrink-0" fill={i === 0 ? "currentColor" : "none"} />
                  <span className="flex-1 font-mono text-xs">{m}</span>
                  {i === 0 ? (
                    <span className="text-[10px] text-muted-foreground">默认</span>
                  ) : (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-5 px-1.5 text-[10px]"
                      onClick={() => handleSetDefault(m)}
                    >
                      设为默认
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5"
                    onClick={() => setModels(models.filter((x) => x !== m))}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={handleFetch}
              disabled={fetchModels.isPending}
            >
              <RefreshCw className={fetchModels.isPending ? "mr-1 h-3 w-3 animate-spin" : "mr-1 h-3 w-3"} />
              从 API 拉取
            </Button>

            {fetchError && (
              <p className="text-xs text-destructive">{fetchError}</p>
            )}

            {fetchResult && fetchResult.filter((m) => !models.includes(m)).length > 0 && (
              <div className="flex flex-wrap gap-1 rounded-md bg-muted/50 p-2">
                {fetchResult
                  .filter((m) => !models.includes(m))
                  .map((m) => (
                    <Button
                      key={m}
                      variant="secondary"
                      size="sm"
                      className="h-6 font-mono text-[10px]"
                      onClick={() => setModels([...models, m])}
                    >
                      {m}
                    </Button>
                  ))}
              </div>
            )}

            <div className="flex gap-1.5">
              <Input
                placeholder="模型名"
                value={newModel}
                onChange={(e) => setNewModel(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleAddManual();
                }}
                className="h-8 text-xs"
              />
              <Button
                variant="outline"
                size="sm"
                className="h-8"
                onClick={handleAddManual}
              >
                <Plus className="mr-1 h-3 w-3" />
                手动添加
              </Button>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "保存中..." : "保存"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
