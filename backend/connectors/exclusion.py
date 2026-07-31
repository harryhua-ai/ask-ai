"""极保守排除规则模块。

提供 ExclusionPolicy,在代码库索引时排除构建产物、二进制文件、测试数据等。
默认策略极保守:源码(.c/.h/.py/.ts 等编程语言)不论大小一律保留,
仅排除构建目录、二进制扩展名、wave_\\d.*\\.c$ 测试数据与非源码的超大文件。
配置/文档类文件(.json/.yaml/.md 等)视为非源码,受 max_file_size 限制。
"""

import re
from pathlib import PurePosixPath

# 构建产物 / 依赖 / 缓存目录(任意层级匹配,大小写不敏感)
BUILD_DIRS: set[str] = {
    "build",
    "dist",
    "node_modules",
    "__pycache__",
    "target",
    "out",
    ".git",
    ".next",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
}

# 二进制文件扩展名
BINARY_EXT: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".wav",
    ".mp3",
    ".mp4",
    ".bin",
    ".elf",
    ".hex",
    ".zip",
    ".gz",
    ".tar",
}

# 源码扩展名(编程语言,不受 size 限制)
# 注意:.json/.yaml/.md/.txt/.ipynb 等配置/文档类文件不在此列,
#       视为非源码,受 max_file_size 限制。
SOURCE_EXT: set[str] = {
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".rs",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".sh",
    ".go",
    ".java",
}

# 默认测试数据正则:wave_1ch_16bits.c 这类音频测试样本
DEFAULT_TEST_DATA_RE = re.compile(r"wave_\d.*\.c$")


class ExclusionPolicy:
    """极保守的文件排除策略。

    规则按优先级依次判定:
    1. 路径任意层级命中构建目录(或用户自定义目录) → 排除
    2. 二进制扩展名 → 排除
    3. 默认测试数据正则(wave_\\d.*\\.c$) → 排除
    4. 用户自定义正则 → 排除
    5. 非源码文件超过 max_file_size → 排除(源码不受 size 限制)

    Args:
        config: 配置字典,支持以下键:
            - exclude_dirs: list[str]  额外排除目录(如 ["vendor/"])
            - exclude_regex: str       额外排除正则(如 r"_test\\.c$")
            - max_file_size: int       非源码文件的最大字节数
    """

    def __init__(self, config: dict) -> None:
        self.exclude_dirs: set[str] = set(config.get("exclude_dirs", []))
        self.user_regex: re.Pattern[str] | None = (
            re.compile(config["exclude_regex"]) if config.get("exclude_regex") else None
        )
        self.max_file_size: int | None = config.get("max_file_size")  # 仅作用于非源码

    def should_exclude(self, rel_path: str, size: int) -> bool:
        """判定相对路径是否应被排除。

        Args:
            rel_path: 相对路径(POSIX 风格,如 "src/main.c")
            size: 文件字节数

        Returns:
            True 表示应排除,False 表示保留
        """
        parts = PurePosixPath(rel_path).parts
        # 用户传入的目录可能带尾部 /,统一去除
        user_dirs = {d.strip("/") for d in self.exclude_dirs}
        # 构建/依赖目录(大小写不敏感),或用户自定义目录
        if any(p.lower() in BUILD_DIRS or p in user_dirs for p in parts):
            return True

        ext = PurePosixPath(rel_path).suffix.lower()

        # 二进制扩展名
        if ext in BINARY_EXT:
            return True

        # 默认测试数据
        if DEFAULT_TEST_DATA_RE.search(rel_path):
            return True

        # 用户自定义正则
        if self.user_regex is not None and self.user_regex.search(rel_path):
            return True

        # 源码不受 size 限制;非源码超大排除
        is_source = ext in SOURCE_EXT
        if (
            not is_source
            and self.max_file_size is not None
            and size > self.max_file_size
        ):
            return True

        return False
