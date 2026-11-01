"""12 个模块的注册表（P2 骨架，P3 逐个实现）。

模块之间不直接调用；只通过 BrainN Core 传递的上下文包交换信息。
"""
from __future__ import annotations

MODULE_LAYERS = {
    "memory": "地基",
    "body": "物质层",
    "time": "约束层",
    "perception": "输入层",
    "drives": "动力层",
    "social": "结构层",
    "practice": "生产层",
    "arbitration": "决策层",
    "conflict": "仲裁层",
    "unconscious": "元层",
    "narrative": "元层",
    "expression": "输出层",
}

MODULE_ROLES = {
    "memory": "所有层的读写介质",
    "body": "生理现象，影响其他模块",
    "time": "预算器：稀缺性调度，不竞标只衰减",
    "perception": "用户与其他社会关系成员的建模",
    "drives": "内驱力 + 外驱力，提案方",
    "social": "关系结构，提案方",
    "practice": "劳动与产出模拟，提案方 + 回写人格",
    "arbitration": "拍卖 + 拍板 + tick",
    "conflict": "扭曲胜出意图",
    "unconscious": "旁路，绕过中枢，权重最小",
    "narrative": "事后改写记忆与叙事",
    "expression": "语言、主动话题、表情、说说、节奏",
}
