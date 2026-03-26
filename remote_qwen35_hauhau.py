import argparse
import textwrap
import time

import paramiko


REMOTE_DIR = "/root/private_data/qwen35-27b-hauhau"
MODEL_DIR = "/root/private_data/models/HauhauCS-Qwen3.5-27B-Uncensored-HauhauCS-Aggressive"
MODEL_FILE = "Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-BF16.gguf"
MODEL_URL = (
    "https://hf-mirror.com/HauhauCS/Qwen3.5-27B-Uncensored-HauhauCS-Aggressive/"
    "resolve/main/Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-BF16.gguf"
)
SERVER_PORT = 8000
LLAMA_BIN = "/root/private_data/llama.cpp-master/build-hip-cublas-2604/bin/llama-server"


DOWNLOAD_PY = textwrap.dedent(
    r"""
    import math
    import os
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import requests

    URL = os.environ["MODEL_URL"]
    OUT = os.environ["OUT_FILE"]
    WORKERS = int(os.environ.get("WORKERS", "8"))
    CHUNK_MB = int(os.environ.get("CHUNK_MB", "64"))
    PROGRESS_SECS = int(os.environ.get("PROGRESS_SECS", "5"))
    CHUNK = CHUNK_MB * 1024 * 1024
    TEMP = OUT + ".part"

    session = requests.Session()
    session.trust_env = True
    session.headers.update({"User-Agent": "parallel-downloader/1.0"})

    lock = threading.Lock()
    done_bytes = 0
    done_chunks = 0
    total_chunks = 0
    start_ts = 0.0
    last_print = 0.0

    def head_size():
        resp = session.head(URL, allow_redirects=True, timeout=120)
        resp.raise_for_status()
        size = int(resp.headers.get("Content-Length", "0"))
        if size <= 0:
            raise RuntimeError(f"Invalid Content-Length: {size}")
        print(f"total_size={size}", flush=True)
        print(f"total_gib={size / 1024**3:.2f}", flush=True)
        return size

    def ensure_file(size):
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(TEMP, "wb") as f:
            f.truncate(size)

    def fetch_chunk(idx, start, end, size):
        global done_bytes, done_chunks, total_chunks, start_ts, last_print
        headers = {"Range": f"bytes={start}-{end}"}
        for attempt in range(6):
            try:
                with session.get(
                    URL,
                    headers=headers,
                    stream=True,
                    allow_redirects=True,
                    timeout=(60, 120),
                ) as resp:
                    if resp.status_code not in (200, 206):
                        raise RuntimeError(f"chunk {idx} bad status {resp.status_code}")
                    with open(TEMP, "r+b", buffering=0) as f:
                        f.seek(start)
                        for buf in resp.iter_content(chunk_size=1024 * 1024):
                            if not buf:
                                continue
                            f.write(buf)
                            with lock:
                                done_bytes += len(buf)
                                now = time.time()
                                if now - last_print >= PROGRESS_SECS:
                                    elapsed = max(now - start_ts, 1e-6)
                                    speed = done_bytes / 1024**2 / elapsed
                                    pct = done_bytes * 100.0 / size
                                    print(
                                        "progress="
                                        f"{done_bytes}/{size} ({pct:.2f}%) "
                                        f"speed={speed:.1f}MiB/s "
                                        f"chunks={done_chunks}/{total_chunks}",
                                        flush=True,
                                    )
                                    last_print = now
                    with lock:
                        done_chunks += 1
                    return
            except Exception as exc:
                wait = min(2**attempt, 30)
                print(
                    f"chunk {idx} retry {attempt + 1}: {exc} sleep={wait}s",
                    flush=True,
                )
                time.sleep(wait)
        raise RuntimeError(f"chunk {idx} failed after retries")

    def main():
        global total_chunks, start_ts, last_print
        size = head_size()
        ensure_file(size)
        total_chunks = math.ceil(size / CHUNK)
        print(
            f"workers={WORKERS} chunk_mb={CHUNK_MB} total_chunks={total_chunks}",
            flush=True,
        )
        start_ts = time.time()
        last_print = start_ts
        futures = []
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            for idx in range(total_chunks):
                start = idx * CHUNK
                end = min(size - 1, start + CHUNK - 1)
                futures.append(executor.submit(fetch_chunk, idx, start, end, size))
            for future in as_completed(futures):
                future.result()
        os.replace(TEMP, OUT)
        elapsed = max(time.time() - start_ts, 1e-6)
        print(
            f"download_complete path={OUT} "
            f"avg_speed={size / 1024**2 / elapsed:.1f}MiB/s elapsed_s={elapsed:.1f}",
            flush=True,
        )

    if __name__ == "__main__":
        main()
    """
).strip() + "\n"


