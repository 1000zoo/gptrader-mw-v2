from enum import Enum

class SymbolConstants(Enum):
    FILTERS_TYPE_PRICE_FILTER = 0
    FILTERS_TYPE_LOT_SIZE = 1
    FILTERS_TYPE_MARKET_LOT_SIZE = 2
    FILTERS_TYPE_MAX_NUM_ORDERS = 3
    FILTERS_TYPE_MAX_NUM_ALGO_ORDERS = 4
    FILTERS_TYPE_MIN_NOTIONAL = 5
    FILTERS_TYPE_PERCENT_PRICE = 6



def _get_filter(filters: list[dict], filter_type: str) -> dict:
    return next((item for item in filters if item.get("filterType") == filter_type), {})


def exchange_info_serializer(data: dict):
    filters = data.get("filters", [])
    price_filter = _get_filter(filters, "PRICE_FILTER")
    lot_size = _get_filter(filters, "LOT_SIZE")
    market_lot_size = _get_filter(filters, "MARKET_LOT_SIZE")
    max_num_orders = _get_filter(filters, "MAX_NUM_ORDERS")
    max_num_algo_orders = _get_filter(filters, "MAX_NUM_ALGO_ORDERS")
    min_notional = _get_filter(filters, "MIN_NOTIONAL")
    percent_price = _get_filter(filters, "PERCENT_PRICE")

    return {
        "symbol": data["symbol"],
        "pair": data.get("pair"),
        "status": data["status"],
        "baseAssetPrecision": data.get("baseAssetPrecision"),
        "quotePrecision": data["quotePrecision"],
        "maxPrice": price_filter.get("maxPrice"),
        "minPrice": price_filter.get("minPrice"),
        "tickSize": price_filter.get("tickSize"),
        "maxQty": lot_size.get("maxQty"),
        "minQty": lot_size.get("minQty"),
        "stepSize": lot_size.get("stepSize"),
        "marketMaxQty": market_lot_size.get("maxQty"),
        "marketMinQty": market_lot_size.get("minQty"),
        "marketStepSize": market_lot_size.get("stepSize"),
        "maxNumOrders": max_num_orders.get("limit"),
        "maxNumAlgoOrders": max_num_algo_orders.get("limit"),
        # "minNotional": min_notional.get("notional"),
        "orderTypes": ",".join(data["orderTypes"]),
        "timeInForce": ",".join(data["timeInForce"]),
        "permissionSets": ",".join(data["permissionSets"])
    }
