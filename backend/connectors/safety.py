"""数据导入 Technical Safety Boundary + Knowledge Eligibility 基础。

产品合同(v1.1)三层准入:
    最终准入 = TECHNICALLY_SAFE ∧ KNOWLEDGE_ELIGIBLE ∧ SOURCE_POLICY_ALLOWED

本模块实现其中前两层的**领域原语**(第三层 file_types/include_dirs 仍由
connector 现有逻辑承担,本模块结论供其叠加与未来 Admin UI 消费):

- Layer 1 Technical Safety:回答「这个文件能否被当前 ingestion pipeline
  安全处理?」——binary 嗅探、解码质量、模型/二进制工件扩展名类、硬尺寸
  上限。判定**必须发生在昂贵 parse/chunk/tokenize/embed 之前**,管理员配置
  不可绕过(G1 `.hef 84MB` 事故防线)。
- Layer 2 Knowledge Eligibility:回答「技术上可处理,但是否值得成为
  ASK-AI 的知识?」——只产出**推荐**(include/exclude/review),绝不是
  技术危险判定;vendor/test/生成物默认推荐排除,但管理员可在技术安全边界
  内纳入。

设计红线(冻结):
- 本判定不得退化成扩展名黑名单:无扩展名二进制(如 `bin/nginx`)与改名为
  `.txt` 的二进制必须被内容嗅探拦下;
- 合法中文/Unicode 文本、合法源码不得被误伤;
- 技术排除与知识推荐在结论结构上分离(FileAdmission 两个字段)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

# 一MB / 十六MB 的字节语义(阈值论证见 docs/implementation 阶段1 报告 §6)
_KB = 1024
_MB = 1024 * 1024

# --------------------------------------------------------------------------
# 默认阈值 —— INITIAL ENGINEERING DEFAULT(非产品冻结数字)
#
# 证据(2026-09-02,真实仓库只读统计):
#   neoruntime  1488 个文本类文件:p99=255KB  p95=90KB   max=1.24MB(nginx ELF
#               二进制误挂无扩展名;最大合法文本为 vendor 头 json.hpp 898KB)
#   neoruntime-apps 182 个:合法文本 max=236KB(main.py);p99=691KB(为 .png,
#               实际合法文本 p99 ≈ 236KB)
#   ask-ai 本仓:max 文本 243KB(package-lock.json,GENERATED)
#   .hef 工件:0.2MB .. 82.1MB —— 尺寸无法单独区分 6.8MB 级工件与合法大文本,
#   故尺寸只是纵深防御之一,工件类扩展名 + 内容嗅探为主防线。
#
# 选择:
#   review 1MB —— 略高于全部已知合法文本(1.24MB 的 ELF 二进制会被嗅探拦,
#   非尺寸误伤);超过者「技术上安全但建议人工确认」。
#   hard  16MB —— 4× 于已知最大合法文本;落入 regex/tokenize 病态区前阻断。
#   绝对上限 64MB —— 管理员配置只允许把上限**调低**,任何配置下不得超过
#   64MB(84MB 级事故物必须在任何配置下被尺寸兜住)。
DEFAULT_REVIEW_SIZE_LIMIT = 1 * _MB
DEFAULT_HARD_SIZE_CEILING = 16 * _MB
ABSOLUTE_HARD_SIZE_MAX = 64 * _MB

# 内容嗅探参数
_SNIFF_SAMPLE_BYTES = 8192  # 头部采样窗口(null/控制字符检测)
_POOR_DECODE_RATIO = 0.05  # U+FFFD 占比超此判解码失败
_CONTROL_RATIO = 0.05  # 控制字符占比超此判 binary

# 模型/二进制工件扩展名(类名单;工程可扩)。命中即 Layer 1 排除——
# 该类内容即使体积小也不应进入文本管线(反例:.hef 最小仅 0.2MB)。
MODEL_ARTIFACT_EXTS: frozenset[str] = frozenset(
    {
        ".hef",
        ".onnx",
        ".pt",
        ".pth",
        ".ckpt",
        ".safetensors",
        ".tflite",
        ".plan",
        ".engine",
        ".trt",
        ".nbo",
        ".npy",
        ".npz",
        ".pkl",
        ".pickle",
        ".joblib",
        ".so",
        ".dll",
        ".dylib",
        ".a",
        ".o",
        ".obj",
        ".axf",
        ".elf",
        ".bin",
        ".exe",
        ".com",
        ".wasm",
        ".class",
        ".jar",
        ".war",
        ".whl",
        ".egg",
        ".deb",
        ".rpm",
        ".dmg",
        ".iso",
        ".img",
        ".parquet",
        ".feather",
        ".sqlite",
        ".db",
    }
)


class KnowledgeRole(str, Enum):
    """知识角色(Layer 2 分类;语义见产品合同 §6)。"""

    PRODUCT_DOC = "product_doc"
    TECHNICAL_DOC = "technical_doc"
    API_REFERENCE = "api_reference"
    SOURCE_CODE = "source_code"
    CONFIGURATION = "configuration"
    EXAMPLE = "example"
    TROUBLESHOOTING = "troubleshooting"
    TEST = "test"
    BUILD_DEPLOYMENT = "build_deployment"
    GENERATED = "generated"
    VENDOR = "vendor"
    BINARY = "binary"


# Layer 2 默认推荐(产品合同已冻结;推荐排除 ≠ 技术排除)
RECOMMENDED_INCLUDE_ROLES: frozenset[KnowledgeRole] = frozenset(
    {
        KnowledgeRole.PRODUCT_DOC,
        KnowledgeRole.TECHNICAL_DOC,
        KnowledgeRole.API_REFERENCE,
        KnowledgeRole.SOURCE_CODE,
        KnowledgeRole.CONFIGURATION,
        KnowledgeRole.EXAMPLE,
        KnowledgeRole.TROUBLESHOOTING,
    }
)
RECOMMENDED_EXCLUDE_ROLES: frozenset[KnowledgeRole] = frozenset(
    {
        KnowledgeRole.TEST,
        KnowledgeRole.BUILD_DEPLOYMENT,
        KnowledgeRole.GENERATED,
        KnowledgeRole.VENDOR,
    }
)

# 知识价值判定所需的路径启发(与 ExclusionPolicy 的 BUILD_DIRS 技术目录不同:
# 命中这里只影响推荐,不影响技术安全性)
_VENDOR_DIRS = frozenset({"vendor", "third_party", "thirdparty", "external", "deps"})
_GENERATED_EXTS = frozenset({".lock", ".sum", ".min.js", ".min.css", ".map", ".pyc", ".pdb", ".d"})
_GENERATED_NAME_PARTS = (".min.", "_pb2.", ".pb.go", ".generated.", ".snap", "-lock.", "_lock.")
_TEST_DIR_PARTS = ("test", "tests", "spec", "specs", "__tests__", "testing")
_BUILD_DEPLOY_HINTS = (
    "dockerfile",
    "makefile",
    ".github/workflows",
    ".gitlab-ci",
    "jenkinsfile",
    ".circleci",
    ".drone.yml",
    "cloudbuild",
)
_DOC_EXTS = frozenset({".md", ".rst", ".txt", ".adoc", ".org"})
_CONFIG_EXTS = frozenset(
    {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties", ".env"}
)
_CODE_EXTS = frozenset(
    {
        ".py",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cc",
        ".rs",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".sh",
        ".go",
        ".java",
        ".kt",
        ".rb",
        ".php",
        ".swift",
        ".sql",
        ".lua",
        ".vim",
        ".el",
    }
)
_EXAMPLE_DIR_PARTS = (
    "example",
    "examples",
    "sample",
    "samples",
    "showcase",
    "showcases",
    "demo",
    "demos",
)
_TROUBLESHOOT_HINTS = ("troubleshoot", "known-issue", "known_issue", "faq")


@dataclass(frozen=True)
class SafetyVerdict:
    """Layer 1 技术安全判定。"""

    safe: bool
    reason: str | None = None  # model_artifact_ext | hard_oversized | binary_content | poor_decode
    detail: str = ""


@dataclass
class FileAdmission:
    """单文件准入结论(阶段6 Admin Repository Scan 将消费的 machine-readable 原语)。"""

    path: str
    size: int
    technical_safe: bool
    technical_reason: str | None
    knowledge_role: str
    recommendation: str  # include | exclude | review
    policy_result: str = "not_applied"  # allowed | excluded | not_applied(本 Gate 不强制)
    eligible: bool = True


class TechnicalSafetyPolicy:
    """Layer 1 技术安全判定 + Layer 2 分类/推荐(无状态、可单测)。

    config 可覆盖(仅能更严):
        review_size_limit: 建议确认阈值(字节);不得超过 hard_size_ceiling
        hard_size_ceiling: 硬上限(字节);任何配置不得高于 ABSOLUTE_HARD_SIZE_MAX
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self.review_size_limit = int(cfg.get("review_size_limit", DEFAULT_REVIEW_SIZE_LIMIT))
        self.hard_size_ceiling = int(cfg.get("hard_size_ceiling", DEFAULT_HARD_SIZE_CEILING))
        # 系统边界:配置只许收紧,绝对上限不可穿越(G1 事故物 84MB 必须任何配置下被拦)
        self.hard_size_ceiling = min(self.hard_size_ceiling, ABSOLUTE_HARD_SIZE_MAX)
        self.review_size_limit = min(self.review_size_limit, self.hard_size_ceiling)

    # ---------------- Layer 1:技术安全 ----------------

    def check_path(self, rel_path: str, size: int) -> SafetyVerdict:
        """廉价判定(仅路径 + size,读内容**之前**调用)。"""
        ext = PurePosixPath(rel_path).suffix.lower()
        # 多重扩展名兜底:models/xxx.min.hef / backup.tar.gz 的末段已覆盖;
        # 双扩展名(.tar.gz)由 BINARY_EXT/类名单逐层命中,这里不再展开。
        if ext in MODEL_ARTIFACT_EXTS:
            return SafetyVerdict(False, "model_artifact_ext", f"ext={ext}")
        if size > self.hard_size_ceiling:
            return SafetyVerdict(
                False,
                "hard_oversized",
                f"size={size} > hard_ceiling={self.hard_size_ceiling}",
            )
        return SafetyVerdict(True)

    def check_content(self, content: str) -> SafetyVerdict:
        """内容嗅探(已读入内存的文本;扩展名伪装/无扩展名二进制的防线)。

        三个廉价信号(全部线性扫描,远廉价于 regex/tokenize):
          1. 头部采样窗口出现 NUL 字节 → binary
          2. U+FFFD(replace 解码残留)占比过高 → 解码失败/二进制
          3. 控制字符占比过高 → binary
        合法中文/Unicode 文本三类信号均为 0,不会误伤。
        """
        if not content:
            return SafetyVerdict(True)
        sample = content[:_SNIFF_SAMPLE_BYTES]
        if "\x00" in sample:
            return SafetyVerdict(False, "binary_content", "NUL byte in head sample")
        control = sum(
            1
            for c in sample
            if c != "\n" and c != "\r" and c != "\t" and (ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F)
        )
        if sample and control / len(sample) > _CONTROL_RATIO:
            return SafetyVerdict(
                False, "binary_content", f"control_char_ratio={control / len(sample):.2%}"
            )
        bad = content.count("\ufffd")
        if content and bad / len(content) > _POOR_DECODE_RATIO:
            return SafetyVerdict(
                False, "poor_decode", f"replacement_ratio={bad / len(content):.2%}"
            )
        return SafetyVerdict(True)

    # ---------------- Layer 2:知识分类与推荐 ----------------

    def classify_role(self, rel_path: str) -> KnowledgeRole:
        """路径启发分类(粗粒度、可解释;阶段6 UI 将逐文件展示)。"""
        p = PurePosixPath(rel_path)
        parts = [x.lower() for x in p.parts]
        name = p.name.lower()
        ext = p.suffix.lower()
        joined = "/".join(parts)

        if ext in MODEL_ARTIFACT_EXTS or ext in {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".svg",
            ".wav",
            ".mp3",
            ".mp4",
            ".mov",
            ".zip",
            ".gz",
            ".tar",
        }:
            return KnowledgeRole.BINARY
        if any(d in parts for d in _VENDOR_DIRS):
            return KnowledgeRole.VENDOR
        if ext in _GENERATED_EXTS or any(marker in name for marker in _GENERATED_NAME_PARTS):
            return KnowledgeRole.GENERATED
        if (
            any(t in parts for t in _TEST_DIR_PARTS)
            or name.startswith("test_")
            or name.endswith("_test.go")
            or ".test." in name
            or ".spec." in name
        ):
            return KnowledgeRole.TEST
        if any(h in joined for h in _BUILD_DEPLOY_HINTS):
            return KnowledgeRole.BUILD_DEPLOYMENT
        if ext in _DOC_EXTS:
            if any(h in joined for h in _TROUBLESHOOT_HINTS):
                return KnowledgeRole.TROUBLESHOOTING
            return KnowledgeRole.TECHNICAL_DOC
        if ext in _CONFIG_EXTS:
            if any(d in parts for d in _EXAMPLE_DIR_PARTS):
                return KnowledgeRole.EXAMPLE
            return KnowledgeRole.CONFIGURATION
        if ext in _CODE_EXTS:
            if any(d in parts for d in _EXAMPLE_DIR_PARTS):
                return KnowledgeRole.EXAMPLE
            return KnowledgeRole.SOURCE_CODE
        if any(d in parts for d in _EXAMPLE_DIR_PARTS):
            return KnowledgeRole.EXAMPLE
        # 无扩展名/未知:保守给 TECHNICAL_DOC(安全上由 Layer 1 兜底,不因未知而判危险)
        return KnowledgeRole.TECHNICAL_DOC

    def recommendation_for(self, role: KnowledgeRole) -> str:
        if role in RECOMMENDED_INCLUDE_ROLES:
            return "include"
        if role in RECOMMENDED_EXCLUDE_ROLES:
            return "exclude"
        return "review"

    def admission(
        self,
        rel_path: str,
        size: int,
        content: str | None = None,
        policy_result: str = "not_applied",
    ) -> FileAdmission:
        """单文件完整准入结论(便捷原语;供测试/未来 Repository Scan 消费)。"""
        verdict = self.check_path(rel_path, size)
        if verdict.safe and content is not None:
            verdict = self.check_content(content)
        role = self.classify_role(rel_path)
        if not verdict.safe:
            role = KnowledgeRole.BINARY
        return FileAdmission(
            path=rel_path,
            size=size,
            technical_safe=verdict.safe,
            technical_reason=verdict.reason,
            knowledge_role=role.value,
            recommendation=self.recommendation_for(role),
            policy_result=policy_result,
            eligible=verdict.safe,
        )


def new_safety_stats() -> dict:
    """connector/pipeline 共用的安全排除计数器(可观察性原语)。"""
    return {"excluded": 0, "reasons": {}}


def record_safety_exclusion(stats: dict, rel_path: str, reason: str, detail: str = "") -> None:
    stats["excluded"] += 1
    stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
    logger.warning("技术安全排除 %s: %s %s", rel_path, reason, detail[:120])
