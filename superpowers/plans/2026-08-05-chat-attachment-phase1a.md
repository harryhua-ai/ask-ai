# 聊天附件分析 Phase 1a(日志先行)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 Phase 1a——用户在聊天窗口上传**文本日志**(txt/log),系统作为会话补充上下文注入 RAG 生成,产出基于日志的分析回答。图片/vision 留给 Phase 1b。

**Architecture:** 两步式上传(`POST /api/upload` 拿 id → `/api/ask` 带 attachments);新增 `Attachment` 表(`Base.metadata.create_all` 自动建表,无 Alembic);日志文本提取异步(`BackgroundTasks`)+ 超限 fallback RAG 检索;`stream_answer` 加 `attachments` 形参,`_build_messages` 注入 `[User uploaded log]` 段;前端 widget 加 `+` 按钮 + chip UI(全英文文案);30 天清理任务。

**Tech Stack:** Python 3.12 / FastAPI(multipart + BackgroundTasks + slowapi)/ SQLAlchemy 2.x / pytest / React + TypeScript(原生 CSS)。

**Spec:** `docs/superpowers/specs/2026-08-05-chat-attachment-analysis-design.md`(双路审核 2 轮收敛)

## Global Constraints

- **无 Alembic**:沿用 `Base.metadata.create_all`(session.py:83),新增 `Attachment` 模型自动建表。生产迁移留作后续。
- **Phase 1a 不开放图片**:`accept` 只 `txt/log`,避免用户传图但无 vision 处理。图片字段(`kind="image"`)在模型层预留,但上传层 1a 拒绝图片。
- **fail-open**:单附件失败降级占位文本,不阻塞整次问答。
- **附件绕过拒答门**(关键,评审 C1 真修复):`stream_answer` 有**两个拒答门**——(1)rag.py:524-548 `intent.category in ("off_topic","commercial")` 早 return;(2)rag.py:549+ `len(reranked) < effective_min` return。两个都要堵:有附件时,在 classify_intent 之后**跳过 off_topic/commercial 早 return**(强制通行),并把 `effective_min = 0`(即使检索为空也走生成)。因为「分析这个日志」这类泛化日志排查语会被意图分类器判 off_topic,不堵第一道门附件就被丢弃。
- **1a 砍掉大日志 fallback**:spec §5.3 的「超限 RAG 检索日志片段」留 1b。1a 统一用 `LOG_MAX_CHARS=100_000` 截断 + `parse_warning`(避免阈值单位矛盾 + 死代码,见评审 H6)。`_retrieve_log_chunks` 不实现。
- **widget session_id**:前端 localStorage UUID,无服务端签发;`owner_id` 校验是防误用非防恶意(spec §4.4)。
- **PII**:日志在 `_extract_and_persist`(BackgroundTask)入库前走 `mask_pii`(pii.py:18);`extract_log_text` 本身不 mask(纯文本提取)。
- **依赖注入风格**:用项目现有的 `SessionFactoryDep = Annotated[..., Depends(get_session_factory)]`(routes.py:52),不是 `Depends(get_session_factory_dep)`。
- **Conversation.attachments lazy**:`lazy="raise"`(强制显式 eager,避免 selectin 对现有 admin 列表回归);`_build_messages` 等业务路径不访问该关系。
- **限流**:1a 实现 widget 10/min + admin 30/min 区分(spec §4.3),用 slowapi 的 `key_func` 按 channel 切换。
- **测试**:`TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest`
- **Vision 不在 1a**:task="vision" 路由、vision provider、`/api/attachments/<id>/raw` 端点都不做(Phase 1b)。

## Terminal Target: implementation(测过 + 本地冒烟,不 deploy 不 reindex)

---

## Task 1: Attachment 数据模型 + 物理存储

**Files:**
- Create: `backend/db/models.py`(在现有文件追加 `Attachment` 类)
- Create: `backend/services/attachments.py`(存储路径 + 文件清理)

**Interfaces:**
- Consumes: `Base`(models.py:36)、`Conversation`(models.py:66)
- Produces: `Attachment` ORM 模型;`attachment_storage_path(id, ext) -> str` 工具函数

- [ ] **Step 1: 写失败测试 — Attachment 模型 CRUD**

`tests/db/test_attachment_model.py`(新建):

