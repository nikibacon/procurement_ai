# 重構測試指南

## 已完成的修改

### 新建檔案
1. **inventory_service.py** (194 行)
   - 庫存載入、儲存、格式化
   - 自然語言命令解析
   - 庫存更新邏輯
   - 地點、動作、數量正規化

2. **ai_service.py** (103 行)
   - OpenAI client 初始化
   - 基礎 AI 對話函數
   - 購買建議生成
   - 今日提醒生成
   - 本週重點生成

3. **vision_service.py** (93 行)
   - OpenAI client 初始化
   - 圖像辨識功能
   - Telegram 檔案路徑取得
   - Telegram 檔案下載

### 修改檔案
4. **telegram_bot.py** (從 511 行縮減到 202 行)
   - 移除已搬移的函數
   - 使用服務模組的函數
   - 保持所有既有功能

### 保持不變
- **inventory.json** - 庫存資料檔案
- **.env** - 環境變數檔案
- **requirements.txt** - Python 依賴
- **Procfile** - Railway 部署設定

---

## 本機測試步驟

### 1. 環境準備

確認環境變數設定正確：

```bash
cd /Users/pei-hsuan/Projects/procurement_ai
cat .env
```

應該包含：
```
TELEGRAM_TOKEN=your_telegram_token
OPENAI_API_KEY=your_openai_api_key
```

### 2. 安裝依賴（如果尚未安裝）

```bash
# 啟動虛擬環境（如果有的話）
source venv/bin/activate

# 安裝依賴
pip install -r requirements.txt
```

### 3. 語法檢查（已通過 ✅）

```bash
python3 -m py_compile inventory_service.py
python3 -m py_compile ai_service.py
python3 -m py_compile vision_service.py
python3 -m py_compile telegram_bot.py
```

### 4. 測試庫存服務

創建一個簡單的測試腳本：

```bash
cat > test_inventory.py << 'EOF'
from inventory_service import (
    load_inventory,
    inventory_text,
    parse_natural_inventory_command,
    format_number
)

# 測試 1: 載入庫存
print("=== 測試 1: 載入庫存 ===")
inventory = load_inventory()
print(f"成功載入 {len(inventory)} 個地點")

# 測試 2: 格式化庫存
print("\n=== 測試 2: 格式化庫存 ===")
text = inventory_text(inventory)
print(text)

# 測試 3: 解析自然語言命令
print("\n=== 測試 3: 解析自然語言命令 ===")
test_commands = [
    "大順新增1包尿布",
    "南屏用了半包尿布",
    "外出用品新增2包濕紙巾隨身包",
]
for cmd in test_commands:
    parsed = parse_natural_inventory_command(cmd)
    print(f"{cmd} -> {parsed}")

# 測試 4: 數字格式化
print("\n=== 測試 4: 數字格式化 ===")
print(f"1.0 -> {format_number(1.0)}")
print(f"1.5 -> {format_number(1.5)}")
print(f"2 -> {format_number(2)}")

print("\n✅ 所有庫存服務測試完成")
EOF

python3 test_inventory.py
```

### 5. 測試 AI 服務（需要 API Key）

創建 AI 服務測試腳本：

```bash
cat > test_ai.py << 'EOF'
import os
from dotenv import load_dotenv
import ai_service
from inventory_service import load_inventory, inventory_text

load_dotenv()

# 初始化
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("❌ 找不到 OPENAI_API_KEY")
    exit(1)

ai_service.initialize_client(api_key)
print("✅ AI 服務初始化成功")

# 載入庫存
inventory = load_inventory()
summary = inventory_text(inventory)

# 測試購買建議（會實際呼叫 API）
print("\n=== 測試購買建議 ===")
try:
    result = ai_service.get_purchase_suggestion(summary)
    print(result)
    print("\n✅ 購買建議測試成功")
except Exception as e:
    print(f"❌ 購買建議測試失敗: {e}")

# 如果要測試其他功能，取消下面的註解
# print("\n=== 測試今日提醒 ===")
# result = ai_service.get_daily_reminder(summary)
# print(result)

# print("\n=== 測試本週重點 ===")
# result = ai_service.get_weekly_summary(summary)
# print(result)
EOF

# 注意：這會呼叫 OpenAI API 並產生費用
# python3 test_ai.py
```

### 6. 測試視覺服務初始化

```bash
cat > test_vision.py << 'EOF'
import os
from dotenv import load_dotenv
import vision_service

load_dotenv()

# 測試初始化
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("❌ 找不到 OPENAI_API_KEY")
    exit(1)

vision_service.initialize_client(api_key)
print("✅ 視覺服務初始化成功")

# 檢查 TMP_DIR
print(f"✅ TMP_DIR 已建立: {vision_service.TMP_DIR}")
print(f"   路徑: {vision_service.TMP_DIR.absolute()}")

print("\n✅ 視覺服務測試完成")
EOF

python3 test_vision.py
```

### 7. 完整 Bot 測試

**重要：這會啟動真實的 Telegram Bot**

```bash
# 啟動 bot（按 Ctrl+C 停止）
python3 telegram_bot.py
```

啟動後，在 Telegram 中測試以下功能：

#### 測試清單

