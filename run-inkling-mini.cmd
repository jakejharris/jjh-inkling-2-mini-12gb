@echo off
rem Start Inkling 2 Mini on a 12 GB RTX 3060 with llama.cpp (llama-server).
rem
rem   run-inkling-mini.cmd          Q4_K_XL (default, better quality; "q4" also works)
rem   run-inkling-mini.cmd iq3      UD-IQ3_XXS (smaller and a little faster, for when the GPU is busy)
rem
rem Paths come from config.cmd. Extra llama-server flags can go in the INKLING_EXTRA_ARGS variable.
rem Stop the server with Ctrl+C in this window.
setlocal
call "%~dp0config.cmd"

set "QUANT="
if "%~1"=="" set "QUANT=Inkling-2-Mini-UD-Q4_K_XL.gguf"& set "WARN_MB=15000"
if /I "%~1"=="q4" set "QUANT=Inkling-2-Mini-UD-Q4_K_XL.gguf"& set "WARN_MB=15000"
if /I "%~1"=="iq3" set "QUANT=Inkling-2-Mini-UD-IQ3_XXS.gguf"& set "WARN_MB=13000"
if not defined QUANT goto :usage
if not "%~2"=="" goto :usage

if not exist "%INKLING_LLAMA_DIR%\llama-server.exe" goto :nollama
if not exist "%INKLING_MODEL_DIR%\%QUANT%" goto :nomodel
if not exist "%INKLING_MODEL_DIR%\mmproj-F16.gguf" goto :nommproj

tasklist /FI "IMAGENAME eq llama-server.exe" 2>nul | find /I "llama-server.exe" >nul
if not errorlevel 1 goto :running

set "FREE_MB="
for /f %%m in ('powershell -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"') do set "FREE_MB=%%m"
if not defined FREE_MB goto :start
echo Free RAM: %FREE_MB% MB
if %FREE_MB% LSS %WARN_MB% echo WARNING: free RAM is below %WARN_MB% MB. The Q4 server used about 14 GB of host RAM on my PC, IQ3 about 2 GB less. If Windows runs low, stop the server and close other programs.
:start
echo Model:  %INKLING_MODEL_DIR%\%QUANT%
echo Server: http://127.0.0.1:%INKLING_PORT%   (wait for "listening on", then leave this window open)
echo.

rem Why these flags (see README):
rem   -ot ...          experts of looped core layers 6-17 on the GPU, the rest on the CPU (do not let -fit choose)
rem   -c 16384 -ub 256 16K context; ub 256 keeps the op-offload compute buffer small enough for 12 GB
rem   --cache-ram 0    the default 8 GB host prompt cache grows by about 500 MB per screenshot request
rem   mmap stays on    (no "-lm none"): -lm none pins 18-26 GB of host RAM per server
rem   --spec-type none the DSpark draft model did not help on this card
"%INKLING_LLAMA_DIR%\llama-server.exe" -m "%INKLING_MODEL_DIR%\%QUANT%" --mmproj "%INKLING_MODEL_DIR%\mmproj-F16.gguf" -ngl 99 -ot "%INKLING_OT%" -fa on -c 16384 -ub 256 --parallel 1 --jinja --cache-ram 0 --spec-type none --temp 1.0 --top-p 1.0 --top-k 0 --min-p 0.0 --host 127.0.0.1 --port %INKLING_PORT% %INKLING_EXTRA_ARGS%
exit /b %errorlevel%

:usage
echo usage: run-inkling-mini.cmd [q4^|iq3]
echo   q4  (default) Inkling-2-Mini-UD-Q4_K_XL.gguf
echo   iq3           Inkling-2-Mini-UD-IQ3_XXS.gguf, smaller and a little faster
exit /b 1
:nollama
echo ERROR: llama-server.exe not found in "%INKLING_LLAMA_DIR%".
echo Unzip the llama.cpp build there (README step 2) or set INKLING_LLAMA_DIR in config.cmd.
exit /b 1
:nomodel
echo ERROR: "%INKLING_MODEL_DIR%\%QUANT%" not found.
echo Download it (README step 3) or set INKLING_MODEL_DIR in config.cmd.
exit /b 1
:nommproj
echo ERROR: "%INKLING_MODEL_DIR%\mmproj-F16.gguf" not found (needed for vision). See README step 3.
exit /b 1
:running
echo ERROR: a llama-server.exe is already running. Stop it first (Ctrl+C in its window), or check with:
echo   tasklist /FI "IMAGENAME eq llama-server.exe"
exit /b 1
