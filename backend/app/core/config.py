"""全局路径与配置。"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATA_DIR = Path(os.environ.get("STOCK_ADVISOR_DATA", PROJECT_ROOT / "data"))
DB_PATH = DATA_DIR / "stock_advisor.db"
QUOTES_DIR = DATA_DIR / "quotes"
FINANCIALS_DIR = DATA_DIR / "financials"

# 首次同步的默认起始日（避免拉取全部上市史）
DEFAULT_START_DATE = "20180101"

# 每次 akshare 请求之间的最小间隔（秒），防止被数据源限频
# 数据源会按 IP 限频并直接断连(RemoteDisconnected)，需保守设置
REQUEST_INTERVAL_SEC = 1.0


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    QUOTES_DIR.mkdir(parents=True, exist_ok=True)
    FINANCIALS_DIR.mkdir(parents=True, exist_ok=True)


SCREEN_TOP_N = 100

WATCHLIST_PATH = DATA_DIR / "watchlist.txt"

def _load_env_file() -> None:
    """从 .env 读取环境变量，已存在的环境变量优先（不覆盖）。

    为什么需要：GLM_API_KEY 只从环境变量读，而 tmux 重启会丢掉 shell 环境，
    导致每次重启 API 都变成「未配置」。用文件持久化避免重复踩坑。
    """
    for candidate in (PROJECT_ROOT / "backend" / ".env", PROJECT_ROOT / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
        break


_load_env_file()

# LLM（智谱 GLM）：key 只存服务端环境变量，禁止下发前端
GLM_API_KEY = os.environ.get("GLM_API_KEY", "")
GLM_MODEL = os.environ.get("GLM_MODEL", "glm-4-flash")
GLM_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_TIMEOUT_SEC = 60.0
CHAT_HISTORY_LIMIT = 20  # 单次请求喂给 LLM 的最近消息条数（防超长）
