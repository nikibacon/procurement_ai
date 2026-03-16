import os
import json
import time
import re
import base64
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI

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
FILE_BASE_URL = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"
INVENTORY_FILE = Path("inventory.json")
TMP_DIR = Path("tmp_images")
TMP_DIR.mkdir(exist_ok=True)


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

            lines.append(f"- {item_name}：{format_number(qty)}{unit}（低庫存門檻：{format_number(threshold)}{unit}）")

            subareas = item_data.get("子區域", {})
            for subarea_name, subarea_qty in subareas.items():
                lines.append(f"  - {subarea_name}：{format_number(subarea_qty)}{unit}")

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


def ask_vision_with_image(image_path):
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一個家庭庫存辨識助理。"
                    "請根據照片判斷最可能的物品類型。"
                    "請用繁體中文回答。"
                    "如果不確定，要明確說不確定。"
                    "回答格式固定為：\n"
                    "辨識結果：xxx\n"
                    "信心：高/中/低\n"
                    "建議品項名稱：xxx\n"
                    "建議操作：新增 地點 品項 數量"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "請辨識這張照片中的家庭用品。"
                            "可能的例子有：尿布、濕紙巾、奶粉、白米、濕紙巾隨身包。"
                            "若看到的是箱裝或多包裝，也請說明。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        },
                    },
                ],
            },
        ],
    )

    return response.choices[0].message.content


def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
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
    qty_text = qty_text.strip()
    mapping = {
        "半": 0.5,
        "半包": 0.5,
        "半片": 0.5,
        "半罐": 0.5,
        "半箱": 0.5,
    }
    if qty_text in mapping:
        return mapping[qty_text]

    qty_text = qty_text.replace("半包", "0.5").replace("半片", "0.5").replace("半罐", "0.5").replace("半箱", "0.5")
    qty_text = qty_text.replace("半", "0.5")

    try:
        return float(qty_text)
    except ValueError:
        return None


