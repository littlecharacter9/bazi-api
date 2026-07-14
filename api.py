# -*- coding: utf-8 -*-
"""
AI命理助手 - API 服务
适配 Railway 部署
"""
import os
import re
import math
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from openai import OpenAI
from lunar_python import Solar, Lunar

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

# ================== 大运计算函数（精确版本） ==================
def get_da_yun(bazi, gender, birth_year, birth_month, birth_day, birth_hour):
    """
    精确计算大运（含起运年龄计算）
    """
    # 获取农历信息
    solar = Solar.fromYmdHms(birth_year, birth_month, birth_day, birth_hour, 0, 0)
    lunar = solar.getLunar()
    
    # 月柱干支
    month_gan = bazi['月柱'][0]
    month_zhi = bazi['月柱'][1]
    
    # 年柱天干
    year_gan = bazi['年柱'][0]
    
    # 阳年判断
    yang_years = ['甲', '丙', '戊', '庚', '壬']
    is_yang = year_gan in yang_years
    
    # 顺逆：阳男阴女顺，阴男阳女逆
    if (is_yang and gender == 1) or (not is_yang and gender == 0):
        direction = 1  # 顺排
    else:
        direction = -1  # 逆排
    
    # ===== 精确计算起运年龄 =====
    start_age = None
    
    # 方法1: 使用 lunar_python 的 getStartAge() 方法
    try:
        start_age = lunar.getStartAge()
        if start_age is not None:
            print(f"✅ 使用 lunar_python 计算起运年龄: {start_age} 岁")
    except Exception as e:
        print(f"⚠️ getStartAge() 调用失败: {e}")
    
    # 方法2: 如果 getStartAge() 失败或返回 None，手动计算
    if start_age is None or start_age <= 0:
        try:
            # 月柱地支对应的节气
            month_zhi_to_jieqi = {
                '寅': '立春', '卯': '惊蛰', '辰': '清明', '巳': '立夏',
                '午': '芒种', '未': '小暑', '申': '立秋', '酉': '白露',
                '戌': '寒露', '亥': '立冬', '子': '大雪', '丑': '小寒'
            }
            
            # 顺排找下一个节气，逆排找上一个节气
            target_jieqi = month_zhi_to_jieqi.get(month_zhi)
            
            if target_jieqi:
                jie_qi_table = lunar.getJieQiTable()
                target_date = None
                
                # 查找目标节气日期
                for name, dt in jie_qi_table.items():
                    if name == target_jieqi:
                        target_date = dt
                        break
                
                if target_date:
                    from datetime import datetime as dt
                    birth_dt = dt(birth_year, birth_month, birth_day, birth_hour)
                    target_dt = dt(
                        target_date.getYear(), 
                        target_date.getMonth(), 
                        target_date.getDay()
                    )
                    
                    # 计算相差天数
                    diff_days = abs((target_dt - birth_dt).days)
                    
                    # 三天为一岁，向上取整
                    start_age = math.ceil(diff_days / 3)
                    
                    # 保证至少 1 岁
                    if start_age < 1:
                        start_age = 1
                    
                    print(f"✅ 手动计算起运年龄: {start_age} 岁（距离{target_jieqi}{diff_days}天）")
        except Exception as e:
            print(f"⚠️ 手动计算起运年龄失败: {e}")
    
    # 方法3: 如果还是失败，默认 3 岁
    if start_age is None or start_age <= 0:
        start_age = 3
        print(f"⚠️ 使用默认起运年龄: {start_age} 岁")
    
    # 天干地支列表
    gan = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
    zhi = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
    
    try:
        gan_index = gan.index(month_gan)
    except ValueError:
        gan_index = 0
    try:
        zhi_index = zhi.index(month_zhi)
    except ValueError:
        zhi_index = 0
    
    # 当前年龄
    current_year = datetime.now().year
    current_age = current_year - birth_year
    
    da_yun_list = []
    current_da_yun = None
    next_da_yun = None
    
    # 排 8 步大运
    for i in range(8):
        step = i + 1
        gan_idx = (gan_index + direction * step) % 10
        zhi_idx = (zhi_index + direction * step) % 12
        da_gan = gan[gan_idx]
        da_zhi = zhi[zhi_idx]
        
        age_start = start_age + i * 10
        age_end = age_start + 9
        
        da_yun = {
            '干支': f'{da_gan}{da_zhi}',
            '年龄范围': f'{age_start}-{age_end}岁',
            '年龄起始': age_start,
            '年龄结束': age_end,
            '序号': i + 1
        }
        da_yun_list.append(da_yun)
        
        # 判断当前大运
        if age_start <= current_age <= age_end:
            current_da_yun = da_yun
            if i + 1 < len(da_yun_list):
                next_da_yun = da_yun_list[i + 1]
    
    # 如果当前年龄还没到起运年龄，第一运为当前
    if current_age < start_age and da_yun_list:
        current_da_yun = da_yun_list[0]
        if len(da_yun_list) > 1:
            next_da_yun = da_yun_list[1]
    
    return {
        'list': da_yun_list,
        'current': current_da_yun,
        'next': next_da_yun,
        'start_age': start_age,
        'direction': '顺排' if direction == 1 else '逆排'
    }

