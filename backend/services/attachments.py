"""聊天附件:文件校验 + 存储路径策略 + 30 天清理。

Phase 1a:仅日志(txt/log),图片(png/jpg/webp)校验逻辑预留但上传层拒绝。
"""
import logging
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import chardet

logger = logging.getLogger(__name__)

# Phase 1a 允许的扩展名(仅日志)
ALLOWED_EXTENSIONS_1A: frozenset[str] = frozenset({".txt", ".log"})
# 完整白名单(含图片,Phase 1b 启用)
ALLOWED_EXTENSIONS_FULL: frozenset[str] = frozenset({".txt", ".log", ".png", ".jpg", ".jpeg", ".webp"})

MAX_FILE_SIZE: int = 5 * 1024 * 1024  # 5 MB
MAX_ATTACHMENTS_PER_MESSAGE: int = 5

# 文本类型判定:无明确 magic bytes,靠「无二进制控制字符 + 可解码」
_TEXT_MAX_BINARY_RATIO = 0.30  # 超过 30% 二进制字节 → 视为二进制(伪装)


def sanitize_filename(name: str) -> str:
    """清洗文件名:去路径、去控制字符、限 255。"""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(c for c in base if unicodedata.category(c)[0] != "C")
    base = base.strip(". ")
    if not base:
        base = "upload"
    return base[:255]


def _looks_like_text(first_bytes: bytes) -> bool:
    """判断首字节是否像文本(非二进制可执行)。"""
    if not first_bytes:
        return True
    sample = first_bytes[:512]
    binary = sum(1 for b in sample if b == 0 or (b < 9) or (13 < b < 32))
    return binary / len(sample) < _TEXT_MAX_BINARY_RATIO


def validate_upload_file(
    filename: str, content_first_bytes: bytes, size: int
) -> tuple[bool, str, str, str | None]:
    """校验上传文件。

    Returns:
        (ok, kind, mime_type, error)。ok=False 时 kind/mime 为空字符串,error 有原因。
    """
    if size > MAX_FILE_SIZE:
        return False, "", "", "File exceeds 5 MB limit"
    clean = sanitize_filename(filename)
    ext = Path(clean).suffix.lower()
    # Phase 1a 只收 txt/log
    if ext not in ALLOWED_EXTENSIONS_1A:
        return False, "", "", "Unsupported file type (Phase 1a: .txt/.log only)"
    # magic bytes:文本类用 _looks_like_text,防 exe 伪装
    if not _looks_like_text(content_first_bytes):
        return False, "", "", "Unsupported file type (binary content detected)"
    mime = "text/x-log" if ext == ".log" else "text/plain"
    return True, "log", mime, None


def compute_storage_path(att_id, ext: str, base_dir: str = "data/attachments") -> Path:
    """按日期分目录的存储路径:data/attachments/YYYY-MM-DD/<id><ext>。"""
    date_dir = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Path(base_dir) / date_dir / f"{att_id}{ext}"


LOG_MAX_CHARS: int = 100_000  # 提取阶段上限(避免乱码撑爆 DB);超限走截断(1a)


def _detect_and_decode(raw: bytes) -> tuple[str, str | None]:
    """尝试 UTF-8 → UTF-8-sig → GBK → UTF-16 → chardet 检测,返回 (text, warning)。"""
    for enc in ("utf-8", "utf-8-sig", "gbk", "utf-16"):
        try:
            return raw.decode(enc), None
        except UnicodeDecodeError:
            continue
    guessed = chardet.detect(raw).get("encoding") or "utf-8"
    try:
        return raw.decode(guessed, errors="replace"), f"guessed encoding: {guessed}"
    except Exception:
        return raw.decode("utf-8", errors="replace"), "decode failed, lossy"


def extract_log_text(path: Path) -> tuple[str, str | None]:
    """读取日志文件 → (text, parse_warning)。截断超 LOG_MAX_CHARS。

    本身不做 PII 脱敏(纯文本提取);PII 在 _extract_and_persist 入库前 mask_pii。
    """
    raw = path.read_bytes()
    text, warning = _detect_and_decode(raw)
    # 去控制字符(保留换行/制表)
    text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c)[0] != "C")
    if len(text) > LOG_MAX_CHARS:
        text = text[:LOG_MAX_CHARS]
        warning = (warning + "; " if warning else "") + f"truncated at {LOG_MAX_CHARS} chars"
    return text, warning

