@echo off
echo Dang khoi dong Frontend va Backend cho AI Dubbing Studio...

:: 1. Mở cửa sổ cho Frontend (Chạy bằng Bun)
start "Frontend Dev Server" cmd /k "npm run dev"

:: 2. Mở cửa sổ cho Backend (Kích hoạt env trước rồi mới gọi Uvicorn)
start "Backend Uvicorn Server" cmd /k "env\Scripts\activate && uvicorn backend.app:app --host 127.0.0.1 --port 17493 --reload"

echo Da gui lenh khoi dong! Giao dien va Backend dang len...
exit