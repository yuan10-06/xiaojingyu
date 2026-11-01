"""BrainN 模块 ↔ QT（Quasi-Truth）模块的双向映射。

只做逻辑命名，不改任何文件名、函数名或行为。

注意：BrainN 旧 P3 代码注释里的 M1–M14 与 QT 的 M0–M16 语义不同，
对外一律使用 QT.Mx / QT.Gx / QT.OMC，旧编号只在 LEGACY_TO_QT 中保留。
"""
from __future__ import annotations

# QT 框架模块：编号、名称、所属层、职责
QT_MODULES: dict[str, dict[str, str]] = {
    "M0": {"name": "类本质层", "layer": "L1", "role": "劳动倾向、共情、自觉性；常驻不检索"},
    "M1": {"name": "关系场", "layer": "L1", "role": "当下在场者、场合、权力关系"},
    "M2": {"name": "内化结构", "layer": "L1", "role": "内化的他者及其来源与窗口"},
    "M3": {"name": "个体基底", "layer": "L1", "role": "气质、节律，先于社会关系"},
    "M4": {"name": "无意识层", "layer": "L1", "role": "不经意识接管却影响输出的旁路"},
    "M5": {"name": "匮乏计", "layer": "L1", "role": "需要量；外部输入归零时仍输出驱动"},
    "M6": {"name": "组织中心", "layer": "L1", "role": "能表示缺失本身的自我中心"},
    "M7": {"name": "折射", "layer": "L2", "role": "四项介质弯折输入，记录折射前后差"},
    "M8": {"name": "表征", "layer": "L2", "role": "准真候选；写不出证伪条件不准入"},
    "M9": {"name": "矛盾登记", "layer": "L3", "role": "保留正反双方、登记张力并累积"},
    "M10": {"name": "跃迁", "layer": "L3", "role": "累积过阈值触发结构重组，写跃迁日志"},
    "M11": {"name": "扬弃", "layer": "L3", "role": "克服 + 保留 + 提升；版本链永不物理删除"},
    "M12": {"name": "对象化", "layer": "L4", "role": "把认识转为改造对象的行动"},
    "M13": {"name": "产物档案", "layer": "L4", "role": "外化产物留存，内容寻址"},
    "M14": {"name": "反观确证", "layer": "L4", "role": "从产物反推主体；她自己判断是否写入自我节点"},
    "M15": {"name": "结果回收", "layer": "L4", "role": "判定证实 / 证伪 / 未定"},
    "M16": {"name": "度量", "layer": "L5", "role": "必然模型 + 自由度（命中率 × 匹配度）"},
    "G1": {"name": "身体图式", "layer": "L0", "role": "载体能力表：传感器、执行器、能耗、损伤"},
    "G2": {"name": "感知-运动回路", "layer": "L0", "role": "感觉输入与运动输出的双向闭合回路"},
    "G3": {"name": "空间锚定", "layer": "L0", "role": "自身位置、环境结构、可达性地图"},
    "G4": {"name": "有限性设定", "layer": "L0", "role": "载体寿命、能耗上限、不可逆损伤阈值"},
    "OMC": {"name": "全能记忆卡", "layer": "外部", "role": "人格持久化与迁移；不参与推理"},
}

