#!/usr/bin/env python3
"""#114 GeoLite2-Country MMDB **硬结构校验**(python3 stdlib,零第三方依赖)。

R2 审查修正:旧校验只查「metadata 标记子串 + 体积下限」,mmdblookup 又是
软失败 —— 无法证明文件是「可读的正确 MMDB 树」。本模块实现真正的结构解析,
任何一步失败即拒(fail-closed):

 1. 完整 MMDB metadata 解码:控制字节驱动的 data-section 解码器(pointer /
    extended / string / map / array / uint / double / float / boolean),
    任何越界/截断/非法控制字节都拒绝;
    R3 修正(阻塞 ①):变长 size(29/30/31 ⇒ +29/+285/+65,821)与 pointer
    (1/2/3/4 字节宽,基数 0/2048/526,336/0,4 字节档低 3 位忽略)按官方
    规范解码并即解引用 —— 旧实现把真实合法 MaxMind 文件误拒(实证:公开
    MaxMind-DB test-data 的 GeoLite2-Country-Test.mmdb,description 76 字节
    走 marker 29,旧实现 metadata 错位 → 误拒)。
 2. metadata 字段语义校验:database_type 必须为 GeoLite2-Country、
    binary_format_major_version=2、ip_version∈{4,6}、record_size∈{24,28,32}、
    node_count≥1;
 3. 布局一致性:搜索树体积(node_count×record_size×2÷8)+ 16 字节数据段
    分隔符必须位于 metadata 标记之前,且 metadata 必须精确消费到 EOF;
 4. 搜索树真实走树:对 RFC 5737 文档地址探针按 record_size 逐节点读记录,
    全部越界检查 + 环路保护,数据指针必须落在数据段内。命中与否不影响
    结论(探针地址是文档段,不在库中属正常),结构可走通才算通过。

输出纪律:只输出类别与计数,不输出文件内容/真实 IP。退出码 0=通过,1=拒绝。

CLI:
    python3 mmdb_validate.py <file> [--min-bytes N]   # 默认下限 1MB
"""

from __future__ import annotations

import argparse
import struct
import sys

METADATA_MARKER = b"\xab\xcd\xefMaxMind.com"
DEFAULT_MIN_BYTES = 1_000_000
_DATA_SECTION_SEPARATOR_BYTES = 16
_EXPECTED_DB_TYPE = "GeoLite2-Country"
# 探针地址 = RFC 5737 文档段(非真实访客 IP;隐私红线)。
_PROBE_IPV4 = ("203.0.113.1", "198.51.100.7", "192.0.2.9")
_MAX_DECODE_DEPTH = 64
_MAX_WALK_STEPS = 224  # 128(ipv6 深度)+ 96 余量,配合 visited 集合防环


class MMDBInvalid(Exception):
    """结构校验失败(类别化消息,不含文件内容)。"""


def _read(buf: bytes, pos: int, n: int) -> bytes:
    if pos < 0 or n < 0 or pos + n > len(buf):
        raise MMDBInvalid("metadata 解码越界(文件截断或损坏)")
    return buf[pos : pos + n]


# R3 修正(阻塞 ①):变长 size 与 pointer 编解码对齐 MaxMind DB v2 官方规范
# (https://maxmind.github.io/MaxMind-DB/):
#   - size 子段 29/30/31 ⇒ 实长 = 29+1B / 285+2B / 65,821+3B(旧实现 +7/+263/
#     +71679 恰差 22,会把合法长 description 截短 → metadata 错位误拒);
#   - pointer 4 档宽度 1/2/3/4 字节,偏移基数 0/2048/526,336/0(4 字节档读满
#     32 位、低 3 位忽略)。旧实现按 0/1/2/3 字节读且无基数,全部错位。
_SIZE_BASE_29 = 29
_SIZE_BASE_30 = 285
_SIZE_BASE_31 = 65_821
_POINTER_BASE = {0: 0, 1: 2048, 2: 526_336, 3: 0}


