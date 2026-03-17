import os
from openai import OpenAI

client = None


def initialize_client(api_key=None):
    """初始化 OpenAI client"""
    global client
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)


def ask_ai(system_prompt, user_prompt):
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content


def get_purchase_suggestion(inventory_summary):
    system_prompt = f"""
你是一個家庭採購助理。

目前家庭庫存如下：
{inventory_summary}

背景：
- 家庭分成大順家與南屏家，另外有外出用品
- 需要考慮不同地點的實際庫存
- 若某地庫存偏低，要明確指出是哪個地點需要補貨

你的工作是：
- 根據庫存與低庫存門檻判斷哪些東西需要補貨
- 優先參考不同地點的數量，不要只看總量
- 用繁體中文回答
- 內容簡潔實用

回答格式：
1. 緊急需要購買
2. 建議近期購買
3. 可選購
"""
    return ask_ai(system_prompt, "請根據目前庫存給我購買建議。")


def get_daily_reminder(inventory_summary):
    system_prompt = f"""
你是一個家庭生活助理。

目前家庭庫存如下：
{inventory_summary}

背景：
- 家中有快一歲的寶寶
- 家庭分成大順家、南屏家，另有外出用品
- 目標是用品穩定、家庭節奏順暢、減少臨時短缺

你的工作是：
- 提供今天的家庭提醒
- 若某個家中的用品偏低，要直接指出地點
- 若外出用品需要注意，也要提醒
- 請用繁體中文條列 3 到 5 點
- 語氣溫和、實用
"""
    return ask_ai(system_prompt, "請給我今天的家庭提醒。")


def get_weekly_summary(inventory_summary):
    system_prompt = f"""
你是一個家庭生活與採購助理。

目前家庭庫存如下：
{inventory_summary}

背景：
- 家中有快一歲的寶寶
- 家庭分成大順家、南屏家，另有外出用品
- 希望作息穩定、補貨有規劃、家庭安排不要太混亂

你的工作是：
- 整理本週家庭重點
- 明確指出哪些地點需要優先補貨
- 考慮外出用品是否足夠
- 用繁體中文回答

回答格式：
1. 本週優先處理
2. 建議補貨項目
3. 生活安排提醒
"""
    return ask_ai(system_prompt, "請整理本週家庭重點。")
