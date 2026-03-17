import os
import time
import re
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
    normalize_location,
    parse_qty,
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

# 暫存照片辨識結果，等待使用者輸入地點和數量
# 結構: {chat_id: {"item": "品項名稱", "timestamp": 時間戳記}}
pending_items = {}


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


def extract_item_name(vision_result):
    """從 vision API 回應中提取品項名稱"""
    lines = vision_result.split('\n')
    for line in lines:
        if '建議品項名稱' in line or '品項名稱' in line:
            parts = line.split('：')
            if len(parts) >= 2:
                return parts[1].strip()
    return None


def parse_location_qty(text):
    """
    解析「地點 + 數量」格式
    例如：大順家 1、南屏 0.5、外出用品 2
    返回：(location, qty) 或 (None, None)
    """
    text = text.strip().replace("　", " ")
    
    # 移除可能的單位詞
    text = re.sub(r'(包|片|罐|個|箱)$', '', text).strip()
    
    # 模式：地點 + 空格/無空格 + 數量
    patterns = [
        r'^(大順家|大順|南屏家|南屏|外出用品|外出)\s*([0-9]+(?:\.[0-9]+)?|半)$',
    ]
    
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            location_raw, qty_text = m.groups()
            location = normalize_location(location_raw)
            qty = parse_qty(qty_text)
            
            if qty is not None:
                return location, qty
    
    return None, None


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
        
        # 嘗試提取品項名稱
        item_name = extract_item_name(result)
        
        if item_name:
            # 暫存品項，等待使用者輸入地點和數量
            pending_items[chat_id] = {
                "item": item_name,
                "timestamp": time.time()
            }
            
            reply = (
                "我看了這張照片，辨識結果：\n\n"
                f"{result}\n\n"
                "━━━━━━━━━━━━━━━━\n"
                f"✅ 已記住品項：{item_name}\n\n"
                "請直接回覆「地點 + 數量」即可新增庫存：\n"
                "例如：\n"
                "• 大順家 1\n"
                "• 南屏 0.5\n"
                "• 外出用品 2\n\n"
                "或者完整輸入：新增 大順家 尿布 1"
            )
        else:
            # 無法提取品項名稱，使用原始流程
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
    
    # 檢查是否有待處理的照片辨識品項
    has_pending = chat_id in pending_items
    
    # 處理系統指令（這些指令會清除 pending 狀態）
    if normalized_text == "/start":
        if has_pending:
            del pending_items[chat_id]
        
        reply = (
            "家庭採購與生活助理已啟動。\n\n"
            "目前支援：\n"
            "查看庫存\n"
            "購買建議\n"
            "今日提醒\n"
            "本週重點\n\n"
            "自然語言更新範例：\n"
            "大順新增尿布1\n"
            "南屏用了尿布半\n"
            "外出用品新增濕紙巾隨身包2\n\n"
            "也可以直接傳照片，我會先幫你辨識品項。"
        )
        send_message(chat_id, reply)
        return

    if normalized_text == "查看庫存":
        if has_pending:
            del pending_items[chat_id]
        send_message(chat_id, inventory_text(inventory))
        return

    # 優先檢查：如果有 pending item，嘗試解析「地點 + 數量」
    if has_pending:
        location, qty = parse_location_qty(normalized_text)
        
        if location and qty:
            # 成功解析，使用 pending 的品項名稱更新庫存
            item_name = pending_items[chat_id]["item"]
            success, message = update_inventory(
                inventory,
                "新增",  # 照片辨識後預設為新增
                location,
                item_name,
                qty,
            )
            
            # 清除 pending 狀態
            del pending_items[chat_id]
            
            # 回覆結果
            send_message(chat_id, f"✅ 使用辨識品項：{item_name}\n\n{message}")
            return
        
        # 無法解析為「地點 + 數量」，但還有其他可能性
        # 1. 可能是完整的自然語言命令
        # 2. 可能是其他系統指令
        # 3. 可能是格式錯誤
        
        # 先嘗試解析為完整的自然語言命令
        parsed = parse_natural_inventory_command(normalized_text)
        if parsed:
            # 使用者輸入了完整命令，清除 pending 並執行
            del pending_items[chat_id]
            success, message = update_inventory(
                inventory,
                parsed["action"],
                parsed["location"],
                parsed["item"],
                parsed["qty"],
            )
            send_message(chat_id, message)
            return
        
        # 檢查是否為其他系統指令
        if normalized_text in ["購買建議", "今日提醒", "本週重點"]:
            # 清除 pending 並處理系統指令
            del pending_items[chat_id]
            # 繼續往下處理
        else:
            # 格式錯誤，提示正確格式（不清除 pending，讓使用者重試）
            item_name = pending_items[chat_id]["item"]
            send_message(
                chat_id,
                f"⚠️ 格式不正確\n\n"
                f"目前記住的品項：{item_name}\n\n"
                f"請輸入「地點 + 數量」，例如：\n"
                f"• 大順家 1\n"
                f"• 南屏 0.5\n"
                f"• 外出用品 2\n\n"
                f"或輸入完整命令：新增 大順家 {item_name} 1"
            )
            return
    
    # 既有的自然語言命令解析
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
        "- 大順新增尿布1\n"
        "- 南屏用了尿布半\n"
        "- 外出用品新增濕紙巾隨身包2\n\n"
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