def format_da_yun_info(da_yun_data):
    """格式化大运信息为文本"""
    if not da_yun_data:
        return ""
    
    result = f"\n【大运信息】起运年龄：{da_yun_data.get('start_age', 3)}岁，{da_yun_data.get('direction', '')}\n\n"
    
    if da_yun_data.get('current'):
        current = da_yun_data['current']
        result += f"当前大运：{current['干支']}（{current['年龄范围']}）\n"
    
    if da_yun_data.get('next'):
        next_dy = da_yun_data['next']
        result += f"下一步大运：{next_dy['干支']}（{next_dy['年龄范围']}）\n"
    
    # 列出所有大运
    result += "\n一生大运排盘：\n"
    for dy in da_yun_data.get('list', []):
        result += f"  第{dy['序号']}步大运：{dy['干支']}（{dy['年龄范围']}）\n"
    
    return result

def get_prompt(bazi_str, gender, has_hour, module, year, liunian, da_yun_data=None):
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
    
    # ===== 格式化大运信息 =====
    da_yun_info = format_da_yun_info(da_yun_data) if da_yun_data else ""
    
    # verify 单独处理，保持原版不变
    if module == 'verify':
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{rules_section}
{da_yun_info}
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
{da_yun_info}
请进行八字综合分析，按以下结构输出：
总体结论：（一句话概括你的八字特点和喜忌）

一、日主强弱
根据是否得令、是否得地、是否得势、日柱旬空四个方面判断日元强弱；
输出格式要求：是否得令、是否得地、是否得势三个方面分条阐述具体情况，如果有日柱旬空影响则加此条 不受日柱旬空影响则不阐述此条；最后给总结判断身强还是身弱
    - XX：XX (得令、得地、得势、旬空按此格式分条列出)
综合：日主XX，原因+表现/影响。

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
② 偏格--准确度低(除正十神格外的格局，例如三奇贵人格、禄元互换格、日规格、天地合、鸳鸯合、枭神夺食、杀印相生、食神制杀、身杀两停、伤官泄秀、伤官配印、伤官生财、伤官伤尽、伤官见官中，如果符合多种则一一例举)
    - XX(格局名称1)：XX，格局类型+原因
    - XX(格局名称2)：……(无则不例举)
    
四、总结
XXX

AI生成内容仅供参考"

注意：每一条都要先给结论，再简单解释理由。""",
        
        'liunian': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
{da_yun_info}
【流年信息】当前年份：{year}年（{liunian}年）

请严格基于以上提供的大运信息和流年信息分析流年运势，不要自行推算大运。按以下结构输出：
总体结论：（一句话概括三年每年的重点关注项）

一、三年运势
1.{year}年整体运势
    - XX：XX，原因
    - XX：XX，原因
    - XX：XX，原因(以上例举2-3条需要重点关注的方面，健康、财运、官运、感情、事业、六亲)
综合：XX(综合说明该流年整体情况及需要重点关注的方面)
2.{year+1}年整体运势
    - XX：XX，原因
    - XX：XX，原因
    - XX：XX，原因(以上例举2-3条需要重点关注的方面，健康、财运、官运、感情、事业、六亲)
综合：XX(综合说明该流年整体情况及需要重点关注的方面)
3.{year+2}年整体运势
    - XX：XX，原因
    - XX：XX，原因
    - XX：XX，原因(以上例举2-3条需要重点关注的方面，健康、财运、官运、感情、事业、六亲)
综合：XX(综合说明该流年整体情况及需要重点关注的方面)

二、当前大运分析（{da_yun_data['current']['干支'] if da_yun_data and da_yun_data['current'] else '未知'}，{da_yun_data['current']['年龄范围'] if da_yun_data and da_yun_data['current'] else '未知'}）
    说明当前大运情况及建议，突出需要重点注意的地方(机遇/风险)

三、下一步大运分析（{da_yun_data['next']['干支'] if da_yun_data and da_yun_data['next'] else '未知'}，{da_yun_data['next']['年龄范围'] if da_yun_data and da_yun_data['next'] else '未知'}）
    说明下一步大运情况及建议，突出需要重点注意的地方(机遇/风险)

四、总结
XXX。

AI生成内容仅供参考""",
        
        'career': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
{da_yun_info}
请分析事业运势，按以下结构输出：
总体结论：（一句话概括你的事业情况）

一、事业总论
1.事业性质
    - 劳动性质：通过什么样的方式挣钱(说明理由)
    - 行业性质：适合什么性质的行业(说明理由)
2. 工作建议
    - 行动建议（具体建议，说明理由）
    - 合伙建议(建议和天乙贵人合伙，注意天乙贵人不对八字本身产生刑冲破害)
    
二、十年发展
1.发展建议
    - 机遇：XX(阐述未来十年发展的机遇点，理由+建议)
    - 风险：XX(阐述未来十年发展的风险点，理由+建议)
2.发展时机
    - 例举几个未来十年的关键发展时机，并说明是风险还是机遇，说明理由(性质+实际建议)

三、总结
XX

AI生成仅供参考""",
        
        'wealth': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
{da_yun_info}
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
{da_yun_info}
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
        
        # ===== 计算大运信息（传入出生年月日时） =====
        da_yun_data = get_da_yun(bazi, gender, year, month, day, hour)
        
        prompt = get_prompt(bazi_str, bazi['性别'], has_hour, request.module, current_year, liunian, da_yun_data)
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
        
        # verify 模块也需要大运信息辅助
        da_yun_data = get_da_yun(bazi, gender, year, month, day, hour)
        prompt = get_prompt(bazi_str, bazi['性别'], has_hour, 'verify', 0, '', da_yun_data)
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
