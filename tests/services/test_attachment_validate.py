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
