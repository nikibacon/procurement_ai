# Telegram Bot 重構計畫

## 目標
將 `telegram_bot.py` 拆分成四個模組，保持既有功能不變，所有使用者輸出維持繁體中文。

## 重構後的檔案結構

```
procurement_ai/
├── telegram_bot.py          # 主程式 (Telegram Bot 邏輯)
├── inventory_service.py     # 庫存服務
├── ai_service.py           # AI 對話服務
├── vision_service.py       # 視覺辨識服務
└── inventory.json          # 庫存資料
```

---

## 一、inventory_service.py (庫存服務)

### 職責
負責所有與庫存資料操作相關的邏輯。

### 包含的函數

#### 1. 資料存取
- `load_inventory()` - 從 JSON 檔案載入庫存資料
- `save_inventory(inventory)` - 儲存庫存資料到 JSON 檔案

#### 2. 資料格式化
- `inventory_text(inventory)` - 將庫存資料格式化成繁體中文文字
- `format_number(value)` - 格式化數字顯示（整數不顯示小數點）

#### 3. 庫存更新
- `update_inventory(inventory, action, location, item, qty)` - 更新庫存數量
- `ensure_location_and_item(inventory, location, item)` - 確保地點和品項存在

#### 4. 自然語言解析
- `parse_natural_inventory_command(text)` - 解析自然語言庫存命令
- `normalize_location(location)` - 標準化地點名稱
- `normalize_action(action)` - 標準化動作名稱
- `parse_qty(qty_text)` - 解析數量（支援「半」、「0.5」等）

### 常數
```python
INVENTORY_FILE = Path("inventory.json")
```

### 對外介面
```python
# 載入和儲存
inventory = load_inventory()
save_inventory(inventory)

# 格式化顯示
text = inventory_text(inventory)

# 更新庫存
success, message = update_inventory(inventory, "新增", "大順家", "尿布", 1)

# 解析命令
parsed = parse_natural_inventory_command("大順新增1包尿布")
# 返回: {"action": "新增", "location": "大順家", "item": "尿布", "qty": 1}
```

---

## 二、ai_service.py (AI 對話服務)

### 職責
負責所有與 OpenAI 文字 API 相關的邏輯。

### 包含的函數

#### 1. 基礎 AI 對話
- `ask_ai(system_prompt, user_prompt)` - 基礎 OpenAI 對話函數

#### 2. 特定情境 AI 服務
- `get_purchase_suggestion(inventory_summary)` - 取得購買建議
- `get_daily_reminder(inventory_summary)` - 取得今日提醒
- `get_weekly_summary(inventory_summary)` - 取得本週重點

### 初始化
```python
from openai import OpenAI
import os

client = None

def initialize_client(api_key=None):
    """初始化 OpenAI client"""
    global client
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)
```

### 對外介面
```python
# 初始化
initialize_client()

# 購買建議
suggestion = get_purchase_suggestion(inventory_summary)

# 今日提醒
reminder = get_daily_reminder(inventory_summary)

# 本週重點
summary = get_weekly_summary(inventory_summary)
```

### 設計細節

**`get_purchase_suggestion(inventory_summary)`**
- 輸入：庫存摘要文字
- 輸出：購買建議（繁體中文）
- 包含完整的 system prompt（考慮大順家、南屏家、外出用品）

**`get_daily_reminder(inventory_summary)`**
- 輸入：庫存摘要文字
- 輸出：今日提醒（繁體中文，3-5點）
- 包含家庭背景（有快一歲的寶寶）

**`get_weekly_summary(inventory_summary)`**
- 輸入：庫存摘要文字
- 輸出：本週重點（繁體中文）
- 包含本週優先處理、建議補貨、生活安排提醒

---

## 三、vision_service.py (視覺辨識服務)

### 職責
負責所有與圖像辨識和 Telegram 檔案處理相關的邏輯。

### 包含的函數

#### 1. 視覺辨識
- `ask_vision_with_image(image_path)` - 使用 OpenAI Vision API 辨識照片

#### 2. Telegram 檔案處理
- `get_file_path(telegram_token, file_id)` - 取得 Telegram 檔案路徑
- `download_telegram_file(telegram_token, file_path, local_path)` - 下載 Telegram 檔案

