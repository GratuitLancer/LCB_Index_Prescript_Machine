import re
from difflib import SequenceMatcher

ACTION_HINTS = [
    "写", "看", "站", "坐", "记录", "整理", "关闭", "打开",
    "倒", "呼吸", "行走", "擦拭", "观察", "收起", "摆正",
    "注视", "触碰", "移动", "移开", "放下", "抬起", "归位",
    "对齐", "数", "听", "记住", "拿起", "放到", "转动",
    "回收", "保留", "折叠", "藏起", "腾出", "替换", "修正",
    "指认", "命名", "封存", "悬置", "清点", "交叠", "留出"
]

NOUN_HINTS = [
    "桌面", "杯子", "门", "窗", "椅子", "纸张", "影子", "角落",
    "编号", "物件", "指尖", "声音", "标签", "残渣", "左侧", "墙面",
    "来客", "房间", "光", "门缝", "空杯", "纸", "物品"
]

def looks_like_reasoning(text: str) -> bool:
    bad_markers = [
        "Thinking Process",
        "Reasoning",
        "思考过程",
        "Analyze the Request",
        "Constraint",
        "<think>"
    ]
    t = text.lower()
    return any(marker.lower() in t for marker in bad_markers)

def normalize_output(text: str) -> str:
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    text = text.strip('"\'“”‘’` ')

    # 移除可能的提示前缀
    text = re.sub(r"^现在只输出一条新的指令：", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^指令：", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^输出：", "", text, flags=re.IGNORECASE)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if re.search(r"[\u4e00-\u9fff]", line):
            parts = re.split(r"[。；;!?！？]", line)
            candidate = parts[0].strip()
            if candidate:
                return candidate

    parts = re.split(r"[。；;!?！？\n]", text)
    for part in parts:
        part = part.strip()
        if part:
            return part

    return ""

def is_valid_output(text: str) -> bool:
    return bool(text and re.search(r"[\u4e00-\u9fff]", text) and not looks_like_reasoning(text))

def is_executable(text: str) -> bool:
    if len(text) < 6 or len(text) > 24:
        return False
    has_action = any(word in text for word in ACTION_HINTS)
    has_target = any(word in text for word in NOUN_HINTS)
    return has_action and has_target

def is_too_similar(text: str, history: list[str], threshold: float = 0.5) -> bool:
    for old in history[-10:]:
        if SequenceMatcher(None, text, old).ratio() >= threshold:
            return True
    return False
