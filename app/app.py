from datetime import datetime
from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Depends ,Query
from app.schemas import PostCreate, PostResponse, UserRead, UserCreate, UserUpdate , ChatRead, ChatCreate ,ChatMessageCreate, ChatMessageRead
from app.db import Post, create_db_and_tables, get_async_session, User, Comments,Likes,Message,Chat,ChatMessage
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
from sqlalchemy import UUID, select, func , and_, or_
from app.images import imagekit
from typing import Optional
from app.schemas import MessageCreate

from imagekitio.models.UploadFileRequestOptions import UploadFileRequestOptions
import shutil
import os
import uuid
import tempfile
from app.users import auth_backend, current_active_user, fastapi_users

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan)

app.include_router(fastapi_users.get_auth_router(auth_backend), prefix='/auth/jwt', tags=["auth"])
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_verify_router(UserRead), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"])

@app.post("/upload")
async def upload_file(
        file: UploadFile = File(...),
        caption: str = Form(""), 
        category:str =Form(""),
        user: User = Depends(current_active_user),
        session: AsyncSession = Depends(get_async_session)
):
    temp_file_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            temp_file_path = temp_file.name
            shutil.copyfileobj(file.file, temp_file)

        upload_result = imagekit.upload_file(
            file=open(temp_file_path, "rb"),
            file_name=file.filename,
            options=UploadFileRequestOptions(
                use_unique_file_name=True,
                tags=["backend-upload"]
            )
        )

        if upload_result.response_metadata.http_status_code == 200:
            post = Post(
                user_id=user.id,
                caption=caption,
                url=upload_result.url,
                file_type="video" if file.content_type.startswith("video/") else "image",
                file_name=upload_result.name,
                category=category
            )
            session.add(post)
            await session.commit()
            await session.refresh(post)
            return post

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        file.file.close()

