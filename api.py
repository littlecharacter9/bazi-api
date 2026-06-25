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

# ================== 构建提示词（规则和格式完全分离） ==================
def get_prompt(bazi_str, gender, has_hour, module, year, liunian):
    hour_warning = get_hour_warning(has_hour)
    
    # ===== 1. 规则库（纯推理依据，不输出） =====
    rules = load_rules()
    rules_section = f"\n【以下是你分析时需要用到的推理规则，只用于辅助判断，不要输出到最终答案中】\n{rules}\n" if rules else ""
    
    # ===== 2. 输出格式模板（纯结构） =====
    format_templates = {
        'overview': """总体结论：你的八字属于XX格局，日主偏X。

一、日主强弱：偏X
   - 得令/不得令：XX
   - 得地/不得地：XX
   - 得势/不得势：XX
   综合：日主XX，因为XX。

二、五行喜忌
   - 喜用五行：X、X、X对你有用
   - 忌凶五行：X、X对你不利

三、颜色建议
   - 喜用：X色、X色
   - 忌凶：X色、X色

四、 数字建议
   - 喜用：X、X、X
   - 忌凶：X、X、X

五、方位建议：
   - 喜用：X方、X方
   - 忌凶：X方、X方

总结：一句话总结XXX。AI生成内容仅供娱乐，理性看待。""",

        'liunian': """总体结论：{year}年你的运势整体偏X。

1. 整体运势：X年对你来说是XX的一年。
2. 事业方面：工作上XX。
3. 财运方面：收入XX。
4. 感情方面：感情上XX。
5. 健康方面：身体XX。
6. 后两年展望：{year+1}年XX，{year+2}年XX。

总结：一句话总结。AI生成内容仅供娱乐，理性看待。""",

        'career': """总体结论：你的事业格局偏X，适合X方向。

1. 事业格局：你属于XX类型。
2. 适合行业：XX、XX、XX比较适合你。
3. 工作建议：建议你XX。
4. 发展时机：XX年、XX年有机会。

总结：一句话总结。AI生成内容仅供娱乐，理性看待。""",

        'wealth': """总体结论：你的财运整体偏X。

1. 财富等级：你属于XX水平。
2. 求财方式：你适合XX方式赚钱。
3. 财运时机：XX年、XX年财运不错。
4. 守财建议：建议你XX。

总结：一句话总结。AI生成内容仅供娱乐，理性看待。""",

        'marriage': """总体结论：你的婚姻运势偏X。

1. 婚姻早晚：你适合XX岁左右结婚。
2. 配偶特征：适合找XX类型的人。
3. 相处建议：建议你XX。

总结：一句话总结。AI生成内容仅供娱乐，理性看待。""",

        'verify': """总体结论：你的八字有以下明显特征。

1. 环境方位：你家X方可能有XX。理由：XX。
2. 六亲情况：你和XX关系XX。理由：XX。
3. 过去经历：XX年你经历过XX。理由：XX。
4. 性格特征：你XX。理由：XX。

以上是我的初步推断，请逐条判断是否准确。哪条不对请告诉我哪里不对。"""
    }
    
    # 获取对应的格式模板
    format_template = format_templates.get(module, format_templates['overview'])
    
    # 如果是流年模块，替换 year 占位符
    if module == 'liunian':
        format_template = format_template.replace('{year}', str(year))
        format_template = format_template.replace('{year+1}', str(year + 1))
        format_template = format_template.replace('{year+2}', str(year + 2))
    
    # ===== 3. 拼接最终提示词 =====
    base_prompt = f"""八字：{bazi_str}，性别：{gender}{hour_warning}

{rules_section}

【输出格式 - 下面的内容就是你的输出模板，请一字不差地照搬这个结构】
{format_template}

【填充要求】
1. 参考示例的格式进行输出，保留整体结构不变，内容可进行适当调整
2. 内容用朴实直白的语言，不用诗句、古文、成语。
3. 直接说"你"，不用"您""尔"。
4. 禁止使用 #、##、###、****、== 等任何 Markdown 符号。
"""
    
    return base_prompt

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
