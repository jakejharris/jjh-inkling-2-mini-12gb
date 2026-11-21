@rem Paths used by run-inkling-mini.cmd and bench\bench.cmd.
@rem Edit the defaults below, or set these variables in your shell before running a script
@rem (cmd: set INKLING_MODEL_DIR=D:\models\inkling-2-mini   PowerShell: $env:INKLING_MODEL_DIR = "D:\models\inkling-2-mini").

@rem Folder that holds the .gguf files.
if not defined INKLING_MODEL_DIR set "INKLING_MODEL_DIR=C:\models\inkling-2-mini"

@rem Folder you unzipped the llama.cpp build into (it must contain llama-server.exe and llama-bench.exe).
if not defined INKLING_LLAMA_DIR set "INKLING_LLAMA_DIR=C:\models\llama.cpp\b12568-mix-8eebad4-win-cuda13"

@rem Port for llama-server. It always binds to 127.0.0.1 (this PC only).
if not defined INKLING_PORT set "INKLING_PORT=8080"

@rem Expert placement: experts of layers 0-5 and 18-23 stay on the CPU, so the experts of the
@rem looped core layers 6-17 (which run three times per token) sit on the GPU.
@rem This one is fixed on purpose (an environment variable does not change it): edit this line to try another placement.
set "INKLING_OT=blk\.([0-5]|1[89]|2[0-3])\.ffn_.*_exps=CPU"