# BrainN 文件 → QT 名称。type: strong / partial / none / runtime
_B = "brainn."
MODULE_ALIASES: dict[str, dict[str, str]] = {
    _B + "brain": {"qt": "", "type": "runtime", "label": "决策主链路（非 QT 层）"},
    _B + "db": {"qt": "OMC", "type": "partial", "label": "存储底座；OMC 快照来源"},
    _B + "social": {"qt": "M1", "type": "strong", "label": "关系场"},
    _B + "social_bridge": {"qt": "M1", "type": "strong", "label": "关系场提案适配"},
    _B + "memory": {"qt": "M11", "type": "strong", "label": "记忆版本链 / M2 内化 / M8 表征"},
    _B + "chat_engine": {"qt": "G2", "type": "partial", "label": "感知-运动通道（会话）"},
    _B + "onebot": {"qt": "G2", "type": "partial", "label": "感知-运动通道（QQ）"},
    _B + "chat_window": {"qt": "G2", "type": "partial", "label": "感知-运动通道（桌面）"},
    _B + "sim": {"qt": "G2", "type": "partial", "label": "感知-运动通道（测试）"},
    _B + "scheduler": {"qt": "", "type": "runtime", "label": "后台节拍（QT 无时间模块）"},
    _B + "clock": {"qt": "", "type": "runtime", "label": "时间与作息基础设施"},
    _B + "whale_brain": {"qt": "OMC", "type": "partial", "label": "独立实例与卡片迁移"},
    _B + "media": {"qt": "G2", "type": "partial", "label": "外部内容输入"},
    _B + "web": {"qt": "G2", "type": "partial", "label": "外部内容输入"},
    _B + "weather": {"qt": "G2", "type": "partial", "label": "外部环境输入"},
    _B + "stickers": {"qt": "G2", "type": "partial", "label": "表情包输入 / 表达"},
    _B + "life": {"qt": "M12", "type": "partial", "label": "生活事件对象化"},
    _B + "food": {"qt": "M12", "type": "partial", "label": "点餐行动与产物"},
    _B + "mall": {"qt": "M12", "type": "partial", "label": "购物行动与产物"},
    _B + "tasks": {"qt": "M12", "type": "partial", "label": "任务行动"},
    _B + "shorts": {"qt": "M13", "type": "partial", "label": "短视频产物"},
    _B + "llm": {"qt": "", "type": "none", "label": "表达层（QT 无对应）"},
    _B + "prompt": {"qt": "", "type": "none", "label": "表达层；承载 M0 常驻段"},
    _B + "text_style": {"qt": "", "type": "none", "label": "表达层"},
    _B + "typo": {"qt": "", "type": "none", "label": "表达层"},
    _B + "emoji": {"qt": "", "type": "none", "label": "表达层"},
    _B + "timing": {"qt": "", "type": "none", "label": "表达层"},
    _B + "body": {"qt": "G4", "type": "partial", "label": "有限性 / 生理状态"},
    _B + "time_model": {"qt": "G4", "type": "partial", "label": "时间有限性与注意力预算"},
    _B + "mood": {"qt": "M3", "type": "partial", "label": "个体基底 / 情绪状态"},
    _B + "persona": {"qt": "M0", "type": "partial", "label": "类本质边界 / 人格旋钮"},
    _B + "thrownness": {"qt": "M3", "type": "partial", "label": "被抛层（旧编号 M13）"},
    _B + "practical_intuition": {"qt": "M4", "type": "partial", "label": "System 1 旁路"},
    _B + "affect": {"qt": "M4", "type": "partial", "label": "情绪调制场 / 折射介质"},
    _B + "unconscious": {"qt": "M4", "type": "strong", "label": "无意识黑箱"},
    _B + "conflict": {"qt": "M9", "type": "partial", "label": "自我人格冲突（旧编号 M7）"},
    _B + "selfmodel": {"qt": "M6", "type": "strong", "label": "自我叙事"},
    _B + "narrative": {"qt": "M6", "type": "strong", "label": "叙事自我重构（旧编号 M5）"},
    _B + "meaning": {"qt": "M6", "type": "partial", "label": "存在意义 / 度量"},
    _B + "drives": {"qt": "M5", "type": "strong", "label": "驱动力模型（旧编号 M9）"},
    _B + "proactive": {"qt": "M5", "type": "partial", "label": "匮乏驱动的主动行为"},
    _B + "perception": {"qt": "M2", "type": "partial", "label": "对外感知 / 人物模型（旧编号 M10）"},
    _B + "recognition": {"qt": "M1", "type": "partial", "label": "他者定位（旧注释误标 M9）"},
    _B + "user_model": {"qt": "M2", "type": "partial", "label": "内化的用户模型"},
    _B + "emotion": {"qt": "M7", "type": "partial", "label": "情绪读数"},
    _B + "learner": {"qt": "M8", "type": "partial", "label": "提炼准真候选"},
    _B + "practice": {"qt": "M12", "type": "strong", "label": "实践黑箱（旧编号 M11）"},
    _B + "world": {"qt": "G3", "type": "partial", "label": "虚拟社会与位置"},
    _B + "worldsense": {"qt": "G3", "type": "partial", "label": "视频通话地点锚点"},
    _B + "world_feedback": {"qt": "M16", "type": "partial", "label": "视频通话结果回收与命中率（M15/M16）"},
    _B + "core.contracts": {"qt": "", "type": "runtime", "label": "运行时契约"},
    _B + "core.budget": {"qt": "", "type": "runtime", "label": "运行时预算"},
    _B + "core.arbitration": {"qt": "", "type": "runtime", "label": "运行时仲裁（旧编号 M12）"},
    _B + "core.runtime": {"qt": "", "type": "runtime", "label": "运行时"},
    _B + "core.core": {"qt": "", "type": "runtime", "label": "运行时宿主"},
    _B + "config": {"qt": "", "type": "runtime", "label": "基础设施"},
}