```python
"""Attachment 模型 CRUD + 归属校验测试。"""
import uuid
import pytest
from sqlalchemy import select

from backend.db.models import Attachment, Conversation


@pytest.mark.unit
async def test_attachment_create_minimal(db_session):
    """最小字段创建(vision_done 默认 False,kind=log)。"""
    att = Attachment(
        id=uuid.uuid4(),
        owner_type="widget_anon",
        owner_id="sess-abc",
        filename="error.log",
        mime_type="text/x-log",
        kind="log",
        size_bytes=1024,
    )
    db_session.add(att)
    await db_session.commit()
    fetched = (await db_session.execute(select(Attachment).where(Attachment.id == att.id))).scalar_one()
    assert fetched.vision_done is False
    assert fetched.kind == "log"
    assert fetched.extracted_text is None
    assert fetched.storage_path is None  # 清理后为 null


@pytest.mark.unit
async def test_attachment_owner_isolation(db_session):
    """不同 owner_id 的附件隔离(widget session 防误用)。"""
    a1 = Attachment(id=uuid.uuid4(), owner_type="widget_anon", owner_id="sess-A",
                   filename="a.log", mime_type="text/x-log", kind="log", size_bytes=10)
    a2 = Attachment(id=uuid.uuid4(), owner_type="widget_anon", owner_id="sess-B",
                   filename="b.log", mime_type="text/x-log", kind="log", size_bytes=10)
    db_session.add_all([a1, a2])
    await db_session.commit()
    mine = (await db_session.execute(
        select(Attachment).where(Attachment.owner_id == "sess-A"))).scalars().all()
    assert len(mine) == 1
    assert mine[0].filename == "a.log"
```

> 若 `tests/db/conftest.py` 无 `db_session` fixture,先核对现有 fixture 名(可能叫 `session`/`async_session`)。沿用现有惯例。

- [ ] **Step 2: 运行测试确认失败**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/db/test_attachment_model.py -q
```

Expected: FAIL(`Attachment` 未定义)

- [ ] **Step 3: 追加 Attachment 模型**

`backend/db/models.py` 末尾追加(在 `QuestionCluster` 之后,`Index(...)` 调用之前):

```python
class Attachment(Base):
    """聊天附件(日志/截图),作为会话补充上下文。

    Phase 1a 仅处理日志(kind="log");图片(kind="image")字段预留,1b 接入 vision。
    """

    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)  # widget_anon | admin
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # log | image
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    vision_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation | None"] = relationship(back_populates="attachments")
```

`Conversation` 类加反向关系(在现有字段后):
```python
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="conversation", lazy="raise"
    )
```

> **lazy="raise"**(评审 H2):强制懒加载,访问时抛错而非静默查询——避免 `lazy="selectin"` 对现有 admin 会话列表引入回归(每次查 Conversation 多一条 selectin 查询)。Phase 1a 业务路径(`stream_answer`/`_build_messages`)不访问 `conversation.attachments`,raise 不会被触发;需要时显式 `selectinload`。

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/db/test_attachment_model.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/db/models.py tests/db/test_attachment_model.py
git commit -m "feat(db): Attachment 模型(日志/截图附件,1a 仅 log)"
```

---

## Task 2: 文件校验(扩展名 ∩ magic bytes)+ 存储路径

**Files:**
- Create: `backend/services/attachments.py`(校验 + 路径策略 + 落盘)

**Interfaces:**
- Consumes: `Attachment` 模型
- Produces: `validate_upload_file(filename, content_first_bytes, size) -> (ok, kind, mime, error)`;`compute_storage_path(att_id, ext, date) -> Path`

- [ ] **Step 1: 写失败测试 — 校验规则**

`tests/services/test_attachment_validate.py`(新建):

```python
"""附件文件校验:扩展名 ∩ magic bytes 白名单。"""
import pytest
from backend.services.attachments import validate_upload_file


@pytest.mark.unit
def test_log_txt_pass():
    ok, kind, mime, err = validate_upload_file("error.log", b"2026-08-05 ERROR crash\n", 100)
    assert ok and kind == "log" and err is None


@pytest.mark.unit
def test_exe_disguised_as_txt_rejected():
    """扩展名 .txt 但 magic bytes 是 PE exe → 拒绝。"""
    pe_header = b"MZ\x90\x00\x03\x00"  # Windows PE/EXE magic
    ok, kind, mime, err = validate_upload_file("fake.txt", pe_header, 100)
    assert not ok and "Unsupported" in err


@pytest.mark.unit
def test_png_rejected_in_phase_1a():
    """1a 不开放图片:扩展名 png → 拒绝。"""
    png_header = b"\x89PNG\r\n\x1a\n"
    ok, kind, mime, err = validate_upload_file("screenshot.png", png_header, 100)
    assert not ok  # 1a 只收 txt/log


@pytest.mark.unit
def test_oversize_rejected():
    ok, kind, mime, err = validate_upload_file("big.log", b"x" * 100, 6 * 1024 * 1024)
    assert not ok and "5 MB" in err


@pytest.mark.unit
def test_filename_sanitized():
    """带路径/控制字符的文件名被清洗。"""
    from backend.services.attachments import sanitize_filename
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("a\x00b.log") == "ab.log"
    assert len(sanitize_filename("x" * 300 + ".log")) <= 255
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/services/test_attachment_validate.py -q
```

