# Agents Trading

Bot phân tích chứng khoán Việt Nam chạy bằng đội LLM đa tác nhân. Fork từ [TradingAgents](https://github.com/TauricResearch/TradingAgents), thay toàn bộ tầng dữ liệu cho thị trường VN và đóng gói thành web app: chat với Orchestrator, cần phân tích sâu thì nó tự handoff sang quy trình mô phỏng quỹ đầu tư — analyst chạy song song, Bull/Bear tranh biện, risk team duyệt, cuối cùng ra khuyến nghị BUY/HOLD/SELL kèm target/stop loss.

Gồm 3 phần:

- `tradingagents/` — thư viện lõi (LangGraph orchestration, 11+ LLM provider, tầng dữ liệu VN)
- `trading-be/` — backend FastAPI: auth, chat streaming (SSE), reports, MongoDB logs
- `trading-ui/` — giao diện Next.js: dashboard, phòng phân tích, lịch sử báo cáo

## Tầng dữ liệu thị trường VN

Điểm khác biệt so với bản gốc: dữ liệu "đóng" của VN được lấy theo chuỗi dự phòng đa nguồn, mỗi tầng đều qua validation contract (giá finite > 0, high ≥ low, đủ số bar, không stale quá 10 ngày):

```
OHLCV:      DNSE Entrade → vnstock/VCI → TCBS
Cơ bản:     vnstock/VCI (BCTC, sở hữu, sự kiện, khối ngoại)
Vĩ mô/ETF:  Browser Agent (Playwright) tự điều hướng SBV/GSO/FireAnt
```

Chuỗi nằm ở [`tradingagents/dataflows/vn_ohlcv.py`](tradingagents/dataflows/vn_ohlcv.py). Một series chỉ được chấp nhận khi qua hết contract, không ghép bar chéo nguồn. Khuyến nghị: cài thêm `VNSTOCK_API_KEY` (miễn phí, 60 req/phút) để tăng hạn mức VCI.

## Chạy local

```bash
# Backend (cần Python ≥ 3.10)
pip install -e .
pip install -e ./trading-be
cd trading-be
cp .env.example .env
alembic upgrade head
python scripts/seed_admin.py
uvicorn main:app --host 0.0.0.0 --port 8000

# UI (terminal mới, cần Node ≥ 20.9)
cd trading-ui
npm install
npm run dev
```

UI tại `http://localhost:3000`, API tại `http://localhost:8000/api/v1`.

Chỉ muốn dùng CLI không cần web:

```bash
export OPENAI_API_KEY=sk-...
tradingagents    # chọn mã, ngày, provider, depth
```

## Deploy Render (free tier)

Repo có sẵn [`render.yaml`](render.yaml) — Render Dashboard → New → Blueprint → trỏ về repo này là xong. Chi tiết từng bước (tạo Mongo Atlas M0, khai báo API key, các hạn chế của free tier) trong [DEPLOY_RENDER.md](DEPLOY_RENDER.md).

## Hướng dẫn sử dụng

### 1. Đăng nhập & cấu hình lần đầu

Đăng nhập UI (local: `admin@tradingagents.com / admin123` hoặc tự đăng ký ở `/sign-up`; Render: mật khẩu trong tab Environment của service backend). Vào **Settings** → chọn LLM provider và dán API key — key lưu riêng theo user.

### 2. Phân tích cổ phiếu — trang Agents

Trang `/research` là nơi làm việc chính:

- **Chat thường:** "giá HPG hôm nay", "VNINDEX thế nào" — Orchestrator trả lời trực tiếp bằng quick tool (biểu đồ, giá, vĩ mô).
- **Phân tích sâu:** "phân tích FPT, có nên mua không?" — Orchestrator handoff sang pipeline đầy đủ: 4 analyst song song → tranh biện Bull/Bear → Research Manager → Trader (entry/TP/SL) → 3 risk debator → Portfolio Manager phê duyệt. Toàn bộ streaming trực tiếp, xem được từng agent đang làm gì.
- Kết quả cuối là Executive Summary: khuyến nghị, target price, stop loss, risk/reward, độ tin cậy, dự phóng 5 ngày. Tự lưu vào **Report History** để xem lại.

Panel trên trang Agents cho chọn provider/model/depth (shallow = nhanh và rẻ, deep = tranh biện nhiều vòng hơn, tốn token hơn).

### 3. Các trang còn lại

| Trang | Chức năng |
|---|---|
| Report History | Xem lại báo cáo đã chạy |
| Analyst System | Sơ đồ đội agent |
| Deliveries | Bản ghi báo cáo đã lưu/giao |
| Scheduled Jobs | CRUD job định kỳ — **preview, chưa nối vào scheduler chạy thật** |
| Settings | Provider/model/API key theo user |

## Ghi chú trung thực

- LightRAG + Reflection Agent (vòng tự học) mới ở giai đoạn preview, chưa chạy thật.
- Browser Agent vĩ mô là non-deterministic (chậm, tốn token, phụ thuộc LLM điều hướng trang web) — kết quả phần này luôn gắn nguồn và nên kiểm chứng chéo.
- Free tier Render: 512MB RAM nên không chạy được Playwright/Chromium; service ngủ sau ~15 phút không traffic.
- Lõi `tradingagents/` đã sync lên upstream v0.4.0 (fix look-ahead, checkpoint resume, FRED/Polymarket vendors, GPT-5.6/GLM-5.3, Bedrock, retry budget). Skill UI/UX (ui-ux-pro-max) nằm trong `.claude/skills/` — AI phát triển giao diện nên đọc `design-system/agents-trading/MASTER.md` trước khi dựng trang mới.
- Mọi khuyến nghị từ AI chỉ để nghiên cứu, không phải lời khuyên đầu tư. Quyết định là của bạn.
