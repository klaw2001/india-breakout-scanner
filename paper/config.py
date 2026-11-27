"""Paper-trading rules. Every number here is a knob; change and commit, the server picks it up next morning."""

CAPITAL = 500_000            # paper capital, ₹
RISK_PER_TRADE = 2_500       # ₹ lost if the stop is hit (before charges)
MAX_OPEN = 5                 # positions open at the same time
MAX_TRADES_PER_DAY = 10
LEVERAGE = 5.0               # intraday (MIS) exposure allowed on paper capital
MAX_POSITION_SHARE = 1 / MAX_OPEN   # each position may use at most this share of CAPITAL x LEVERAGE

# Timing (IST, candle *end* times; a 15-minute candle that starts 09:15 ends 09:30)
FIRST_ENTRY = "09:30"        # the opening candle may trigger, but needs OPEN_CANDLE_VOL_MULT volume
LAST_ENTRY = "14:30"         # no new entries on candles ending after this
SQUARE_OFF = "15:15"         # every open position exits at the close of the candle ending 15:15

# Entry filters
REQUIRE_VOLUME = True        # breakout candle volume >= scan's 15m trigger (1.5x avg candle)
OPEN_CANDLE_VOL_MULT = 3.0   # the 09:15 candle must do >= 3x the average candle (it is always heavy)
MAX_CHASE_ATR = 0.5          # skip if the candle closes more than 0.5 x ATR above the trigger
MIN_RR = 1.0                 # skip if (target - entry) < 1.0 x (entry - stop)
GROUPS = ("above", "on", "near1", "near2")

# Fills
SLIPPAGE = 0.0005            # 0.05% worse than the candle price on every fill

# Approximate NSE intraday equity charges (edit if your broker differs)
BROKERAGE_FLAT = 20.0        # ₹ per executed order, or BROKERAGE_PCT if lower
BROKERAGE_PCT = 0.0003
STT_SELL = 0.00025
EXCHANGE_TXN = 0.0000297
SEBI_PER_CRORE = 10.0
STAMP_BUY = 0.00003
GST = 0.18