### 常數
```python
TMP_DIR = Path("tmp_images")
TMP_DIR.mkdir(exist_ok=True)
```

### 初始化
```python
from openai import OpenAI
import os

client = None

def initialize_client(api_key=None):
    """初始化 OpenAI client"""
    global client
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)
```

### 對外介面
```python
# 初始化
initialize_client()

# 取得檔案並下載
file_path = get_file_path(telegram_token, file_id)
local_path = TMP_DIR / f"{file_id}.jpg"
download_telegram_file(telegram_token, file_path, local_path)

# 辨識圖片
result = ask_vision_with_image(local_path)
```

### 設計細節

**`ask_vision_with_image(image_path)`**
- 讀取圖片並轉換為 base64
- 使用固定的 system prompt（家庭庫存辨識助理）
- 返回辨識結果（繁體中文）
- 格式：辨識結果 / 信心 / 建議品項名稱 / 建議操作

**`get_file_path(telegram_token, file_id)`**
- 呼叫 Telegram API 取得檔案路徑
- 返回 file_path 字串

**`download_telegram_file(telegram_token, file_path, local_path)`**
- 從 Telegram 下載檔案到本地

---

## 四、telegram_bot.py (主程式)

### 職責
作為調度者，處理 Telegram Bot 的主要邏輯。

### 保留的函數

#### 1. Telegram API 操作
- `send_message(chat_id, text)` - 傳送訊息
- `get_updates(offset=None)` - 取得更新

#### 2. 訊息處理
- `handle_photo_message(chat_id, photo_list)` - 處理照片訊息
- `handle_text_message(chat_id, text)` - 處理文字訊息

#### 3. 主程式
- `main()` - 主迴圈

### 環境變數和初始化
```python
import os
from dotenv import load_dotenv
from pathlib import Path

# 載入環境變數
load_dotenv()

# 取得 tokens
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 驗證
if not TELEGRAM_TOKEN:
    raise ValueError("找不到 TELEGRAM_TOKEN，請確認 Railway Variables 或 .env 有設定。")
if not OPENAI_API_KEY:
    raise ValueError("找不到 OPENAI_API_KEY，請確認 Railway Variables 或 .env 有設定。")

# 初始化服務
import ai_service
import vision_service

ai_service.initialize_client(OPENAI_API_KEY)
vision_service.initialize_client(OPENAI_API_KEY)

# Telegram API URLs
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
```

### 重構後的 handle_text_message() 流程
```python
def handle_text_message(chat_id, text):
    from inventory_service import (
        load_inventory,
        inventory_text,
        parse_natural_inventory_command,
        update_inventory,
    )
    from ai_service import (
        get_purchase_suggestion,
        get_daily_reminder,
        get_weekly_summary,
    )
    
    inventory = load_inventory()
    normalized_text = text.strip()

    if normalized_text == "/start":
        # ... 啟動訊息 ...
        return

    if normalized_text == "查看庫存":
        send_message(chat_id, inventory_text(inventory))
        return

    # 嘗試解析自然語言庫存命令
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
        result = get_purchase_suggestion(summary)
        send_message(chat_id, result)
        return

    if normalized_text == "今日提醒":
        summary = inventory_text(inventory)
        result = get_daily_reminder(summary)
        send_message(chat_id, result)
        return

    if normalized_text == "本週重點":
        summary = inventory_text(inventory)
        result = get_weekly_summary(summary)
        send_message(chat_id, result)
        return

    # 預設回覆
    send_message(chat_id, "我目前支援：\n...")
```

### 重構後的 handle_photo_message() 流程
```python
def handle_photo_message(chat_id, photo_list):
    from vision_service import (
        get_file_path,
        download_telegram_file,
        ask_vision_with_image,
        TMP_DIR,
    )
    
    if not photo_list:
        send_message(chat_id, "沒有收到照片資料。")
        return

    largest_photo = photo_list[-1]
    file_id = largest_photo["file_id"]

    try:
        file_path = get_file_path(TELEGRAM_TOKEN, file_id)
        local_path = TMP_DIR / f"{file_id}.jpg"
        download_telegram_file(TELEGRAM_TOKEN, file_path, local_path)

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
```

---

## 五、依賴關係圖

