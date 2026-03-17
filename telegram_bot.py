import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

import ai_service
import vision_service
from inventory_service import (
    load_inventory,
    inventory_text,
    parse_natural_inventory_command,
    update_inventory,
)

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

# 初始化 AI 服務
ai_service.initialize_client(OPENAI_API_KEY)
vision_service.initialize_client(OPENAI_API_KEY)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


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


def handle_photo_message(chat_id, photo_list):
    if not photo_list:
        send_message(chat_id, "沒有收到照片資料。")
        return

    largest_photo = photo_list[-1]
    file_id = largest_photo["file_id"]

    try:
        file_path = vision_service.get_file_path(TELEGRAM_TOKEN, file_id)
        local_path = vision_service.TMP_DIR / f"{file_id}.jpg"
        vision_service.download_telegram_file(TELEGRAM_TOKEN, file_path, local_path)

        result = vision_service.ask_vision_with_image(local_path)

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
        result = ai_service.get_purchase_suggestion(summary)
        send_message(chat_id, result)
        return

    if normalized_text == "今日提醒":
        summary = inventory_text(inventory)
        result = ai_service.get_daily_reminder(summary)
        send_message(chat_id, result)
        return

    if normalized_text == "本週重點":
        summary = inventory_text(inventory)
        result = ai_service.get_weekly_summary(summary)
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