- [ ] **Step 3: 实现 `backend/services/attachments.py`**

```python
"""聊天附件:文件校验 + 存储路径策略 + 30 天清理。

Phase 1a:仅日志(txt/log),图片(png/jpg/webp)校验逻辑预留但上传层拒绝。
"""
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Phase 1a 允许的扩展名(仅日志)
ALLOWED_EXTENSIONS_1A: frozenset[str] = frozenset({".txt", ".log"})
# 完整白名单(含图片,Phase 1b 启用)
ALLOWED_EXTENSIONS_FULL: frozenset[str] = frozenset({".txt", ".log", ".png", ".jpg", ".jpeg", ".webp"})

MAX_FILE_SIZE: int = 5 * 1024 * 1024  # 5 MB
MAX_ATTACHMENTS_PER_MESSAGE: int = 5

# magic bytes 白名单(前 8 字节足够区分)
MAGIC_BYTES: dict[bytes, str] = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"RIFF": "image/webp",  # webp = RIFF....WEBP,简化用 RIFF 前缀
}

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
    binary = sum(1 for b in first_bytes[:512] if b == 0 or (b < 9) or (13 < b < 32))
    return binary / min(len(first_bytes), 512) < _TEXT_MAX_BINARY_RATIO


def validate_upload_file(
    filename: str, content_first_bytes: bytes, size: int
) -> tuple[bool, str, str, str | None]:
    """校验上传文件。

    Returns:
        (ok, kind, mime_type, error)。ok=False 时 kind/mime 为空,error 有原因。
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
```

- [ ] **Step 4: 运行确认通过**

```bash
.venv/bin/python -m pytest tests/services/test_attachment_validate.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/services/attachments.py tests/services/test_attachment_validate.py
git commit -m "feat(attachments): 文件校验(扩展名∩magic)+ 存储路径策略"
```

---

## Task 3: 日志文本提取(异步 BackgroundTasks)

**Files:**
- Modify: `backend/services/attachments.py`(追加 `extract_log_text`)

**Interfaces:**
- Consumes: Task 2 的模块
- Produces: `async def extract_log_text(att_id, storage_path) -> str`(异步,BackgroundTasks 调用)

- [ ] **Step 1: 写失败测试 — 编码/截断/PII**

`tests/services/test_log_extract.py`(新建):

```python
"""日志文本提取:编码识别 + 截断 + PII mask。"""
import pytest
from backend.services.attachments import extract_log_text


@pytest.mark.unit
def test_utf8_log(tmp_path):
    p = tmp_path / "a.log"
    p.write_text("2026-08-05 INFO ok\n", encoding="utf-8")
    text, warning = extract_log_text(p)
    assert "INFO ok" in text and warning is None


@pytest.mark.unit
def test_gbk_log_falls_back(tmp_path):
    p = tmp_path / "gbk.log"
    p.write_bytes("中文日志 ERROR 崩溃\n".encode("gbk"))
    text, warning = extract_log_text(p)
    assert "中文日志" in text  # GBK 解码成功


@pytest.mark.unit
def test_truncation_warning(tmp_path):
    p = tmp_path / "big.log"
    p.write_text("a" * 200000 + "\n", encoding="utf-8")  # 假设上限 100k chars
    text, warning = extract_log_text(p)
    assert warning is not None and "truncat" in warning.lower()
```

- [ ] **Step 2-3: 实现 `extract_log_text`**

```python
# 追加到 backend/services/attachments.py
import chardet

LOG_MAX_CHARS: int = 100_000  # 提取阶段上限(避免乱码撑爆 DB);超限走 RAG fallback

def _detect_and_decode(raw: bytes) -> tuple[str, str | None]:
    """尝试 UTF-8 → GBK → chardet 检测,返回 (text, warning)。"""
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
    """读取日志文件 → (text, parse_warning)。截断超 LOG_MAX_CHARS。"""
    raw = path.read_bytes()
    text, warning = _detect_and_decode(raw)
    # 去控制字符(保留换行/制表)
    text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c)[0] != "C")
    if len(text) > LOG_MAX_CHARS:
        text = text[:LOG_MAX_CHARS]
        warning = (warning + "; " if warning else "") + f"truncated at {LOG_MAX_CHARS} chars"
    return text, warning
```

> **依赖**:`chardet` 不在 pyproject 则 `uv add chardet`。

- [ ] **Step 4-5: 测试通过 + Commit**

```bash
.venv/bin/python -m pytest tests/services/test_log_extract.py -q
git add backend/services/attachments.py tests/services/test_log_extract.py pyproject.toml uv.lock
git commit -m "feat(attachments): 日志文本提取(编码检测+截断+PII)"
```

