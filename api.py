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

def get_prompt(bazi_str, gender, has_hour, module, year, liunian):
    hour_warning = get_hour_warning(has_hour)
    
    # 风格控制（仅用于非 verify 模块）
    style_control = """
【全局风格要求】
1. 语言风格：朴实无华但该说明的地方就要说明，避免华丽辞藻；
2. 结构要求：先给出一句总体结论概括全貌，再分条详细说明，所有推断结束后再作一条总结。每条分析采用"结论 + 理由"的形式。
3. 格式要求：禁止使用 Markdown 标题符号（#、##、###、****、==、---）。
4. 内容末尾加上：AI生成内容仅供参考。
"""
    
    # ===== 加载规则库 =====
    rules_content = load_rules()
    rules_section = f"""
【八字推理规则库 - 请严格依据以下规则进行推断，并按照格式输出】
{rules_content}
""" if rules_content else ""
    
    # verify 单独处理，保持原版不变
    if module == 'verify':
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{rules_section}
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
{rules_section}
请进行八字综合分析，按以下结构输出：
总体结论：（一句话概括你的八字特点和喜忌）

一、日主强弱
根据是否得令、是否得地、是否得势、日柱旬空四个方面判断日元强弱；
输出格式要求：得令、得地、得势三个方面分条阐述具体情况，如果有日柱旬空影响则加此条 不受日柱旬空影响则不阐述此条；最后给总结判断身强还是身弱
    - XX：XX (得令、得地、得势、旬空按此格式分条列出)
综合：日主XX，因为XX。

二、五行总论
① 五行平衡
    先判断五行是否齐全/平衡，如果五行齐全并且平衡就产出五行平衡及平衡带来的影响/好处；如果存在五行缺失/五行不均衡按照以下论点分点阐述(没有的部分不阐述 如不存在缺失五行)
    - 五行缺失：XXX，理由+影响+建议
    - 五行过弱：XXX，理由+影响+建议
    - 五行过强：XXX，理由+影响+建议
② 五行喜忌
   - 喜用五行：XX，原因+影响
   - 忌凶五行：XX，原因+影响
③ 行动建议
    - 颜色建议：XXX，理由+具体行动(吃、穿、住、行XXX颜色对应物品，例举一两条即可)
    - 数字建议：XXX，理由+具体行动(吃、穿、住、行XXX数字内容，例举一两条即可)
    - 方位建议：XXX，理由+具体行动(住、行XXX方位内容，例举一两条即可)
五行总结：XXX

三、八字格局
① 正格
    - 格局：XX，格局类型+原因(正格判断规则：月令十神(包括藏干)在在天干上有对应五行或十神透出则为正格，否则为杂格(格局随大运变化))
    - 特征：XX，表现+影响(正格十神对应的性格、追求、表现)
② 偏格(此条参考rule中列出的成格条件进行判断, 若有多个偏格的一一例举)
    - 格局1：XX，格局类型+原因
    - 特征：XX，表现+影响(对格局效果进行补充延伸/自行生成)
    - 格局2：……
    - 特征：……
    
总结：XXX。

AI生成内容仅供参考"

注意：每一条都要先给结论，再简单解释理由。""",
        
        'liunian': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
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
{rules_section}
请分析事业运势，按以下结构输出：
总体结论：（一句话概括你的事业情况）

一、事业性质
    - 劳动性质：通过什么样的方式挣钱(说明理由)
    - 行业性质：适合什么性质的行业(说明理由)
二、工作建议
    - 行动建议（具体建议，说明理由）
    - 合伙建议(建议和天乙贵人合伙，注意天乙贵人不对八字本身产生刑冲破害)
三、发展时机
    - 例举几个关键发展的时机，并说明是风险还是机遇，说明理由

总结：XX

AI生成仅供参考""",
        
        'wealth': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
请分析财运运势，按以下结构输出：
总体结论：（一句话概括你的财运水平）

一、财富等级：（你属于什么水平，说明理由）
二、求财方式：（适合用什么方式赚钱，说明理由）
三、财运时机：（哪些年份财运好，说明理由）
四、守财建议：（如何守住财富，说明理由）

总结：XX。

AI生成仅供参考""",
        
        'marriage': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
请分析婚姻运势，按以下结构输出：
总体结论：（一句话概括你的婚姻运势）

一、婚姻早晚：（大概什么年龄结婚合适，说明理由）
二、配偶特征：（适合找什么类型的人，说明理由）
三、相处建议：（婚后如何相处，说明理由）

总结：XX

AI生成仅供参考"""
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
2. 根据用户的反馈判断是否符合八字情况(避免性质相同但表现形式不同)；如果符合八字性质特征则为用户重新解释，如果不符合则重新生成该条推断内容
3. 格式保持与原来类似，包含具体推断和分析理由

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

# ===== 注意：不在这里初始化 OpenAI 客户端 =====
# client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")
# 改为在 call_ai 函数中延迟初始化

def call_ai(prompt):
    """调用 DeepSeek API（延迟初始化）"""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return "❌ API Key 未配置，请在 Railway 环境变量中设置 DEEPSEEK_API_KEY"
    
    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ AI 调用失败: {str(e)}"

@app.get("/")
def root():
    return {"message": "AI命理助手API运行中", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}

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
