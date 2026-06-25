# -*- coding: utf-8 -*-
"""
AI命理助手 - API 服务
适配 Railway 部署
"""
import os
import re
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from openai import OpenAI
from lunar_python import Solar

# ================== 请求模型 ==================
class BaziRequest(BaseModel):
    birth: str
    module: str = "all"

class FeedbackItem(BaseModel):
    section: str
    content: str
    feedback: str

class VerifyAdjustRequest(BaseModel):
    birth: str
    feedback_items: List[FeedbackItem]

# ================== 基础函数 ==================
def parse_gender(user_input):
    text = user_input.lower()
    if any(kw in text for kw in ['男', '男性', 'male', 'boy', '先生']):
        return 1
    if any(kw in text for kw in ['女', '女性', 'female', 'girl', '女士']):
        return 0
    return None

def has_hour_info(user_input):
    hour_patterns = [r'(\d{1,2})[点时]', r'早上', r'上午', r'中午', r'下午', r'晚上', r'凌晨',
                     r'子时', r'丑时', r'寅时', r'卯时', r'辰时', r'巳时',
                     r'午时', r'未时', r'申时', r'酉时', r'戌时', r'亥时']
    for pattern in hour_patterns:
        if re.search(pattern, user_input):
            return True
    return False

def parse_birth_and_gender(user_input):
    gender = parse_gender(user_input)
    has_hour = has_hour_info(user_input)

    year_match = re.search(r'(\d{4})', user_input)
    month_match = re.search(r'[年\-\/\.](\d{1,2})[月\-\/\.]', user_input)
    day_match = re.search(r'[月\-\/\.](\d{1,2})(?:[日\s]|$)', user_input)

    if not (year_match and month_match and day_match):
        date_match = re.search(r'(\d{4})[\.\-](\d{1,2})[\.\-](\d{1,2})', user_input)
        if date_match:
            year = int(date_match.group(1))
            month = int(date_match.group(2))
            day = int(date_match.group(3))
        else:
            return None
    else:
        year = int(year_match.group(1))
        month = int(month_match.group(1))
        day = int(day_match.group(1))

    hour = 12
    if has_hour:
        hour_match = re.search(r'(\d{1,2})[点时]', user_input)
        if hour_match:
            hour = int(hour_match.group(1))

    return (year, month, day, hour, gender, has_hour)

def get_bazi(year, month, day, hour, gender):
    solar = Solar.fromYmdHms(year, month, day, hour, 0, 0)
    lunar = solar.getLunar()
    ec = lunar.getEightChar()
    return {
        '年柱': ec.getYear(),
        '月柱': ec.getMonth(),
        '日柱': ec.getDay(),
        '时柱': ec.getTime(),
        '性别': '男' if gender == 1 else '女',
    }

def get_liunian_ganzhi(year):
    gan = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
    zhi = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
    return f"{gan[(year - 4) % 10]}{zhi[(year - 4) % 12]}"

def get_hour_warning(has_hour):
    if not has_hour:
        return "\n⚠️ 未提供时辰，准确率约30%-40%"
    return ""

def get_prompt(bazi_str, gender, has_hour, module, year, liunian):
    hour_warning = get_hour_warning(has_hour)
    
    # 风格控制（仅用于非 verify 模块）
    style_control = """
【全局风格要求】
1. 语言风格：朴实无华但该说明的地方就要说明，避免华丽辞藻；
2. 结构要求：先给出一句总体结论概括全貌，再分条详细说明。每条分析采用"结论 + 理由"的形式。
3. 格式要求：禁止使用 Markdown 标题符号（#、##、###、****、==、---）。
4. 内容末尾加上：AI生成内容仅供参考。
"""
    
    # verify 单独处理，保持原版不变
    if module == 'verify':
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}

请根据八字推断以下内容：

【环境方位】
家里或家外的XX方向有什么特征物品/环境，请给出分析理由。注意明确指出家里还是家外。
【六亲情况】
与哪位亲人的关系如何，或该亲人的性格特征，请给出分析理由。
【过去经历】
列举两个最有把握的年份发生过的事情，请给出分析理由。
【性格特征】
列出2-3个明显的性格特点，请给出分析理由。

