# -*- coding: utf-8 -*-
"""
AI命理助手 - API 服务
适配 Railway 部署
"""
import os
import re
import math
import sqlite3
import base64
from datetime import datetime
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from openai import OpenAI
from lunar_python import Solar, Lunar

# ================== 请求模型 ==================
class BaziRequest(BaseModel):
    birth: str
    module: str = "overview"

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
    image: Optional[str] = ""

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
        return "，未提供时辰"
    return ""

# ================== 大运计算 ==================
def get_da_yun(bazi, gender, birth_year, birth_month, birth_day, birth_hour):
    solar = Solar.fromYmdHms(birth_year, birth_month, birth_day, birth_hour, 0, 0)
    lunar = solar.getLunar()
    
    month_gan = bazi['月柱'][0]
    month_zhi = bazi['月柱'][1]
    year_gan = bazi['年柱'][0]
    
    yang_years = ['甲', '丙', '戊', '庚', '壬']
    is_yang = year_gan in yang_years
    
    if (is_yang and gender == 1) or (not is_yang and gender == 0):
        direction = 1
    else:
        direction = -1
    
    start_age = None
    try:
        start_age = lunar.getStartAge()
    except:
        pass
    
    if start_age is None or start_age <= 0:
        try:
            month_zhi_to_jieqi = {
                '寅': '立春', '卯': '惊蛰', '辰': '清明', '巳': '立夏',
                '午': '芒种', '未': '小暑', '申': '立秋', '酉': '白露',
                '戌': '寒露', '亥': '立冬', '子': '大雪', '丑': '小寒'
            }
            target_jieqi = month_zhi_to_jieqi.get(month_zhi)
            if target_jieqi:
                jie_qi_table = lunar.getJieQiTable()
                target_date = None
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
                    diff_days = abs((target_dt - birth_dt).days)
                    start_age = max(1, math.ceil(diff_days / 3))
        except:
            pass
    
    if start_age is None or start_age <= 0:
        start_age = 3
    
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
    
    current_year = datetime.now().year
    current_age = current_year - birth_year
    
    da_yun_list = []
    current_da_yun = None
    next_da_yun = None
    
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
        
        if age_start <= current_age <= age_end:
            current_da_yun = da_yun
            if i + 1 < len(da_yun_list):
                next_da_yun = da_yun_list[i + 1]
    
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
    if not da_yun_data:
        return ""
    result = f"\n起运年龄：{da_yun_data.get('start_age', 3)}岁，{da_yun_data.get('direction', '')}\n"
    if da_yun_data.get('current'):
        current = da_yun_data['current']
        result += f"当前大运：{current['干支']}（{current['年龄范围']}）\n"
    if da_yun_data.get('next'):
        next_dy = da_yun_data['next']
        result += f"下一步大运：{next_dy['干支']}（{next_dy['年龄范围']}）\n"
    return result

# ================== 极简提示词（带思考模式控制） ==================
def get_prompt(bazi_str, gender, has_hour, module, year, liunian, da_yun_data=None):
    hour_warning = get_hour_warning(has_hour)
    da_yun_info = format_da_yun_info(da_yun_data) if da_yun_data else ""
    
    # 极简提示词
    if module == 'overview':
        prompt = f"八字{bazi_str}，性别{gender}{hour_warning}。{da_yun_info}请综合分析：日主强弱、五行喜忌、格局、事业、感情、健康。每项一句话，总共不超过200字。"
    elif module == 'career':
        prompt = f"八字{bazi_str}，性别{gender}{hour_warning}。{da_yun_info}请分析事业：适合行业、发展建议。总共不超过150字。"
    elif module == 'wealth':
        prompt = f"八字{bazi_str}，性别{gender}{hour_warning}。{da_yun_info}请分析财运：求财方式、守财建议。总共不超过150字。"
    elif module == 'marriage':
        prompt = f"八字{bazi_str}，性别{gender}{hour_warning}。{da_yun_info}请分析婚姻：配偶特征、相处建议。总共不超过150字。"
    elif module == 'parents':
        prompt = f"八字{bazi_str}，性别{gender}{hour_warning}。{da_yun_info}请分析父母情况。总共不超过150字。"
    elif module == 'children':
        prompt = f"八字{bazi_str}，性别{gender}{hour_warning}。{da_yun_info}请分析子女运势。总共不超过150字。"
    elif module == 'liunian':
        prompt = f"八字{bazi_str}，性别{gender}{hour_warning}。{da_yun_info}当前{year}年({liunian})。请分析三年流年运势，每点一句话。总共不超过200字。"
    elif module == 'verify':
        prompt = f"八字{bazi_str}，性别{gender}{hour_warning}。请验证：环境方位、六亲、过去经历、性格。每项不超过30字。"
    else:
        prompt = f"八字{bazi_str}，性别{gender}{hour_warning}。请简要分析，总共不超过200字。"
    
    return prompt

