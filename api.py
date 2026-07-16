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

一、日主深度剖析
1. 日主强弱
    - 得令与否：（月支是否生扶日主，说明理由）
    - 得地与否：（日支是否生扶日主，说明理由）
    - 得势与否：（其他天干地支是否生扶日主，说明理由）
    - 日柱旬空：（日柱是否落旬空，如有则说明影响，无则不阐述）
综合判断：日主XX（身强/身弱/中和），原因+具体表现。
2. 日主喜忌
    - 喜用五行：（对日主最有利的五行，说明理由）
    - 忌凶五行：（对日主最不利的五行，说明理由）
    - 调候需求：（是否需调候，需要什么五行调候，说明理由）
3. 日主特性
    - 性格特质：（日主五行对应的性格特点，说明理由）
    - 优点与缺点：（性格上的优势与不足，说明理由）
    - 行为模式：（为人处世的惯常方式，说明理由）

二、五行格局总论
1. 五行平衡
① 五行分布
    - 五行分布情况：（金木水火土各有多少，哪几个旺、哪几个弱、哪几个缺失，说明理由）
② 五行缺失/过弱/过强分析（根据需要选一项）
    - 五行缺失：（缺失的五行，缺失的影响及补救建议，说明理由）
    - 五行过弱：（过弱的五行，对命局的影响及补救建议，说明理由）
    - 五行过强：（过强的五行，对命局的影响及化解建议，说明理由）
2. 五行喜忌
① 喜用五行
    - 喜用五行：（列出喜用的五行及其作用，说明理由）
    - 原因分析：（为什么这些五行对你有用，说明理由）
    - 有益表现：（喜用五行能带来哪些好的影响，说明理由）
② 忌凶五行
    - 忌凶五行：（列出忌凶的五行及其危害，说明理由）
    - 原因分析：（为什么这些五行对你不利，说明理由）
    - 不利表现：（忌凶五行会带来哪些问题，说明理由）
③ 平衡机制
    - 五行流转：（命局中五行的流通情况，说明理由）
    - 冲合影响：（六冲、六合对五行平衡的影响，说明理由）
3. 行动建议
① 颜色建议
    - 宜用颜色：（哪些颜色对你有益，理由+具体行动）
    - 忌讳颜色：（哪些颜色不利，理由+具体行动）
② 数字建议
    - 宜用数字：（哪些数字对你有益，理由+具体行动）
    - 忌讳数字：（哪些数字不利，理由+具体行动）
③ 方位建议
    - 宜用方位：（哪些方位对你有益，理由+具体行动）
    - 忌讳方位：（哪些方位不利，理由+具体行动）
④ 季节建议
    - 有利季节：（哪个季节运势最好，理由+建议）
    - 不利季节：（哪个季节需特别注意，理由+建议）
五行总结：（概括五行对命局的核心影响及实践建议）

三、八字格局
1. 正格
① 格局判定
    - 格局名称：（是什么正格，说明理由）
    - 成因分析：（为什么形成这个格局，说明理由）
② 格局特征
    - 性格特征：（格局对应的性格特点，说明理由）
    - 追求方向：（格局对应的人生追求，说明理由）
    - 行为表现：（格局在日常行为上的体现，说明理由）
③ 格局优劣
    - 优势：（格局带来的好处，说明理由）
    - 劣势：（格局带来的局限，说明理由）
2. 偏格（准确度较低，如有则分析）
① 格局判定
    - 格局名称：（是什么偏格，说明理由）
    - 成因分析：（为什么形成这个格局，说明理由）
② 格局特征
    - 特殊表现：（偏格对应的特殊命理现象，说明理由）
    - 注意事项：（偏格需要注意的问题，说明理由）
3. 格局与人生
    - 格局与事业：（格局对事业发展的影响，说明理由）
    - 格局与财富：（格局对财运的影响，说明理由）
    - 格局与性格：（格局对性格的塑造，说明理由）

四、用神与人生指导
1. 用神运用
    - 用神本质：（用神的深层含义，说明理由）
    - 用神发力：（用神在哪些领域最能发挥价值，说明理由）
    - 用神时机：（用神在什么时候最得力，说明理由）
