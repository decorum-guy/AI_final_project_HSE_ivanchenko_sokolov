import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "watchdog.log"
BOT_COMMAND = [sys.executable, "-u", "-m", "app.bot.main"]


def configure_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    logging.info("Stopping bot process PID=%s", process.pid)
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        logging.warning("Bot did not stop in time, killing PID=%s", process.pid)
        process.kill()


def main() -> None:
    configure_logging()
    process: subprocess.Popen[str] | None = None
    restart_delay = 5
    max_delay = 60

    def handle_stop(signum, frame) -> None:
        logging.info("Watchdog received signal %s", signum)
        if process:
            stop_process(process)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_stop)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, handle_stop)

    while True:
        try:
            logging.info("Starting bot: %s", " ".join(BOT_COMMAND))
            process = subprocess.Popen(
                BOT_COMMAND,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=os.environ.copy(),
            )
            logging.info("Bot started PID=%s", process.pid)
            stdout, stderr = process.communicate()
            logging.error("Bot process exited with return code %s", process.returncode)
            if stdout:
                logging.info("Bot stdout:\n%s", stdout[-4000:])
            if stderr:
                logging.error("Bot stderr:\n%s", stderr[-4000:])
            logging.info("Restarting bot in %s seconds", restart_delay)
            time.sleep(restart_delay)
            restart_delay = min(max_delay, restart_delay * 2)
        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt received")
            if process:
                stop_process(process)
            break
        except Exception:
            logging.exception("Critical watchdog error")
            time.sleep(restart_delay)
            restart_delay = min(max_delay, restart_delay * 2)


if __name__ == "__main__":
    main()
