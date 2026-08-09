"""城镇名称与区域地名生成器 — 古代冒险者城镇风格。

命名逻辑：每个名称由 前缀 + 后缀 组合，词库参考古代地理命名规律、
武侠/奇幻世界观、以及《水经注》《徐霞客游记》等古典地名语料。
所有生成均为确定性（基于 seed + ordinal 的稳定随机数）。
"""

import re
from typing import Literal

from .models import TownDistrict

# ═══════════════════════════════════════════════════════
#  城镇名 — 前缀（120+）
#  来源：古代城池名、自然景观、神话意象、武侠冒险常见元素
# ═══════════════════════════════════════════════════════
_TOWN_PREFIX = (
    # -- 方位地理（16）--
    "龙首", "凤鸣", "虎踞", "鹤归", "鹰扬", "鹿苑", "雁落", "麟游",
    "紫霞", "青云", "碧落", "苍梧", "赤松", "玄岳", "白浪", "翠微",
    # -- 地形地貌（24）--
    "沉星", "望月", "凌霄", "落枫", "听涛", "枕石", "渡云", "栖霞",
    "临渊", "揽胜", "倚天", "破晓", "燃灯", "饮马", "射日", "追风",
    "摘星", "踏雪", "覆雨", "映日", "衔月", "含烟", "凝霜", "漱玉",
    # -- 城池意象（20）--
    "镇远", "定安", "宁朔", "靖边", "抚远", "平夷", "怀柔", "绥化",
    "承天", "宣德", "崇文", "尚武", "兴隆", "永昌", "长乐", "未央",
    "建业", "朔方", "云中", "渔阳",
    # -- 人文典故（24）—
    "铸剑", "藏锋", "论道", "观棋", "听琴", "品茗", "焚香", "抚琴",
    "刻石", "铭碑", "筑台", "立柱", "开坛", "设局", "布防", "铸铁",
    "烧瓷", "炼药", "织锦", "雕木", "凿玉", "采珠", "淘金", "锁烟",
    # -- 自然奇观（20）—
    "寒泉", "暖谷", "温泉", "冷涧", "幽潭", "深渊", "险壑", "危崖",
    "断崖", "绝壁", "孤峰", "群峦", "叠嶂", "层岭", "回峰", "曲径",
    "古道", "天梯", "云阶", "仙踪",
    # -- 神话传说（20）—
    "伏龙", "镇蛟", "锁妖", "禁魔", "通灵", "显圣", "降神", "招仙",
    "祈年", "祭天", "启明", "长庚", "北辰", "南斗", "东君", "西母",
    "扶桑", "若木", "建木", "空桑",
    # -- 历史名城（16）--
    "阳关", "玉门", "金陵", "长安", "洛阳", "邯郸", "临淄", "宛城",
    "扶风", "天水", "武威", "张掖", "酒泉", "敦煌", "会稽", "琅琊",
    # -- 贤者隐居（12）--
    "卧龙", "栖凤", "归雁", "散花", "种玉", "耕云",
    "钓月", "牧星", "拾翠", "寻梅", "访桂", "探幽",
)

# ═══════════════════════════════════════════════════════
#  城镇名 — 后缀（50+）
# ═══════════════════════════════════════════════════════
_TOWN_SUFFIX = (
    # -- 大城巨邑（10）--
    "城", "都", "府", "州", "郡", "邑", "邦", "国", "关", "镇",
    # -- 军寨要塞（8）--
    "堡", "塞", "隘", "垒", "营", "屯", "卫", "寨",
    # -- 山水形胜（12）--
    "谷", "原", "野", "川", "泽", "皋", "隰",
    "岭", "峰", "岗", "麓", "崖",
    # -- 水陆码头（8）--
    "港", "津", "渡", "口", "埠", "浦", "湾", "渚",
    # -- 老镇小城（8）--
    "甸", "丘", "驿", "亭", "集", "场", "铺", "墟",
    # -- 仙境灵地（6）--
    "坪", "台", "洞", "源", "坛", "阁",
)

# ═══════════════════════════════════════════════════════
#  区域名 — 前缀（共 200+，按类型分组）
#  每个词最多 3 个汉字，便于组合
# ═══════════════════════════════════════════════════════

# 方位修饰（24）— 用于主轴区域前缀
_DIRECTIONAL = (
    "东", "南", "西", "北", "中",
    "东北", "东南", "西南", "西北",
    "左", "右", "前", "后", "上", "下", "内", "外",
    "正", "偏", "横", "直", "曲", "环", "绕",
)