2. 人生建议
① 事业方向
    - 适合的行业：（与喜用五行匹配的行业，说明理由）
    - 适合的岗位：（与命局匹配的岗位类型，说明理由）
    - 发展建议：（具体的事业发展建议，说明理由）
② 财富管理
    - 求财方式：（适合的求财方式，说明理由）
    - 理财建议：（财务管理建议，说明理由）
③ 人际关系
    - 与亲友相处：（与家人的相处建议，说明理由）
    - 贵人类型：（什么类型的人对你有帮助，说明理由）
    - 需要避开的类型：（什么类型的人对你不利，说明理由）
④ 健康养生
    - 易患疾病：（需要注意哪些健康问题，说明理由）
    - 养生方向：（适合的养生方式，说明理由）
3. 大运指引
    - 当前大运：（当前大运的机遇与挑战，说明理由）
    - 关键年份：（未来几年需要重点关注的时间点，说明理由）
    - 长期发展：（未来10-20年的发展主线，说明理由）

五、总结
1. 命局核心特征
    - 优势（天生优势，如何发挥）
    - 不足（先天不足，如何化解）
    - 关键（人生关键点）
2. 行动纲领
    - 适合做什么、怎么选择、怎么调整

AI生成内容仅供参考"

注意：每一条都要先给结论，再简单解释理由。""",
        
        'liunian': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
{da_yun_info}
【流年信息】当前年份：{year}年（{liunian}年）

请严格基于以上提供的大运信息和流年信息分析流年运势，不要自行推算大运。按以下结构输出：
总体结论：（一句话概括三年每年的重点关注项）

一、当前大运总览（{da_yun_data['current']['干支'] if da_yun_data and da_yun_data['current'] else '未知'}，{da_yun_data['current']['年龄范围'] if da_yun_data and da_yun_data['current'] else '未知'}）
1. 当前大运的优势
    - 最有利的领域：（这十年最容易出成绩的方向，说明理由）
    - 可以借助的力量：（身边哪些人/资源可以利用，说明理由）
    - 如何把握：（具体建议，说明理由）
2. 当前大运的风险
    - 最需要注意的领域：（这十年最容易出问题的地方，说明理由）
    - 需要规避的人和事：（哪些人/事要避开，说明理由）
    - 风险控制：（如何降低风险，说明理由）

二、三步流年详批
1. {year}年（{liunian}年）运势
① 整体运势
    - 流年与八字的关系：（流年干支对命局的影响，说明理由）
    - 流年与大运的关系：（流年与大运的互动关系，说明理由）
    - 全年基调：（这一年整体上吉凶如何，说明理由）
② 分项运势
    - 事业运势：（工作上的机遇与挑战，说明理由）
    - 财运运势：（收入、投资、消费情况，说明理由）
    - 感情运势：（单身/恋爱/婚姻的情况，说明理由）
    - 健康运势：（身体状况及需要注意的方面，说明理由）
    - 人际关系：（与家人、朋友、同事的关系，说明理由）
③ 月份指引
    - 有利月份：（哪几个月运势较好，适合行动，说明理由）
    - 需谨慎月份：（哪几个月要特别注意，说明理由）
④ 年度建议
    - 应该做的事：（今年适合做什么，说明理由）
    - 应该避免的事：（今年要避开什么，说明理由）

2. {year+1}年整体运势
    - 干支分析：（流年干支对命局的影响，说明理由）
    - 事业：（工作上的情况，说明理由）
    - 财运：（收入情况，说明理由）
    - 感情：（感情上的情况，说明理由）
    - 健康：（身体状况，说明理由）
    - 关键月份：（哪个月份最需要注意，说明理由）
    - 建议：（对明年的建议，说明理由）

3. {year+2}年整体运势
    - 干支分析：（流年干支对命局的影响，说明理由）
    - 事业：（工作上的情况，说明理由）
    - 财运：（收入情况，说明理由）
    - 感情：（感情上的情况，说明理由）
    - 健康：（身体状况，说明理由）
    - 准备建议：（提前可以做什么准备，说明理由）


三、下一大运展望（{da_yun_data['next']['干支'] if da_yun_data and da_yun_data['next'] else '未知'}，{da_yun_data['next']['年龄范围'] if da_yun_data and da_yun_data['next'] else '未知'}）
1. 大运性质
    - 十神属性：（下一步大运的天干地支十神组合，说明理由）
    - 五行倾向：（下一步大运的整体方向，说明理由）
    - 与前十年对比：（相比当前大运的变化，说明理由）
2. 提前准备
    - 能力准备：（需要提前提升什么能力，说明理由）
    - 资源准备：（需要提前积累什么资源，说明理由）
    - 心态准备：（如何调整心态迎接新大运，说明理由）

总结与建议
1. 三年综合建议
    - 今年重点：（当前年份的行动重点，说明理由）
    - 明年布局：（明年可以提前布局的方向，说明理由）
    - 后年展望：（后年的规划建议，说明理由）
2. 长期建议
    - 大运期间目标：（当前大运结束前应该完成什么，说明理由）
    - 人生阶段定位：（当前处于人生的什么阶段，说明理由）

AI生成内容仅供参考""",
        
        'career': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
{da_yun_info}
请分析事业运势，按以下结构输出：
总体结论：（一句话概括你的事业情况）

