import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    """Minimal .env loader for local development (Render injects real env vars)."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "4"))
# In-process scheduler: syncs shortly after every draw while the web service is awake.
ENABLE_SCHEDULER = os.environ.get("ENABLE_SCHEDULER", "1") == "1"
PUBLISH_DELAY = 40                # seconds after a draw before its numbers are usually published

PREDICT_STARS = (3, 4, 5, 6)      # games shown on the site
HISTORY_FOR_PREDICTION = 12000    # draws loaded to rank numbers for the next draw
LOGIT_TRAIN_LEN = 10000           # draws the logistic model is refit on before each prediction
