import os
import json
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI

# 本機可讀 .env；Railway 主要讀環境變數
load_dotenv()

debug_keys = [k for k in os.environ.keys() if "TELEGRAM" in k or "OPENAI" in k]
print("DEBUG ENV KEYS:", debug_keys)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

print("DEBUG TELEGRAM_TOKEN exists:", bool(TELEGRAM_TOKEN))
print("DEBUG OPENAI_API_KEY exists:", bool(OPENAI_API_KEY))

if not TELEGRAM_TOKEN:
    raise ValueError("找不到 TELEGRAM_TOKEN，請確認 Railway Variables 或 .env 有設定。")

if not OPENAI_API_KEY:
    raise ValueError("找不到 OPENAI_API_KEY，請確認 Railway Variables 或 .env 有設定。")

client = OpenAI(api_key=OPENAI_API_KEY)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
INVENTORY_FILE = Path("inventory.json")


def load_inventory():
    if not INVENTORY_FILE.exists():
        return {}
    with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_inventory(inventory):
    with open(INVENTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2, ensure_ascii=False)


def inventory_text(inventory):
    if not inventory:
        return "目前沒有庫存資料。"

    lines = ["目前庫存："]

    for location, items in inventory.items():
        lines.append(f"\n【{location}】")

        for item_name, item_data in items.items():
            qty = item_data.get("數量", 0)
            unit = item_data.get("單位", "個")
            threshold = item_data.get("低庫存門檻", 0)

            lines.append(f"- {item_name}：{qty}{unit}（低庫存門檻：{threshold}{unit}）")

            subareas = item_data.get("子區域", {})
            for subarea_name, subarea_qty in subareas.items():
                lines.append(f"  - {subarea_name}：{subarea_qty}{unit}")

    return "\n".join(lines)


def ask_ai(system_prompt, user_prompt):
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content


def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()


def get_updates(offset=None):
    url = f"{BASE_URL}/getUpdates"
    params = {"timeout": 20}
    if offset is not None:
        params["offset"] = offset

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_qty(qty_text):
    try:
        return float(qty_text)
    except ValueError:
        return None


def format_number(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def ensure_location_and_item(inventory, location, item):
    if location not in inventory:
        inventory[location] = {}

    if item not in inventory[location]:
        inventory[location][item] = {
            "數量": 0,
            "低庫存門檻": 1,
            "單位": "個"
        }


def handle_inventory_update(text, inventory):
    parts = text.split()

    if len(parts) < 4:
        return False, "格式錯誤，請用：\n新增 大順家 尿布 1\n使用 南屏家 尿布 0.5"

    action = parts[0]
    location = parts[1]
    qty_text = parts[-1]
    item = " ".join(parts[2:-1])

    qty = parse_qty(qty_text)
    if qty is None:
        return False, "數量格式錯誤，請輸入數字，例如 1 或 0.5"

    if qty <= 0:
        return False, "數量必須大於 0"

    ensure_location_and_item(inventory, location, item)

    current_qty = inventory[location][item].get("數量", 0)
    unit = inventory[location][item].get("單位", "個")

    if action == "新增":
        inventory[location][item]["數量"] = current_qty + qty
        save_inventory(inventory)
        return True, (
            f"已新增 {location} 的 {item} {format_number(qty)}{unit}\n"
            f"目前數量：{format_number(inventory[location][item]['數量'])}{unit}"
        )

    if action == "使用":
        if qty > current_qty:
            return False, (
                f"{location} 的 {item} 庫存不足\n"
                f"目前只有：{format_number(current_qty)}{unit}"
            )

        inventory[location][item]["數量"] = current_qty - qty
        save_inventory(inventory)
        return True, (
            f"已使用 {location} 的 {item} {format_number(qty)}{unit}\n"
            f"剩餘數量：{format_number(inventory[location][item]['數量'])}{unit}"
        )

    return False, "不支援的操作。"


def handle_text_message(chat_id, text):
    inventory = load_inventory()

    if text == "/start":
        reply = (
            "家庭採購與生活助理已啟動。\n\n"
            "目前支援指令：\n"
            "查看庫存\n"
            "購買建議\n"
            "今日提醒\n"
            "本週重點\n\n"
            "庫存操作：\n"
            "新增 大順家 尿布 1\n"
            "使用 南屏家 尿布 0.5\n"
            "新增 外出用品 濕紙巾隨身包 2"
        )
        send_message(chat_id, reply)
        return

    if text == "查看庫存":
        send_message(chat_id, inventory_text(inventory))
        return

    if text.startswith("新增 ") or text.startswith("使用 "):
        success, message = handle_inventory_update(text, inventory)
        send_message(chat_id, message)
        return

    if text == "購買建議":
        summary = inventory_text(inventory)

        system_prompt = f"""
你是一個家庭採購助理。

目前家庭庫存如下：
{summary}

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
        result = ask_ai(system_prompt, "請根據目前庫存給我購買建議。")
        send_message(chat_id, result)
        return

    if text == "今日提醒":
        summary = inventory_text(inventory)

        system_prompt = f"""
你是一個家庭生活助理。

目前家庭庫存如下：
{summary}

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
        result = ask_ai(system_prompt, "請給我今天的家庭提醒。")
        send_message(chat_id, result)
        return

    if text == "本週重點":
        summary = inventory_text(inventory)

        system_prompt = f"""
你是一個家庭生活與採購助理。

目前家庭庫存如下：
{summary}

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
        result = ask_ai(system_prompt, "請整理本週家庭重點。")
        send_message(chat_id, result)
        return

    send_message(
        chat_id,
        "目前支援的指令有：\n"
        "- 查看庫存\n"
        "- 購買建議\n"
        "- 今日提醒\n"
        "- 本週重點\n\n"
        "庫存操作：\n"
        "- 新增 大順家 尿布 1\n"
        "- 使用 南屏家 尿布 0.5\n"
        "- 新增 外出用品 濕紙巾隨身包 2"
    )


def main():
    print("Telegram Bot 啟動中（requests 版）...")

    offset = None

    while True:
        try:
            data = get_updates(offset=offset)

            if not data.get("ok"):
                print("Telegram API 回傳失敗：", data)
                time.sleep(3)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                message = update.get("message")
                if not message:
                    continue

                chat_id = message["chat"]["id"]
                text = message.get("text", "").strip()

                if not text:
                    continue

                print("收到訊息：", text)
                handle_text_message(chat_id, text)

        except requests.exceptions.RequestException as e:
            print("網路錯誤：", e)
            time.sleep(5)
        except Exception as e:
            print("程式錯誤：", e)
            time.sleep(5)


if __name__ == "__main__":
    main()