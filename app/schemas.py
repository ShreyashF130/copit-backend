from pydantic import BaseModel

class StatusUpdate(BaseModel):
    order_id: int
    new_status: str

class BroadcastRequest(BaseModel):
    shop_id: int
    message: str
    image_url: str
    limit: int

class UpgradeRequest(BaseModel):
    shop_id: int
    plan: str
    payment_id: str