**基礎功能：**
- [ ] 傳送 `/start` - 確認收到啟動訊息
- [ ] 傳送 `查看庫存` - 確認顯示完整庫存列表

**自然語言更新：**
- [ ] 傳送 `大順新增1包尿布` - 確認新增成功
- [ ] 傳送 `南屏用了半包尿布` - 確認使用成功
- [ ] 傳送 `外出用品新增2包濕紙巾隨身包` - 確認新增成功
- [ ] 傳送 `查看庫存` - 確認數量已更新

**AI 助理功能：**
- [ ] 傳送 `購買建議` - 確認收到 AI 生成的購買建議
- [ ] 傳送 `今日提醒` - 確認收到今日提醒（3-5點）
- [ ] 傳送 `本週重點` - 確認收到本週重點

**圖像辨識功能：**
- [ ] 傳送一張產品照片 - 確認收到辨識結果
- [ ] 確認辨識結果格式正確（辨識結果/信心/建議品項名稱/建議操作）

**錯誤處理：**
- [ ] 傳送無效命令 - 確認收到使用說明
- [ ] 嘗試使用超過庫存的數量 - 確認收到庫存不足訊息

---

## 測試結果驗證

### 功能完整性檢查

所有功能應與重構前完全相同：

1. ✅ **庫存管理**
   - 載入和儲存 JSON 檔案
   - 支援多地點（大順家、南屏家、外出用品）
   - 支援子區域
   - 正確處理數量（包括 0.5、半包等）

2. ✅ **自然語言解析**
   - 支援多種命令格式
   - 正確解析地點、動作、品項、數量
   - 正規化地點和動作名稱

3. ✅ **AI 助理**
   - 購買建議考慮不同地點
   - 今日提醒包含家庭背景
   - 本週重點有明確結構

4. ✅ **圖像辨識**
   - 下載並處理 Telegram 照片
   - 使用 Vision API 辨識
   - 返回結構化結果

5. ✅ **使用者介面**
   - 所有訊息維持繁體中文
   - Prompt 內容完全不變
   - 錯誤訊息正確顯示

---

## 檔案路徑驗證

所有檔案路徑使用絕對路徑：

```bash
# 檢查 inventory_service.py
grep "BASE_DIR" inventory_service.py
# 應該看到: BASE_DIR = Path(__file__).resolve().parent

# 檢查 vision_service.py
grep "BASE_DIR" vision_service.py
# 應該看到: BASE_DIR = Path(__file__).resolve().parent
```

---

## 清理測試檔案

測試完成後，可以刪除測試腳本：

```bash
rm -f test_inventory.py test_ai.py test_vision.py
```

---

## 程式碼行數對比

**重構前：**
- telegram_bot.py: 511 行（包含所有邏輯）

**重構後：**
- telegram_bot.py: 202 行（-60%）
- inventory_service.py: 194 行（新建）
- ai_service.py: 103 行（新建）
- vision_service.py: 93 行（新建）
- **總計：592 行（+16%）**

增加的行數主要來自：
- 模組化後的函數宣告
- 每個檔案的 imports
- 更清楚的職責分離

---

## 重構效益

✅ **可維護性提升**
- 每個模組職責單一
- 容易定位和修改特定功能

✅ **可測試性提升**
- 各服務模組可獨立測試
- 容易撰寫單元測試

✅ **可讀性提升**
- 主程式邏輯清晰（202 行）
- 模組命名明確

✅ **可擴展性提升**
- 新增功能只需修改特定模組
- 不會影響其他模組

---

## 常見問題

### Q1: Bot 啟動失敗，顯示 "ModuleNotFoundError"
A: 確認所有新建的檔案都在同一目錄下，並且虛擬環境已啟動。

### Q2: "找不到 OPENAI_API_KEY"
A: 確認 .env 檔案存在且包含正確的 API key。

### Q3: 庫存更新後沒有儲存
A: 檢查 inventory.json 的檔案權限，確保程式有寫入權限。

### Q4: 圖像辨識失敗
A: 確認：
- TELEGRAM_TOKEN 正確
- 網路連線正常
- tmp_images 目錄可寫入

### Q5: AI 回應與之前不同
A: Prompt 完全沒有修改，但 GPT 回應本身有隨機性。如果格式或語氣差異很大，請檢查 ai_service.py 中的 prompt。

---

## 部署到 Railway

重構後的程式可以直接部署到 Railway：

```bash
# 確認 Procfile 內容
cat Procfile
# 應該是: worker: python telegram_bot.py

# Git 提交
git add .
git commit -m "Refactor: Split telegram_bot.py into service modules"
git push

# Railway 會自動偵測並部署
```

---

## 下一步建議

1. **添加單元測試**
   - 為 inventory_service 撰寫完整測試
   - 測試自然語言解析的邊界情況

2. **添加日誌記錄**
   - 使用 logging 模組替代 print
   - 記錄關鍵操作和錯誤

3. **錯誤處理強化**
   - 更細緻的異常處理
   - 使用者友好的錯誤訊息

4. **效能優化**
   - 考慮快取 AI 回應
   - 批次處理圖像

5. **功能擴展**
   - 支援更多 Telegram 互動（inline keyboard）
   - 支援多使用者
   - 添加統計和報表功能
