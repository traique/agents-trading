# Deploy lên Render (Free Tier)

Hướng dẫn deploy full stack (backend + UI) lên Render bằng Blueprint.

## 1. Chuẩn bị Mongo Atlas (bắt buộc)

Render free tier không có MongoDB. Tạo cluster miễn phí M0:

1. Đăng ký [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) → tạo cluster **M0 (Free)**, region gần Singapore.
2. **Database Access** → tạo user + password.
3. **Network Access** → thêm `0.0.0.0/0` (Render free dùng IP động).
4. Lấy connection string dạng:
   `mongodb+srv://<user>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority`

## 2. Deploy bằng Blueprint

1. Render Dashboard → **New → Blueprint** → chọn repo `traique/agents-trading`.
2. Render đọc `render.yaml` và tạo 2 service:
   - `agents-trading-be` — FastAPI, health check `/api/v1/health`
   - `agents-trading-ui` — Next.js
3. Khi apply, Render hỏi giá trị cho các biến `sync: false`:
   - `MONGO_URI` — dán connection string ở bước 1 (thêm tên DB nếu muốn:
     `...mongodb.net/trading_agents_logs?retryWrites=true...`)
   - `TRADINGAGENTS_LLM_PROVIDER` — ví dụ `openai`
   - `OPENAI_API_KEY` — key của provider tương ứng (xem `.env.root.example`
     cho các provider khác: `DEEPSEEK_API_KEY`, `GOOGLE_API_KEY`, ...)
4. Bấm **Apply**. Lần build đầu mất ~10-15 phút (cài LangChain stack + build Next).

`SECRET_KEY` và `DEFAULT_ADMIN_PASSWORD` được Render sinh ngẫu nhiên
(`generateValue: true`) — xem giá trị trong **Environment** của service
`agents-trading-be` sau khi deploy để đăng nhập UI.

## 3. Kiểm tra sau deploy

- Backend: mở `https://agents-trading-be.onrender.com/api/v1/health` → `{"status": "ok"}`
- UI: mở `https://agents-trading-ui.onrender.com` → đăng nhập bằng admin email + password ở bước 2.
- Vào **Settings** trong UI để cấu hình provider/model cho user trước khi chạy phân tích.

## Hạn chế của free tier cần biết

- **Service sleep**: sau ~15 phút không có request, service bị tạm dừng;
  request đầu tiên sau đó mất ~50 giây để lạnh lại. Dùng
  [UptimeRobot](https://uptimerobot.com) ping `/api/v1/health` mỗi 10 phút
  nếu muốn giữ ấm (vượt quá giờ free hàng tháng thì service bị suspend).
- **RAM 512MB**: không chạy được Browser Agent (Playwright/Chromium) —
  phân tích sẽ dùng các nguồn HTTP (DNSE → vnstock/VCI → TCBS) và Bước vĩ mô
  qua browser có thể fail; hệ thống vẫn trả báo cáo từ các analyst còn lại.
- **SQLite ephemeral**: file DB mất khi service restart/redeploy (tài khoản
  admin được seed lại tự động lúc start). Muốn dữ liệu bền thì set
  `DATABASE_URL` trỏ Postgres riêng (không nằm trong free tier).
- **`NEXT_PUBLIC_API_URL` bake lúc build**: nếu đổi tên service backend
  (khác `agents-trading-be`), sửa `render.yaml` trước khi apply; nếu đổi sau
  khi deploy phải bấm **Clear build cache & deploy** trên service UI.
- Free tier chỉ đủ cho 1-2 người dùng thử nghiệm, không dùng cho production.
