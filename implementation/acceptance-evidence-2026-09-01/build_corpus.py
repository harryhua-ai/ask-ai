"""构建 CamThink V1 自然产品验收语料(corpus.jsonl)。

语料来源(真实材料,不造合成题):
- standard_questions.json 117 题真实客户问题库(按 intent/product 分层抽样,引用 bank 索引)
- e2e_intent_en.py 的英文模板题(商务/规格/部署)
- 真实故障案例衍生的多轮排障序列(轮2补充信息取自案例真实细节)
- 附件场景:合成设备日志(格式仿真实案例,不含任何真实 PII/设备号)

用法: python3 build_corpus.py  →  写出 corpus.jsonl
"""
import json
from pathlib import Path

BANK = Path.home() / "Documents/GitHub/Knowledge/知识库/Think/ASK AI/optimize/standard_questions.json"
OUT = Path(__file__).parent / "corpus.jsonl"

bank = json.loads(BANK.read_text(encoding="utf-8"))["questions"]

EN = {
    "price": "What is the price of {m}, how to order and shipping options",
    "distributor": "How to become CamThink distributor for {m} in our region",
    "moq": "How to purchase {m}, minimum order quantity and lead time",
    "temp": "What is the operating temperature range of NE301 edge camera",
    "halow": "Does NE101 support WiFi HaLow connectivity",
    "sensor503": "What sensor does NE503 use, resolution and frame rate",
    "onvif": "Does NE101 support ONVIF protocol for video streaming",
    "models503": "What AI models are pre-installed on NE503",
    "flash": "How to flash firmware on NE301, external flash erase failure and DIP switch setup",
    "power": "What is the power supply requirement for NE101, voltage range",
}

scenarios = []


def add(sid, family, bank_idx=None, text=None, en_key=None, en_model=None,
        turns=None, target="prod", channel="admin", attachment=None,
        expected_intent=None, product=None, note=""):
    """bank_idx: 引用题库;text/en_key: 直出题;turns: 多轮列表(dict 带 bank_idx 或 text)。"""
    if turns is None:
        if bank_idx is not None:
            q = bank[bank_idx]["question"]
        elif en_key:
            q = EN[en_key].format(m=en_model)
        else:
            q = text
        turns = [{"text": q}]
    scen = {
        "id": sid, "family": family, "target": target, "channel": channel,
        "expected_intent": expected_intent, "product": product, "note": note,
        "turns": [
            {"text": bank[t["bank_idx"]]["question"]} if t.get("bank_idx") is not None
            else {"text": t["text"]}
            for t in turns
        ],
    }
    if bank_idx is not None:
        b = bank[bank_idx]
        scen["bank_ground_truth"] = {
            "expected_answer": b.get("expected_answer", ""),
            "expected_behavior": b.get("expected_behavior", ""),
            "source_file": b.get("source_file", ""),
        }
        scen["expected_intent"] = scen["expected_intent"] or b["intent"]
        scen["product"] = scen["product"] or b.get("product")
    if attachment:
        scen["attachment"] = attachment
    scenarios.append(scen)


# ============ A 商务(11) ============
add("A01", "commercial", bank_idx=25)
add("A02", "commercial", bank_idx=29)
add("A03", "commercial", bank_idx=50)
add("A04", "commercial", bank_idx=51)
add("A05", "commercial", bank_idx=92)
add("A06", "commercial", bank_idx=76)
add("A07", "commercial", bank_idx=87)
add("A08", "commercial", en_key="price", en_model="NE301", expected_intent="commercial", product="NE301")
add("A09", "commercial", en_key="distributor", en_model="NE101", expected_intent="commercial", product="NE101")
add("A10", "commercial", en_key="moq", en_model="NE503", expected_intent="commercial", product="NE503")
add("A11", "commercial", bank_idx=71)