输出风格采描述+理由方式(描述、理由分行显示)，输出内容避免使用Markdown 标题符号（#、##、###、****、==、---）
输出完毕后请说：以上是我的初步推断，请判断是否准确？如果哪一条不准确，请告诉我具体是哪一条、哪里不对。"""

    # 其他模块使用新风格
    templates = {
        'overview': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
请进行八字综合分析，按以下结构输出：
总体结论：（一句话概括你的八字特点和喜忌）

一、日主强弱
   - XX：XX，原因(此条阐述得令与否)
   - XX：XX，原因(此条阐述得地与否)
   - XX：XX，原因(此条阐述得势与否)
综合：日主XX，因为XX。
二、五行喜忌
   - 喜用五行：X、X、X对你有用，原因
   - 忌凶五行：X、X对你不利，原因
三、颜色建议
   - 喜用：X、X；根据喜用五行对应的颜色，X对应X、X对应X
   - 忌凶：X、X；根据忌凶五行对应的颜色，X对应X、X对应X
四、 数字建议
   - 喜用：X、X；根据喜用五行对应的数字，X对应X、X对应X
   - 忌凶：X、X；根据忌凶五行对应的数字，X对应X、X对应X
五、方位建议：
   - 喜用：X、X；根据喜用五行对应的方位，X对应X、X对应X
   - 忌凶：X、X；根据忌凶五行对应的方位，X对应X、X对应X

总结：XXX。

AI生成内容仅供参考"

注意：每一条都要先给结论，再简单解释理由。""",
        
        'liunian': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
请分析{year}年（{liunian}年）及未来两年的流年运势，按以下结构输出：
总体结论：（一句话概括三年每年的重点关注项）

一、{year}年整体运势
    - XX：XX，原因
    - XX：XX，原因
    - XX：XX，原因(以上例举2-3条需要重点关注的方面，健康、财运、官运、感情、事业、六亲)
综合：XX(综合说明该流年整体情况及需要重点关注的方面)

二、{year+1}年整体运势
    - XX：XX，原因
    - XX：XX，原因
    - XX：XX，原因(以上例举2-3条需要重点关注的方面，健康、财运、官运、感情、事业、六亲)
综合：XX(综合说明该流年整体情况及需要重点关注的方面)

三、{year+2}年整体运势
    - XX：XX，原因
    - XX：XX，原因
    - XX：XX，原因(以上例举2-3条需要重点关注的方面，健康、财运、官运、感情、事业、六亲)
综合：XX(综合说明该流年整体情况及需要重点关注的方面)

总结：XXX。

AI生成内容仅供参考""",
        
        'career': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
请分析事业运势，按以下结构输出：
总体结论：（一句话概括你的事业格局）

一、事业格局：（你属于什么类型，说明理由）
二、适合行业：（哪些行业适合你，说明理由）
三、工作建议：（具体建议，说明理由）
四、发展时机：（哪些年份有机会，说明理由）

注意：每一条都要先给结论，再简单解释理由。""",
        
        'wealth': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
请分析财运运势，按以下结构输出：
总体结论：（一句话概括你的财运水平）

一、财富等级：（你属于什么水平，说明理由）
二、求财方式：（适合用什么方式赚钱，说明理由）
三、财运时机：（哪些年份财运好，说明理由）
四、守财建议：（如何守住财富，说明理由）

注意：每一条都要先给结论，再简单解释理由。""",
        
        'marriage': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
请分析婚姻运势，按以下结构输出：
总体结论：（一句话概括你的婚姻运势）

一、婚姻早晚：（大概什么年龄结婚合适，说明理由）
二、配偶特征：（适合找什么类型的人，说明理由）
三、相处建议：（婚后如何相处，说明理由）

注意：每一条都要先给结论，再简单解释理由。"""
    }
    return templates.get(module, templates['overview'])

def get_adjust_prompt(bazi_str, gender, section, original_content, user_feedback):
    """生成单条调整的提示词"""
    hour_warning = get_hour_warning(True)
    return f"""八字：{bazi_str}，性别：{gender}{hour_warning}

请根据以下用户反馈，重新生成【{section}】的推断内容：

用户反馈的原推断：{original_content}
用户的实际情况：{user_feedback}

请根据用户的实际情况，重新生成一段准确的推断。要求：
1. 只输出该条推断的内容，不要输出其他部分
2. 根据用户的反馈调整分析方向，使推断更贴近用户描述的实际
3. 保持专业但易懂的语气
4. 格式保持与原来类似，包含具体推断和分析理由

请直接输出重新生成后的【{section}】内容："""

