@echo off
echo ================================================
echo  Saturday AI - Free AI Setup Script
echo ================================================
echo.

REM Clear old config that may have API key requirements
echo Clearing old API key config...
del /f /q "%APPDATA%\Saturday\config.json" 2>nul
echo (Done - Saturday will use free AI from now on)
echo.

REM Install g4f
echo Installing g4f (Free AI - no API key required)...
python -m pip install -U g4f
echo.

if %errorlevel% == 0 (
    echo [SUCCESS] g4f installed!
) else (
    echo Trying with --user flag...
    python -m pip install --user -U g4f
)

REM Remove old litellm if present
echo.
echo Removing old litellm (if present)...
python -m pip uninstall litellm -y 2>nul
echo.

REM Test g4f
echo Testing free AI connection...
python -c "from g4f.client import Client; c=Client(); r=c.chat.completions.create(model='gpt-4o-mini',messages=[{'role':'user','content':'Say: Saturday AI is working!'}]); print('AI Response:', r.choices[0].message.content)"
echo.

echo ================================================
echo  DONE! Run Saturday with: python main.py
echo  No API key required - AI is completely free!
echo ================================================
echo.
pause