START_SH = textwrap.dedent(
    f"""\
    #!/bin/bash
    set -e
    mkdir -p {REMOTE_DIR}
    source /public/home/fadsfa/.ai_user_info/ai_proxy >/dev/null 2>&1 || true
    export MODEL_URL="{MODEL_URL}"
    export OUT_FILE="{MODEL_DIR}/{MODEL_FILE}"
    export WORKERS="${{WORKERS:-8}}"
    export CHUNK_MB="${{CHUNK_MB:-64}}"
    export PROGRESS_SECS="${{PROGRESS_SECS:-5}}"
    cd {REMOTE_DIR}
    nohup python {REMOTE_DIR}/download_parallel.py > {REMOTE_DIR}/download.log 2>&1 &
    echo $! > {REMOTE_DIR}/download.pid
    sleep 2
    ps -p $(cat {REMOTE_DIR}/download.pid) -o pid,etime,cmd
    """
)

SERVE_SH = textwrap.dedent(
    f"""\
    #!/bin/bash
    set -e
    mkdir -p {REMOTE_DIR}
    source /opt/dtk-26.04/env.sh >/dev/null 2>&1 || source /opt/dtk-25.04.2/env.sh >/dev/null 2>&1 || true
    export HIP_VISIBLE_DEVICES="${{HIP_VISIBLE_DEVICES:-0,1}}"
    export CUDA_VISIBLE_DEVICES="${{CUDA_VISIBLE_DEVICES:-0,1}}"
    export LLAMA_CACHE="${{LLAMA_CACHE:-/root/private_data/hf_cache/llama}}"
    mkdir -p "$LLAMA_CACHE"
    cd {REMOTE_DIR}
    nohup {LLAMA_BIN} \\
      --model {MODEL_DIR}/{MODEL_FILE} \\
      --device ROCm0,ROCm1 \\
      --gpu-layers all \\
      --ctx-size 8192 \\
      --threads 32 \\
      --threads-batch 32 \\
      --batch-size 1024 \\
      --ubatch-size 512 \\
      --parallel 2 \\
      --cont-batching \\
      --jinja \\
      --reasoning-format none \\
      --metrics \\
      --host 0.0.0.0 \\
      --port {SERVER_PORT} \\
      > {REMOTE_DIR}/server.log 2>&1 &
    echo $! > {REMOTE_DIR}/server.pid
    sleep 3
    ps -p $(cat {REMOTE_DIR}/server.pid) -o pid,etime,cmd
    """
)

AUTO_START_SH = textwrap.dedent(
    f"""\
    #!/bin/bash
    set -e
    cd {REMOTE_DIR}
    while true; do
      if [ -f "{MODEL_DIR}/{MODEL_FILE}" ] && [ ! -f "{MODEL_DIR}/{MODEL_FILE}.part" ]; then
        bash {REMOTE_DIR}/start_server.sh
        exit 0
      fi
      if [ -f "{REMOTE_DIR}/download.pid" ] && ! ps -p $(cat {REMOTE_DIR}/download.pid) >/dev/null 2>&1; then
        echo "download process exited before final file appeared" >> {REMOTE_DIR}/autostart.log
        exit 1
      fi
      sleep 10
    done
    """
)


def ssh_connect(host: str, port: int, user: str, password: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=password, timeout=20)
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = 120) -> tuple[str, str, int]:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "ignore")
    err = stderr.read().decode("utf-8", "ignore")
    code = stdout.channel.recv_exit_status()
    return out, err, code


def upload(client: paramiko.SSHClient) -> None:
    sftp = client.open_sftp()
    try:
        sftp.mkdir(REMOTE_DIR)
    except IOError:
        pass
    with sftp.file(f"{REMOTE_DIR}/download_parallel.py", "w") as f:
        f.write(DOWNLOAD_PY)
    sftp.chmod(f"{REMOTE_DIR}/download_parallel.py", 0o755)
    with sftp.file(f"{REMOTE_DIR}/start_download.sh", "w") as f:
        f.write(START_SH)
    sftp.chmod(f"{REMOTE_DIR}/start_download.sh", 0o755)
    with sftp.file(f"{REMOTE_DIR}/start_server.sh", "w") as f:
        f.write(SERVE_SH)
    sftp.chmod(f"{REMOTE_DIR}/start_server.sh", 0o755)
    with sftp.file(f"{REMOTE_DIR}/auto_start_server.sh", "w") as f:
        f.write(AUTO_START_SH)
    sftp.chmod(f"{REMOTE_DIR}/auto_start_server.sh", 0o755)
    sftp.close()