---

## Task 4: POST /api/upload 端点(校验 + 落盘 + DB + 异步提取)

**Files:**
- Modify: `backend/api/routes.py`(加 `/api/upload` 路由)

**Interfaces:**
- Consumes: Task 1-3 的模型 + 校验 + 提取
- Produces: `POST /api/upload` multipart 端点,返回 `{attachments: [{id, filename, kind, status, ok}]}`

- [ ] **Step 1: 写失败测试 — 上传集成测试(mock 存储)**

`tests/api/test_upload.py`(新建):

```python
"""POST /api/upload 集成测试。"""
import io
import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app  # 核对 app 导出位置


@pytest.mark.integration
async def test_upload_single_log(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/upload", data={"channel": "widget", "session_id": "s1"},
                                 files=[("files", ("err.log", io.BytesIO(b"ERROR crash\n"), "text/x-log"))])
    assert resp.status_code == 200
    data = resp.json()
    assert data["attachments"][0]["ok"] is True
    assert data["attachments"][0]["kind"] == "log"
    assert data["attachments"][0]["status"] in ("ready", "processing")


@pytest.mark.integration
async def test_upload_rejects_exe_disguised(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/upload", data={"channel": "widget", "session_id": "s1"},
                                 files=[("files", ("fake.txt", io.BytesIO(b"MZ\x90\x00\x03\x00"), "text/plain"))])
    body = resp.json()
    assert body["attachments"][0]["ok"] is False
```

- [ ] **Step 2: 实现 `/api/upload`(routes.py 追加)**

```python
# routes.py 顶部 imports 补
from fastapi import BackgroundTasks, UploadFile, File, Form
from backend.db.models import Attachment
from backend.services.attachments import (
    validate_upload_file, sanitize_filename, compute_storage_path,
    extract_log_text, MAX_ATTACHMENTS_PER_MESSAGE,
)

# 限流 key_func:按 channel + ip 区分(widget 10/min,admin 30/min;spec §4.3)
def _upload_key(channel: str, request: Request) -> str:
    ip = get_remote_address(request)
    return f"{channel}:{ip}"

# 新增路由(在 /ask 之后)— widget 上传,10/min
@router.post("/upload")
@limiter.limit("10/minute")
async def upload_attachments_widget(
    request: Request,
    background_tasks: BackgroundTasks,
    session_id: str = Form(...),  # widget 必传 session_id
    files: list[UploadFile] = File(...),
    session_factory: SessionFactoryDep,  # ★ 用现有 Annotated 依赖(routes.py:52)
):
    # widget 路由:固定 owner_type=widget_anon,owner_id=session_id
    owner_type, owner_id = "widget_anon", session_id
    return await _do_upload(files, owner_type, owner_id, background_tasks, session_factory)


# admin 上传放 backend/api/admin/(admin_router prefix=/api/admin,见 Step 3)
# 路由:/api/admin/upload,30/min,用 AdminUserDep(require_role("admin"))

async def _do_upload(files, owner_type, owner_id, background_tasks, session_factory):
    """共享上传逻辑:校验 + 落盘 + DB + 异步提取。"""

    results = []
    for f in files:
        first_bytes = await f.read(512)
        await f.seek(0)
        content = await f.read()
        ok, kind, mime, err = validate_upload_file(f.filename, first_bytes, len(content))
        if not ok:
            results.append({"ok": False, "error": err})
            continue
        att = Attachment(owner_type=owner_type, owner_id=owner_id,
                         filename=sanitize_filename(f.filename), mime_type=mime,
                         kind=kind, size_bytes=len(content))
        ext = Path(att.filename).suffix.lower()
        storage_path = compute_storage_path(att.id, ext)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)
        att.storage_path = str(storage_path)
        if kind == "log":
            background_tasks.add_task(_extract_and_persist, att.id, str(storage_path), session_factory)
            status = "processing"
        else:
            status = "ready"  # 图片 1b 才启用(1a 校验已拒)
        async with session_factory() as s:
            s.add(att)
            await s.commit()
        results.append({"ok": True, "id": str(att.id), "filename": att.filename,
                        "kind": kind, "mime_type": mime, "size_bytes": att.size_bytes,
                        "status": status})
    if all(not r["ok"] for r in results):
        raise HTTPException(422, "All files rejected")
    return {"attachments": results}


async def _extract_and_persist(att_id, storage_path: str, session_factory):
    """BackgroundTask:提取日志文本 + mask_pii + 写 extracted_text。

    session_factory 是 async_sessionmaker,在 BackgroundTask 内 `async with` 可复用
    (BackgroundTask 在响应发送后、同请求事件循环内运行)。
    提取失败 fail-open:extracted_text 留 None,ask 时该附件贡献空 log_text。
    """
    from pathlib import Path
    from backend.utils.pii import mask_pii
    try:
        text, warning = extract_log_text(Path(storage_path))
        masked = mask_pii(text)
    except Exception as e:
        logger.warning("log extract failed att=%s: %s", att_id, e)
        masked, warning = "", f"extract failed: {e}"
    # session_factory 块也包 try(评审:BackgroundTask 内 session 异常时 fail-open,
    # extracted_text 留 None,ask 时该附件贡献空 log_text,不阻塞整次问答)
    try:
        async with session_factory() as s:
            att = await s.get(Attachment, att_id)
            if att:
                att.extracted_text = masked
                att.parse_warning = warning
                await s.commit()
    except Exception as e:
        logger.warning("persist extracted_text failed att=%s: %s", att_id, e)
        # fail-open:extracted_text 留 None,ask 时该附件贡献空 log_text
```