def format_number(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def normalize_location(location):
    mapping = {
        "大順": "大順家",
        "大順家": "大順家",
        "南屏": "南屏家",
        "南屏家": "南屏家",
        "外出": "外出用品",
        "外出用品": "外出用品",
    }
    return mapping.get(location, location)


def normalize_action(action):
    if action in ["新增", "增加", "補充", "買了", "買進"]:
        return "新增"
    if action in ["使用", "用了", "用掉", "消耗"]:
        return "使用"
    return action


def ensure_location_and_item(inventory, location, item):
    if location not in inventory:
        inventory[location] = {}

    if item not in inventory[location]:
        inventory[location][item] = {
            "數量": 0,
            "低庫存門檻": 1,
            "單位": "個"
        }


def update_inventory(inventory, action, location, item, qty):
    ensure_location_and_item(inventory, location, item)

    current_qty = inventory[location][item].get("數量", 0)
    unit = inventory[location][item].get("單位", "個")

    if action == "新增":
        inventory[location][item]["數量"] = current_qty + qty
        save_inventory(inventory)
        return (
            True,
            f"已新增 {location} 的 {item} {format_number(qty)}{unit}\n"
            f"目前數量：{format_number(inventory[location][item]['數量'])}{unit}"
        )

    if action == "使用":
        if qty > current_qty:
            return (
                False,
                f"{location} 的 {item} 庫存不足\n目前只有：{format_number(current_qty)}{unit}"
            )

        inventory[location][item]["數量"] = current_qty - qty
        save_inventory(inventory)
        return (
            True,
            f"已使用 {location} 的 {item} {format_number(qty)}{unit}\n"
            f"剩餘數量：{format_number(inventory[location][item]['數量'])}{unit}"
        )

    return False, "不支援的操作。"


def parse_natural_inventory_command(text):
    text = text.strip().replace("　", "").replace(" ", "")

    patterns = [
        r"^(新增|增加|補充|使用|用了|用掉|消耗)(大順家|大順|南屏家|南屏|外出用品|外出)(.+?)([0-9]+(?:\.[0-9]+)?|半)(包|片|罐|個|箱)?$",
        r"^(大順家|大順|南屏家|南屏|外出用品|外出)(新增|增加|補充|使用|用了|用掉|消耗)(.+?)([0-9]+(?:\.[0-9]+)?|半)(包|片|罐|個|箱)?$",
        r"^(大順家|大順|南屏家|南屏|外出用品|外出)(.+?)(新增|增加|補充|使用|用了|用掉|消耗)([0-9]+(?:\.[0-9]+)?|半)(包|片|罐|個|箱)?$",
    ]

    for idx, pattern in enumerate(patterns):
        m = re.match(pattern, text)
        if not m:
            continue

        groups = m.groups()

        if idx == 0:
            action, location, item, qty_text, _unit = groups
        elif idx == 1:
            location, action, item, qty_text, _unit = groups
        else:
            location, item, action, qty_text, _unit = groups

        location = normalize_location(location)
        action = normalize_action(action)
        qty = parse_qty(qty_text)

        if qty is None:
            return None

        return {
            "action": action,
            "location": location,
            "item": item,
            "qty": qty,
        }

    return None


def get_file_path(file_id):
    url = f"{BASE_URL}/getFile"
    response = requests.get(url, params={"file_id": file_id}, timeout=30)
    response.raise_for_status()
    data = response.json()

    if not data.get("ok"):
        raise ValueError("無法取得 Telegram 檔案資訊")

    return data["result"]["file_path"]


def download_telegram_file(file_path, local_path):
    file_url = f"{FILE_BASE_URL}/{file_path}"
    response = requests.get(file_url, timeout=60)
    response.raise_for_status()

    with open(local_path, "wb") as f:
        f.write(response.content)


def handle_photo_message(chat_id, photo_list):
    if not photo_list:
        send_message(chat_id, "沒有收到照片資料。")
        return

    largest_photo = photo_list[-1]
    file_id = largest_photo["file_id"]

    try:
        file_path = get_file_path(file_id)
        local_path = TMP_DIR / f"{file_id}.jpg"
        download_telegram_file(file_path, local_path)

        result = ask_vision_with_image(local_path)

        reply = (
            "我看了這張照片，先幫你做初步辨識：\n\n"
            f"{result}\n\n"
            "如果辨識正確，你可以直接回覆像這樣：\n"
            "新增 大順家 尿布 1\n"
            "新增 南屏家 濕紙巾 2\n"
            "新增 外出用品 濕紙巾隨身包 3"
        )
        send_message(chat_id, reply)

    except Exception as e:
        send_message(chat_id, f"照片辨識失敗：{e}")


def handle_text_message(chat_id, text):
    inventory = load_inventory()
    normalized_text = text.strip()

    if normalized_text == "/start":
        reply = (
            "家庭採購與生活助理已啟動。\n\n"
            "目前支援：\n"
            "查看庫存\n"
            "購買建議\n"
            "今日提醒\n"
            "本週重點\n\n"
            "自然語言更新範例：\n"
            "大順新增1包尿布\n"
            "南屏用了半包尿布\n"
            "外出用品新增2包濕紙巾隨身包\n\n"
            "也可以直接傳照片，我會先幫你辨識品項。"
        )
        send_message(chat_id, reply)
        return

    if normalized_text == "查看庫存":
        send_message(chat_id, inventory_text(inventory))
        return

    parsed = parse_natural_inventory_command(normalized_text)
    if parsed:
        success, message = update_inventory(
            inventory,
            parsed["action"],
            parsed["location"],
            parsed["item"],
            parsed["qty"],
        )
        send_message(chat_id, message)
        return

    if normalized_text == "購買建議":
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

    if normalized_text == "今日提醒":
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

    if normalized_text == "本週重點":
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
        "我目前支援：\n"
        "- 查看庫存\n"
        "- 購買建議\n"
        "- 今日提醒\n"
        "- 本週重點\n\n"
        "自然語言更新範例：\n"
        "- 大順新增1包尿布\n"
        "- 南屏用了半包尿布\n"
        "- 外出用品新增2包濕紙巾隨身包\n\n"
        "也可以直接傳照片給我辨識。"
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

                if "photo" in message:
                    print("收到照片訊息")
                    handle_photo_message(chat_id, message["photo"])
                    continue

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