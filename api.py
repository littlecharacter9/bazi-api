# -*- coding: utf-8 -*-
"""
AI命理助手 - API 服务
适配 Railway 部署
"""
import os
import re
import math
import sqlite3
import smtplib
import base64
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from openai import OpenAI
from lunar_python import Solar, Lunar

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

class FeedbackRequest(BaseModel):
    feedback_type: str
    content: str
    contact: Optional[str] = ""
    birth: Optional[str] = ""
    bazi: Optional[str] = ""
    image: Optional[str] = ""  # Base64 编码的图片

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

# ================== 精简后的提示词 ==================
def get_prompt(bazi_str, gender, has_hour, module, year, liunian, da_yun_data=None):
    hour_warning = get_hour_warning(has_hour)
    da_yun_info = format_da_yun_info(da_yun_data) if da_yun_data else ""
    
    style = "语言朴实，结论先行再简述理由，禁用Markdown标题，末尾加：AI生成仅供参考"
    
    # ===== verify 模块 =====
    if module == 'verify':
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{da_yun_info}
请推断：
【环境方位】家里或家外什么方向有什么特征物品/环境，给出理由
【六亲情况】与哪位亲人关系如何，给出理由
【过去经历】列举两个最有把握的年份及事件，给出理由
【性格特征】列出2-3个明显性格特点，给出理由

要求：结论+理由，每项不超过60字。最后说：请判断是否准确？"""

    # 模块名称映射
    names = {
        'overview': '综合分析',
        'career': '事业分析',
        'wealth': '财运分析',
        'marriage': '婚姻分析',
        'parents': '父母分析',
        'children': '子女分析',
        'liunian': '流年分析'
    }
    module_name = names.get(module, '分析')

    # ===== 综合 =====
    if module == 'overview':
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{da_yun_info}
风格：{style}

请进行综合分析，按以下结构输出（每项不超过60字）：

总体结论：（一句话概括命局特点和喜忌）

一、日主剖析
- 日主强弱：（结论+理由）
- 喜用五行：（结论+理由）
- 忌凶五行：（结论+理由）

二、五行格局
- 五行分布：（金木水火土旺衰，结论+理由）
- 五行缺失/过弱/过强：（结论+补救建议+理由）

三、八字格局
- 格局名称：（结论+理由）
- 格局特征：（性格/事业/财富影响，结论+理由）

四、用神与人生指导
- 用神发力方向：（适合的行业/岗位，结论+理由）
- 人际关系：（贵人类型+需避开类型，结论+理由）
- 健康提示：（易患疾病+养生方向，结论+理由）

五、大运指引
- 当前大运：（机遇与挑战，结论+理由）
- 关键年份：（未来需关注的时间点，结论+理由）

总结：（一句话概括命局核心与行动方向）

AI生成仅供参考"""

    # ===== 流年 =====
    if module == 'liunian':
        current_dy = da_yun_data['current']['干支'] if da_yun_data and da_yun_data['current'] else '未知'
        current_age = da_yun_data['current']['年龄范围'] if da_yun_data and da_yun_data['current'] else '未知'
        next_dy = da_yun_data['next']['干支'] if da_yun_data and da_yun_data['next'] else '未知'
        next_age = da_yun_data['next']['年龄范围'] if da_yun_data and da_yun_data['next'] else '未知'
        
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{da_yun_info}
【流年】当前：{year}年（{liunian}年）
风格：{style}

请分析流年运势（每项不超过60字）：

总体结论：（三年概况，一句话）

一、当前大运（{current_dy}，{current_age}）
- 优势：（最有利的领域+如何把握，结论+理由）
- 风险：（需规避的领域+控制方法，结论+理由）

二、三步流年详批
1. {year}年（{liunian}年）
   - 整体：（吉凶基调，结论+理由）
   - 事业/财运/感情/健康：（各一句，结论+理由）
   - 有利月份：（2-3个，结论+理由）
   - 需谨慎月份：（1-2个，结论+理由）

2. {year+1}年整体：（事业/财运/感情/健康各一句+关键月份，结论+理由）

3. {year+2}年整体：（事业/财运/感情/健康各一句+准备建议，结论+理由）