```
telegram_bot.py (主程式)
    ├─> inventory_service.py (庫存服務)
    ├─> ai_service.py (AI 對話服務)
    │       └─> (可能使用 inventory_service.inventory_text)
    └─> vision_service.py (視覺辨識服務)
```

---

## 六、重構步驟

### Step 1: 建立 inventory_service.py
1. 複製所有庫存相關函數
2. 加入必要的 imports (json, Path, re)
3. 定義 INVENTORY_FILE 常數
4. 測試基本功能（載入、儲存、解析）

### Step 2: 建立 ai_service.py
1. 建立 OpenAI client 初始化函數
2. 移動 ask_ai() 基礎函數
3. 將「購買建議」、「今日提醒」、「本週重點」重構為三個獨立函數
4. 每個函數包含完整的 system prompt
5. 測試 AI 回應功能

### Step 3: 建立 vision_service.py
1. 建立 OpenAI client 初始化函數
2. 移動 ask_vision_with_image() 函數
3. 移動 get_file_path() 和 download_telegram_file() 函數
4. 修改函數簽名，接受 telegram_token 參數
5. 定義 TMP_DIR 常數並建立目錄
6. 測試圖像辨識和檔案下載功能

### Step 4: 重構 telegram_bot.py
1. 移除已移到其他模組的函數
2. 加入對三個服務模組的 import
3. 在初始化階段呼叫 ai_service 和 vision_service 的 initialize_client()
4. 修改 handle_text_message() 使用服務模組的函數
5. 修改 handle_photo_message() 使用服務模組的函數
6. 保留主迴圈和 Telegram API 操作函數

### Step 5: 測試
1. 測試「查看庫存」功能
2. 測試自然語言更新功能（新增、使用）
3. 測試「購買建議」功能
4. 測試「今日提醒」功能
5. 測試「本週重點」功能
6. 測試照片辨識功能
7. 確認所有輸出維持繁體中文

---

## 七、注意事項

### 1. 保持功能不變
- 所有現有功能必須維持原樣
- 所有使用者訊息維持繁體中文
- 不改變任何邏輯或輸出格式

### 2. 錯誤處理
- 保持原有的錯誤處理機制
- 在服務模組中適當處理異常

### 3. 環境變數
- 環境變數載入保留在主程式
- API keys 透過初始化函數傳遞給服務模組

### 4. 檔案路徑
- INVENTORY_FILE 定義在 inventory_service.py
- TMP_DIR 定義在 vision_service.py
- 使用相對路徑確保在不同環境可運作

### 5. OpenAI Client
- ai_service 和 vision_service 各自維護自己的 client
- 透過 initialize_client() 函數初始化

### 6. 程式碼風格
- 保持原有的程式碼風格
- 函數命名維持簡潔明確
- 註解使用繁體中文

---

## 八、預期效益

### 1. 可維護性提升
- 職責清楚分離
- 容易定位和修改特定功能

### 2. 可測試性提升
- 各服務模組可獨立測試
- 容易撰寫單元測試

### 3. 可擴展性提升
- 新增功能時只需修改特定模組
- 容易添加新的 AI 服務或庫存操作

### 4. 可讀性提升
- 主程式邏輯更清晰
- 每個模組專注於特定領域

---

## 九、未來可能的擴展

### 1. inventory_service.py
- 支援更多庫存操作（移動、轉移）
- 支援庫存歷史紀錄
- 支援多種資料來源（Database, CSV）

### 2. ai_service.py
- 新增更多 AI 助理功能
- 支援對話歷史
- 支援個性化建議

### 3. vision_service.py
- 支援批次圖像處理
- 支援更多圖像來源
- 改進辨識準確度

### 4. telegram_bot.py
- 支援更多 Telegram 功能（inline keyboard）
- 支援多使用者管理
- 支援權限控制

---

## 十、總結

這個重構計畫的目標是將單一檔案拆分成四個職責明確的模組，同時保持所有既有功能不變。重構後的架構將更易於維護、測試和擴展，為未來的功能開發奠定良好基礎。

**重構原則：**
✅ 保持功能完全不變  
✅ 保持繁體中文輸出  
✅ 清楚的職責分離  
✅ 最小化耦合  
✅ 易於維護和擴展  