def _decode(buf: bytes, pos: int, depth: int = 0, pointer_base: int = 0) -> tuple[object, int]:
    """按 MaxMind DB 数据段格式解码一个值,返回 (value, next_pos)。

    pointer_base:pointer 指向目标段的起点(数据段解码传数据段起点;
    metadata 内 pointer 按规范相对 metadata 起点,由调用方传入)。
    解析即解引用(规范:指针不得指向指针;深度门防环)。"""
    if depth > _MAX_DECODE_DEPTH:
        raise MMDBInvalid("metadata 嵌套/指针链过深(结构异常)")
    ctrl = _read(buf, pos, 1)[0]
    pos += 1
    tnum = ctrl >> 5

    if tnum == 1:  # pointer:3 位 size 子段 = 指针尺寸档(0-3)
        psize = (ctrl >> 3) & 0x3
        high = ctrl & 0x7
        nbytes = psize + 1
        raw = _read(buf, pos, nbytes)
        pos += nbytes
        if psize == 3:  # 4 字节档:读满 32 位,低 3 位控制位忽略
            pval = int.from_bytes(raw, "big")
        else:
            pval = (high << (8 * nbytes)) | int.from_bytes(raw, "big")
        pval += _POINTER_BASE[psize]
        value, _ = _decode(buf, pointer_base + pval, depth + 1, pointer_base)
        return value, pos

    size = ctrl & 0x1F
    if tnum == 0:  # extended:下一字节 = 真实类型 - 7
        tnum = _read(buf, pos, 1)[0] + 7
        pos += 1
        if tnum > 15:
            raise MMDBInvalid("非法 extended 类型")

    if tnum == 14:  # boolean:size 子段即值,不走 29/30/31 扩展
        return (size != 0), pos
    if tnum == 13:  # end_marker(仅 container 内合法;顶层出现即异常)
        return None, pos

    if size == 29:
        size = _SIZE_BASE_29 + _read(buf, pos, 1)[0]
        pos += 1
    elif size == 30:
        size = _SIZE_BASE_30 + int.from_bytes(_read(buf, pos, 2), "big")
        pos += 2
    elif size == 31:
        size = _SIZE_BASE_31 + int.from_bytes(_read(buf, pos, 3), "big")
        pos += 3

    if tnum == 2:  # utf8 string
        raw = _read(buf, pos, size)
        pos += size
        try:
            return raw.decode("utf-8"), pos
        except UnicodeDecodeError as exc:
            raise MMDBInvalid("字符串字段非 UTF-8(结构异常)") from exc
    if tnum == 3:  # double
        return struct.unpack(">d", _read(buf, pos, 8))[0], pos + 8
    if tnum == 4:  # bytes
        return _read(buf, pos, size), pos + size
    if tnum == 5:  # uint16
        return int.from_bytes(_read(buf, pos, size), "big"), pos + size
    if tnum == 6:  # uint32
        return int.from_bytes(_read(buf, pos, size), "big"), pos + size
    if tnum == 8:  # int32
        return int.from_bytes(_read(buf, pos, size), "big", signed=True), pos + size
    if tnum == 9:  # uint64
        return int.from_bytes(_read(buf, pos, size), "big"), pos + size
    if tnum == 10:  # uint128(按规范为有符号)
        return int.from_bytes(_read(buf, pos, size), "big", signed=True), pos + size
    if tnum == 15:  # float
        return struct.unpack(">f", _read(buf, pos, 4))[0], pos + 4
    if tnum == 7:  # map
        out: dict = {}
        for _ in range(size):
            key, pos = _decode(buf, pos, depth + 1, pointer_base)
            if not isinstance(key, str):
                raise MMDBInvalid("map 键非字符串(结构异常)")
            out[key], pos = _decode(buf, pos, depth + 1, pointer_base)
        return out, pos
    if tnum == 11:  # array
        out_list: list = []
        for _ in range(size):
            item, pos = _decode(buf, pos, depth + 1, pointer_base)
            out_list.append(item)
        return out_list, pos
    if tnum == 12:  # data cache container:规范允许但不会出现在落盘文件
        raise MMDBInvalid("data cache container 不应出现在文件中")
    raise MMDBInvalid("未知类型(结构异常)")


def _read_record(buf: bytes, node: int, side: int, record_size: int, tree_size: int) -> int:
    """读节点 node 的左/右记录;全部越界检查,只允许落在搜索树区域内。"""
    if node < 0:
        raise MMDBInvalid("节点索引为负(结构异常)")
    if record_size == 24:
        off = node * 6 + side * 3
        end = off + 3
    elif record_size == 28:
        off = node * 7
        end = off + 7
    elif record_size == 32:
        off = node * 8 + side * 4
        end = off + 4
    else:  # 调用方已在 metadata 门拒绝其它值
        raise MMDBInvalid("record_size 非法")
    if end > tree_size:
        raise MMDBInvalid("节点记录越出搜索树区域(结构异常)")
    b = buf[off:end]
    if record_size == 24:
        return int.from_bytes(b, "big")
    if record_size == 28:
        if side == 0:
            return ((b[3] & 0xF0) >> 4) << 24 | int.from_bytes(b[:3], "big")
        return (b[3] & 0x0F) << 24 | int.from_bytes(b[4:7], "big")
    return int.from_bytes(b, "big")


