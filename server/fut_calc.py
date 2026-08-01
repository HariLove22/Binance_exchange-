"""COIN-M / USDT-M futures calculator — UI ke numbers verify karne ke liye.

Backend ke bilkul same formulas. Apna actual entry/exit price (jo UI me dikhe) daalo,
aur margin / liq price / PnL nikaal ke Positions panel se match kar lo.

Usage:
  python fut_calc.py                                  # do worked example
  python fut_calc.py coinm long  60000 61000 6000 10  # COIN-M: size = USD notional
  python fut_calc.py usdtm short 60000 59000 0.1  10  # USDT-M: size = base qty (BTC)
    args: mode(coinm|usdtm)  side(long|short)  entry  exit  size  leverage
"""
import sys
from decimal import Decimal as D

FEE = D("0.0004")   # 0.04% taker fee
MMR = D("0.005")    # 0.5% maintenance margin


def calc(mode, side, entry, exit, size, lev):
    entry, exit, size, lev = map(D, (entry, exit, size, lev))
    inv, long = mode == "coinm", side == "long"
    if inv:                                    # COIN-M: sab base coin (BTC) me
        margin = (size / entry) / lev          # (notional_usd / price) / leverage
        base = size * (D(1) / entry - D(1) / exit)
        fee = (size / exit) * FEE
        if long:
            liq = size * (1 + MMR) / (margin + size / entry)
        else:
            denom = size / entry - margin
            liq = size * (1 - MMR) / denom if denom > 0 else D(0)
        unit = "coin"
    else:                                      # USDT-M: sab USDT me
        margin = (size * entry) / lev          # (base_qty * price) / leverage
        base = (exit - entry) * size
        fee = (size * exit) * FEE
        if long:
            liq = (entry * size - margin) / (size * (1 - MMR))
        else:
            liq = (margin + entry * size) / (size * (1 + MMR))
        unit = "USDT"
    pnl = base if long else -base
    print(f"mode={mode} {side} entry={entry} exit={exit} size={size} lev={lev}x")
    print(f"  margin        = {margin.normalize():f} {unit}     <- UI 'Margin'")
    print(f"  liq price     = {liq.normalize():f}              <- UI 'Liq. Price'")
    print(f"  PnL (gross)   = {pnl.normalize():f} {unit}")
    print(f"  fee           = {fee.normalize():f} {unit}")
    print(f"  realized PnL  = {(pnl - fee).normalize():f} {unit}   <- Positions PnL")
    print(f"  back to avail = {(margin + pnl - fee).normalize():f} {unit}   (margin + pnl - fee)")


if len(sys.argv) == 7:
    calc(*sys.argv[1:])
else:
    calc("coinm", "long", "60000", "61000", "6000", "10")
    print()
    calc("usdtm", "long", "60000", "61000", "0.1", "10")
