#!/usr/bin/env python3
"""#114 precheck 纯函数检查库(可离线单测的机械门逻辑)。

R2 审查修正:precheck-geoip2.sh 的两处核心门从「源码 grep / 含网关即过」
改为机械精确语义,逻辑集中在本模块以便离线负向 fixture 单测:

- check_trusted_cidrs_exact:受信 CIDR 必须与网桥网关 /32 **精确相等**
  (旧逻辑接受含网关的任意网桥子网,整 /24 也假 PASS);
- check_effective_nginx_config:基于 `nginx -T` **生效配置** dump 解析
  geoip2 → map → proxy_set_header 覆盖链(注释不进 dump,静态值仍可见 ——
  旧逻辑 grep 源文件会命中被注释指令或静态值,假 PASS);
- check_publish_binding:backend 发布端口必须仅绑定 loopback(R1 阻塞项:
  0.0.0.0 发布时,外部/同网段流量经 DNAT 后同样表现为网桥网关 peer,
  网关 /32 授信被旁路,信任模型不成立)。

红线:所有结论只输出类别/布尔/计数,**不回显**真实网关/子网/CIDR/头名值
(操作员现场比对;禁止落入持久日志/Issue)。

CLI(precheck-geoip2.sh 调用;nginx 模式从 stdin 读 dump,不落盘):
    python3 precheck_checks.py cidr    --cidrs S --gateway G
    python3 precheck_checks.py nginx   --header H --mmdb P --port N --expect on|off < dump
    python3 precheck_checks.py binding --host-ip IP
退出码 0=PASS,1=FAIL;stdout 一行类别消息。
"""

from __future__ import annotations

import argparse
import ipaddress
import sys

GEOIP2_VAR = "$ask_ai_geoip_country_code"
MAP_VAR = "$ask_ai_geo_country"


# --------------------------------------------------------------------- CIDR --
def check_trusted_cidrs_exact(cidrs_text: str, gateway: str) -> tuple[bool, str]:
    """受信列表必须与网桥网关 /32 精确相等(恰好 1 条 = 该单地址)。

    契约语义:「只有 nginx 能供 geo-country」要求信任面 = 网关单地址;
    含网关的整网段(如整个网桥 /24)会让同网段任一容器可伪造,拒绝。
    """
    entries = [e.strip() for e in (cidrs_text or "").split(",") if e.strip()]
    if not entries:
        return False, "受信列表为空 = 无人可信(启用态非法)"
    if len(entries) != 1:
        return False, f"受信条目数={len(entries)};契约要求恰好 1 条 = 网关 /32 精确相等"
    try:
        net = ipaddress.ip_network(entries[0], strict=False)
        gw = ipaddress.ip_address(gateway)
    except ValueError:
        return False, "受信条目或网关地址非法(值不回显)"
    if net.version != 4 or gw.version != 4:
        return False, "受信条目/网关须为 IPv4(compose 网桥语义)"
    if net != ipaddress.ip_network(f"{gw}/32"):
        if net.prefixlen < 32 and gw in net:
            return False, "受信条目宽于网关 /32(覆盖网关但含同网段其它地址)—— 拒绝"
        return False, "受信条目不是「网关 /32 精确相等」—— 拒绝"
    return True, "受信 CIDR = 网桥网关 /32(精确相等)"


# ------------------------------------------------------------------ binding --
def check_publish_binding(host_ip: str) -> tuple[bool, str]:
    """backend 发布端口绑定必须为 loopback(受信跳边界,fail-closed)。

    Docker 标准端口发布(0.0.0.0/::)接受非 nginx vhost 流量;DNAT 后源地址
    表现为网桥网关 peer,与 nginx 转发的直连 peer 不可区分 → 网关 /32 授信
    被旁路。收口(loopback 绑定或等效宿主防火墙)属**另行授权的网络变更**,
    未验证前必须保持 off。"""
    ip = (host_ip or "").strip()
    if ip in ("127.0.0.1", "::1"):
        return True, "发布端口仅绑定 loopback(受信跳边界成立)"
    if ip in ("0.0.0.0", "::", ""):
        return False, (
            "发布端口绑定所有地址(0.0.0.0/::)或绑定信息不可得 —— 外部/同网段"
            "流量可经 DNAT 伪装成网桥网关 peer,网关 /32 授信被旁路;保持 off。"
            "收口需另行授权(loopback 绑定或防火墙),验证与回滚见 README §2.4"
        )
    return False, "发布端口绑定非 loopback 地址 —— 同 0.0.0.0,受信跳边界不成立,保持 off"


