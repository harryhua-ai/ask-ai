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
(操作员现场比对;禁止落入持久日志/Issue)。发布绑定的 HostIp/HostPort
同样**不回显**(R3 阻塞 ②:旧 G8 FAIL 消息插值真实宿主 IP = 日志泄漏)。

CLI(precheck-geoip2.sh 调用;nginx dump / ports JSON 从 stdin 读,不落盘):
    python3 precheck_checks.py cidr     --cidrs S --gateway G
    python3 precheck_checks.py nginx    --header H --mmdb P --port N --expect on|off < dump
    python3 precheck_checks.py binding  --host-ip IP
    python3 precheck_checks.py bindings --backend-port N [--container-port P] < ports.json
退出码 0=PASS,1=FAIL;stdout 一行类别消息。
"""

from __future__ import annotations

import argparse
import ipaddress
import json
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
_LOOPBACK_IPS = ("127.0.0.1", "::1")


def _binding_is_loopback(host_ip: str) -> bool:
    return (host_ip or "").strip() in _LOOPBACK_IPS


def check_publish_binding(host_ip: str) -> tuple[bool, str]:
    """backend 发布端口绑定必须为 loopback(受信跳边界,fail-closed)。

    Docker 标准端口发布(0.0.0.0/::)接受非 nginx vhost 流量;DNAT 后源地址
    表现为网桥网关 peer,与 nginx 转发的直连 peer 不可区分 → 网关 /32 授信
    被旁路。收口(loopback 绑定或等效宿主防火墙)属**另行授权的网络变更**,
    未验证前必须保持 off。"""
    ip = (host_ip or "").strip()
    if ip in _LOOPBACK_IPS:
        return True, "发布端口仅绑定 loopback(受信跳边界成立)"
    if ip in ("0.0.0.0", "::", ""):
        return False, (
            "发布端口绑定所有地址(0.0.0.0/::)或绑定信息不可得 —— 外部/同网段"
            "流量可经 DNAT 伪装成网桥网关 peer,网关 /32 授信被旁路;保持 off。"
            "收口需另行授权(loopback 绑定或防火墙),验证与回滚见 README §2.4"
        )
    return False, "发布端口绑定非 loopback 地址 —— 同 0.0.0.0,受信跳边界不成立,保持 off"


def check_publish_bindings(
    ports_json: str, *, backend_port: int, container_port: str = "8000/tcp"
) -> tuple[bool, str]:
    """R3 修正(阻塞 ②):审计**全部**发布映射的**每一条** HostIp/HostPort。

    旧实现只取 `NetworkSettings.Ports[port][0].HostIp` 单值:第一条 loopback、
    第二条 0.0.0.0/::/公网 IP 时假 PASS;FAIL 消息还插值真实宿主 IP(日志泄漏)。
    本函数(fail-closed,类别输出,零值回显):
      - 发布映射 JSON 不可得/不可解析/为空 = FAIL;
      - 目标容器端口无映射或绑定列表为空 = FAIL;
      - 任一端口任一条绑定:HostIp 缺失/空/非 loopback = FAIL(单项否决);
      - 目标端口的任一条绑定 HostPort 缺失/非整数 = FAIL;
      - 目标端口绑定 HostPort 必须含 nginx 实际使用的 backend_port = FAIL(不一致)。
    """
    try:
        ports = json.loads(ports_json or "")
    except ValueError:
        return False, "发布端口映射不可解析(JSON)—— 绑定审计无法成立,保持 off"
    if not isinstance(ports, dict) or not ports:
        return False, "发布端口映射为空或形态非法 —— backend 无受审计的发布面,保持 off"

    bindings = ports.get(container_port)
    if not isinstance(bindings, list) or not bindings:
        return (
            False,
            f"目标容器端口({container_port})无发布绑定 —— nginx 无法到达 backend,保持 off",
        )

    host_ports: list[str] = []
    for port_key, entries in ports.items():
        if not isinstance(entries, list):
            return False, "发布映射条目形态非法 —— fail closed,保持 off"
        for entry in entries:
            if not isinstance(entry, dict):
                return False, "发布绑定形态非法 —— fail closed,保持 off"
            hip = entry.get("HostIp")
            if hip is None or str(hip).strip() == "":
                return False, "存在缺失 HostIp 的发布绑定(单项缺失 = fail closed),保持 off"
            if not _binding_is_loopback(str(hip)):
                return False, (
                    "存在非 loopback 的发布绑定(全部映射逐一审计)—— 外部/同网段流量可经 "
                    "DNAT 伪装成网桥网关 peer,网关 /32 授信被旁路;保持 off。"
                    "收口需另行授权(loopback 绑定或防火墙),验证与回滚见 README §2.4"
                )
            if port_key == container_port:
                hport = entry.get("HostPort")
                if hport is None or str(hport).strip() == "":
                    return False, "存在缺失 HostPort 的发布绑定(单项缺失 = fail closed),保持 off"
                if not str(hport).strip().isdigit():
                    return False, "存在非法 HostPort 的发布绑定 —— fail closed,保持 off"
                host_ports.append(str(hport).strip())

    if not host_ports:
        return False, "目标容器端口发布绑定不可审计 —— fail closed,保持 off"
    if str(backend_port) not in host_ports:
        return (
            False,
            "发布绑定与 nginx 实际使用的 backend 端口不一致 —— 所审非所转,保持 off",
        )
    return (
        True,
        (
            f"全部发布映射(含目标端口 {len(host_ports)} 条绑定)仅绑定 loopback,"
            "且含 nginx 使用的 backend 端口(受信跳边界成立)"
        ),
    )


# -------------------------------------------------------------------- nginx --
def _proxy_authority(arg: str) -> str | None:
    """从 proxy_pass 参数提取 authority(scheme://host[:port][/path])。

    变量型/不可解析目标返回 None(= 不可审计,fail closed)。"""
    rest = arg.split("://", 1)[1] if "://" in arg else arg
    auth = rest.split("/", 1)[0].strip()
    if not auth or "$" in auth or "{" in auth:
        return None
    return auth


def _split_host_port(authority: str) -> tuple[str | None, int | None]:
    """authority → (host, port);port = 显式端口或 None(默认 80 语义)。"""
    auth = (authority or "").strip()
    if not auth:
        return None, None
    if auth.startswith("["):  # [v6 字面量][:port]
        end = auth.find("]")
        if end == -1:
            return auth, None
        host, rest = auth[: end + 1], auth[end + 1 :]
        if rest.startswith(":") and rest[1:].isdigit():
            return host, int(rest[1:])
        return host, None
    if auth.rsplit(":", 1)[-1].isdigit() and ":" in auth:
        host, port = auth.rsplit(":", 1)
        return host, int(port)
    return auth, None


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
    """深度遍历,携带上下文标签链(如 http→server→location /)。

    R3 修正(阻塞 ③):同层同名容器(server/location/if)追加 **#序号**
    消歧 —— 否则第二个 vhost 的 location 与第一个共享同一 ctx 元组,
    「第二个 vhost 裸 proxy_pass」会借用第一个 vhost 的头覆盖假 PASS。"""
    seen: dict[tuple[tuple[str, ...], str], int] = {}
    for name, args, block in items:
        yield ctx, name, args, block
        if block is not None:
            label = f"{name} {' '.join(args)}" if name in ("location", "if") else name
            key = (ctx, label)
            seen[key] = seen.get(key, 0) + 1
            uniq = label if seen[key] == 1 else f"{label}#{seen[key]}"
            yield from _walk(block, ctx + (uniq,))


def _label_kind(label: str) -> str:
    """去掉消歧 #序号 后的容器种类(server / location …)。"""
    return label.split("#", 1)[0]


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
      R3 **全部**指向 backend 端口的 proxy_pass 路径(含显式 upstream)
         逐一证明生效层有无条件 proxy_set_header <header>=$<map 变量>:
         生效层按 nginx 继承语义从内向外取第一个含任一 proxy_set_header
         的层级(location 内层→外层→server→http);任何一条路径断裂 =
         FAIL。不能审计的路径(变量型 proxy_pass / 歧义 upstream 命名)=
         FAIL(拒绝不能审计的额外路径);
      R4 全配置内该头名不得有静态值/他处覆盖/if 包裹(无条件覆盖语义);
      R5 生效配置不得含 real_ip_*/set_real_ip_from(可伪造 XFF 可被提升为
         $remote_addr;受信 RealIP 拓扑不可机械证实 → fail closed,而非仅
         文档声明「不要配置」)。
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

    # R5:受信 RealIP 拓扑不可机械证实 → 任何 real_ip_* 都 fail closed
    real_ip = [n for _, n, _, _ in flat if n.startswith("real_ip_") or n == "set_real_ip_from"]
    if real_ip:
        return False, (
            "生效配置含 real_ip_*/set_real_ip_from(可伪造 X-Forwarded-For 可被提升为"
            "$remote_addr;受信 RealIP 拓扑不可机械证实)→ 保持 off"
        )

    # ---- R3:枚举全部 backend 路径,不可审计路径 fail closed -------------
    # upstream 名 → server 显式端口集合(None = 存在无端口 server,歧义)
    upstreams: dict[str, set[int] | None] = {}
    for _, name, args, block in flat:
        if name == "upstream" and args and block is not None:
            entries = [srv.split()[0] for n, a, _ in block if n == "server" for srv in a]
            ports = {_split_host_port(e)[1] for e in entries}
            prev = upstreams.get(args[0], ports)
            if None in ports or prev is None:  # 无显式端口 server = 歧义命名
                upstreams[args[0]] = None
            else:
                upstreams[args[0]] = ports | prev

    def _classify(arg: str) -> bool | None:
        """proxy_pass 目标分类:True=backend 路径 / False=与 backend 无关 /
        None=不可审计(变量、歧义 upstream)。"""
        host, port = _split_host_port(_proxy_authority(arg) or "")
        if host is None:
            return None
        if port == backend_port:
            return True
        if host in upstreams:
            ups = upstreams[host]
            if ups is None:  # upstream 含无显式端口的 server = 歧义命名
                return None
            return backend_port in ups
        return False  # 显式其它端口或无端口域名(默认 80 ≠ backend 端口)

    backend_paths: list[tuple[str, ...]] = []
    for c, a in ppass:
        for arg in a:
            verdict = _classify(arg)
            if verdict is None:
                return (
                    False,
                    (
                        "存在不可审计的 proxy_pass 目标(变量型/歧义 upstream 命名)"
                        "—— 无法证明是否为 backend 路径,fail closed,保持 off"
                    ),
                )
            if verdict:
                backend_paths.append(c)
                break
    if not backend_paths:
        return False, "生效配置未找到指向 backend 端口的 proxy_pass —— 保持 off"

    # nginx 继承遮蔽:从内向外找第一个含任一 proxy_set_header 的层级,
    # 该层即为生效层;同名头必须是 $<map 变量>(无条件计算值)。
    def _effective_level_has_header(ctx: tuple[str, ...]) -> bool:
        levels: list[tuple[str, ...]] = []
        for i, label in enumerate(ctx):
            if _label_kind(label).startswith("location"):
                levels.append(ctx[: i + 1])
        levels.reverse()  # 内层 → 外层
        srv = [i for i, label in enumerate(ctx) if _label_kind(label) == "server"]
        if srv:
            levels.append(ctx[: srv[-1] + 1])
        if ctx and _label_kind(ctx[0]) == "http":
            levels.append(ctx[:1])
        for level in levels:
            at_level = [a for c, a in psh if c == level]
            if at_level:  # 继承在此层被遮蔽并终止
                return any(a and a[0].lower() == header_l and a[1:] == [mvar] for a in at_level)
        return False

    # R4 先行:全配置内该头名不得有任何非计算值/包 if 的出现(精确归因),
    # 再对**每条** backend 路径做生效层判定。
    for c, a in psh:
        if a and a[0].lower() == header_l:
            if any(_label_kind(step) == "if" or _label_kind(step).startswith("if ") for step in c):
                return False, "geo 头下发被包在 if 块内 —— 无条件覆盖语义破坏,保持 off"
            if a[1:] != [mvar]:
                return False, "存在非计算值的同名头(静态值/他处覆盖)—— 保持 off"

    broken = sum(1 for ctx in backend_paths if not _effective_level_has_header(ctx))
    if broken:
        return (
            False,
            (
                f"存在生效层缺失无条件 proxy_set_header <头>=$<map 变量的 backend 路径"
                f"(共 {len(backend_paths)} 条 backend 路径,{broken} 条断裂;"
                "静态值或缺失均不合格)—— 覆盖链断裂,保持 off"
            ),
        )
    return (
        True,
        (
            f"nginx 生效配置覆盖链完整(geoip2+map+全部 {len(backend_paths)} 条 backend"
            "路径无条件同名头覆盖,基于 nginx -T dump)"
        ),
    )


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
    pb = sub.add_parser("binding", help="发布端口 loopback 边界(单条绑定)")
    pb.add_argument("--host-ip", required=True)
    pbs = sub.add_parser("bindings", help="全部发布映射逐一审计(R3 阻塞 ②)")
    pbs.add_argument("--backend-port", type=int, required=True)
    pbs.add_argument("--container-port", default="8000/tcp")
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
    elif args.mode == "bindings":
        ok, msg = check_publish_bindings(
            sys.stdin.read(), backend_port=args.backend_port, container_port=args.container_port
        )
    else:
        ok, msg = check_publish_binding(args.host_ip)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_cli())
