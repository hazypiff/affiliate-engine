"""Network postback adapters: each network's S2S callback format -> (subid, revenue, raw).

Written once per network, reused for every tenant on that network. Networks without
S2S fall back to the attribution-window censored accounting (expiry job) automatically.
"""


class PostbackError(ValueError):
    pass


def parse_mocknet(params: dict) -> tuple[str, float, dict]:
    """Test/reference adapter: ?subid=...&payout=..."""
    try:
        return params["subid"], float(params["payout"]), dict(params)
    except (KeyError, ValueError) as e:
        raise PostbackError(f"bad mocknet postback: {e}") from e


def parse_generic(params: dict) -> tuple[str, float, dict]:
    """Generic adapter: accepts common subid/clickid + payout/amount/revenue names."""
    subid = params.get("subid") or params.get("clickid") or params.get("click_id")
    amount = params.get("payout") or params.get("amount") or params.get("revenue")
    if not subid or amount is None:
        raise PostbackError("generic postback needs subid/clickid and payout/amount/revenue")
    return subid, float(amount), dict(params)


ADAPTERS = {"mocknet": parse_mocknet, "generic": parse_generic}


def parse(network: str, params: dict) -> tuple[str, float, dict]:
    if network not in ADAPTERS:
        raise PostbackError(f"unknown network: {network}")
    return ADAPTERS[network](params)
