"""日志文本提取:编码识别 + 截断。"""
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
    p.write_text("a" * 200000 + "\n", encoding="utf-8")  # 超上限 100k chars
    text, warning = extract_log_text(p)
    assert warning is not None and "truncat" in warning.lower()