> **依赖注入(评审 C2)**:用 `SessionFactoryDep`(routes.py:52,Annotated 风格),不是 `get_session_factory_dep`。
> **BackgroundTask fail-open(评审)**:提取 + 持久化两层 try,任何失败都不阻塞,extracted_text 留 None。
> **admin 30/min(评审 H4)**:slowapi `@limiter.limit` 不支持运行时按 channel 切阈值。两种实现:(1) 拆两个路由 `/upload/widget` + `/upload/admin` 各自限流;(2) 自定义 `key_func` 按 channel+ip 分桶(但阈值仍单一)。**1a 选(1)拆路由**最干净——见 Step 3。

- [ ] **Step 3: admin 独立路由 + require_role + app 导出核对(评审 H4)**

- **admin 上传走 admin_router**(prefix=`/api/admin`,见 `backend/api/admin/router.py:15`),路由 `/api/admin/upload`(`@limiter.limit("30/minute")`)。widget 上传走顶层 `routes.py` 的 `/api/upload`(`/api/upload`,10/min)。两个路由各自独立,各自限流阈值。
- **admin 鉴权用现有 `require_role`**(评审 H4,非虚构的 `_get_admin_user_id`):
  ```python
  from backend.auth.dependencies import CurrentUser, require_role
  AdminUserDep = Annotated[CurrentUser, Depends(require_role("admin"))]
  # admin upload 路由签名:user: AdminUserDep
  ```
- 核对 `backend/main.py` 的 `app` 导出(测试用 `from backend.main import app`)——确认 app 是模块级 ASGI 实例。
- CORS multipart:main.py 现有 `CORSMiddleware`(allow_headers 含 Content-Type、allow_methods GET/POST)足够处理 multipart + preflight,无需改(评审 M1)。

- [ ] **Step 4: mask_pii 集成测试(评审 H5)**

`tests/api/test_upload.py` 追加:

```python
@pytest.mark.integration
async def test_upload_masks_pii_in_log(tmp_path, monkeypatch):
    """日志含邮箱 → 入库 extracted_text 已脱敏。"""
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/upload", data={"channel": "widget", "session_id": "s1"},
                                 files=[("files", ("p.log", io.BytesIO(b"contact john@example.com\n"), "text/x-log"))])
    att_id = resp.json()["attachments"][0]["id"]
    # 等 BackgroundTask 完成(轮询 DB,最多 5s)
    import asyncio, uuid
    from backend.db.models import Attachment
    from sqlalchemy import select
    from backend.db.session import get_session_factory, get_engine
    from backend.config import load_settings
    sf = get_session_factory(get_engine(load_settings().postgres_dsn))
    for _ in range(10):
        await asyncio.sleep(0.5)
        async with sf() as s:
            att = await s.get(Attachment, uuid.UUID(att_id))
            if att and att.extracted_text is not None:
                break
    assert att.extracted_text is not None, "BackgroundTask 未完成"
    assert "john@example.com" not in att.extracted_text  # 邮箱已脱敏
    assert "@" in att.extracted_text or "***" in att.extracted_text  # 含 mask 占位
```

- [ ] **Step 5: 测试通过 + Commit**

```bash
.venv/bin/python -m pytest tests/api/test_upload.py -q
git add backend/api/routes.py tests/api/test_upload.py
git commit -m "feat(api): POST /api/upload(校验+落盘+异步提取+mask_pii+widget/admin 分流限流)"
```

---

## Task 5: stream_answer + _build_messages 注入附件上下文

**Files:**
- Modify: `backend/pipeline/rag.py`(`stream_answer` 加 attachments 形参,`_build_messages` 加 log_text 注入)

**Interfaces:**
- Consumes: Task 1 的 Attachment 模型
- Produces: `stream_answer(..., attachments: list[Attachment] | None)`,注入 `[User uploaded log]` 段

