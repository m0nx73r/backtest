"""Constants for the ggshot_v2 backtest (coins, periods, account rules, gates)."""

from core.config import FEE_MAKER, FEE_TAKER  # noqa: F401  (re-exported)

COINS = [f"{c}USDT" for c in (
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX",
    "LINK", "DOT", "LTC", "NEAR", "UNI", "AAVE", "FIL",
)]
TIMEFRAMES = ["1h", "30m"]

START = "2021-01-01"
SPLIT = "2025-01-01"

ACCOUNT = 5000.0
FLOOR = 4700.0
PASS_LEVEL = 5500.0
RISK_USD = 20.0
RISK_USD_ALT = 25.0
MAX_OPEN = 3
SLIPPAGE = 0.0002

DATA_DIR = "data/futures"
REPORT_DIR = "reports/ggshot_v2"
TRADE_CACHE_DIR = "data/futures/trades_cache/v1"   # resumable resolved-trade store (data/futures is gitignored)

MIN_IS_TRADES = 150
MIN_OOS_TRADES = 100
MAX_FINALISTS = 3
BOOTSTRAP_RUNS = 5000
BOOTSTRAP_GATE = 0.65
MAX_DD = 0.10
MIN_WIN_RATE = 0.40
MAX_COIN_SHARE = 0.30
TOP_TRADES_REMOVED = 5
MIN_BAR_COVERAGE = 0.9