一、事业格局
1. 官杀状态
    - 官杀类型：（正官/七杀/官杀混杂/无官杀，说明理由）
    - 官杀强弱：（官杀旺衰情况，说明理由）
    - 官杀与日主关系：（官杀对日主是压力还是助力，说明理由）
2. 事业发展潜力
    - 先天基础：（命局自带的事业潜力，说明理由）
    - 后天发展：（通过努力能达到的事业高度，说明理由）
    - 贵人情况：（命中有无贵人相助，说明理由）
3. 适合的职场角色
    - 管理能力：（适合做管理还是技术，说明理由）
    - 独立程度：（适合上班还是创业，说明理由）
    - 团队配合：（适合单打独斗还是团队协作，说明理由）

二、行业与职业方向
1. 适合行业
    - 五行行业：（与喜用五行匹配的行业，说明理由）
    - 行业类型：（具体行业方向建议，说明理由）
    - 发展领域：（建议深耕哪个领域，说明理由）
2. 职业发展路径
    - 短期建议：（未来3-5年应该怎么走，说明理由）
    - 中期规划：（5-10年的发展目标，说明理由）
    - 长期方向：（10年以上的最终方向，说明理由）

三、事业发展时机
1. 大运事业运
    - 当前大运：（当前大运的事业发展情况，说明理由）
    - 最佳大运：（一生中事业最旺的大运，说明理由）
    - 需谨慎的大运：（哪些大运要特别注意事业波动，说明理由）
2. 流年事业运
    - 近期机会：（未来1-3年事业发展的机会点，说明理由）
    - 风险年份：（哪些年份容易有事业变动或压力，说明理由）
3. 关键节点
    - 升迁时机：（适合争取升职加薪的年份，说明理由）
    - 转型时机：（适合转行或调整方向的年份，说明理由）

四、事业建议
1. 行动策略
    - 提升方向：（需要重点提升什么能力，说明理由）
    - 人际关系：（如何处理职场人际关系，说明理由）
    - 决策建议：（做重大事业决策时要注意什么，说明理由）
2. 禁忌与提醒
    - 事业禁忌：（容易踩的坑，说明理由）
    - 时机把握：（什么该争取、什么该等待，说明理由）
    - 心态调整：（事业低谷时该如何调整，说明理由）

总结
XX