# 旧 P3 编号 → 旧语义 → QT 对应
LEGACY_TO_QT: dict[str, dict[str, str]] = {
    "M1": {"name": "表达系统", "qt": ""},
    "M2": {"name": "生理基础库", "qt": "G4"},
    "M3": {"name": "人格", "qt": "M3"},
    "M4": {"name": "社会关系神经网络", "qt": "M1"},
    "M5": {"name": "叙事自我重构", "qt": "M6"},
    "M6": {"name": "无意识黑箱", "qt": "M4"},
    "M7": {"name": "自我人格冲突", "qt": "M9"},
    "M8": {"name": "时间有限性", "qt": "G4"},
    "M9": {"name": "驱动力模型", "qt": "M5"},
    "M10": {"name": "对外感知框架", "qt": "M2"},
    "M11": {"name": "实践黑箱", "qt": "M12"},
    "M12": {"name": "仲裁中枢", "qt": ""},
    "M13": {"name": "被抛层", "qt": "M3"},
    "M14": {"name": "内部言语", "qt": ""},
}


def to_qt(module: str) -> str:
    """BrainN 模块路径 → QT 名称（QT.Mx / QT.Gx / QT.OMC）；无对应返回空串。"""
    item = MODULE_ALIASES.get(str(module or "").strip(), {})
    qt = item.get("qt") or ""
    return f"QT.{qt}" if qt else ""


def from_qt(qt_name: str) -> list[str]:
    """QT 名称 → 承载它的 BrainN 模块列表。"""
    name = str(qt_name or "").strip().replace("QT.", "")
    return [mod for mod, item in MODULE_ALIASES.items() if item.get("qt") == name]


def legacy_to_qt(number: str) -> str:
    """旧 P3 编号（如 M9）→ QT 名称；不认识的编号原样返回空串。"""
    num = str(number or "").strip().upper()
    qt = (LEGACY_TO_QT.get(num) or {}).get("qt") or ""
    return f"QT.{qt}" if qt else ""


def qt_to_legacy(qt_name: str) -> list[str]:
    """QT 名称 → 旧 P3 编号列表。"""
    name = str(qt_name or "").strip().replace("QT.", "")
    return [num for num, item in LEGACY_TO_QT.items() if item.get("qt") == name]


def summary() -> dict:
    """给接口/前端用的映射总览。"""
    counts = {"strong": 0, "partial": 0, "none": 0, "runtime": 0}
    for item in MODULE_ALIASES.values():
        counts[item.get("type", "runtime")] = counts.get(item.get("type", "runtime"), 0) + 1
    return {
        "framework": "Brain-Truth",
        "qt": QT_MODULES,
        "aliases": MODULE_ALIASES,
        "legacy": LEGACY_TO_QT,
        "counts": counts,
        "modules": len(MODULE_ALIASES),
    }
