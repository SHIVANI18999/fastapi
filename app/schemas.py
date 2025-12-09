from pydantic import BaseModel
from fastapi_users import schemas
from datetime import datetime
import uuid

class PostCreate(BaseModel):
    title: str
    content: str 
    category: str

class PostResponse(BaseModel):
    title: str
    content: str 
    category: str

"""

class MessageCreate(BaseModel):
    receiver_id:str 
    content: str 

class MessageRead(BaseModel):
    id: uuid.UUID 
    sender_id: uuid.UUID 
    receiver_id: uuid.UUID
    content: str
    created_at: datetime 

"""

class ChatCreate(BaseModel):
    other_user_id: str  # UUID of the other participant

class ChatMessageCreate(BaseModel):
    content: str

class ChatRead(BaseModel):
    id: uuid.UUID
    user1_id: uuid.UUID
    user2_id: uuid.UUID
    created_at: datetime

class ChatMessageRead(BaseModel):
    id: uuid.UUID
    chat_id: uuid.UUID
    sender_id: uuid.UUID
    content: str
    created_at: datetime

class UserRead(schemas.BaseUser[uuid.UUID]):
    pass

class UserCreate(schemas.BaseUserCreate):
    pass

class UserUpdate(schemas.BaseUserUpdate):
    pass