AI生成仅供参考""",
        
        'wealth': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
{da_yun_info}
请分析财运运势，按以下结构输出：
总体结论：（一句话概括你的财运水平）

一、财富格局
1. 财星状态
    - 财星类型：（正财/偏财/财库/无财星，说明理由）
    - 财星强弱：（财星旺衰情况，说明理由）
    - 财星位置：（财星在八字中的位置，说明理由）
2. 财富等级
    - 先天基础：（命局自带的财富潜力，说明理由）
    - 后天发展：（通过努力能达到的财富水平，说明理由）
    - 财库情况：（是否有财库、财库是否被冲开，说明理由）

二、求财方式
1. 适合行业
    - 五行行业：（与喜用五行匹配的行业，说明理由）
    - 行业类型：（具体行业方向建议，说明理由）
    - 职业属性：（适合打工/创业/自由职业等，说明理由）
2. 求财手段
    - 主要方式：（适合的求财方式，说明理由）
    - 合作方向：（是否需要合伙，适合与什么类型的人合伙，说明理由）
    - 风险偏好：（适合激进还是保守的理财方式，说明理由）

三、财运时机
1. 大运财运
    - 当前大运：（当前大运的财运情况，说明理由）
    - 最佳大运：（一生中财运最好的大运，说明理由）
    - 需谨慎的大运：（哪些大运要特别注意守财，说明理由）
2. 流年财运
    - 近期机会：（未来1-3年财运较好的年份，说明理由）
    - 风险年份：（哪些年份容易破财需谨慎，说明理由）

四、守财建议
1. 财务管理
    - 储蓄建议：（如何积累财富，说明理由）
    - 投资建议：（适合的投资方向，说明理由）
    - 消费建议：（需要克制哪方面的消费，说明理由）
2. 风水辅助
    - 财位方向：（适合的求财方位，说明理由）
    - 颜色搭配：（有助于财运的颜色，说明理由）
    - 物品建议：（可以摆放什么物品助运，说明理由）

总结：XX

AI生成仅供参考""",
        
        'marriage': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
{da_yun_info}
请分析婚姻运势，按以下结构输出：
总体结论：（一句话概括你的婚姻运势）

一、婚姻早晚
- 结婚年龄：（大概什么年龄结婚合适，说明理由）
- 早婚或晚婚：（属于早婚还是晚婚类型，说明理由）

二、配偶特征
- 性格：（配偶大概是什么性格，说明理由）
- 外貌：（配偶可能的外貌特征，说明理由）
- 职业：（配偶可能从事什么职业或行业，说明理由）
- 方位：（配偶可能来自什么方位，说明理由）

三、婚姻质量
- 感情状态：（婚后感情整体如何，说明理由）
- 相处模式：（你们适合什么样的相处方式，说明理由）
- 需要注意：（婚姻中需要注意什么问题，说明理由）

四、婚姻时机
- 有利年份：（哪些年份适合结婚或感情发展顺利，说明理由）
- 不利年份：（哪些年份感情容易出问题需要留意，说明理由）

总结：XX

AI生成仅供参考""",

        'parents': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
{da_yun_info}
请分析父母运势，按以下结构输出：
总体结论：（一句话概括你与父母的关系和父母整体情况）

一、父亲情况
    - 关系：（你与父亲的关系如何，说明理由）
    - 性格：（父亲的性格特征，说明理由）
    - 健康状况：（父亲的身体状况如何，说明理由）
    - 事业财运：（父亲的事业财运情况，说明理由）

二、母亲情况
    - 关系：（你与母亲的关系如何，说明理由）
    - 性格：（母亲的性格特征，说明理由）
    - 健康状况：（母亲的身体状况如何，说明理由）
    - 事业财运：（母亲的事业财运情况，说明理由）

三、父母关系
    - 关系：（父母之间关系如何，说明理由）
    - 家庭氛围：（整体家庭氛围如何，说明理由）

四、对个人的影响
    - 正面影响：（父母对你产生了哪些积极影响，说明理由）
    - 注意事项：（需要注意或规避哪些方面，说明理由）

总结
XX

AI生成仅供参考""",

        'children': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
{style_control}
{rules_section}
{da_yun_info}
请分析子女运势，按以下结构输出：
总体结论：（一句话概括你的子女运势）

一、子女概况
    - 子女缘分：（子女缘分深还是浅，说明理由）
    - 性格：（子女的性格特征，说明理由）
    - 天赋：（子女可能有什么天赋特长，说明理由）
    - 健康状况：（子女的身体状况如何，说明理由）

二、子女发展
    - 学业：（子女学业运势如何，说明理由）
    - 事业：（子女未来事业发展如何，说明理由）
    - 与父母关系：（子女与你的关系如何，说明理由）

三、教育建议
    - 教育方式：（适合什么样的教育方式，说明理由）
    - 需要注意：（教育中需要注意什么，说明理由）

总结
XX

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

@app.options("/feedback")
def options_feedback():
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