- [ ] **Step 1: 写失败测试 — 附件注入 + 拒答绕过**

`tests/pipeline/test_rag_attachments.py`(新建):

```python
"""附件上下文注入 + 有附件绕过拒答门。"""
import json
import pytest

# _build_orchestrator 是 tests/pipeline/test_rag.py:61 的普通函数(非 fixture),import 复用
from tests.pipeline.test_rag import _build_orchestrator


@pytest.mark.unit
def test_build_messages_includes_log_text():
    """log_text 非空 → user_content 含 [User uploaded log] 段。"""
    rag, _, _, _ = _build_orchestrator(searcher_results=[], reranked_results=[])
    msgs = rag._build_messages(
        query="why crash", context="retrieved docs", language="en",
        conversation_history=[], channel="widget", intent="support",
        log_text="2026-08-05 ERROR segfault at 0x1234", image_context="",
    )
    user_content = msgs[-1]["content"]
    assert "## 用户上传的日志" in user_content
    assert "segfault" in user_content


@pytest.mark.unit
def test_build_messages_no_log_section_when_empty():
    """log_text 空 → 不出现 [User uploaded log] 段(保留原模板)。"""
    rag, _, _, _ = _build_orchestrator(searcher_results=[], reranked_results=[])
    msgs = rag._build_messages(
        query="q", context="ctx", language="en",
        conversation_history=[], channel="widget", intent="support",
        log_text="", image_context="",
    )
    assert "## 用户上传的日志" not in msgs[-1]["content"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_attachments_bypass_reject_when_search_empty():
    """有附件但检索为空 → 不拒答,走正常生成(附件作 fallback context)。评审 C1。"""
    rag, _, _, _ = _build_orchestrator(searcher_results=[], reranked_results=[])
    events = []
    class FakeAtt:
        kind = "log"
        extracted_text = "ERROR segfault backtrace..."
    async for ev in rag.stream_answer(query="analyze log", channel="widget",
                                       attachments=[FakeAtt()]):
        events.append(ev)
    types = [json.loads(e).get("type") for e in events]
    assert "token" in types  # 真生成,非直接 REJECT_ANSWER return
```

- [ ] **Step 2: 改 `_build_messages` — 完整 f-string 改造**

`rag.py:257` `_build_messages` 加 `log_text: str = "", image_context: str = ""` 形参(**必须有默认值**,rag.py:451 的 answer() 路径不传这些,否则 TypeError)。现有模板(rag.py:288-306)改造为(注入段中文,与现有 `## 检索到的资料` 风格一致;spec §6 全英文指 widget UI,不指 system prompt 模板):

```python
        # 构造附件段(条件拼接,空则不出现)
        attachment_section = ""
        if log_text:
            attachment_section += f"\n\n## 用户上传的日志\n\n{log_text}"
        if image_context:
            attachment_section += f"\n\n## 用户上传的截图分析\n\n{image_context}"

        user_content = f"""请根据以下检索到的官方资料回答问题。

## 检索到的资料

{context}{attachment_section}

## 问题

{query}

## 要求
- 只依据上面的资料回答,不编造
- 用 Markdown 格式,用 **粗体** 做小节标题
- 在每段末尾用 [N] 标注该段引用的资料序号,不在句中穿插
- 不要使用 emoji
- 不要输出文档路径
- 回答简洁,直答问题
- 用 {language} 回答
"""
        messages.append({"role": "user", "content": user_content})
```

> 注:注入段放 `{context}` 之后、`## 问题` 之前,作为 `## 用户上传的日志` 二级标题段。`## 要求` 保持不变(附件日志也算「资料」)。

- [ ] **Step 3: 改 `stream_answer` — attachments 形参 + 堵两道拒答门 + 附件预处理**

`rag.py:469` 签名加 `attachments: list | None = None`。**关键(评审 C1 真修复):堵两道拒答门**。

**第一道门(rag.py:524-548)**:`classify_intent` 之后的 `off_topic`/`commercial` 早 return。有附件时跳过这两段——把附件查询当 product/support 通行:

```python
# 在 rag.py:524 `if intent.category == "off_topic":` 之前加附件判断
# 有附件时:不做意图拒答(日志分析场景可能被判 off_topic,但附件就是 context)
if not attachments:
    if intent.category == "off_topic":
        yield json.dumps({...REJECT_OFF_TOPIC...})
        return
    if intent.category == "commercial":
        yield json.dumps({...REJECT_BUSINESS...})
        return
```

> 实施要点:把现有 rag.py:524-548 的两个 `if intent.category == ...: yield ...; return` 块**整体包进 `if not attachments:`**,有附件时这两个块不执行。

**第二道门(rag.py:549)**:`effective_min`。有附件时不拒答:

