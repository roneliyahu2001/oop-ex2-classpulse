"""Start ClassPulse:  python3 run.py  [--port 8000] [--pin 1234] [--public-url URL]"""
from __future__ import annotations

import argparse
import os
import secrets
import socket

from classpulse.app import ClassPulseApp, Config
from classpulse.llm import build_llm_client
from classpulse.web import make_server


def lan_ip() -> str:
    """The address phones on the same Wi-Fi / hotspot can reach."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    p = argparse.ArgumentParser(description="ClassPulse teaching tool")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    p.add_argument("--pin", default=os.environ.get("LECTURER_PIN") or f"{secrets.randbelow(10**4):04d}")
    p.add_argument("--public-url", default=os.environ.get("PUBLIC_URL"))
    p.add_argument("--db", default=os.environ.get("CLASSPULSE_DB", "classpulse.db"))
    p.add_argument("--late-after", type=int, default=15, metavar="MINUTES",
                   help="a check-in later than this many minutes after the start is marked late")
    a = p.parse_args()

    public = (a.public_url or f"http://{lan_ip()}:{a.port}").rstrip("/")
    secret_hex = os.environ.get("CLASSPULSE_SECRET")
    app = ClassPulseApp(Config(db_path=a.db, lecturer_pin=a.pin, public_url=public,
                               late_after_minutes=a.late_after,
                               secret=bytes.fromhex(secret_hex) if secret_hex else b""),
                        llm=build_llm_client())
    srv = make_server(app, port=a.port)
    print(f"""
  ClassPulse is running
  Lecturer dashboard : http://localhost:{a.port}/lecturer   (PIN: {a.pin})
  Students reach it  : {public}   (they scan the QR shown on the dashboard)
  LLM features       : {"Claude API" if app.llm_enabled else "offline mode (set ANTHROPIC_API_KEY to enable)"}
  Stop with Ctrl+C
""")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
