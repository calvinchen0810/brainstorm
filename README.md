# Brainstorm

以瀏覽器為基礎的協作視覺化思維導圖工具，支援節點、便利貼、連線與即時多人協作。

---

## 功能概覽

### 畫布操作
- 單指/滑鼠拖曳平移畫布；雙指/滾輪縮放
- 雙擊空白處新增節點
- 長按空白處開啟右鍵選單

### 節點（Node）
- 可拖曳移動，支援多選群體拖曳
- 可編輯標題與內文（點擊直接編輯）
- 六種背景色（白、藍、紫、紅、綠、橘）
- 右下角浮動刪除按鈕
- 四向連接埠可拉出連線

### 便利貼（Sticky）
- 手寫/繪圖畫布，支援橡皮擦與清除
- 可設定標題文字
- 拖曳把手（右上角九點圖示）移動位置
- 右下角浮動刪除按鈕
- 標準與寬版兩種尺寸

### 連線（Connection）
- 節點間可建立方向連線
- 支援刪除單條連線

### 工具列
- 復原 / 重做（60 步歷史）
- 全選、刪除選取、清空畫布
- 顏色選取器（彈窗式）
- 群體移動模式
- 多人協作入口
- 雲端存取入口（需後端 SQLite 支援）
- 縮圖地圖（右下角）
- 響應式設計：寬度足夠時顯示文字標籤，窄版只顯示圖示

### 存取與協作
- 狀態自動儲存至瀏覽器 localStorage（30 秒間隔）
- 雲端存取：可將畫布以密碼保護存至 Server（需後端支援）
- 即時多人協作：房間代碼機制，WebRTC（PeerJS）優先，自動 fallback 至 WebSocket

---

## 專案架構

```
brainstorm/
├── index.html      # 單檔前端（HTML + CSS + JS，~3700 行）
├── server.py       # FastAPI 後端（協作 WebSocket + 雲端存取 REST API）
├── requirements.txt
└── .gitignore
```

### 前端（index.html）
純 Vanilla JS，無 build 步驟，無框架依賴。所有狀態儲存於：

```js
state = {
  nodes:       [{ id, x, y, text, color }],
  stickies:    [{ id, x, y, dataURL, title, width }],
  connections: [{ id, from, to, fromPort, toPort }]
}
```

### 後端（server.py）
FastAPI 應用，提供：
- 靜態頁面服務（`GET /`）
- 多人協作 WebSocket（`WS /ws/collab`）
- 雲端存取 REST API（`/api/projects/*`）
- 健康檢查（`GET /health`）

---

## 安裝與啟動

### 需求
- Python 3.11+

### 安裝依賴

```bash
pip install -r requirements.txt
```

### 啟動伺服器

```bash
python server.py
```

或：

```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

開啟瀏覽器前往 `http://localhost:8000`。

---

## 雲端存取功能（☁ 按鈕）

工具列的 ☁ 按鈕允許將畫布存至 Server，以便在不同裝置或瀏覽器間還原。  
**此功能需後端能成功初始化 SQLite**；若無法初始化（例如 Render.com 免費方案的臨時檔案系統），按鈕自動隱藏。

### 流程

**儲存**
1. 點擊 ☁ → 儲存分頁
2. 輸入密碼 → 取得六碼代碼（例如 `A3K9PQ`）
3. 記下代碼；下次開啟時可用「覆寫」更新同一份專案

**載入**
1. 點擊 ☁ → 載入分頁
2. 輸入代碼 + 密碼 → 畫布即時還原

### REST API

| Method | Path | 說明 |
|--------|------|------|
| `GET`  | `/api/storage-info` | `{"available": true/false}` |
| `POST` | `/api/projects` | 新建：`{password, state}` → `{code}` |
| `POST` | `/api/projects/{code}/load` | 載入：`{password}` → `{state}` |
| `PUT`  | `/api/projects/{code}` | 覆寫：`{password, state}` → 200 |

### 環境變數

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `SQLITE_DB_PATH` | SQLite 資料庫路徑 | `brainstorm.db`（與 server.py 同目錄）|

---

## 多人協作功能

### 連線方式
1. 主持人點擊工具列協作按鈕，取得六碼房間代碼
2. 分享代碼給協作者
3. 協作者輸入代碼加入房間

### 傳輸層策略
前端自動選擇最佳傳輸方式：

1. **PeerJS / WebRTC**（優先）：點對點傳輸，延遲低
2. **FastAPI WebSocket**（fallback）：若 WebRTC 在受限網路環境失敗，自動切換

### WebSocket 協定（`/ws/collab`）

連線 URL 參數：

| 參數 | 說明 |
|------|------|
| `room` | 房間代碼（六碼） |
| `role` | `host` 或 `guest` |
| `clientId` | 前端隨機識別碼 |

支援訊息型別：

| 型別 | 說明 |
|------|------|
| `join` | 加入房間 |
| `ping` / `pong` | 心跳 |
| `state_sync` | 廣播完整狀態 |
| `state_update` | 廣播差異更新 |
| `state_request` | 新加入者請求當前狀態 |
| `peer_count` | 目前房間人數（後端廣播） |

狀態 payload 結構：

```json
{
  "nodes": [],
  "stickies": [],
  "connections": [],
  "nextId": 1
}
```

---

## 部署注意事項

| 環境 | SQLite 雲端存取 | 協作 WebSocket |
|------|----------------|----------------|
| 本地（`python server.py`）| ✅ 持久化 | ✅ |
| Render.com 免費方案 | ❌ 自動停用 | ✅ |
| Render.com 付費（持久 Disk）| ✅ 設定 `SQLITE_DB_PATH` 指向持久磁碟 | ✅ |
