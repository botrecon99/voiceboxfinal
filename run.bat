@echo off
echo Dang khoi dong Frontend va Backend...

:: Mở cửa sổ cho Frontend
start "Frontend Dev Server" cmd /k "npm run dev"

:: Mở cửa sổ cho Backend
start "Backend Uvicorn Server" cmd /k "uvicorn backend.app:app --host 127.0.0.1 --port 17493 --reload"

echo Da gui lenh khoi dong!
exit