# ================== 反馈数据库 ==================
def init_feedback_db():
    conn = sqlite3.connect('feedback.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='feedback'")
    table_exists = cursor.fetchone()
    
    if not table_exists:
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
        print("✅ 反馈数据库创建完成")
    else:
        cursor.execute("PRAGMA table_info(feedback)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'image' not in columns:
            cursor.execute('ALTER TABLE feedback ADD COLUMN image TEXT')
            print("✅ 已添加 image 字段")
        else:
            print("✅ 反馈数据库已就绪")
    
    conn.commit()
    conn.close()

# ================== API 服务 ==================
app = FastAPI(title="AI命理助手API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not API_KEY:
    print("⚠️ 警告: DEEPSEEK_API_KEY 环境变量未设置")

init_feedback_db()

def call_ai(prompt):
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return "❌ API Key 未配置"
    
    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=30)
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}}  # 关闭思考模式，加快响应
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

def analyze_handler(birth: str, module: str):
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
    return analyze_handler(request.birth, request.module)

@app.get("/analyze")
def analyze_get(birth: str = "", module: str = "overview"):
    if not birth or not birth.strip():
        return {"status": "ok", "message": "health check"}
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
        
        da_yun_data = get_da_yun(bazi, gender, year, month, day, hour)
        prompt = get_prompt(bazi_str, bazi['性别'], has_hour, 'verify', 0, '', da_yun_data)
        content = call_ai(prompt)
        
        return {"success": True, "data": {"bazi": bazi_str, "verify": content}}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/verify_adjust")
def verify_adjust(request: VerifyAdjustRequest):
    try:
        parsed = parse_birth_and_gender(request.birth)
        if not parsed:
            return {"success": False, "error": "无法解析生辰"}
        
        year, month, day, hour, gender, has_hour = parsed
        bazi = get_bazi(year, month, day, hour, gender)
        bazi_str = f"{bazi['年柱']} {bazi['月柱']} {bazi['日柱']} {bazi['时柱']}"
        
        adjusted_items = []
        for fb in request.feedback_items:
            prompt = f"八字{bazi_str}，性别{bazi['性别']}。重新生成【{fb.section}】：原内容{fb.content}，用户反馈{fb.feedback}。请重新生成，不超过50字。"
            new_content = call_ai(prompt)
            adjusted_items.append({
                "section": fb.section,
                "original_content": fb.content,
                "new_content": new_content.strip()
            })
        
        return {"success": True, "data": {"adjusted_items": adjusted_items}}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/feedback")
def submit_feedback(request: FeedbackRequest):
    try:
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
        return {"success": True, "message": "感谢您的反馈！"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/feedback_list")
def get_feedback_list(password: str = ""):
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

@app.get("/feedback_image/{feedback_id}")
def get_feedback_image(feedback_id: int, password: str = ""):
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
        
        if image_data.startswith('data:image'):
            img_type = image_data.split(';')[0].split('/')[1]
            base64_str = image_data.split(',')[1]
            try:
                image_bytes = base64.b64decode(base64_str)
                return Response(content=image_bytes, media_type=f"image/{img_type}")
            except:
                try:
                    image_bytes = base64.b64decode(image_data)
                    return Response(content=image_bytes, media_type="image/png")
                except:
                    return {"success": False, "error": "图片格式错误"}
        else:
            try:
                image_bytes = base64.b64decode(image_data)
                return Response(content=image_bytes, media_type="image/png")
            except:
                return {"success": False, "error": "图片格式不支持"}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"启动服务，端口: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
