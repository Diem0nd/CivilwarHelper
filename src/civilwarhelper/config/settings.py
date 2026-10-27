import logging
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# 쉼표로 구분된 테스트 서버 ID 파싱
TEST_GUILD_IDS: list[int] = []
for raw in os.getenv("TEST_GUILD_IDS", "").split(","):
    raw = raw.strip()
    if not raw:
        continue
    try:
        TEST_GUILD_IDS.append(int(raw))
    except ValueError:
        logging.warning("잘못된 TEST_GUILD_IDS 값 무시: %r", raw)