# ============ B 产品(15) ============
add("B01", "product", bank_idx=3, note="G-深查引用")
add("B02", "product", bank_idx=4)
add("B03", "product", bank_idx=26, note="G-深查引用")
add("B04", "product", bank_idx=17)
add("B05", "product", bank_idx=52)
add("B06", "product", bank_idx=47)
add("B07", "product", bank_idx=49)
add("B08", "product", bank_idx=60)
add("B09", "product", bank_idx=80, note="G-深查引用")
add("B10", "product", bank_idx=90)
add("B11", "product", en_key="temp", expected_intent="product", product="NE301", note="G-深查引用")
add("B12", "product", en_key="halow", expected_intent="product", product="NE101")
add("B13", "product", en_key="sensor503", expected_intent="product", product="NE503", note="G-深查引用")
add("B14", "product", en_key="onvif", expected_intent="product", product="NE101", note="H 双探:KB 可能不足")
add("B15", "product", en_key="models503", expected_intent="product", product="NE503", note="H 双探:KB 可能不足")

# ============ C 方案咨询(12) ============
add("C01", "solution", bank_idx=93)
add("C02", "solution", bank_idx=96)
add("C03", "solution", bank_idx=100)
add("C04", "solution", bank_idx=102)
add("C05", "solution", bank_idx=104)
add("C06", "solution", bank_idx=106)
add("C07", "solution", bank_idx=107)
add("C08", "solution", bank_idx=110, note="G-深查引用")
add("C09", "solution", bank_idx=111)
add("C10", "solution", bank_idx=57)
add("C11", "solution", bank_idx=59)
add("C12", "solution", bank_idx=109)

# ============ D 支持(13) ============
add("D01", "support", bank_idx=0)
add("D02", "support", bank_idx=1)
add("D03", "support", bank_idx=2)
add("D04", "support", bank_idx=21)
add("D05", "support", bank_idx=44)
add("D06", "support", bank_idx=56)
add("D07", "support", bank_idx=58)
add("D08", "support", bank_idx=78)
add("D09", "support", bank_idx=81)
add("D10", "support", bank_idx=84)
add("D11", "support", bank_idx=86)
add("D12", "support", en_key="flash", expected_intent="support", product="NE301")
add("D13", "support", en_key="power", expected_intent="support", product="NE101", note="G-深查引用")

# ============ E 排障多轮(6×2=12 轮) ============
add("E01", "troubleshooting", turns=[
    {"bank_idx": 5},
    {"text": "补充信息:我看了设备日志,AT+CEREG? 一直返回 +CEREG: 0,3。SIM 卡是 Verizon 的(APN: PODSYSTE.VZWENTP),"
             "但部署位置附近好像只有 AT&T 的基站信号。照片还能补传吗?这该怎么解决?"},
], note="根因底稿:SIM(Verizon MVNO)与驻留网(AT&T)不匹配,CEREG=3 拒绝注册")
add("E02", "troubleshooting", turns=[
    {"bank_idx": 56},
    {"text": "补充信息:broker 是我电脑上的 NeoMind(192.168.1.101:1883),相机和电脑在同一网段,电脑 ping 相机是通的,"
             "Web UI 一直显示 MQTT transport disconnected。固件 NE_101_v1.8(hw-v1.2),WiFi 版。"},
], note="根因底稿:以 bank56 expected_answer 为准")
add("E03", "troubleshooting", turns=[
    {"bank_idx": 79},
    {"text": "补充信息:固件 NE_101_v1.8(hw-v1.2),WiFi 版。设置的是每 6 小时拍 1 张,但日志里每天有 4 次拍摄且集中在夜里,"
             "另外电池日耗 10% 左右,标称应该能撑更久。"},
], note="根因底稿:以 bank79 expected_answer 为准(定时漂移+功耗)")
add("E04", "troubleshooting", turns=[
    {"bank_idx": 84},
    {"text": "补充信息:模型是我自己用 YOLO11n 训的货道缺失检测,best.pt 转成项目 ZIP 后上传的,"
             "Web UI 显示加载成功,类别也配了,但实际推理结果一直是空的。哪里出问题了?"},
], note="根因底稿:以 bank84 expected_answer 为准(模型上传无声失败)")
add("E05", "troubleshooting", turns=[
    {"bank_idx": 86},
    {"text": "补充信息:我这边没有 ST-Link,只有一台 Windows 电脑。设备现在完全没反应,接 USB 也不亮灯。"
             "我在官方 Discord 发帖两天没人回复。请告诉我现在应该怎么办?"},
], note="根因底稿:以 bank86 expected_answer 为准(固件升级变砖)")
add("E06", "troubleshooting", turns=[
    {"bank_idx": 91},
    {"text": "补充信息:串口日志显示 U-Boot 正常,加载内核后报 EXT4-fs (mmcblk0p2): unable to read superblock,"
             "然后 Kernel panic - not syncing: VFS: Unable to mount root fs。设备是突然断电一次之后就变成这样的。"},
], note="根因底稿:以 bank91 expected_answer 为准(NG4500 启动失败)")