# ================== API 服务 ==================
app = FastAPI(title="AI命理助手API", version="1.0.0")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.bajiemingli.top", "https://bajiemingli.top"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)

# ===== 从环境变量读取 API Key（安全！） =====
API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not API_KEY:
    print("⚠️ 警告: DEEPSEEK_API_KEY 环境变量未设置")

client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")

def call_ai(prompt):
    """调用 DeepSeek API"""
    if not API_KEY:
        return "❌ API Key 未配置，请在 Railway 环境变量中设置 DEEPSEEK_API_KEY"
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        stream=False
    )
    return response.choices[0].message.content

@app.get("/")
def root():
    return {"message": "AI命理助手API运行中", "version": "1.0.0"}

@app.options("/analyze")
def options_analyze():
    return {"message": "OK"}

@app.options("/verify")
def options_verify():
    return {"message": "OK"}

@app.options("/verify_adjust")
def options_verify_adjust():
    return {"message": "OK"}

@app.post("/analyze")
def analyze(request: BaziRequest):
    try:
        parsed = parse_birth_and_gender(request.birth)
        if not parsed:
            return {"success": False, "error": "无法解析生辰，格式如：2001.10.30 18时 男"}
        
        year, month, day, hour, gender, has_hour = parsed
        bazi = get_bazi(year, month, day, hour, gender)
        bazi_str = f"{bazi['年柱']} {bazi['月柱']} {bazi['日柱']} {bazi['时柱']}"
        current_year = datetime.now().year
        liunian = get_liunian_ganzhi(current_year)
        
        prompt = get_prompt(bazi_str, bazi['性别'], has_hour, request.module, current_year, liunian)
        content = call_ai(prompt)
        
        return {"success": True, "data": {"bazi": bazi_str, "analysis": content}}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/verify")
def verify(request: BaziRequest):
    try:
        parsed = parse_birth_and_gender(request.birth)
        if not parsed:
            return {"success": False, "error": "无法解析生辰"}
        
        year, month, day, hour, gender, has_hour = parsed
        bazi = get_bazi(year, month, day, hour, gender)
        bazi_str = f"{bazi['年柱']} {bazi['月柱']} {bazi['日柱']} {bazi['时柱']}"
        
        prompt = get_prompt(bazi_str, bazi['性别'], has_hour, 'verify', 0, '')
        content = call_ai(prompt)
        
        return {"success": True, "data": {"bazi": bazi_str, "verify": content}}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/verify_adjust")
def verify_adjust(request: VerifyAdjustRequest):
    """
    根据用户反馈重新生成不准确的验证条目
    """
    try:
        parsed = parse_birth_and_gender(request.birth)
        if not parsed:
            return {"success": False, "error": "无法解析生辰"}
        
        year, month, day, hour, gender, has_hour = parsed
        bazi = get_bazi(year, month, day, hour, gender)
        bazi_str = f"{bazi['年柱']} {bazi['月柱']} {bazi['日柱']} {bazi['时柱']}"
        
        adjusted_items = []
        
        for fb in request.feedback_items:
            # 构建重新生成的提示词
            prompt = get_adjust_prompt(
                bazi_str, 
                bazi['性别'], 
                fb.section, 
                fb.content, 
                fb.feedback
            )
            
            new_content = call_ai(prompt)
            
            # 清理内容，去掉可能的多余标记
            new_content = new_content.strip()
            if new_content.startswith(f"【{fb.section}】"):
                new_content = new_content.replace(f"【{fb.section}】", "").strip()
            elif new_content.startswith(f"{fb.section}"):
                new_content = new_content.replace(f"{fb.section}", "").strip()
            
            adjusted_items.append({
                "section": fb.section,
                "original_content": fb.content,
                "new_content": new_content
            })
        
        return {"success": True, "data": {"adjusted_items": adjusted_items}}
        
    except Exception as e:
        return {"success": False, "error": str(e)}

# ================== 启动服务 ==================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"启动服务，端口: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
