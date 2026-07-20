"""Route layer — FastAPI-shaped decorated handlers (async included)."""

from deps import get, post
from services import OrderFlow, list_orders


@get("/orders")
async def read_orders(user):
    return list_orders(user)


@post("/orders")
async def create_order(payload):
    flow = OrderFlow()
    return flow.place(payload)


@get("/orders/{order_id}")
async def read_order(order_id):
    flow = OrderFlow()
    return flow.fetch(order_id)
