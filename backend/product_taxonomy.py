"""Canonical Product Taxonomy(CamThink V1 Answer Correctness,Issue #5 契约 §1)。

配置驱动的产品身份唯一事实源(``config/product_taxonomy.yaml``):

- **canonicalize**:原始标签(含大小写/历史漂移,如 ``AI-ToolStack`` /
  ``meta-hailo-os``)→ canonical slug;未登记值一律返回 ``None``(禁止猜测)。
- **extract_products**:用户文本 → 出现顺序的 canonical slugs(别名扫描,
  确定性、零 LLM;数字边界防 ``NE5030``/``HTTP 301`` 误命中)。
- **derive_product**:文档级产品推导 —— 先按 ``document_derivation`` 路径/URL
  规则(wiki 系列目录、官网产品页),再按标签 canonicalize,均未命中 =
  ``unknown``。ingest 与 migration 共用同一条代码路径。
- **eligible_slugs / eligible_labels**:目标产品的检索资格集合 —— 目标自身 +
  适用平台(applies_to 交集)+ 共享/支持桶;sibling、混合源标签、store
  绝不入围。labels 版额外展开历史标签(迁移前兜底;迁移后自然收敛)。

设计红线(冻结契约):
- 不做不可扩展的产品名 if/else——一切产品知识在本配置;
- ``unknown`` 永不静默变成目标证据;
- 本模块零业务依赖(pipeline/retrieval/api 可安全反向导入)。
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# --------------------------------------------------------------------------- #
# 常量与数据类型
# --------------------------------------------------------------------------- #

KIND_PRODUCT = "product"
KIND_PLATFORM = "platform"
KIND_SHARED = "shared"
KIND_SUPPORT = "support"
KIND_STORE = "store"

#: 可作为问答目标解析结果的 kind(§2 Target Product Resolution)
TARGETABLE_KINDS = frozenset({KIND_PRODUCT, KIND_PLATFORM})
#: 可作为共享证据入资格集合的 kind(§5 Retrieval Boundary)
SHARABLE_KINDS = frozenset({KIND_PLATFORM, KIND_SHARED, KIND_SUPPORT})

UNKNOWN_SLUG = "unknown"

_DERIVED_RULE = "rule"
_DERIVED_CANONICAL = "canonical"
_DERIVED_NONE = "none"


@dataclass(frozen=True)
class Entity:
    """canonical 实体(产品 / 平台 / 共享桶)。"""

    slug: str
    kind: str
    display_name: str
    aliases: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = ()


@dataclass(frozen=True)
class DerivedProduct:
    """文档级产品推导结果。

    ``reason``: ``rule``(路径/URL 规则)/ ``canonical``(标签 canonicalize)
    / ``none``(不可判定 → unknown)。
    """

    slug: str
    reason: str


# --------------------------------------------------------------------------- #
# Taxonomy
# --------------------------------------------------------------------------- #


def _alias_pattern(alias: str) -> re.Pattern[str] | None:
    """别名 → 带数字边界的匹配正则(别名内空格/连字符弹性匹配)。"""
    tokens = [re.escape(tok) for tok in alias.strip().lower().replace("-", " ").split() if tok]
    if not tokens:
        return None
    flexible = r"[-\s]?".join(tokens)
    return re.compile(rf"(?<![a-z0-9]){flexible}(?![a-z0-9])")


class Taxonomy:
    """canonical 产品身份表(不可变;加载自 ``product_taxonomy.yaml``)。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self._entities: dict[str, Entity] = {}
        self._legacy: dict[str, str] = {}
        self._alias_patterns: list[tuple[re.Pattern[str], str]] = []
        self._deixis: tuple[str, ...] = ()
        self._derivation: tuple[tuple[str, tuple[dict[str, Any], ...]], ...] = ()
        self._load(config)

    # -- 加载 -------------------------------------------------------------- #

    def _load(self, config: dict[str, Any]) -> None:
        entries = list(config.get("products") or []) + list(config.get("shared_buckets") or [])
        aliases: list[tuple[str, str]] = []
        for entry in entries:
            entity = Entity(
                slug=str(entry["slug"]),
                kind=str(entry.get("kind", KIND_PRODUCT)),
                display_name=str(entry.get("display_name") or entry["slug"]),
                aliases=tuple(str(a) for a in (entry.get("aliases") or [])),
                applies_to=tuple(str(a) for a in (entry.get("applies_to") or [])),
            )
            self._entities[entity.slug] = entity
            aliases.append((entity.slug, entity.slug))
            for alias in entity.aliases:
                aliases.append((alias, entity.slug))

        # 长别名优先,避免短别名抢先生成低精度匹配点
        seen: set[str] = set()
        for alias, slug in sorted(aliases, key=lambda p: -len(p[0])):
            if alias in seen:
                continue
            seen.add(alias)
            pattern = _alias_pattern(alias)
            if pattern is not None:
                self._alias_patterns.append((pattern, slug))

        for raw, slug in (config.get("legacy_labels") or {}).items():
            key = str(raw).strip().lower()
            self._legacy[key] = str(slug)
            # 历史标签同时作为查询文本别名(仅限可作目标的 slug;用户会直接
            # 敲仓库名如 meta-hailo-os,映射已在本文件冻结,非猜测)
            entity = self._entities.get(str(slug))
            if entity is not None and entity.kind in TARGETABLE_KINDS and key not in seen:
                seen.add(key)
                pattern = _alias_pattern(key)
                if pattern is not None:
                    self._alias_patterns.append((pattern, entity.slug))

        groups: list[tuple[str, tuple[dict[str, Any], ...]]] = []
        for group in config.get("document_derivation") or []:
            rules = tuple(dict(rule) for rule in (group.get("rules") or []))
            groups.append((str(group.get("label", "")).strip().lower(), rules))
        self._derivation = tuple(groups)

        self._deixis = tuple(
            str(p).lower() for p in ((config.get("ambiguity") or {}).get("deixis_patterns") or [])
        )

    # -- canonicalize(标签 → slug)----------------------------------------- #

    def canonicalize(self, label: str | None) -> str | None:
        """原始标签 → canonical slug;未登记值返回 ``None``(禁止猜测)。"""
        if not label:
            return None
        key = str(label).strip().lower()
        if not key:
            return None
        if key in self._legacy:
            return self._legacy[key]
        entity = self._entities.get(key)
        return entity.slug if entity else None

    # -- 查询侧:别名扫描 --------------------------------------------------- #

    def extract_products(self, text: str) -> tuple[str, ...]:
        """文本中出现的 canonical slugs(按首次出现顺序去重;零 LLM 确定性)。"""
        if not text:
            return ()
        lowered = text.lower()
        hits: list[tuple[int, str]] = []
        for pattern, slug in self._alias_patterns:
            match = pattern.search(lowered)
            if match is not None:
                hits.append((match.start(), slug))
        hits.sort()
        ordered: list[str] = []
        for _, slug in hits:
            if slug not in ordered:
                ordered.append(slug)
        return tuple(ordered)

    def has_device_deixis(self, text: str) -> bool:
        """查询是否含设备指代词(「这个设备/this camera」等;歧义检测输入)。"""
        if not text:
            return False
        lowered = text.lower()
        return any(pattern in lowered for pattern in self._deixis)

    # -- 实体查询 ----------------------------------------------------------- #

    def entity(self, slug: str) -> Entity | None:
        return self._entities.get(slug)

    def is_targetable(self, slug: str) -> bool:
        """是否可作为问答目标(product / platform;shared/store/未知不可)。"""
        entity = self._entities.get(slug)
        return entity is not None and entity.kind in TARGETABLE_KINDS

    def display_name(self, slug_or_label: str) -> str:
        """展示名;未登记标签原样返回(诚实呈现,不猜)。"""
        entity = self._entities.get(slug_or_label)
        return entity.display_name if entity else slug_or_label

    def boundary_prompt(self, targets: tuple[str, ...] | list[str]) -> str:
        """生成 system prompt 的产品边界段(Issue #5 契约 §6 冻结生成规则)。

        单目标 = exact 语义;sibling 冒充禁令 + 不足即明示。
        多目标 = comparison 语义(§10):按产品分节归属 + 单侧不足不得填位。
        """
        names = "、".join(self.display_name(t) for t in targets)
        if len(targets) > 1:
            return (
                "## 产品边界(冻结规则)\n"
                f"- 本轮要求比较多个产品:{names}。\n"
                "- 回答必须按产品分节,并明确标注每节内容属于哪个产品;引用编号"
                "必须来自对应产品(或共享)的资料。\n"
                "- 严禁把一个产品的规格、接口、步骤、兼容性或能力记到另一个产品名下。\n"
                "- 单侧产品资料不足时,就该产品明确说明,严禁用另一产品的数据填位。"
            )
        return (
            "## 产品边界(冻结规则)\n"
            f"- 本轮询问的目标产品:{names}。\n"
            "- 只有目标产品的资料和上面标注为共享/平台的资料,才可以作为"
            "目标产品的事实依据。\n"
            "- 严禁把其他产品的规格、接口、步骤、兼容性或能力描述成目标产品的事实。\n"
            "- 目标产品资料不足时,直接明确说明资料不足;严禁借其他产品的资料补位。"
        )

    # -- 检索资格集合(§5 Retrieval Boundary)-------------------------------- #

    def eligible_slugs(self, targets: tuple[str, ...] | list[str]) -> frozenset[str]:
        """目标产品的 canonical 资格集合(sibling / 混合标签 / store 永不入围)。

        展开规则:目标自身 + applies_to 与任一目标相交的平台/共享/支持桶
        (any-target 语义:比较模式下任一侧适用的平台均可用)。
        """
        target_list = [t for t in targets if self.is_targetable(t)]
        if not target_list:
            return frozenset()
        target_set = set(target_list)
        out = set(target_set)
        for entity in self._entities.values():
            if entity.slug in out or entity.kind not in SHARABLE_KINDS:
                continue
            if target_set & set(entity.applies_to):
                out.add(entity.slug)
        return frozenset(out)

    def eligible_labels(self, targets: tuple[str, ...] | list[str]) -> list[str]:
        """资格集合对应的 Weaviate 原始标签集(含历史标签;迁移前兜底)。

        迁移完成后历史标签自然消失,本展开收敛为 canonical 标签集合。
        """
        labels: list[str] = []
        for slug in sorted(self.eligible_slugs(targets)):
            if slug not in labels:
                labels.append(slug)
            for raw, mapped in self._legacy.items():
                if mapped == slug and raw not in labels:
                    labels.append(raw)
        return labels

    # -- 文档级推导(§3 Document Product Derivation)-------------------------- #

    def derive_product(self, label: str | None, source_id: str, url: str) -> DerivedProduct:
        """文档产品推导:规则优先 → 标签 canonicalize → unknown(禁止猜)。"""
        lbl = (label or "").strip().lower()
        hay = (source_id or "").lower()
        u = (url or "").lower()
        for group_label, rules in self._derivation:
            if group_label != lbl:
                continue
            for rule in rules:
                path_tokens = [str(t).lower() for t in (rule.get("path_any") or [])]
                url_tokens = [str(t).lower() for t in (rule.get("url_any") or [])]
                if path_tokens and any(token in hay for token in path_tokens):
                    return DerivedProduct(str(rule["product"]), _DERIVED_RULE)
                if url_tokens and any(token in u for token in url_tokens):
                    return DerivedProduct(str(rule["product"]), _DERIVED_RULE)
        slug = self.canonicalize(lbl)
        if slug is not None:
            return DerivedProduct(slug, _DERIVED_CANONICAL)
        return DerivedProduct(UNKNOWN_SLUG, _DERIVED_NONE)


# --------------------------------------------------------------------------- #
# 加载(默认仓库配置;进程内缓存)
# --------------------------------------------------------------------------- #

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "product_taxonomy.yaml"


def load_taxonomy(path: str | Path) -> Taxonomy:
    """从 YAML 文件加载 taxonomy(文件缺失显式报错,fail-fast)。"""
    config_path = Path(path)
    with open(config_path, encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    return Taxonomy(config)


@functools.lru_cache(maxsize=1)
def get_taxonomy() -> Taxonomy:
    """进程级默认 taxonomy(仓库 ``config/product_taxonomy.yaml``)。"""
    return load_taxonomy(_DEFAULT_CONFIG_PATH)