def start_download(client: paramiko.SSHClient) -> None:
    cleanup = textwrap.dedent(
        f"""\
        bash -lc '
        set -e
        pkill -f "wget .*{MODEL_FILE}" || true
        pkill -f "python {REMOTE_DIR}/download_parallel.py" || true
        mkdir -p {MODEL_DIR}
        rm -f {MODEL_DIR}/{MODEL_FILE}
        rm -f {MODEL_DIR}/{MODEL_FILE}.part
        mkdir -p {REMOTE_DIR}
        '
        """
    )
    out, err, _ = run(client, cleanup, timeout=120)
    if out:
        print(out, end="")
    if err:
        print(err, end="")
    upload(client)
    out, err, _ = run(client, f'bash -lc "{REMOTE_DIR}/start_download.sh"', timeout=120)
    print(out, end="")
    if err:
        print(err, end="")


def status(client: paramiko.SSHClient) -> None:
    cmd = textwrap.dedent(
        f"""\
        bash -lc '
        echo "== processes =="
        ps -ef | grep -E "download_parallel.py|wget .*{MODEL_FILE}|llama-server|vllm" | grep -v grep || true
        echo "== file =="
        ls -lh {MODEL_DIR}/{MODEL_FILE} 2>/dev/null || true
        ls -lh {MODEL_DIR}/{MODEL_FILE}.part 2>/dev/null || true
        du -sh {MODEL_DIR} 2>/dev/null || true
        echo "== log tail =="
        tail -n 30 {REMOTE_DIR}/download.log 2>/dev/null || true
        echo "== server =="
        ps -p $(cat {REMOTE_DIR}/server.pid 2>/dev/null) -o pid,etime,cmd 2>/dev/null || true
        tail -n 30 {REMOTE_DIR}/server.log 2>/dev/null || true
        '
        """
    )
    out, err, _ = run(client, cmd, timeout=120)
    print(out, end="")
    if err:
        print(err, end="")


def watch(client: paramiko.SSHClient, loops: int, interval: int) -> None:
    for i in range(loops):
        if i:
            time.sleep(interval)
        print(f"--- watch {i + 1}/{loops} ---")
        status(client)


def start_server(client: paramiko.SSHClient) -> None:
    upload(client)
    cmd = textwrap.dedent(
        f"""\
        bash -lc '
        test -f {MODEL_DIR}/{MODEL_FILE}
        pkill -f "{LLAMA_BIN} .*{MODEL_FILE}" || true
        {REMOTE_DIR}/start_server.sh
        '
        """
    )
    out, err, _ = run(client, cmd, timeout=120)
    print(out, end="")
    if err:
        print(err, end="")


def test_server(client: paramiko.SSHClient) -> None:
    cmd = textwrap.dedent(
        f"""\
        bash -lc '
        curl -s http://127.0.0.1:{SERVER_PORT}/v1/models || true
        echo
        curl -s http://127.0.0.1:{SERVER_PORT}/v1/chat/completions \\
          -H "Content-Type: application/json" \\
          -d '"'"'{{"model":"{MODEL_FILE}","messages":[{{"role":"user","content":"请用50字介绍你自己。"}}],"max_tokens":128,"temperature":0.7}}'"'"' || true
        echo
        '
        """
    )
    out, err, _ = run(client, cmd, timeout=180)
    print(out, end="")
    if err:
        print(err, end="")


def arm_autostart(client: paramiko.SSHClient) -> None:
    upload(client)
    cmd = textwrap.dedent(
        f"""\
        bash -lc '
        pkill -f "{REMOTE_DIR}/auto_start_server.sh" || true
        nohup bash {REMOTE_DIR}/auto_start_server.sh > {REMOTE_DIR}/autostart.log 2>&1 &
        echo $! > {REMOTE_DIR}/autostart.pid
        ps -p $(cat {REMOTE_DIR}/autostart.pid) -o pid,etime,cmd
        '
        """
    )
    out, err, _ = run(client, cmd, timeout=120)
    print(out, end="")
    if err:
        print(err, end="")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "action",
        choices=[
            "start",
            "status",
            "watch",
            "start-server",
            "test-server",
            "arm-autostart",
        ],
    )
    parser.add_argument("--loops", type=int, default=4)
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()

    client = ssh_connect(args.host, args.port, args.user, args.password)
    try:
        if args.action == "start":
            start_download(client)
        elif args.action == "status":
            status(client)
        elif args.action == "start-server":
            start_server(client)
        elif args.action == "test-server":
            test_server(client)
        elif args.action == "arm-autostart":
            arm_autostart(client)
        else:
            watch(client, args.loops, args.interval)
    finally:
        client.close()


if __name__ == "__main__":
    main()