```python
# rag.py:549 改造
has_attachments = bool(attachments)
if has_attachments:
    effective_min = 0
else:
    effective_min = 1 if intent.category in ("product", "support") else self._min_results
```

在 `_build_messages` 调用前(rag.py:590 附近)构造 log_text:

```python
log_text = ""
if attachments:
    for att in attachments:
        if getattr(att, "kind", None) == "log" and getattr(att, "extracted_text", None):
            # 1a:直接拼接(截断在 extract_log_text 入库时已做,Task 3)
            log_text += att.extracted_text + "\n---\n"
        # kind == "image" 1a 不处理(Phase 1b vision)

# reranked 为空但有附件:context 空串,不拒答
context = self._build_context(reranked) if reranked else ""
messages = self._build_messages(
    query, context, language, conversation_history, channel, intent=intent.category,
    log_text=log_text, image_context="",
)
```

> **1a 不实现 `_extract_or_retrieve` / `_retrieve_log_chunks`**(评审 H6:1a 截断已足够,token/char 阈值矛盾,fallback 留 1b 统一阈值)。

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/pipeline/test_rag_attachments.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/rag.py tests/pipeline/test_rag_attachments.py
git commit -m "feat(rag): stream_answer 注入附件日志 + 有附件绕过拒答门(C1)"
```

---

## Task 6: /api/ask 接受 attachments + 归属校验

**Files:**
- Modify: `backend/api/routes.py`(`/ask` 端点加 attachments 参数 + 校验归属)
- Modify: `backend/api/schemas.py`(`AskRequest` 加 `attachments`)

**Interfaces:**
- Consumes: Task 5 的 `stream_answer(attachments=)`
- Produces: `/api/ask` 接受 `attachments: list[str]`(attachment id),校验归属后传 ORM 对象

- [ ] **Step 1: 改 schemas.py**

```python
class AskRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    channel: str = "widget"
    conversation_history: list[dict] = Field(default_factory=list)
    source_url: str | None = None
    source_type: str | None = None
    attachments: list[str] = Field(default_factory=list)  # 新增:attachment id 列表
```

- [ ] **Step 2: 改 /ask 路由 — 加载 + 归属校验**

`/ask` 端点在调用 `stream_answer` 前:

```python
# 加载 attachments + 校验归属
attachment_objs = []
if req.attachments:
    async with session_factory() as s:
        for att_id in req.attachments:
            att = await s.get(Attachment, att_id)
            if not att:
                raise HTTPException(422, f"Unknown attachment: {att_id}")
            # 归属校验:widget 用 session_id,admin 用 user_id
            expected_owner = session_id if req.channel == "widget" else admin_user_id
            if att.owner_id != expected_owner:
                raise HTTPException(403, "Attachment access denied")
            attachment_objs.append(att)
# 传给 stream_answer
async for event in rag.stream_answer(..., attachments=attachment_objs):
    yield event
```

- [ ] **Step 3: 写越权测试**

```python
@pytest.mark.integration
async def test_ask_attachment_wrong_owner_403(...):
    # att 属于 session-B,用 session-A 调 /api/ask → 403
    ...
```

- [ ] **Step 4: 测试 + Commit**

```bash
.venv/bin/python -m pytest tests/api/ -q -k "attachment or upload"
git add backend/api/routes.py backend/api/schemas.py tests/api/
git commit -m "feat(api): /api/ask 接受 attachments + 归属校验(403 越权)"
```

---

## Task 7: 前端 widget UI(+ 按钮 + chip + session_id + useSSE)

**Files:**
- Modify: `widget/src/components/ChatPanel.tsx`(胶囊输入 + + 按钮 + chip 行)
- Modify: `widget/src/hooks/useSSE.ts`(upload 方法 + ask 带 attachments)
- Modify: `widget/src/types.ts`(ChatMessage.attachments)
- Modify: `widget/src/components/MessageBubble.tsx`(气泡上 chip 展示)
- Modify: `widget/src/styles/widget.css`(chip 样式,全英文文案)

**Interfaces:**
- Consumes: `/api/upload` + `/api/ask(attachments)`(Task 4, 6)
- Produces: 完整上传 + 发问 UI 流程

- [ ] **Step 1: types.ts 扩展**

```typescript
export interface AttachmentRef { id: string; filename: string; kind: string; status: "uploading"|"ready"|"failed"; error?: string }
export interface ChatMessage {
  // ...existing
  attachments?: AttachmentRef[];
}
```

- [ ] **Step 2: useSSE.ts 加 upload + session_id**

```typescript
const SESSION_ID = (() => {
  let s = localStorage.getItem("ask_ai_session_id");
  if (!s) { s = crypto.randomUUID(); localStorage.setItem("ask_ai_session_id", s); }
  return s;
})();

