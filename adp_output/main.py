from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI()

# Item models
class ItemBase(BaseModel):
    name: str

class ItemCreate(ItemBase):
    pass

class Item(ItemBase):
    id: int

# TODO: ItemUpdate model definition is missing
# class ItemUpdate(BaseModel):
#     ...

# In-memory storage for items
items = {}

@app.post("/items", status_code=201)
def create_item(item: ItemCreate):
    new_id = len(items) + 1
    new_item = Item(id=new_id, **item.dict())
    items[new_id] = new_item
    return new_item

@app.get("/items/{item_id}")
def get_item(item_id: int):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    return items[item_id]

# Order models
class OrderBase(BaseModel):
    product_id: int = Field(..., description="The ID of the product.")
    quantity: int = Field(..., description="The quantity of the product ordered.")
    price: float = Field(..., description="The price per unit of the product.")

class OrderCreate(OrderBase):
    pass

class OrderUpdate(OrderBase):
    pass

class Order(OrderBase):
    id: int

# In-memory storage for orders
orders = {}

@app.post("/orders", status_code=201)
def create_order(order: OrderCreate):
    new_id = len(orders) + 1
    order = Order(id=new_id, **order.dict())
    orders[new_id] = order
    return order

@app.get("/orders/{order_id}")
def get_order(order_id: int):
    if order_id not in orders:
        raise HTTPException(status_code=404, detail="Order not found")
    return orders[order_id]

@app.get("/orders")
def list_orders():
    return list(orders.values())

@app.put("/items/{item_id}")
def update_item(item_id: int, item: ItemUpdate):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    stored = items[item_id]
    update_data = item.dict(exclude_unset=True)
    updated = stored.copy(update=update_data)
    items[item_id] = updated
    return updated

@app.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: int):
    if order_id not in orders:
        raise HTTPException(status_code=404, detail="Order not found")
    del orders[order_id]
    return Response(status_code=204)