三、下一大运（{next_dy}，{next_age}）
- 与前十年对比：（变化方向，结论+理由）
- 提前准备：（能力/资源/心态，结论+理由）

总结与建议：（今年重点+明年布局+后年展望，结论+理由）

AI生成仅供参考"""

    # ===== 事业 =====
    if module == 'career':
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{da_yun_info}
风格：{style}

请分析事业运势（每项不超过60字）：

总体结论：（事业格局，一句话）

一、事业格局
- 官杀状态：（类型+强弱+与日主关系，结论+理由）
- 发展潜力：（先天基础+后天可达高度，结论+理由）
- 职场角色：（管理/技术/独立/团队，结论+理由）

二、行业与职业方向
- 适合行业：（2-3个具体行业，结论+理由）
- 发展路径：（短期/中期/长期规划，结论+理由）

三、事业发展时机
- 当前大运事业运：（结论+理由）
- 近期机会：（未来1-3年机会点，结论+理由）
- 风险年份：（需谨慎的年份，结论+理由）

四、事业建议
- 提升方向：（需重点提升的能力，结论+理由）
- 决策建议：（重大决策注意事项，结论+理由）

总结：（一句话）

AI生成仅供参考"""

    # ===== 财运 =====
    if module == 'wealth':
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{da_yun_info}
风格：{style}

请分析财运运势（每项不超过60字）：

总体结论：（财富格局，一句话）

一、财富格局
- 财星状态：（类型+旺衰，结论+理由）
- 财富等级：（先天基础+后天可达水平，结论+理由）
- 财库情况：（是否有财库+是否被冲开，结论+理由）

二、求财方式
- 适合行业：（2-3个具体方向，结论+理由）
- 求财手段：（主要方式+合作建议，结论+理由）
- 风险偏好：（激进/保守，结论+理由）

三、财运时机
- 当前大运财运：（结论+理由）
- 近期机会：（未来1-3年财运较好的年份，结论+理由）
- 风险年份：（需守财的年份，结论+理由）

四、守财建议
- 财务管理：（储蓄/投资/消费，结论+理由）
- 风水辅助：（财位方向+颜色搭配，结论+理由）

总结：（一句话）

AI生成仅供参考"""

    # ===== 婚姻 =====
    if module == 'marriage':
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{da_yun_info}
风格：{style}

请分析婚姻运势（每项不超过60字）：

总体结论：（婚姻运势，一句话）

一、婚姻早晚
- 结婚年龄：（大概年龄范围，结论+理由）
- 早婚或晚婚：（属于哪种类型，结论+理由）

二、配偶特征
- 性格：（结论+理由）
- 外貌：（结论+理由）
- 职业：（可能从事的行业，结论+理由）
- 方位：（可能来自什么方位，结论+理由）

三、婚姻质量
- 感情状态：（婚后整体情况，结论+理由）
- 相处模式：（适合的方式，结论+理由）
- 需注意：（婚姻中需留意的问题，结论+理由）

四、婚姻时机
- 有利年份：（适合结婚/感情顺利的年份，结论+理由）
- 不利年份：（感情易出问题的年份，结论+理由）

总结：（一句话）

AI生成仅供参考"""

    # ===== 父母 =====
    if module == 'parents':
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{da_yun_info}
风格：{style}

请分析父母运势（每项不超过60字）：

总体结论：（与父母关系及父母整体情况，一句话）

一、父亲情况
- 关系：（与父亲的关系，结论+理由）
- 性格：（父亲的性格特征，结论+理由）
- 健康：（身体状况，结论+理由）
- 事业财运：（结论+理由）

二、母亲情况
- 关系：（与母亲的关系，结论+理由）
- 性格：（母亲的性格特征，结论+理由）
- 健康：（身体状况，结论+理由）
- 事业财运：（结论+理由）

三、父母关系
- 父母之间关系：（结论+理由）
- 家庭氛围：（整体氛围，结论+理由）

四、对个人的影响
- 正面影响：（父母带来的积极影响，结论+理由）
- 注意事项：（需规避的方面，结论+理由）

总结：（一句话）

