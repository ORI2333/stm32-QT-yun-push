import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


def stream_output(name: str, pipe):
    try:
        for line in iter(pipe.readline, b""):
            text = decode_output_line(line).rstrip("\r\n")
            if text:
                print(f"[{name}] {text}", flush=True)
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def decode_output_line(raw: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def terminate_process(proc: subprocess.Popen, name: str):
    if proc.poll() is not None:
        return

    print(f"Stopping {name}...", flush=True)
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
    except Exception:
        pass

    deadline = time.time() + 5
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.2)

    try:
        proc.kill()
    except Exception:
        pass


def _resolve_cmd_paths_for_frozen(args):
    base_dir = Path(sys.executable).resolve().parent
    qt_exe = args.qt_exe or "AliyunQtHost.exe"
    web_exe = args.web_exe or "WebDashboard.exe"

    qt_path = Path(qt_exe)
    web_path = Path(web_exe)
    if not qt_path.is_absolute():
        qt_path = (base_dir / qt_path).resolve()
    if not web_path.is_absolute():
        web_path = (base_dir / web_path).resolve()

    if not qt_path.exists() or not web_path.exists():
        print(
            f"Missing exe: qt={qt_path} exists={qt_path.exists()}, "
            f"web={web_path} exists={web_path.exists()}",
            flush=True,
        )
        return None, None, None

    return [str(qt_path)], [str(web_path)], str(base_dir)


def _resolve_cmd_paths_for_script(args):
    host_dir = Path(args.host_dir).resolve()
    qt_path = host_dir / "qt.py"
    web_path = host_dir / "web_dashboard.py"
    if not qt_path.exists() or not web_path.exists():
        print("qt.py or web_dashboard.py not found.", flush=True)
        return None, None, None

    return [args.python, str(qt_path)], [args.python, str(web_path)], str(host_dir.parent)


def main():
    parser = argparse.ArgumentParser(
        description="Start Qt app and Web dashboard together."
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable path for child processes.",
    )
    parser.add_argument(
        "--host-dir",
        default=str(Path(__file__).resolve().parent),
        help="Directory containing qt.py and web_dashboard.py.",
    )
    parser.add_argument(
        "--qt-exe",
        default="",
        help="Qt exe path (for frozen mode). Default: AliyunQtHost.exe in current exe dir.",
    )
    parser.add_argument(
        "--web-exe",
        default="",
        help="Web exe path (for frozen mode). Default: WebDashboard.exe in current exe dir.",
    )
    args = parser.parse_args()

    if getattr(sys, "frozen", False):
        qt_cmd, web_cmd, run_cwd = _resolve_cmd_paths_for_frozen(args)
        if not qt_cmd:
            return 2
        print("Running in frozen mode (exe launcher).", flush=True)
    else:
        qt_cmd, web_cmd, run_cwd = _resolve_cmd_paths_for_script(args)
        if not qt_cmd:
            return 2
        print(f"Using Python: {args.python}", flush=True)

    popen_kwargs = {
        "cwd": run_cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": False,
        "bufsize": 0,
    }

    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    print("Starting Qt and Web dashboard...", flush=True)
    print(f"QT cmd : {' '.join(qt_cmd)}", flush=True)
    print(f"WEB cmd: {' '.join(web_cmd)}", flush=True)

    qt_proc = subprocess.Popen(qt_cmd, **popen_kwargs)
    web_proc = subprocess.Popen(web_cmd, **popen_kwargs)

    threads = [
        threading.Thread(target=stream_output, args=("QT", qt_proc.stdout), daemon=True),
        threading.Thread(target=stream_output, args=("WEB", web_proc.stdout), daemon=True),
    ]
    for t in threads:
        t.start()

    print("Open dashboard in browser: http://127.0.0.1:8000/", flush=True)
    print("Press Ctrl+C to stop both processes.", flush=True)

    exit_code = 0
    try:
        while True:
            qt_code = qt_proc.poll()
            web_code = web_proc.poll()

            if qt_code is not None:
                print(f"QT process exited with code {qt_code}", flush=True)
                exit_code = qt_code or 0
                break

            if web_code is not None:
                print(f"WEB process exited with code {web_code}", flush=True)
                exit_code = web_code or 0
                break

            time.sleep(0.3)
    except KeyboardInterrupt:
        print("Keyboard interrupt received.", flush=True)
    finally:
        terminate_process(qt_proc, "qt")
        terminate_process(web_proc, "web")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
