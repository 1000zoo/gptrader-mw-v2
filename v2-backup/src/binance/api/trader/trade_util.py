from decimal import Decimal, ROUND_DOWN

def cal_quantity(price, balance, percent, leverage, step_size, precision):
    notional = Decimal(str(balance)) * Decimal(str(percent)) * Decimal(str(leverage))
    raw_qty = notional / Decimal(str(price))

    step = Decimal(str(step_size))
    qty = (raw_qty / step).to_integral_value(rounding=ROUND_DOWN) * step

    # round() 쓰지 말고 quantize로 고정 자릿수 + 문자열
    q = qty.quantize(Decimal("1").scaleb(-precision), rounding=ROUND_DOWN)
    return format(q, "f")