AI生成仅供参考"""

    # ===== 子女 =====
    if module == 'children':
        return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{da_yun_info}
风格：{style}

请分析子女运势（每项不超过60字）：

总体结论：（子女运势，一句话）

一、子女概况
- 子女缘分：（深或浅，结论+理由）
- 性格：（子女的性格特征，结论+理由）
- 天赋：（可能有的特长，结论+理由）
- 健康：（身体状况，结论+理由）

二、子女发展
- 学业：（学业运势，结论+理由）
- 事业：（未来发展，结论+理由）
- 与父母关系：（与你的关系，结论+理由）

三、教育建议
- 教育方式：（适合的方式，结论+理由）
- 需注意：（教育中的注意事项，结论+理由）

总结：（一句话）

AI生成仅供参考"""

    # fallback
    return f"""八字：{bazi_str}，性别：{gender}{hour_warning}
风格：{style}

请进行八字分析，输出：总体结论、核心判断、关键要点、建议、总结。每项不超过60字。

AI生成仅供参考"""

# ================== 反馈数据库 ==================
def init_feedback_db():
    """初始化反馈数据库（含 image 字段）"""
    conn = sqlite3.connect('feedback.db')
    cursor = conn.cursor()
    # 检查表是否存在，不存在则创建
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='feedback'")
    table_exists = cursor.fetchone()
    
    if not table_exists:
        # 创建新表
        cursor.execute('''
            CREATE TABLE feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_type TEXT,
                content TEXT,
                contact TEXT,
                birth TEXT,
                bazi TEXT,
                image TEXT,
                created_at TEXT
            )
        ''')
        print("✅ 反馈数据库创建完成（含 image 字段）")
    else:
        # 检查 image 字段是否存在
        cursor.execute("PRAGMA table_info(feedback)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'image' not in columns:
            # 添加 image 字段
            cursor.execute('ALTER TABLE feedback ADD COLUMN image TEXT')
            print("✅ 已添加 image 字段到反馈数据库")
        else:
            print("✅ 反馈数据库已就绪（含 image 字段）")
    
    conn.commit()
    conn.close()

# ================== 邮件通知（暂时禁用） ==================
def send_feedback_email(feedback_type, content, contact, birth, bazi):
    """发送反馈邮件到你的邮箱（Railway Free 计划不支持出站网络，暂时禁用）"""
    # 此函数暂时保留但不会被调用
    # 如需启用，请升级 Railway 到 Hobby 或 Pro 计划
    print("📧 邮件发送功能已禁用（Railway Free 计划不支持出站网络）")
    return False

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

# ===== 初始化反馈数据库 =====
init_feedback_db()

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
            model="deepseek-v4-flash",
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

@app.options("/feedback")
def options_feedback():
    return {"message": "OK"}

# ===== 分析处理函数 =====
def analyze_handler(birth: str, module: str):
    """实际的分析逻辑"""
    try:
        parsed = parse_birth_and_gender(birth)
        if not parsed:
            return {"success": False, "error": "无法解析生辰，格式如：2001.10.30 18时 男"}
        
        year, month, day, hour, gender, has_hour = parsed
        bazi = get_bazi(year, month, day, hour, gender)
        bazi_str = f"{bazi['年柱']} {bazi['月柱']} {bazi['日柱']} {bazi['时柱']}"
        current_year = datetime.now().year
        liunian = get_liunian_ganzhi(current_year)
        
        da_yun_data = get_da_yun(bazi, gender, year, month, day, hour)
        
        prompt = get_prompt(bazi_str, bazi['性别'], has_hour, module, current_year, liunian, da_yun_data)
        content = call_ai(prompt)
        
        return {"success": True, "data": {"bazi": bazi_str, "analysis": content}}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/analyze")
def analyze_post(request: BaziRequest):
    """POST 方式分析（前端正常调用）"""
    return analyze_handler(request.birth, request.module)

@app.get("/analyze")
def analyze_get(birth: str = "", module: str = "all"):
    """GET 方式访问 /analyze - 支持 Railway 健康检查"""
    # 如果没有 birth 参数，说明是 Railway 健康检查，直接返回成功
    if not birth or not birth.strip():
        return {"status": "ok", "message": "health check"}
    
    # 如果有 birth 参数，执行正常分析
    return analyze_handler(birth, module)

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

# ================== 反馈端点（支持图片） ==================
@app.post("/feedback")
def submit_feedback(request: FeedbackRequest):
    """提交反馈（支持图片，Railway Free 计划不支持出站网络发送邮件）"""
    try:
        # 1. 保存到 SQLite（含图片）
        conn = sqlite3.connect('feedback.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO feedback (feedback_type, content, contact, birth, bazi, image, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            request.feedback_type,
            request.content,
            request.contact,
            request.birth,
            request.bazi,
            request.image,
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()
        
        # 2. 邮件发送已禁用（Railway Free 计划不支持出站网络）
        # 如需启用邮件通知，请升级 Railway 到 Hobby 或 Pro 计划
        
        return {"success": True, "message": "感谢您的反馈！"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ================== 查看反馈列表（密码保护，含图片链接） ==================
@app.get("/feedback_list")
def get_feedback_list(password: str = ""):
    """查看所有反馈（需要密码验证），有图片时直接显示图片链接"""
    # 密码验证（密码设为你的微信号）
    if password != "mmj1399094604":
        return {"success": False, "error": "密码错误"}
    
    try:
        conn = sqlite3.connect('feedback.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, feedback_type, content, contact, birth, bazi, 
                   CASE WHEN image IS NOT NULL AND image != '' THEN '有图片' ELSE '无图片' END as has_image,
                   created_at 
            FROM feedback ORDER BY id DESC
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return {"success": True, "count": 0, "data": "📋 暂无反馈记录"}
        
        result = "📋 反馈列表\n" + "="*50 + "\n"
        for row in rows:
            result += f"\nID: {row[0]}\n"
            result += f"类型: {row[1]}\n"
            result += f"内容: {row[2]}\n"
            result += f"联系方式: {row[3] or '未提供'}\n"
            result += f"生辰: {row[4] or '未提供'}\n"
            result += f"八字: {row[5] or '未提供'}\n"
            if row[6] == '有图片':
                result += f"📷 图片: https://api.bajiemingli.top/feedback_image/{row[0]}?password=mmj1399094604\n"
            else:
                result += f"📷 图片: 无图片\n"
            result += f"时间: {row[7]}\n"
            result += "-"*30 + "\n"
        
        return {"success": True, "count": len(rows), "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ================== 查看反馈图片（密码保护） ==================
@app.get("/feedback_image/{feedback_id}")
def get_feedback_image(feedback_id: int, password: str = ""):
    """查看反馈图片"""
    # 密码验证
    if password != "mmj1399094604":
        return {"success": False, "error": "密码错误"}
    
    try:
        conn = sqlite3.connect('feedback.db')
        cursor = conn.cursor()
        cursor.execute('SELECT image FROM feedback WHERE id = ?', (feedback_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row or not row[0]:
            return {"success": False, "error": "没有图片"}
        
        image_data = row[0]
        
        # 检查是否是 data:image/xxx;base64, 格式
        if image_data.startswith('data:image'):
            # 提取图片类型
            img_type = image_data.split(';')[0].split('/')[1]
            # 提取 Base64 数据（去掉前缀）
            base64_str = image_data.split(',')[1]
            try:
                # 解码 Base64
                image_bytes = base64.b64decode(base64_str)
                # 直接返回图片二进制数据
                return Response(content=image_bytes, media_type=f"image/{img_type}")
            except Exception as e:
                print(f"❌ Base64解码失败: {e}")
                # 如果解码失败，尝试作为纯 Base64 字符串处理
                try:
                    image_bytes = base64.b64decode(image_data)
                    return Response(content=image_bytes, media_type="image/png")
                except:
                    return {"success": False, "error": f"图片数据格式错误: {str(e)}"}
        else:
            # 如果不是 data:image 格式，尝试直接解码
            try:
                image_bytes = base64.b64decode(image_data)
                return Response(content=image_bytes, media_type="image/png")
            except:
                return {"success": False, "error": "图片格式不支持"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}

# ================== 启动服务 ==================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"启动服务，端口: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
