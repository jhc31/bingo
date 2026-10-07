# Bingo Bingo 策略實驗室

台灣彩券 Bingo Bingo 的選號策略比較網站：每期開獎前用 13 種策略產生 3～6 星推薦號碼，開獎後自動對獎、累積真實的樣本外戰績，並附上 18.5 萬期回測報告與倍數／資金模擬器。

> 回測結論：所有選號策略都無法勝過隨機選號，各玩法長期回收率都低於 100%（含加碼期間）。本站是研究與風險試算工具，不保證中獎。

## 架構

| 部分 | 技術 | 說明 |
|---|---|---|
| 網站＋API | FastAPI（Render Web Service） | `app/main.py`，前端是 `app/static/` 的純 HTML/JS |
| 資料庫 | Supabase Postgres | 開獎、預測、加碼活動、回測結果，schema 在 `supabase/migrations/` |
| 排程 | 網站內建排程器＋Render Cron Job（或 Supabase pg_cron） | `app/scheduler.py` 在每期開獎後約 40 秒開始抓結果（官方約晚 1~2 分鐘公布，每 15 秒重試）；Cron Job 是網站休眠時的備援 |
| 共用邏輯 | `core/` | 獎金表與加碼（`payouts.py`）、選號策略（`strategies.py`）、官方 API（`taiwan_lottery.py`） |
| 回測 | `backtest/` | `run_backtest.py`（策略）、`multiplier_3star.py`（倍數），報告在 `backtest/output/` |

資料來源是台灣彩券官方 API（`api.taiwanlottery.com`），歷史資料從 2024-01-01 起。

## 部署步驟

### 1. 建立 Supabase 專案

1. 到 [supabase.com](https://supabase.com) 建立專案，Region 選 **Southeast Asia (Singapore)**。
2. Project Settings → Database → Connection string，選 **Session pooler**（Render 只支援 IPv4，不要用 Direct connection），複製連線字串並填入密碼。
3. 在專案根目錄建立 `.env`（可參考 `.env.example`）：
   ```
   DATABASE_URL=postgresql://postgres.xxxx:密碼@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
   ```

### 2. 在本機建表並匯入資料

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.migrate          # 建表＋加碼活動資料（可重複執行，新版本更新後也要再跑一次）
python -m backtest.fetch_draws     # 下載歷史開獎到 data/draws.csv（約 1~2 分鐘）
python -m scripts.seed_history     # 匯入約 20 萬期開獎
python -m backtest.run_backtest    # 跑回測（約 1 分鐘）
python -m scripts.upload_backtest  # 上傳回測結果給網站
python -m app.sync                 # 試跑一次排程，產生下一期預測
```

### 3. 推到 GitHub，用 Render Blueprint 部署

1. 把專案推到 GitHub（`.env` 和 `data/` 已在 `.gitignore` 裡，不會上傳）。
2. Render → New → **Blueprint** → 選這個 repo，Render 會讀 `render.yaml` 建立：
   - `bingo-lab`：Web Service（免費方案）
   - `bingo-sync`：Cron Job，每 5 分鐘執行（**付費服務**）
3. 依提示為兩個服務填入 `DATABASE_URL`。
4. 部署完成後打開網址，確認首頁出現最新開獎與倒數。

**不想付 Cron Job 費用：** 刪掉 `render.yaml` 裡的 cron 區塊，改用 `supabase/cron_free_option.sql`，讓 Supabase 每 5 分鐘呼叫網站的 `/api/cron/sync`。缺點是免費 Web Service 閒置時會休眠，早上第一次被叫醒約需 1 分鐘。

## 預測什麼時候出現

每期開獎 → 官方約 1~2 分鐘後公布號碼 → 排程器抓到後立刻對獎，並產生下一期預測。所以下一期預測大約在開獎前 3~4 分鐘出現。如果新開獎在下一期開獎前才進來，預測會用最新資料重新計算（仍然在開獎前），開獎後就不會再改動。網頁會在開獎後自動更新，不需要重新整理。

「本期投注建議」依下一期適用的獎金表（含加碼）比較 3~6 星回收率、顯示所選策略的號碼，並依預算與打算玩的期數建議倍數（預算 ÷ 25 元 ÷ 期數，確保一直沒中也能玩完）。

## 日常維護

**新增加碼活動：** 在 Supabase Table Editor 的 `promotions` 新增一列。`star_overrides` 只要列出有變動的獎項，例如 3 星中 3 改成 1,000 元、4 星中 4 改成 2,000 元：

```json
{"3": {"3": 1000}, "4": {"4": 2000, "3": 150}}
```

網站的獎金表、回收率、模擬器和即時戰績都會自動套用（最多約 5 分鐘快取）。

**更新回測：** 重新執行 `fetch_draws` → `run_backtest` → `upload_backtest`。

## 環境變數

| 變數 | 說明 |
|---|---|
| `DATABASE_URL` | Supabase Session pooler 連線字串 |
| `CRON_SECRET` | `/api/cron/sync` 的密鑰 |
| `ENABLE_SCHEDULER` | 預設 `1`，網站程序內建排程；設成 `0` 則完全交給外部排程 |

## 本機開發

```bash
uvicorn app.main:app --reload
```

打開 http://localhost:8000。`.env` 的 `DATABASE_URL` 可以指向 Supabase，也可以指向任何本機 Postgres。

## API

| 路徑 | 說明 |
|---|---|
| `GET /api/overview` | 最新開獎、下一期時間、當下獎金表（含加碼）、各策略推薦號碼與上期結果 |
| `GET /api/live-stats` | 上線後的即時樣本外戰績 |
| `GET /api/strategy/{name}` | 單一策略最近的預測、命中與獎金 |
| `GET /api/backtest` | 最新回測結果 |
| `GET /api/draws?limit=50` | 開獎紀錄 |
| `GET /api/promotions` | 加碼活動 |
| `POST /api/cron/sync` | 觸發同步（需要 `X-Cron-Secret` header） |

## 注意

- 預測只會在開獎前寫入，開獎後才產生的不算進即時戰績，確保戰績是真正的樣本外結果。
- 所有資料表都啟用了 RLS 且沒有開放任何 policy，Supabase 公開的 anon API 無法存取，只有後端的資料庫連線可以讀寫。
- 理性投注，未滿 18 歲不得購買或兌領彩券。