def _walk_tree(
    buf: bytes,
    *,
    node_count: int,
    record_size: int,
    tree_size: int,
    data_end: int,
    ip_version: int,
) -> int:
    """对探针地址真实走树;返回成功通过走树越界门的探针数。

    ip_version=6(真实 GeoLite2 为 v6 混合树)时先走 96 个零位再走 IPv4 位;
    ip_version=4 时直接从 node 0 走地址位。"""
    probes = []
    for ip in _PROBE_IPV4:
        octets = [int(p) for p in ip.split(".")]
        addr_bits = [(o >> (7 - i)) & 1 for o in octets for i in range(8)]
        probes.append(([0] * 96 if ip_version == 6 else []) + addr_bits)

    ok = 0
    for bits in probes:
        node = 0
        visited: set[int] = set()
        for step in range(_MAX_WALK_STEPS):
            if node in visited:
                raise MMDBInvalid("走树遇环(结构异常)")
            visited.add(node)
            bit = bits[step] if step < len(bits) else 0
            rec = _read_record(buf, node, bit, record_size, tree_size)
            if rec == 0:
                break  # not found:探针为文档段地址,属正常
            if rec < node_count:
                node = rec
                continue
            # R3 修正(阻塞 ①):数据指针文件内位置 = tree_size + (rec - node_count)。
            # 规范:rec=node_count+n(n=1..15)落在 16 字节分隔符内部 = 非法,拒绝;
            # rec==node_count(offset 0 = 分隔符首字节,解码为空 map)在真实
            # MaxMind 文件的「无数据」路径上实证存在(公开 test-data
            # GeoLite2-Country-Test.mmdb;官方 reader 对其返回 None),放行。
            offset = rec - node_count
            if 0 < offset < _DATA_SECTION_SEPARATOR_BYTES:
                raise MMDBInvalid("数据指针落入数据段分隔符内部(结构异常)")
            absolute = tree_size + offset
            if absolute >= data_end:
                raise MMDBInvalid("数据指针越出数据段(结构异常)")
            break
        else:
            raise MMDBInvalid("走树超出最大步数(结构异常)")
        ok += 1
    return ok


def validate_bytes(
    data: bytes, *, expected_type: str = _EXPECTED_DB_TYPE, min_bytes: int = DEFAULT_MIN_BYTES
) -> str:
    """对完整文件字节做硬结构校验;通过返回类别化摘要,失败抛 MMDBInvalid。"""
    if len(data) < min_bytes:
        raise MMDBInvalid(f"体积 {len(data)} 低于下限 {min_bytes}(疑似截断)")

    idx = data.rfind(METADATA_MARKER)
    if idx == -1:
        raise MMDBInvalid("metadata 标记缺失")

    meta, end_pos = _decode(
        data, idx + len(METADATA_MARKER), pointer_base=idx + len(METADATA_MARKER)
    )
    if end_pos != len(data):
        raise MMDBInvalid("metadata 未精确消费到 EOF(尾部截断或附加垃圾)")
    if not isinstance(meta, dict):
        raise MMDBInvalid("metadata 不是 map(结构异常)")

    db_type = meta.get("database_type")
    if db_type != expected_type:
        raise MMDBInvalid(f"database_type 不匹配(期望 {expected_type})")
    if meta.get("binary_format_major_version") != 2:
        raise MMDBInvalid("binary_format_major_version ≠ 2")
    if meta.get("ip_version") not in (4, 6):
        raise MMDBInvalid("ip_version 非 4/6")
    record_size = meta.get("record_size")
    if record_size not in (24, 28, 32):
        raise MMDBInvalid("record_size 非 24/28/32")
    node_count = meta.get("node_count")
    if not isinstance(node_count, int) or isinstance(node_count, bool) or node_count < 1:
        raise MMDBInvalid("node_count 非法")

    tree_size = node_count * record_size * 2 // 8
    data_start = tree_size + _DATA_SECTION_SEPARATOR_BYTES
    if idx < data_start:
        raise MMDBInvalid("搜索树+分隔符区域与 metadata 标记位置矛盾(布局异常)")

    probes_ok = _walk_tree(
        data,
        node_count=node_count,
        record_size=record_size,
        tree_size=tree_size,
        data_end=idx,
        ip_version=meta.get("ip_version"),
    )
    return (
        f"MMDB 硬结构校验通过: type={db_type} node_count={node_count} "
        f"record_size={record_size} 走树探针 {probes_ok}/{len(_PROBE_IPV4)} 未越界"
    )


def validate_file(path: str, *, min_bytes: int = DEFAULT_MIN_BYTES) -> str:
    with open(path, "rb") as fh:
        return validate_bytes(fh.read(), min_bytes=min_bytes)


def _cli() -> int:
    parser = argparse.ArgumentParser(description="GeoLite2-Country MMDB 硬结构校验(stdlib)")
    parser.add_argument("file")
    parser.add_argument("--min-bytes", type=int, default=DEFAULT_MIN_BYTES)
    args = parser.parse_args()
    try:
        print(validate_file(args.file, min_bytes=args.min_bytes))
        return 0
    except (MMDBInvalid, OSError) as exc:
        print(f"MMDB 校验拒绝: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_cli())