async function uploadFiles(files: File[]): Promise<AttachmentRef[]> { ... }

function ask(message: string, history: ChatMessage[], attachments: string[]) {
  // body 加 attachments + session_id
}
```

- [ ] **Step 3: ChatPanel.tsx 胶囊输入 + + 按钮 + chip 行**

按 spec §6.1 样式表实现。`<input type="file" multiple accept=".txt,.log" hidden>`,+ 按钮触发。

- [ ] **Step 4: MessageBubble.tsx 气泡上 chip**

- [ ] **Step 5: widget.css 追加样式**

- [ ] **Step 6: build 验证 + Commit**

```bash
cd widget && npm run build
git add widget/
git commit -m "feat(widget): 胶囊输入 + + 附件上传 + chip UI(全英文)"
```

---

## Task 8: 30 天清理任务

**Files:**
- Create: `scripts/cleanup_attachments.py`(独立脚本,cron 调)

**Interfaces:**
- Consumes: Task 1 Attachment 模型
- Produces: 清理 `created_at < now - 30 天` 的物理文件,置 `storage_path=null`

- [ ] **Step 1: 实现 cleanup_attachments.py**

```python
"""清理 30 天前的附件物理文件(保留 DB 元数据 + extracted_text)。

cron: 每日 03:00 跑一次。
"""
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from backend.db.models import Attachment
from backend.db.session import get_engine, get_session_factory
from backend.config import load_settings
from pathlib import Path

RETENTION_DAYS = 30

async def main():
    engine = get_engine(load_settings().postgres_dsn)
    sf = get_session_factory(engine)
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    async with sf() as s:
        rows = (await s.execute(select(Attachment).where(Attachment.created_at < cutoff, Attachment.storage_path.isnot(None)))).scalars().all()
        for att in rows:
            if att.storage_path:
                p = Path(att.storage_path)
                if p.exists():
                    p.unlink()
                att.storage_path = None
        await s.commit()
    print(f"cleaned {len(rows)} attachments")
```

- [ ] **Step 2: 写清理测试(>30 天删、<30 天留)**

- [ ] **Step 3: Commit + 记录 cron 部署(不实际部署)**

```bash
git add scripts/cleanup_attachments.py tests/scripts/test_cleanup_attachments.py
git commit -m "feat(attachments): 30 天清理任务(保留 extracted_text)"
```

> cron 部署(tesla-t4 crontab)不在本 plan,部署阶段单独加。

---

## Task 9: 全量回归 + Real-Run Gate

- [ ] **Step 1: 后端全量测试**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/ -q --ignore=tests/api/admin --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e
```

- [ ] **Step 2: widget build**

```bash
cd widget && npm run build
```

- [ ] **Step 3: 本地冒烟(启动 backend + widget,上传日志发问)**

手动或脚本:启动本地 backend,上传一个 sample log,发问 "分析这个日志的错误",确认答案引用了日志内容。

- [ ] **Step 4: 记录 Real-Run 结果,不 deploy 不 reindex**

---

## Self-Review Checklist

- [ ] Attachment 模型 + create_all 自动建表(无 Alembic)
- [ ] Conversation.attachments lazy="raise"(不回归 admin 列表)
- [ ] 文件校验:扩展名 ∩ magic bytes(exe 伪装拒绝)
- [ ] Phase 1a 只收 txt/log,图片拒绝
- [ ] 日志提取:编码检测 + 截断 + PII mask(入库前 mask,Task 4 集成测试覆盖)
- [ ] POST /api/upload:SessionFactoryDep(非 _dep)+ 落盘 + DB + 异步提取 + widget10/admin30 分流
- [ ] stream_answer 注入 [User uploaded log] 段(fail-open)
- [ ] **有附件时绕过拒答门(effective_min=0,评审 C1)**
- [ ] /api/ask attachments 归属校验(403)
- [ ] widget UI:胶囊 + + + chip(全英文)
- [ ] 30 天清理脚本
- [ ] 测试绿 + widget build 绿
- [ ] 不动生产(不 deploy 不 reindex)

## 不在本 plan(Phase 1b + 后续)

- vision provider 接入(task="vision")
- 图片上传开放(accept 加 png/jpg/webp)
- build_vision_messages + vision 缓存
- /api/attachments/<id>/raw 端点
- 大日志 RAG fallback 检索(1a 用截断,统一 token/char 阈值后留 1b)
- Alembic 迁移引入
- cron 实际部署
- **部署侧 `data/attachments` 卷映射**(M3:deploy/docker-compose.yml backend 服务无 volume,部署阶段必须加,否则容器重启文件丢失)
- **attachments 表 DB 行清理**(M2:30 天只删文件置 null,DB 行无限增长;60 天后删行留后续)
