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

# ================== 读取规则文件 ==================
def load_rules():
    """从 rules.txt 读取八字推理规则"""
    rules_path = os.path.join(os.path.dirname(__file__), "rules.txt")
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            content = f.read()
            print(f"✅ 规则文件加载成功，共 {len(content)} 字符")
            return content
    except FileNotFoundError:
        print("⚠️ 警告: rules.txt 文件未找到，使用默认规则")
        return ""
    except Exception as e:
        print(f"⚠️ 读取 rules.txt 失败: {e}")
        return ""

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

# ================== 构建提示词 ==================
def get_prompt(bazi_str, gender, has_hour, module, year, liunian):
    hour_warning = get_hour_warning(has_hour)
    
    # 加载规则库
    rules = load_rules()
    rules_section = f"\n\n【推理规则库 - 请严格按以下规则推理】\n{rules}\n" if rules else ""
    
    # 统一的格式要求
    format_rule = """
【输出格式要求】
1. 语言朴实直白，禁止使用诗句、古文、成语堆砌，用日常语表达。
2. 采用总分结构：先给出总体结论（一句话概括），再分条详细说明。
3. 分条时用数字编号（1. 2. 3. ...），每条内容简洁有力。
4. 每条分析必须包含：结论 + 简要理由（为什么这样判断）。
5. 不要使用"您""尔"等敬语，直接说"你"即可。
6. 结尾不要写诗，用一句朴实的总结或建议收尾，同时提示AI生成仅供参考。
"""
    
    templates = {
        'overview': f"""八字：{bazi_str}，性别：{gender}{hour_warning}{rules_section}

请对八字进行综合分析。

{format_rule}

分析内容：
一、日元强弱：判断日主是旺是弱，说明依据。
二、喜用忌凶五行：哪些五行对你有利，哪些不利。
三、颜色建议：有利的颜色和不利的颜色。
四、数字建议：有利的数字。
五、方位建议：有利的方位。

输出格式示例：
总体结论：你的八字属于XX格局，日主偏X。

1. 日主强弱：偏X。因为XX原因，所以XX。
2. 喜用五行：X、X、X对你有利，X、X对你不利。
3. 颜色建议：多穿X色，少用X色。
4. 数字建议：X、X、X是你的幸运数字。
5. 方位建议：去X方发展对你有利。

总结：...（一句话）""",

        'liunian': f"""八字：{bazi_str}，性别：{gender}{hour_warning}{rules_section}

请分析{year}年（{liunian}年）及未来两年的流年运势。

{format_rule}

分析内容：
1. 当年整体运势（{year}年）
2. 事业方面
3. 财运方面
4. 感情方面（如适用）
5. 健康方面（如适用）
6. 后两年简单展望

输出格式示例：
总体结论：{year}年你的运势整体偏X。

1. 整体运势：X年对你来说是XX的一年。因为XX，所以XX。
2. 事业方面：工作上XX。建议XX。
3. 财运方面：收入XX。建议XX。
4. 感情方面：感情上XX。建议XX。
5. 健康方面：身体XX。注意XX。
6. 后两年：{year+1}年XX，{year+2}年XX。

总结：...（一句话）""",

        'career': f"""八字：{bazi_str}，性别：{gender}{hour_warning}{rules_section}

请分析事业运势。

{format_rule}

分析内容：
1. 事业格局：整体事业特点
2. 适合行业：哪些行业适合你
3. 工作建议：怎么做能更好
4. 发展时机：什么时候有机会

输出格式示例：
总体结论：你的事业格局偏X，适合X方向。

1. 事业格局：你适合XX。因为八字中XX，所以XX。
2. 适合行业：推荐你做XX、XX、XX。因为这些行业跟你的八字比较合。
3. 工作建议：建议你XX。理由是XX。
4. 发展时机：XX年、XX年机会比较好。

总结：...（一句话）""",

        'wealth': f"""八字：{bazi_str}，性别：{gender}{hour_warning}{rules_section}

请分析财运运势。

{format_rule}

分析内容：
1. 财富等级：整体财运水平
2. 求财方式：适合怎么赚钱
3. 财运时机：什么时候财运好
4. 守财建议：怎么把钱留住

输出格式示例：
总体结论：你的财运整体偏X。

1. 财富等级：你属于XX水平。因为XX，所以XX。
2. 求财方式：你适合XX方式赚钱。理由是XX。
3. 财运时机：XX年、XX年财运不错。
4. 守财建议：建议你XX。

总结：...（一句话）""",

        'marriage': f"""八字：{bazi_str}，性别：{gender}{hour_warning}{rules_section}

请分析婚姻运势。

{format_rule}

分析内容：
1. 婚姻早晚：什么时候结婚比较合适
2. 配偶特征：什么样的人适合你
3. 相处建议：怎么相处更和谐

输出格式示例：
总体结论：你的婚姻运势偏X。

1. 婚姻早晚：你适合XX岁左右结婚。因为XX，所以XX。
2. 配偶特征：适合找XX类型的人。因为八字中XX，所以XX。
3. 相处建议：建议你XX。

总结：...（一句话）""",

        'verify': f"""八字：{bazi_str}，性别：{gender}{hour_warning}{rules_section}

请根据八字推断以下内容。

{format_rule}

推断内容：
1. 环境方位：家里或家外哪个方向有什么特征物品/环境
2. 六亲情况：和哪位亲人关系怎样，或亲人的性格特征
3. 过去经历：列举两个最有把握的年份发生过的事
4. 性格特征：2-3个明显的性格特点

输出格式示例：
总体结论：你的八字有一些明显的特征指向以下情况。

1. 环境方位：你家X方可能有XX。理由：XX。
2. 六亲情况：你和XX关系XX。理由：XX。
3. 过去经历：XX年你经历过XX。理由：XX。
4. 性格特征：你XX。理由：XX。

以上是我的初步推断，请逐条判断是否准确。哪条不对请告诉我哪里不对。"""
    }
    
    return templates.get(module, templates['overview'])

def get_adjust_prompt(bazi_str, gender, section, original_content, user_feedback):
    """生成单条调整的提示词"""
    hour_warning = get_hour_warning(True)
    return f"""八字：{bazi_str}，性别：{gender}{hour_warning}

请根据以下用户反馈，重新生成【{section}】的推断内容：

用户反馈的原推断：{original_content}
用户的实际情况：{user_feedback}

请根据用户的反馈，重新生成推断。要求：
1. 只输出该条推断的内容，不要输出其他部分
2. 判断用户反馈事情性质是否符合八字情况(避免性质相同但表现形式不同)，相同则为用户重新解释符合八字情况不同，不同则重新生成推断
3. 格式保持与原来类似，包含具体推断和分析理由
4. 语言朴实直白，不要用诗句古文

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

# ===== 从环境变量读取 API Key =====
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