# 自然草木（48）
_PLANTS = (
    "柳", "梅", "竹", "松", "柏", "槐", "桃", "杏", "枫", "莲", "菊", "兰",
    "桂", "荷", "榆", "桑", "杨", "桐", "梓", "椿", "柞", "栎", "棣", "棠",
    "芷", "蕙", "荻", "苇", "蒲", "藤", "葛", "藓",
    "牡丹", "芍药", "海棠", "芙蓉", "蔷薇", "月季", "丁香", "茉莉",
    "樱桃", "枇杷", "石榴", "柑橘", "葡萄", "荔枝", "龙眼", "橄榄",
)

# 山川地物（40）
_GEOGRAPHY = (
    "石", "岩", "山", "岭", "坡", "岗", "丘", "崖",
    "水", "泉", "溪", "涧", "潭", "池", "湖", "河",
    "井", "桥", "渡", "津", "港", "埠", "滩", "洲",
    "塔", "钟", "鼓", "碑", "坊", "楼", "阁", "台",
    "亭", "榭", "廊", "轩", "斋", "庐", "舍", "院",
)

# 人文地标（36）
_LANDMARKS = (
    "庙", "祠", "寺", "观", "庵", "堂", "殿", "坛",
    "市", "集", "墟", "场", "铺", "店", "栈", "驿",
    "衙", "署", "仓", "库", "窑", "灶", "磨", "碾",
    "铁铺", "木坊", "染坊", "酒坊", "酱园", "药铺",
    "书院", "武馆", "镖局", "钱庄", "当铺", "客栈",
)

# 色彩质感（30）
_COLORS = (
    "青", "碧", "翠", "苍", "蓝", "黛", "绀", "靛",
    "红", "赤", "朱", "丹", "绛", "绯", "彤", "赭",
    "金", "银", "铜", "铁", "锡", "铅", "玉", "石",
    "素", "玄", "乌", "墨", "皓", "粉",
)

# 气质描写（32）
_CHARACTER = (
    "清", "幽", "静", "深", "远", "高", "明", "暗",
    "香", "雅", "古", "新", "旧", "老", "大", "小",
    "长", "短", "宽", "窄", "阔", "狭", "曲", "直",
    "安", "宁", "平", "泰", "和", "康", "乐", "永",
)

# 天象时辰（24）
_CELESTIAL = (
    "日", "月", "星", "辰", "云", "霞", "虹", "霓",
    "风", "雨", "雷", "电", "霜", "雪", "露", "雾",
    "晨", "晓", "暮", "夕", "夜", "曙", "昏", "旦",
)

# 神话动物（20）
_MYTHICAL = (
    "龙", "凤", "麟", "龟", "鹤", "鸾", "鹏", "鲲",
    "虎", "狮", "豹", "熊", "犀", "象", "蟒", "蛟",
    "鸾", "鹤", "鹿", "猿",
)

# ═══════════════════════════════════════════════════════
#  区域名 — 后缀（100+，按环位分层）
# ═══════════════════════════════════════════════════════

# 中心区后缀（ring 0-1）— 繁华城镇风貌（30）
_SUFFIX_CENTER = (
    "坊", "里", "街", "市", "门", "楼", "阁", "台",
    "廊", "庭", "院", "园", "苑", "宅", "第", "府",
    "巷口", "街头", "市口", "牌楼", "鼓楼", "钟楼",
    "正街", "前街", "后街", "横街", "直街", "十字",
    "学宫", "庙前",
)

# 中环后缀（ring 2-3）— 民居手工业风貌（35）
_SUFFIX_MIDDLE = (
    "巷", "弄", "桥", "池", "园", "院", "庄", "舍",
    "铺", "栈", "坊", "窑", "灶", "井", "塘", "沟",
    "溪畔", "桥头", "井边", "巷尾", "弄堂", "园子",
    "作坊", "染坊", "磨坊", "酒坊", "油坊", "酱园",
    "圩子", "场院", "河沿", "塘边", "池畔",
    "碾道", "仓后",
)

# 外环后缀（ring 4+）— 乡野农庄风貌（35）
_SUFFIX_OUTER = (
    "庄", "村", "屯", "坡", "岗", "河", "沟", "岭",
    "甸", "川", "原", "野", "谷", "湾", "滩", "洲",
    "庄子", "村子", "屯子", "甸子", "岗子", "坡地",
    "河湾", "山谷", "林边", "田头", "垄上", "墩台",
    "烽台", "驿亭", "茶棚", "路亭",
    "渡口", "津头", "河口",
)


