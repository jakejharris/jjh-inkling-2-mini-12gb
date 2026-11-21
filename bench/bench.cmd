@echo off
rem llama-bench runs that reproduce the placement table in the README (section "Speed").
rem
rem   bench\bench.cmd q4                 recommended setup: core 6-17 experts on GPU, op offload on, mmap (about 1-2 min)
rem   bench\bench.cmd iq3                same for UD-IQ3_XXS (quick mode warns below 22,000 MB free for q4, 16,000 MB for iq3)
rem   bench\bench.cmd q4 placement       three no-mmap rows: -ncmoe 12 vs core 6-17, op offload off/on
rem   bench\bench.cmd iq3 placement      (placement mode pins the CPU experts in RAM: up to about 20.6 GB private for Q4)
rem
rem Stop llama-server first: the benchmark needs the whole GPU.
rem The llama-bench table goes to this window; its full log goes to bench\logs\.
setlocal
call "%~dp0..\config.cmd"

set "QUANT="
rem NEED_MB: placement-mode gate. WARN_MB: quick-mode warning threshold, a rule of thumb (model file size plus 4 GB).
rem llama-bench maps the whole model file (mmap) and holds it in memory while it runs.
if /I "%~1"=="q4" set "QUANT=Q4_K_XL"& set "NEED_MB=25000"& set "WARN_MB=22000"
if /I "%~1"=="iq3" set "QUANT=IQ3_XXS"& set "NEED_MB=19000"& set "WARN_MB=16000"
if not defined QUANT goto :usage
set "MODE=%~2"
if not defined MODE set "MODE=quick"
if /I not "%MODE%"=="quick" if /I not "%MODE%"=="placement" goto :usage

set "MODEL=%INKLING_MODEL_DIR%\Inkling-2-Mini-UD-%QUANT%.gguf"
set "BENCH=%INKLING_LLAMA_DIR%\llama-bench.exe"
if not exist "%BENCH%" goto :nollama
if not exist "%MODEL%" goto :nomodel

tasklist /FI "IMAGENAME eq llama-server.exe" 2>nul | find /I "llama-server.exe" >nul
if not errorlevel 1 goto :running

set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "COMMON=-m "%MODEL%" -ngl 99 -fa on -o md"

if /I "%MODE%"=="placement" goto :placement

set "FREE_MB="
for /f %%m in ('powershell -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"') do set "FREE_MB=%%m"
if not defined FREE_MB goto :quick_go
echo Free RAM: %FREE_MB% MB
if %FREE_MB% LSS %WARN_MB% echo WARNING: free RAM is below %WARN_MB% MB. llama-bench maps the model file (mmap) and holds it in memory while it runs. Close heavy apps first if Windows runs low.
:quick_go
echo == %QUANT%: core 6-17 experts on GPU, op offload on, mmap, pp512/pp2048/tg128, 3 reps
"%BENCH%" %COMMON% -ot "%INKLING_OT%" -nopo 0 -p 512,2048 -n 128 -r 3 2> "%LOGDIR%\%QUANT%_quick.log"
set "RC=%errorlevel%"
echo RC=%RC%   (log: bench\logs\%QUANT%_quick.log)
exit /b %RC%

:placement
rem -lm none puts the CPU-side experts in pinned (non-pageable) RAM. Check there is room first.
set "FREE_MB="
for /f %%m in ('powershell -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"') do set "FREE_MB=%%m"
if not defined FREE_MB goto :ramunknown
echo Free RAM: %FREE_MB% MB (placement mode for %QUANT% wants about %NEED_MB% MB)
if %FREE_MB% LSS %NEED_MB% goto :lowram
echo == %QUANT%: experts of layers 12-23 on GPU, 0-11 on CPU (-ncmoe 12), op offload off, no mmap
"%BENCH%" %COMMON% -ncmoe 12 -nopo 1 -lm none -p 512 -n 128 -r 3 2> "%LOGDIR%\%QUANT%_ncmoe12_nopo.log"
if errorlevel 1 goto :benchfail
echo == %QUANT%: core 6-17 experts on GPU, op offload off, no mmap
"%BENCH%" %COMMON% -ot "%INKLING_OT%" -nopo 1 -lm none -p 512 -n 128 -r 3 2> "%LOGDIR%\%QUANT%_core_nopo.log"
if errorlevel 1 goto :benchfail
echo == %QUANT%: core 6-17 experts on GPU, op offload on, no mmap
"%BENCH%" %COMMON% -ot "%INKLING_OT%" -nopo 0 -lm none -p 512 -n 128 -r 3 2> "%LOGDIR%\%QUANT%_core_po.log"
if errorlevel 1 goto :benchfail
echo (logs: bench\logs\%QUANT%_*.log)
exit /b 0

:usage
echo usage: bench\bench.cmd q4^|iq3 [quick^|placement]
exit /b 1
:nollama
echo ERROR: llama-bench.exe not found in "%INKLING_LLAMA_DIR%". See README step 2 or edit config.cmd.
exit /b 1
:nomodel
echo ERROR: "%MODEL%" not found. See README step 3 or edit config.cmd.
exit /b 1
:running
echo ERROR: llama-server.exe is running. Stop it first so the benchmark gets the whole GPU.
exit /b 1
:lowram
echo ERROR: not enough free RAM for placement mode. Close programs and retry, or run quick mode instead.
exit /b 1
:ramunknown
echo ERROR: could not read free RAM for placement mode. Run quick mode or retry.
exit /b 1
:benchfail
echo ERROR: llama-bench failed with exit code %errorlevel%. See bench\logs\%QUANT%_*.log.
exit /b 1
