# SINTU Local AI on Android / Termux

This is a free, local-only text-inference path for Android arm64. It uses the official Termux `llama-cpp` package and the official Qwen2.5-0.5B-Instruct GGUF (Q4_K_M, about 491 MB, Apache-2.0). The small model is a compatibility/bootstrap profile, not a claim of professional documentary-grade Hindi quality.

## Setup

From the SINTU repository root in Termux:

```bash
bash scripts/setup_local_ai_termux.sh
```

The script checks arm64, available RAM and free storage, installs `llama-cpp` through Termux's package manager, downloads the model to `~/.sintu/models`, and verifies the GGUF magic bytes. It does not alter `.env`, credentials, the SINTU database, or source media.

## Start

Keep this process running in a Termux session:

```bash
bash scripts/start_local_ai_termux.sh
```

The server binds only to `127.0.0.1:8080`. SINTU's existing local AI detector probes `/v1/models` and uses the OpenAI-compatible chat API automatically. No provider secret or paid API is required.

## Resource profile

Default context is 1024 tokens and four CPU threads. On a phone with less than 900 MB currently available RAM, the bootstrap refuses to proceed. Close other apps and retry later. Do not raise context/thread limits until the device has been benchmarked. The model download needs at least 1.25 GB free storage for a safe temporary download.

## Verify

With the server running, the SINTU dashboard's **Local AI Runtime Diagnostics** should show the llama.cpp-compatible backend and model as READY. Also verify:

```bash
curl -fsS http://127.0.0.1:8080/v1/models
```

A model being downloaded or the server process starting is not an inference PASS. Send a Hindi test prompt through SINTU and confirm a real response before marking Local AI ready.

## Upstream references

- llama.cpp Android / Termux instructions: https://github.com/ggml-org/llama.cpp/blob/master/docs/android.md
- Official Qwen model and license: https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF
