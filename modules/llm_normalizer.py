"""AI 语义清洗模块：通过 LLM 从乱码 ROM 文件名提取标准中/英文游戏名"""

import json
import re
import time
from pathlib import Path
from modules.llm_client import LLMClient

SYSTEM_PROMPT = """你是复古游戏专家。从 ROM 文件名提取游戏信息。

规则：
1. 去除汉化组、版本号、语言/区域标签
2. 识别游戏真实身份，不要猜错
3. 中文名用中国大陆通用译名
4. 英文名用官方英文名（用于搜索匹配）

返回 JSON：
{"standard_zh": "中文名", "standard_en": "English Name", "desc_zh": "一句话中文简介"}

关键示例：
"[Advance汉化组] 最终幻想VI v1.2.gba" → {"standard_zh": "最终幻想VI", "standard_en": "Final Fantasy VI", "desc_zh": "史克威尔经典角色扮演游戏第六代"}
"Super_Mario_World_(USA).sfc" → {"standard_zh": "超级马力欧世界", "standard_en": "Super Mario World", "desc_zh": "任天堂经典横版动作游戏"}
"Street_Fighter_II_(World).zip" → {"standard_zh": "街头霸王II", "standard_en": "Street Fighter II", "desc_zh": "卡普空经典格斗游戏"}
"塞尔达传说缩小帽 [中文].gba" → {"standard_zh": "塞尔达传说 缩小帽", "standard_en": "The Legend of Zelda: The Minish Cap", "desc_zh": "任天堂经典动作冒险游戏"}
"Pokemon_Emerald_(USA).gba" → {"standard_zh": "宝可梦 绿宝石", "standard_en": "Pokemon Emerald", "desc_zh": "Game Freak经典角色扮演游戏"}
"Metal_Slug_X.zip" → {"standard_zh": "合金弹头X", "standard_en": "Metal Slug X", "desc_zh": "SNK经典横版射击游戏"}"""

TRANSLATE_PROMPT = """把以下英文游戏简介翻译成流畅的中文，保留游戏专有名词，控制在200字以内：

英文：
{en_desc}

直接返回中文译文，不要其他内容。"""

RETRY_MAX = 3
RETRY_DELAY = 1.0

# 预编译 JSON 提取正则，兼容 LLM 偶尔输出的 markdown 代码块
JSON_PATTERN = re.compile(r"\{[^{}]*\"standard_zh\"[^{}]*\"standard_en\"[^{}]*\}", re.DOTALL)


def normalize_rom_name(client: LLMClient, model: str, filename: str,
                       temperature: float = 0.1, max_tokens: int = 300) -> dict[str, str]:
    """调用 LLM 清洗单个文件名，返回 {standard_zh, standard_en, desc_zh}。"""
    stem = Path(filename).stem

    for attempt in range(1, RETRY_MAX + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": stem},
                ],
            )
            raw = response.choices[0].message.content.strip()
            return _parse_json_response(raw, filename)

        except json.JSONDecodeError as e:
            if attempt < RETRY_MAX:
                time.sleep(RETRY_DELAY * attempt)
            else:
                raise RuntimeError(
                    f"LLM JSON 解析失败 ({RETRY_MAX}次): {filename}"
                ) from e
        except Exception as e:
            if attempt < RETRY_MAX:
                time.sleep(RETRY_DELAY * attempt)
            else:
                raise RuntimeError(
                    f"LLM API 失败: {filename}\n{e}"
                ) from e

    return {"standard_zh": "", "standard_en": "", "desc_zh": ""}


def _parse_json_response(raw: str, filename: str) -> dict[str, str]:
    """从 LLM 原始回复中提取 JSON。兼容 markdown 代码块包裹。"""
    try:
        data = json.loads(raw)
        return {
            "standard_zh": data.get("standard_zh", "").strip(),
            "standard_en": data.get("standard_en", "").strip(),
            "desc_zh": data.get("desc_zh", "").strip(),
        }
    except json.JSONDecodeError:
        pass

    # 正则兜底
    m = JSON_PATTERN.search(raw)
    if m:
        try:
            data = json.loads(m.group(0))
            return {
                "standard_zh": data.get("standard_zh", "").strip(),
                "standard_en": data.get("standard_en", "").strip(),
                "desc_zh": data.get("desc_zh", "").strip(),
            }
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError(f"无法提取 JSON", raw, 0)


def translate_desc(client: LLMClient, model: str, en_desc: str) -> str:
    """将英文简介翻译为中文。"""
    if not en_desc or len(en_desc) < 20:
        return ""
    # 截断过长文本
    en_desc = en_desc[:800]
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.3,
            max_tokens=400,
            messages=[
                {"role": "user", "content": TRANSLATE_PROMPT.format(en_desc=en_desc)},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ""


def normalize_batch(client: LLMClient, model: str, filenames: list[str],
                    temperature: float = 0.1, max_tokens: int = 200) -> dict[str, dict[str, str]]:
    """批量清洗文件名。返回 {filename: {standard_zh, standard_en}}。"""
    results = {}
    for i, fname in enumerate(filenames, 1):
        print(f"  [{i}/{len(filenames)}] 清洗: {Path(fname).name[:60]}")
        try:
            results[fname] = normalize_rom_name(client, model, fname, temperature, max_tokens)
        except RuntimeError as e:
            print(f"  [警告] {e}")
            results[fname] = {"standard_zh": "", "standard_en": ""}
    return results