# -------------------------------------------------------------------- nginx --
class _Parser:
    """nginx 配置 tokenize + 嵌套解析(nginx -T dump:注释已被剥离)。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def _tokens(self) -> list[str]:
        text, n = self.text, len(self.text)
        tokens: list[str] = []
        i, buf = 0, ""
        while i < n:
            c = text[i]
            if c == "#":  # dump 理论无注释;双保险剥离
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if c in " \t\r\n":
                if buf:
                    tokens.append(buf)
                    buf = ""
                i += 1
                continue
            if c in "\"'":
                quote, i, val = c, i + 1, ""
                while i < n and text[i] != quote:
                    if text[i] == "\\" and i + 1 < n:
                        val += text[i + 1]
                        i += 2
                    else:
                        val += text[i]
                        i += 1
                i += 1
                tokens.append(val)  # 去引号后的字面值(空串保留)
                continue
            if c in ";{}":
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(c)
                i += 1
                continue
            buf += c
            i += 1
        if buf:
            tokens.append(buf)
        return tokens

    def parse(self) -> list[tuple[str, list[str], list | None]]:
        tokens = self._tokens()
        pos = 0

        def parse_block() -> list[tuple[str, list[str], list | None]]:
            nonlocal pos
            items: list[tuple[str, list[str], list | None]] = []
            while pos < len(tokens):
                if tokens[pos] == "}":
                    pos += 1
                    return items
                args: list[str] = []
                while pos < len(tokens) and tokens[pos] not in (";", "{", "}"):
                    args.append(tokens[pos])
                    pos += 1
                if pos >= len(tokens):
                    break
                if tokens[pos] == "{":
                    pos += 1
                    block = parse_block()
                    if args:
                        items.append((args[0], args[1:], block))
                else:  # ';' 或裸 '}'
                    if tokens[pos] == ";":
                        pos += 1
                    if args:
                        items.append((args[0], args[1:], None))
            return items

        return parse_block()


def _walk(items: list[tuple[str, list[str], list | None]], ctx: tuple[str, ...] = ()):
    """深度遍历,携带上下文标签链(如 http→server→location /)。"""
    for name, args, block in items:
        yield ctx, name, args, block
        if block is not None:
            label = f"{name} {' '.join(args)}" if name in ("location", "if") else name
            yield from _walk(block, ctx + (label,))


def check_effective_nginx_config(
    dump: str,
    *,
    header: str,
    mmdb_path: str,
    backend_port: int,
    expect: str = "on",
) -> tuple[bool, str]:
    """基于 nginx -T 生效配置机械验证覆盖链(on)或默认关闭(off)。

    on 模式规则:
      R1 恰有 1 个 geoip2 块,数据库路径与 MMDB_PATH 一致,块内含
         auto_reload 且定义了输出变量;
      R2 该输出变量被恰好 1 个 map 消费,map 输出变量为下发变量,块内
         default→空串 且 XX→空串;
      R3 存在 proxy_pass 指向 backend 端口的 location;该 location 自身
         (若其内有任何 proxy_set_header;否则其 server 级)必须含
         proxy_set_header <header> $<map 输出变量>(nginx 的
         proxy_set_header 不按指令继承 —— location 内一旦出现任何
         proxy_set_header,父级全部失效,故必须落在生效层);
      R4 全配置内该头名不得出现任何非计算值的其它取值(静态值/他处
         覆盖),也不得包在 if 块内(无条件覆盖语义)。
    off 模式规则:生效配置中不得出现 geoip2 指令、消费 geoip2 变量的
      map、或下发 geo 头的 proxy_set_header。
    """
    header_l = (header or "").strip().lower()
    if not header_l:
        return False, "backend 头名未配置,nginx 侧一致性无从核验 —— 保持 off"
    try:
        directives = _Parser(dump).parse()
    except (IndexError, ValueError):
        return False, "nginx -T 生效配置解析失败(结构异常)—— 保持 off"
    flat = list(_walk(directives))
    geo2 = [(a, b) for _, n, a, b in flat if n == "geoip2"]
    maps = [(a, b) for _, n, a, b in flat if n == "map"]
    psh = [(c, a) for c, n, a, _ in flat if n == "proxy_set_header"]
    ppass = [(c, a) for c, n, a, _ in flat if n == "proxy_pass"]

    if expect == "off":
        if geo2:
            return False, "生效配置含 geoip2 指令 —— 与默认关闭不符"
        if any(a and len(a) >= 2 and a[0] == GEOIP2_VAR for a, _ in maps):
            return False, "生效配置含 geoip2 输出变量的 map —— 与默认关闭不符"
        for _, a in psh:
            if a and a[0].lower() == header_l:
                return False, "生效配置含 geo 头下发 —— 与默认关闭不符"
        return True, "nginx 生效配置无 geoip2/geo 头(默认关闭成立,基于 nginx -T dump)"

    # ---- on 模式 ----
    if len(geo2) != 1:
        return False, f"geoip2 指令数={len(geo2)}(须恰 1)—— 覆盖链断裂,保持 off"
    gargs, gblock = geo2[0]
    if not gargs or gargs[0] != mmdb_path:
        return False, "geoip2 数据库路径与 MMDB_PATH 不一致 —— 保持 off"
    gnames = [n for n, _, _ in (gblock or [])]
    if "auto_reload" not in gnames:
        return False, "geoip2 块缺 auto_reload(原子替换后免 reload 语义失效)"
    gvars = [n for n in gnames if n.startswith("$")]
    if not gvars:
        return False, "geoip2 块未定义输出变量"
    gvar = gvars[0]

    consumers = [(a, b) for a, b in maps if len(a) >= 2 and a[0] == gvar]
    if len(consumers) != 1:
        return False, f"geoip2 输出变量的 map 数={len(consumers)}(须恰 1)"
    margs, mblock = consumers[0]
    mvar = margs[1]
    if not mvar.startswith("$"):
        return False, "map 结果须为变量(下发值必须经 map 计算)"
    mentries = [a for n, a, _ in (mblock or []) if n == "default"]
    if not mentries or mentries[0] != [""]:
        return False, "map 缺 default→空串(无数据/内网 IP 必须不下发头)"
    xx = [a for n, a, _ in (mblock or []) if n == "XX"]
    if not xx or xx[0] != [""]:
        return False, "map 缺 XX→空串(保留码必须不下发头)"

    api_ctx = None
    for c, a in ppass:
        if any(f":{backend_port}" in arg for arg in a):
            api_ctx = c
            break
    if api_ctx is None:
        return False, "生效配置未找到指向 backend 端口的 proxy_pass —— 保持 off"

    def _direct_children(ctx_prefix: tuple[str, ...]) -> list[list[str]]:
        return [a for c, a in psh if c == ctx_prefix]

    # R4 先行:全配置内该头名不得有任何非计算值/包 if 的出现(精确归因),
    # 再做 R3 生效层存在性判定。
    for c, a in psh:
        if a and a[0].lower() == header_l:
            if any(step.startswith("if ") or step == "if" for step in c):
                return False, "geo 头下发被包在 if 块内 —— 无条件覆盖语义破坏,保持 off"
            if a[1:] != [mvar]:
                return False, "存在非计算值的同名头(静态值/他处覆盖)—— 保持 off"

    loc_levels = [i for i, c in enumerate(api_ctx) if c.startswith("location ")]
    srv_levels = [i for i, c in enumerate(api_ctx) if c == "server"]
    matched = False
    if loc_levels:
        loc_ctx = api_ctx[: loc_levels[-1] + 1]
        children = _direct_children(loc_ctx)
        if children:  # location 级有任一 proxy_set_header ⇒ 生效层就是这里
            matched = any(a and a[0].lower() == header_l and a[1:] == [mvar] for a in children)
        else:
            srv_ctx = api_ctx[: srv_levels[-1] + 1] if srv_levels else api_ctx
            matched = any(
                a and a[0].lower() == header_l and a[1:] == [mvar]
                for a in _direct_children(srv_ctx)
            )
    else:
        srv_ctx = api_ctx[: srv_levels[-1] + 1] if srv_levels else api_ctx
        matched = any(
            a and a[0].lower() == header_l and a[1:] == [mvar] for a in _direct_children(srv_ctx)
        )
    if not matched:
        return (
            False,
            "生效 location/server 层未找到无条件 proxy_set_header <头>=$<map 变量>(静态值或缺失均不合格)—— 覆盖链断裂,保持 off",
        )
    return True, "nginx 生效配置覆盖链完整(geoip2+map+无条件同名头覆盖,基于 nginx -T dump)"


# ----------------------------------------------------------------------- CLI --
def _cli() -> int:
    parser = argparse.ArgumentParser(description="#114 precheck 机械门(类别输出)")
    sub = parser.add_subparsers(dest="mode", required=True)
    pc = sub.add_parser("cidr", help="受信 CIDR = 网关 /32 精确相等")
    pc.add_argument("--cidrs", required=True)
    pc.add_argument("--gateway", required=True)
    pn = sub.add_parser("nginx", help="nginx -T 生效配置覆盖链校验(dump 走 stdin)")
    pn.add_argument("--header", required=True)
    pn.add_argument("--mmdb", required=True)
    pn.add_argument("--port", type=int, required=True)
    pn.add_argument("--expect", choices=("on", "off"), default="on")
    pb = sub.add_parser("binding", help="发布端口 loopback 边界")
    pb.add_argument("--host-ip", required=True)
    args = parser.parse_args()

    if args.mode == "cidr":
        ok, msg = check_trusted_cidrs_exact(args.cidrs, args.gateway)
    elif args.mode == "nginx":
        ok, msg = check_effective_nginx_config(
            sys.stdin.read(),
            header=args.header,
            mmdb_path=args.mmdb,
            backend_port=args.port,
            expect=args.expect,
        )
    else:
        ok, msg = check_publish_binding(args.host_ip)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_cli())
