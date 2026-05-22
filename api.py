# -*- coding: utf-8 -*-
"""
AI命理助手 - API 服务
阿里云函数计算版本
"""
import re
import time
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from openai import OpenAI

from lunar_python import Solar

# ================== 配置 ==================
API_KEY = "sk-70db94f98a2d463da58e225244b0c0bb"  # 请替换为你的真实 Key


# ================== 请求/响应模型 ==================
class BaziRequest(BaseModel):
    """八字分析请求"""
    birth: str  # 用户输入的生辰，如 "2001.10.30 18时 男"
    module: str = "all"  # all, liunian, career, wealth, marriage, overview


class BaziResponse(BaseModel):
    """八字分析响应"""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


class AnalysisResponse(BaseModel):
    """分析结果响应"""
    module: str
    content: str


# ================== 基础函数（从原代码复用）==================
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
    minute = 0

    if has_hour:
        hour_match = re.search(r'(\d{1,2})[点时]', user_input)
        if hour_match:
            hour = int(hour_match.group(1))

    return (year, month, day, hour, minute, gender, has_hour)


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


def get_analysis_prompt(bazi_str, gender, has_hour, module, year, liunian):
    """根据模块生成对应的提示词"""
    hour_warning = get_hour_warning(has_hour)

    templates = {
        'overview': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
请进行八字综合分析：
一、日元强弱
二、喜用忌凶五行
三、喜用忌凶颜色
四、喜用忌凶数字
五、喜用忌凶方位
结尾注明仅供参考。""",

        'liunian': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
请分析{year}年（{liunian}年）及未来两年的流年运势，重点关注事业、财运。结尾注明仅供参考。""",

        'career': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
请分析事业运势：格局特点、适合行业、发展建议。结尾注明仅供参考。""",

        'wealth': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
请分析财运运势：财富等级、求财方式、财运时机。结尾注明仅供参考。""",

        'marriage': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
请分析婚姻运势：配偶特征、婚姻早晚、相处建议。结尾注明仅供参考。""",

        'verify': f"""八字：{bazi_str}，性别：{gender}{hour_warning}
请根据八字推断以下内容：
① 环境方位：（家里或家外的XX方向有什么特征）
② 六亲情况：（与XX亲人的关系或性格）
③ 过去经历：（XX年份发生过什么事）
④ 性格特征：（1-2个明显特点）"""
    }

    return templates.get(module, templates['overview'])


# ================== API 服务 ==================
# 创建 FastAPI 应用
app = FastAPI(title="AI命理助手API", description="八字命理分析服务", version="1.0.0")

# 允许跨域（小程序调用需要）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化 OpenAI 客户端
client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")


def call_ai(prompt):
    """调用 AI 获取分析结果"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI调用失败: {str(e)}")


@app.get("/")
def root():
    return {"message": "AI命理助手API服务运行中", "version": "1.0.0"}


@app.post("/analyze", response_model=BaziResponse)
def analyze(request: BaziRequest):
    """
    分析八字
    - birth: 出生时间 + 性别，如 "2001.10.30 18时 男"
    - module: all(全部), overview(综合分析), liunian(流年), career(事业), wealth(财运), marriage(婚姻)
    """
    try:
        # 1. 解析生辰
        parsed = parse_birth_and_gender(request.birth)
        if not parsed:
            return BaziResponse(success=False, error="无法解析生辰信息，请提供如'2001.10.30 18时 男'格式")

        year, month, day, hour, minute, gender, has_hour = parsed
        bazi_info = get_bazi(year, month, day, hour, gender)
        bazi_str = f"{bazi_info['年柱']} {bazi_info['月柱']} {bazi_info['日柱']} {bazi_info['时柱']}"
        current_year = datetime.now().year
        liunian = get_liunian_ganzhi(current_year)

        # 2. 根据模块生成分析
        results = []

        if request.module == 'all':
            modules = ['overview', 'liunian', 'career', 'wealth', 'marriage']
            for mod in modules:
                prompt = get_analysis_prompt(bazi_str, bazi_info['性别'], has_hour, mod, current_year, liunian)
                content = call_ai(prompt)
                results.append(AnalysisResponse(module=mod, content=content))
        else:
            prompt = get_analysis_prompt(bazi_str, bazi_info['性别'], has_hour, request.module, current_year, liunian)
            content = call_ai(prompt)
            results.append(AnalysisResponse(module=request.module, content=content))

        return BaziResponse(
            success=True,
            data={
                'bazi': bazi_str,
                'gender': bazi_info['性别'],
                'has_hour': has_hour,
                'analyses': [r.dict() for r in results]
            }
        )

    except HTTPException as e:
        return BaziResponse(success=False, error=e.detail)
    except Exception as e:
        return BaziResponse(success=False, error=str(e))


@app.post("/verify")
def verify(request: BaziRequest):
    """
    八字验证（返回4条推断让用户判断准确性）
    """
    try:
        parsed = parse_birth_and_gender(request.birth)
        if not parsed:
            return BaziResponse(success=False, error="无法解析生辰信息")

        year, month, day, hour, minute, gender, has_hour = parsed
        bazi_info = get_bazi(year, month, day, hour, gender)
        bazi_str = f"{bazi_info['年柱']} {bazi_info['月柱']} {bazi_info['日柱']} {bazi_info['时柱']}"

        prompt = get_analysis_prompt(bazi_str, bazi_info['性别'], has_hour, 'verify', 0, '')
        content = call_ai(prompt)

        return BaziResponse(
            success=True,
            data={
                'bazi': bazi_str,
                'gender': bazi_info['性别'],
                'verify_content': content
            }
        )

    except Exception as e:
        return BaziResponse(success=False, error=str(e))

# ================== 本地测试入口 ==================
# 注意：函数计算不需要 if __name__ == "__main__"，会直接使用上面的 app 对象