@app.get("/feed")
async def get_feed(
        category:Optional[str]=Query(None,description="Filter by category"),
        session: AsyncSession = Depends(get_async_session),
        user: User = Depends(current_active_user),
): 
    try:
        print("feed request:", category, user.id)

        query_stmt=select(Post).order_by(Post.created_at.desc())

        if category is not None :
            query_stmt=query_stmt.where(Post.category == category)
        

        result = await session.execute(query_stmt)
        posts = [row[0] for row in result.all()]

        result_users = await session.execute(select(User))
        users = [row[0] for row in result_users.all()]
        user_dict = {u.id: u.email for u in users}

        posts_data = []
        for post in posts:

            result_likes = await session.execute(
                select(func.count(Likes.id)).where(Likes.post_id == post.id)
            )
            like_count = result_likes.scalar() or 0

            posts_data.append(
                {
                    "id": str(post.id),
                    "user_id": str(post.user_id),
                    "caption": post.caption,
                    "url": post.url,
                    "file_type": post.file_type,
                    "file_name": post.file_name,
                    "created_at": post.created_at.isoformat(),
                    "category":post.category,
                    "is_owner": post.user_id == user.id,
                    "email": user_dict.get(post.user_id, "Unknown"),
                    "like_count": like_count
                }
            )

        return {"posts": posts_data}
    except Exception as e:
        print("❌ FEED ERROR:", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/posts/{post_id}")
async def delete_post(post_id: str, session: AsyncSession = Depends(get_async_session), user: User = Depends(current_active_user),):
    try:
        post_uuid = uuid.UUID(post_id)

        result = await session.execute(select(Post).where(Post.id == post_uuid))
        post = result.scalars().first()

        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        if post.user_id != user.id:
            raise HTTPException(status_code=403, detail="You don't have permission to delete this post")

        await session.delete(post)
        await session.commit()

        return {"success": True, "message": "Post deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/posts/{post_id}/comments")
async def get_comments(
        post_id: str,
        session: AsyncSession = Depends(get_async_session),
        user: User = Depends(current_active_user),
):
    try:
        post_uuid = uuid.UUID(post_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid post_id UUID")
    
    result = await session.execute(select(Comments).where(Comments.post_id == post_uuid).order_by(Comments.created_at.desc()))
    comments_by_post = [row[0] for row in result.all()] 

    if not comments_by_post:
        return{"comments": []}
    
    comments_by_post_data = []
    for comment in comments_by_post:
        comments_by_post_data.append(
            {
                "id": str(comment.id),
                "user_id": str(comment.user_id),
                "post_id": str(comment.post_id),
                "description": comment.description,
                "created_at": comment.created_at.isoformat()
            }
        )

    return {"comments": comments_by_post_data}



@app.post("/posts/{post_id}/createcomment")
async def create_comment(
        post_id: str ,
        description: str= Form(...),     
        user: User = Depends(current_active_user),
        session: AsyncSession = Depends(get_async_session)
):

    try:
        post_uuid = uuid.UUID(post_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid post_id UUID")
    

    result = await session.execute(select(Post).where(Post.id == post_uuid))
    post = result.first
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    comment=Comments(
        id=uuid.uuid4(),
        post_id=post_uuid,
        user_id=user.id,
        description=description,
        created_at=datetime.utcnow()
        )

    session.add(comment)
    await session.commit()
    await session.refresh(comment)
            

    return{
        "id": str(comment.id),
        "post_id": str(comment.post_id),
        "user_id": str(comment.user_id),
        "description": comment.description,
        "created_at": comment.created_at.isoformat()
    }

@app.delete("/comments/{comment_id}")
async def delete_comment(
        comment_id: str,
        
        user: User = Depends(current_active_user),
        session: AsyncSession = Depends(get_async_session)
):
    try:
        comment_uuid = uuid.UUID(comment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid comment_id UUID")

    result = await session.execute(
        select(Comments).where(Comments.id == comment_uuid)
    )
    comment = result.scalars().first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Optional: restrict user so they can delete only their own comment
    if comment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not allowed")

    await session.delete(comment)
    await session.commit()

    return {"message": "Comment deleted"}

@app.post("/posts/{post_id}/like")
async def toggle_like(
        post_id: str,
        user: User = Depends(current_active_user),
        session: AsyncSession = Depends(get_async_session)
):
    # Validate post_id
    try:
        post_uuid = uuid.UUID(post_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid post_id UUID")

    # Check if the post exists (optional, recommended)
    result_post = await session.execute(select(Post).where(Post.id == post_uuid))
    post = result_post.scalars().first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Check if like already exists
    result_like = await session.execute(
        select(Likes).where(Likes.post_id == post_uuid, Likes.user_id == user.id)
    )
    like = result_like.scalars().first()

    if like:
        # Unlike
        await session.delete(like)
        await session.commit()
        return {"liked": False, "message": "Post unliked"}

    # Add new like
    new_like = Likes(post_id=post_uuid, user_id=user.id)
    session.add(new_like)
    await session.commit()
    await session.refresh(new_like)

    return {"liked": True, "message": "Post liked"}

@app.get("/posts/{post_id}/likes")
async def get_likes(
        post_id: str,
        session: AsyncSession = Depends(get_async_session)
):
    try:
        post_uuid = uuid.UUID(post_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid post_id UUID")

    result = await session.execute(
        select(func.count(Likes.id)).where(Likes.post_id == post_uuid)
    )
    count = result.scalar()

    return {"likes": count}



@app.get("/posts/liked")
async def get_my_liked_posts(
    user: User =Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    result= await session.execute(
        select(Post)
        .join(likes,likes.post_id == Post.id)
        .where(likes.user_id == user.id)
        .order_by(Post.created_at.desc())
    )
    posts=result.scalars().all()

    posts_data=[]
    for post in posts:
        result_likes = await session.execute(
            select(func.count(Likes.id)).where(Likes.post_id == post.id)
        )
        like_count = result_likes.scalar() or 0 

        posts_data.append({
            "id": str(post.id),
            "user_id": str(post.user_id),
            "caption": post.caption,
            "url": post.url,
            "file_type": post.file_type,
            "file_name": post.file_name,
            "created_at": post.created_at.isoformat(),
            "category": post.category,
            "like_count": like_count
        })

    return {"liked_posts": posts_data}
    

@app.get("/search")
async def search_posts(
    query: str,
    category:Optional[str]=None,
    session:AsyncSession=Depends(get_async_session)
):
    try:
        query_stmt=select(Post).where(Post.caption.ilike(f"%{query}%"))

        if category:
            query_stmt=query_stmt.where(Post.category == category)
        result = await session.execute(query_stmt)
        posts=result.scalars().all()

        posts_data = []
        for post in posts:
            posts_data.append({
                "id":str(post.id),
                "user_id":str(post.user_id),
                "caption": post.caption,
                "url": post.url,
                "file_type": post.file_type, 
                "file_name": post.file_name,
                "created_at":post.created_at.isoformat(),
                "category":post.category


            })
        return {"posts": posts_data} 
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

""""
@app.post("/messages/send")  
async def send_message(
    data:MessageCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    try:
        receiver_uuid= uuid.UUID(data.receiver_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid receiver_id")
    
    message=Message(
        sender_id=user.id,
        receiver_id=receiver_uuid,
        content=data.content
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)

    return {
        "id": str(message.id),
        "sender_id": str(message.sender_id),
        "receiver_id": str(message.receiver_id),
        "content": message.content,
        "created_at": message.created_at.isoformat()
    }

@app.get("/messages/{other_user_id}")
async def get_messages(
    other_user_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    try:
        other_uuid = uuid.UUID(other_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID")

    query = select(Message).where(
        or_(
            and_(Message.sender_id == user.id, Message.receiver_id == other_uuid),
            and_(Message.sender_id == other_uuid, Message.receiver_id == user.id)
        )
    ).order_by(Message.created_at.asc())

    result = await session.execute(query)
    messages = result.scalars().all()

    return [
        {
            "id": str(msg.id),
            "sender_id": str(msg.sender_id),
            "receiver_id": str(msg.receiver_id),
            "content": msg.content,
            "created_at": msg.created_at.isoformat()
        } for msg in messages
    ]
"""

# Create or get a chat between two users
@app.post("/chats/", response_model=ChatRead)
async def create_or_get_chat(
    data: ChatCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    try:
        other_uuid = uuid.UUID(data.other_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID")

    # Check if chat already exists
    query = select(Chat).where(
        or_(
            and_(Chat.user1_id == user.id, Chat.user2_id == other_uuid),
            and_(Chat.user1_id == other_uuid, Chat.user2_id == user.id)
        )
    )
    result = await session.execute(query)
    chat = result.scalars().first()
    
    if chat:
        return chat

    # Create new chat
    chat = Chat(id=uuid.uuid4(), user1_id=user.id, user2_id=other_uuid)
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    return chat

# Send a message in a chat
@app.post("/chats/{chat_id}/messages", response_model=ChatMessageRead)
async def send_chat_message(
    chat_id: str,
    data: ChatMessageCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    try:
        chat_uuid = uuid.UUID(chat_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chat ID")

    # Check if chat exists
    result = await session.execute(select(Chat).where(Chat.id == chat_uuid))
    chat = result.scalars().first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    message = ChatMessage(chat_id=chat_uuid, sender_id=user.id, content=data.content)
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message

# Get messages from a chat
@app.get("/chats/{chat_id}/messages", response_model=list[ChatMessageRead])
async def get_chat_messages(
    chat_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    try:
        chat_uuid = uuid.UUID(chat_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chat ID")

    # Verify chat exists and user is participant
    result = await session.execute(select(Chat).where(Chat.id == chat_uuid))
    chat = result.scalars().first()
    if not chat or user.id not in [chat.user1_id, chat.user2_id]:
        raise HTTPException(status_code=404, detail="Chat not found")

    result = await session.execute(
        select(ChatMessage).where(ChatMessage.chat_id == chat_uuid).order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()
    return messages

# Get all chats of a user
@app.get("/chats/", response_model=list[ChatRead])
async def get_my_chats(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    result = await session.execute(
        select(Chat).where(or_(Chat.user1_id == user.id, Chat.user2_id == user.id)).order_by(Chat.created_at.desc())
    )
    chats = result.scalars().all()
    return chats


