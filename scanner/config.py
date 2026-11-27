"""Scan definitions. Every tunable number lives here."""

SECTOR_INDICES = [
    ("^NSEI", "Nifty 50", "NSE:NIFTY"),
    ("^NSEBANK", "Bank Nifty", "NSE:BANKNIFTY"),
    ("NIFTY_FIN_SERVICE.NS", "Nifty Financial Services", "NSE:FINNIFTY"),
    ("^CNXIT", "Nifty IT", "NSE:CNXIT"),
    ("^CNXFMCG", "Nifty FMCG", "NSE:CNXFMCG"),
    ("^CNXAUTO", "Nifty Auto", "NSE:CNXAUTO"),
    ("^CNXPHARMA", "Nifty Pharma", "NSE:CNXPHARMA"),
    ("^CNXMETAL", "Nifty Metal", "NSE:CNXMETAL"),
    ("^CNXREALTY", "Nifty Realty", "NSE:CNXREALTY"),
    ("^CNXENERGY", "Nifty Energy", "NSE:CNXENERGY"),
    ("^CNXPSUBANK", "Nifty PSU Bank", "NSE:CNXPSUBANK"),
    ("^CNXINFRA", "Nifty Infra", "NSE:CNXINFRA"),
]

# Overnight / global context shown on the intraday scan (US close matters for India's open).
GLOBAL_TICKERS = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq Composite"),
    ("^DJI", "Dow Jones"),
    ("INDA", "iShares MSCI India ETF (US-listed)"),
    ("^VIX", "US VIX"),
    ("INR=X", "USD/INR"),
    ("BZ=F", "Brent crude"),
    ("^TNX", "US 10Y yield (%)"),
]

SCANS = {
    "intraday": dict(
        title="India Intraday Breakout Watchlist",
        short="Intraday",
        universe="fo",               # F&O stocks
        period="3y",
        timeframe="D",
        pivot=(3, 2),                # bars left / right that confirm a swing high
        lookback=60,                 # bars searched for breakout levels
        recent=2,                    # a level broken within this many bars still counts as a fresh breakout
        inv_pivot=(3, 2),
        on_tol=0.10,                 # |close vs level| <= this % -> "on"
        bands=(1.0, 2.0),            # near groups: within band1 % below, band1-band2 % below
        max_ext=3.0,                 # more than this % above the level -> extended, not listed
        vol_avg=20,
        vol_min=1.5,
        atr_stop=0.5,                # intraday stop = trigger - 0.5 x ATR14
        atr_target=1.0,              # intraday target = trigger + 1.0 x ATR14 (2R)
        w=dict(pivot=(3, 2), lookback=52, recent=2),
        m=dict(pivot=(2, 2), lookback=36, recent=1),
        indices=SECTOR_INDICES[:3],
        level_word="breakout",
        tf_word="daily",
    ),
    "swing": dict(
        title="India Swing Breakout Scan",
        short="Swing",
        universe="nifty500",
        period="5y",
        timeframe="D",
        pivot=(5, 3),
        lookback=120,
        recent=5,
        inv_pivot=(3, 3),
        on_tol=0.10,
        bands=(1.5, 2.0),
        max_ext=5.0,
        vol_avg=20,
        vol_min=1.5,
        r_multiple=2.0,              # target = breakout + 2 x (breakout - invalidation)
        w=dict(pivot=(3, 2), lookback=52, recent=2),
        m=dict(pivot=(2, 2), lookback=60, recent=1),
        indices=SECTOR_INDICES,
        level_word="breakout",
        tf_word="daily",
    ),
    "longterm": dict(
        title="India Long-Term Breakout Scan",
        short="Long-term",
        universe="allnse",
        min_turnover_cr=5.0,         # 20-day average traded value
        period="10y",
        timeframe="W",
        pivot=(4, 2),
        lookback=104,                # weeks (2 years)
        recent=3,
        inv_pivot=(3, 2),
        on_tol=0.25,
        bands=(3.0, 5.0),
        max_ext=10.0,
        vol_avg=10,                  # weeks
        vol_min=1.5,
        r_multiple=2.0,
        m=dict(pivot=(2, 2), lookback=60, recent=1),
        indices=SECTOR_INDICES,
        level_word="breakout",
        tf_word="weekly",
    ),
}
