"""Charge a caller's items/coin atomically for an upgrade or purchase.

Each helper checks affordability first and writes nothing unless the whole bill can be
paid, so an operation can never half-charge and then fail. Call inside the operation's
own DB transaction.
"""

from db.user import add_currency, get_currencys, get_items, increment_item_stocks


async def item_stock(conn, user_id: int) -> dict:
    """Everything the caller owns, ``{itemMasterId: stock}``."""
    return {i.itemMasterId: i.stock for i in await conn.fetch(get_items(user_id))}


async def pay_items(conn, user_id: int, cost: dict, stock: dict | None = None) -> bool:
    """Charge a whole item bill (``{itemMasterId: quantity}``) in one statement.
    Returns False (writing nothing) if any line is unaffordable."""
    cost = {i: q for i, q in cost.items() if q}
    if not cost:
        return True
    if stock is None:
        stock = await item_stock(conn, user_id)
    if any(stock.get(item, 0) < quantity for item, quantity in cost.items()):
        return False
    await conn.execute(
        increment_item_stocks(user_id, [(i, -q) for i, q in cost.items()])
    )
    return True


async def pay_coin(conn, user_id: int, amount: int) -> bool:
    """Charge ``amount`` coin. Returns False (writing nothing) if the balance is short."""
    if amount <= 0:
        return True
    currency = next(iter(await conn.fetch(get_currencys(user_id))), None)
    if currency is None or currency.coin < amount:
        return False
    await conn.execute(add_currency(user_id, coin=-amount))
    return True