def _pick(candidates: tuple[str, ...], seed: int, ns: str, ordinal: int) -> str:
    """确定性从词库中选取一个词。ns 需与 stable_float 的 namespace 对齐。"""
    # 这里使用简单的 hash 做确定性选择，避免引入稳定的全局随机函数
    from hashlib import sha256

    payload = f"radial-v1:{seed}:{ns}:{ordinal}".encode("utf-8")
    number = int.from_bytes(sha256(payload).digest()[:8], "big")
    return candidates[number % len(candidates)]


TownScale = Literal["village", "town", "city"]
_SCALE_SUFFIX: dict[TownScale, str] = {"village": "村", "town": "镇", "city": "城"}


def normalize_town_name(name: str, scale: TownScale = "town") -> str:
    """Keep a supplied or generated place name consistent with its settlement scale."""
    stem = name.strip()
    # Keep existing latin aliases usable (for example imported scenario IDs).
    # Chinese place names, which are what the generator produces, receive the
    # scale suffix below.
    if not any("\u4e00" <= character <= "\u9fff" for character in stem):
        return stem
    # Names supplied by older drafts may already carry a different place suffix.
    # Remove only the final suffix, preserving the meaningful geographic stem.
    known_suffixes = sorted(set(_TOWN_SUFFIX) | set(_SCALE_SUFFIX.values()), key=len, reverse=True)
    for suffix in known_suffixes:
        if stem.endswith(suffix) and len(stem) > len(suffix):
            stem = stem[: -len(suffix)]
            break
    return f"{stem}{_SCALE_SUFFIX[scale]}"


def generate_town_name(seed: int, scale: TownScale = "town") -> str:
    """Generate a deterministic name with a scale-matching suffix."""
    prefix = _pick(_TOWN_PREFIX, seed, "town-name-prefix", 0)
    return normalize_town_name(prefix, scale)


def generate_district_names(seed: int, districts: list[TownDistrict]) -> dict[str, str]:
    """为每个区域生成一个古代冒险者风格的中文地名。

    命名策略：
    - 主轴区域（ring 0 的 4/8 个 direction、以及每个环的 direction sector）→ 方位 + 地标 + 后缀
    - 普通区域 → 草木/色彩/气质 + 后缀
    - 后缀按环位选择（中心区/中环/外环）
    """

    all_prefix = _PLANTS + _GEOGRAPHY + _LANDMARKS + _COLORS + _CHARACTER + _CELESTIAL + _MYTHICAL
    direction_names = ("北", "东北", "东", "东南", "南", "西南", "西", "西北")

    # 扇区数：从 ring-0 推算
    sector_count = max(
        (int(m.group(1)) for d in districts if (m := re.match(r"^district-r00-s(\d{2})$", d.id))),
        default=23,
    ) + 1

    names: dict[str, str] = {}
    for district in districts:
        match = re.match(r"^district-r(\d{2})-s(\d{2})$", district.id)
        if not match:
            ward_match = re.match(r"^district-w(\d+)$", district.id)
            ordinal = int(ward_match.group(1)) if ward_match else len(names)
            prefix = _pick(all_prefix, seed, "dn-watabou-p", ordinal)
            suffix = _pick(_SUFFIX_MIDDLE if ordinal % 3 else _SUFFIX_CENTER, seed, "dn-watabou-s", ordinal)
            names[district.id] = f"{prefix}{suffix}"
            continue
        ring = int(match.group(1))
        sector = int(match.group(2))
        ordinal = ring * 100 + sector

        if ring <= 1:
            suffix_pool = _SUFFIX_CENTER
        elif ring <= 3:
            suffix_pool = _SUFFIX_MIDDLE
        else:
            suffix_pool = _SUFFIX_OUTER

        prefix = _pick(all_prefix, seed, "dn-p", ordinal)
        suffix = _pick(suffix_pool, seed, "dn-s", ordinal)
        direction = direction_names[round(sector / sector_count * 8) % 8]

        # 主轴区域：添加方位前缀
        is_main = ring == 0 or sector % max(1, sector_count // 4) == 0
        if is_main:
            # 用地理类前缀让名称更有力量感
            geo = _pick(_GEOGRAPHY, seed, "dn-geo", ordinal)
            names[district.id] = f"{direction}{geo}{suffix}"
        else:
            names[district.id] = f"{prefix}{suffix}"
    return names