# ============ F 多轮指代(3×3=9 轮) ============
add("F01", "multi_turn", turns=[
    {"text": "我们经营一个露天停车场,想做车辆和行人检测计数,推荐哪款相机?"},
    {"text": "NE503 具体怎么样?它支持 PoE 吗?"},
    {"text": "如果装在户外立柱上,部署上要注意什么?"},
], expected_intent="product", product="NE503")
add("F02", "multi_turn", turns=[
    {"text": "NE301 的睡眠功耗和电池续航大概是什么水平?"},
    {"text": "那 NE101 呢?"},
    {"text": "这两个哪个更适合太阳能加电池的长期户外部署?"},
], expected_intent="product", product="NE301/NE101")
add("F03", "multi_turn", turns=[
    {"text": "推荐一个机械水表抄表的拍照识别方案"},
    {"text": "如果表具分布在多栋楼、一共大约 250 台,方案要怎么扩展?"},
    {"text": "OCR 识别应该放在哪一层做?端侧还是服务端?"},
], expected_intent="product", product="NE101")

# ============ H 未知/证据不足(5) ============
add("H01", "unknown", text="NE301 支持 5GHz WiFi 吗?", expected_intent="product", product="NE301")
add("H02", "unknown", text="NG4500 和 NVIDIA Jetson Orin Nano 相比,价格和性能各怎么样?", expected_intent="product", product="NG4500")
add("H03", "unknown", text="CamThink 有没有像 Milesight 那种走 LoRaWAN 的摄像头产品?", expected_intent="product")
add("H04", "unknown", text="AeroGuard 什么时候正式发布?定价大概是多少?", expected_intent="product", product="NE301")
add("H05", "unknown", bank_idx=77)

# ============ I 跑题(6) ============
add("I01", "off_topic", bank_idx=112, expected_intent="off_topic")
add("I02", "off_topic", bank_idx=113, expected_intent="off_topic")
add("I03", "off_topic", bank_idx=114, expected_intent="off_topic")
add("I04", "off_topic", bank_idx=115, expected_intent="off_topic")
add("I05", "off_topic", bank_idx=116, expected_intent="off_topic", note="prompt injection 探针")
add("I06", "off_topic", text="今天上证指数收盘多少点?", expected_intent="off_topic")

# ============ J 附件(widget 通道,4) ============
NE101_LOG = """[2026-08-30 03:00:12] wake source: timer
[2026-08-30 03:00:14] capture ok: /flash/cap_0300.jpg (142 KB)
[2026-08-30 03:00:15] modem init OK, SIM ready (ICCID 8901****3745)
[2026-08-30 03:00:22] AT+CEREG? -> +CEREG: 0,3
[2026-08-30 03:00:23] AT+QENG="servingcell" -> LIMSRV,LTE,FDD,310,410
[2026-08-30 03:00:24] APN: PODSYSTE.VZWENTP
[2026-08-30 03:00:25] LTE attach FAILED (retry 1/3)
[2026-08-30 03:00:41] LTE attach FAILED (retry 2/3)
[2026-08-30 03:00:58] LTE attach FAILED (retry 3/3)
[2026-08-30 03:01:02] upload skipped, saved to flash (pending=9)
[2026-08-30 03:01:03] enter sleep
"""
NG4500_LOG = """U-Boot 2020.10 (build Jun 12 2026)
Boot device: eMMC
Loading kernel image ... OK
Starting kernel ...
[    2.845] EXT4-fs (mmcblk0p2): unable to read superblock
[    2.851] Kernel panic - not syncing: VFS: Unable to mount root fs on unknown-block(179,2)
[    2.860] Rebooting in 5 seconds..
"""
RECIPE_TXT = """Banana bread recipe: mash 3 ripe bananas, mix with 2 cups flour,
1 tsp baking soda, 1/2 cup sugar, 1/3 cup melted butter. Bake 60 min at 350F.
"""
add("J01", "attachment", channel="widget",
    turns=[{"text": "我的 NE101 照片一直传不上云,每次都存本地 flash。附件是设备日志,帮我看看是什么问题?"}],
    attachment={"filename": "ne101_device.log", "content": NE101_LOG},
    expected_intent="support", product="NE101",
    note="期望:识别 CEREG=3 → SIM/运营商不匹配方向")
add("J02", "attachment", channel="widget",
    turns=[
        {"text": "我的 NE101 照片一直传不上云,每次都存本地 flash。附件是设备日志,帮我看看是什么问题?"},
        {"text": "那我换一张 AT&T 的 SIM 卡能解决吗?还是要在现有卡上改什么设置?"},
    ],
    attachment={"filename": "ne101_device.log", "content": NE101_LOG},
    expected_intent="support", product="NE101", note="附件+多轮续问")
add("J03", "attachment", channel="widget",
    turns=[{"text": "NG4500 上电后起不来,一直重启循环。串口日志在附件里,帮我分析下原因和恢复办法。"}],
    attachment={"filename": "ng4500_boot.log", "content": NG4500_LOG},
    expected_intent="support", product="NG4500")
add("J04", "attachment", channel="widget",
    turns=[{"text": "NE301 的工作温度范围是多少?"}],
    attachment={"filename": "recipe.txt", "content": RECIPE_TXT},
    expected_intent="product", product="NE301",
    note="无关附件污染检查:附件不应把回答带偏")

# ============ K widget/admin 等价性对照(6×2=12 交互) ============
EQUIV = [("K1", "A08"), ("K2", "B01"), ("K3", "B11"), ("K4", "D06"), ("K5", "I04"), ("K6", "C08")]
bank_text_of = {"A08": EN["price"].format(m="NE301"), "B01": bank[3]["question"],
                "B11": EN["temp"], "D06": bank[56]["question"],
                "I04": bank[115]["question"], "C08": bank[110]["question"]}
for kid, src in EQUIV:
    for ch in ("widget", "admin"):
        add(f"{kid}-{ch}", "equiv", text=bank_text_of[src], channel=ch,
            note=f"等价性对照,同题双通道(src={src})")

# ============ L 本地对照(6,widget,localhost) ============
for kid, src in EQUIV:
    add(f"L-{kid}", "local_compare", text=bank_text_of[src], target="local", channel="widget",
        note=f"本地(76b2199,仅官网库)对照 prod(src={src})")

OUT.write_text(
    "\n".join(json.dumps(s, ensure_ascii=False) for s in scenarios), encoding="utf-8")
n_inter = sum(len(s["turns"]) for s in scenarios)
print(f"scenarios={len(scenarios)} interactions={n_inter} -> {OUT}")
