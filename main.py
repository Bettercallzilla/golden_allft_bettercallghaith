import os
import json
import uuid
import time
import tempfile
import requests
from typing import List
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from instagrapi import Client

# Directory to store session settings
SESSIONS_DIR = "/data/sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

app = FastAPI(title="Instagram Full API", version="1.0.0")

# ----- Models -----
class LoginRequest(BaseModel):
    username: str
    password: str

class SendRequest(BaseModel):
    session_id: str
    recipients: List[str]
    message: str
    interval: float = 0.0

class PhotoRequest(BaseModel):
    session_id: str
    image_url: str
    caption: str = ""

class StoryRequest(BaseModel):
    session_id: str
    file_url: str
    is_video: bool = False

class LikeRequest(BaseModel):
    session_id: str
    media_id: str

class CommentRequest(BaseModel):
    session_id: str
    media_id: str
    text: str

class DeleteCommentRequest(BaseModel):
    session_id: str
    media_id: str
    comment_id: str

class FollowRequest(BaseModel):
    session_id: str
    username: str

class ReelRequest(BaseModel):
    session_id: str
    file_url: str
    caption: str = ""

def load_client(session_id: str) -> Client:
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Session not found")
    settings = json.load(open(path))
    client = Client()
    client.set_settings(settings)
    return client

def save_settings(client: Client, session_id: str):
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    json.dump(client.get_settings(), open(path, "w"))

# ----- Session Endpoints -----
@app.post("/login")
async def login(req: LoginRequest):
    client = Client()
    try:
        client.login(req.username, req.password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Login failed: {e}")
    session_id = str(uuid.uuid4())
    with open(os.path.join(SESSIONS_DIR, f"{session_id}.json"), "w") as f:
        json.dump(client.get_settings(), f)
    return {"session_id": session_id}

@app.get("/sessions")
async def list_sessions():
    files = os.listdir(SESSIONS_DIR)
    return {"sessions": [f.replace(".json", "") for f in files if f.endswith(".json")]}

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return {"deleted": session_id}
    raise HTTPException(status_code=404, detail="Session not found")

# ----- DM Endpoints -----
@app.post("/send")
async def send_dm(req: SendRequest):
    client = load_client(req.session_id)
    results = {}
    for user in req.recipients:
        try:
            uid = client.user_id_from_username(user)
            client.direct_send(req.message, [uid])
            results[user] = "sent"
        except Exception as e:
            results[user] = f"error: {e}"
        if req.interval > 0:
            time.sleep(req.interval)
    save_settings(client, req.session_id)
    return {"results": results}

# ----- Media & Stories -----
@app.post("/upload_photo")
async def upload_photo(req: PhotoRequest):
    client = load_client(req.session_id)
    # Download image
    r = requests.get(req.image_url, stream=True)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to download image")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    for chunk in r.iter_content(1024):
        tmp.write(chunk)
    tmp.close()
    media = client.photo_upload(tmp.name, caption=req.caption)
    os.unlink(tmp.name)
    save_settings(client, req.session_id)
    return {"media_id": media.pk}

@app.post("/upload_story")
async def upload_story(req: StoryRequest):
    client = load_client(req.session_id)
    r = requests.get(req.file_url, stream=True)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to download file")
    suffix = ".mp4" if req.is_video else ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    for chunk in r.iter_content(1024):
        tmp.write(chunk)
    tmp.close()
    if req.is_video:
        story = client.story_upload_video(tmp.name)
    else:
        story = client.story_upload_photo(tmp.name)
    os.unlink(tmp.name)
    save_settings(client, req.session_id)
    return {"story_id": story.pk}

# ----- Feed & Profiles -----
@app.get("/feed")
async def get_feed(session_id: str = Query(...)):
    client = load_client(session_id)
    feed = client.feed_timeline()
    return {"feed": [m.dict() for m in feed]}

@app.get("/user/{username}")
async def get_user(username: str, session_id: str = Query(...)):
    client = load_client(session_id)
    uid = client.user_id_from_username(username)
    info = client.user_info(uid)
    return info.dict()

@app.get("/user/{username}/posts")
async def get_user_posts(username: str, session_id: str = Query(...), amount: int = Query(10)):
    client = load_client(session_id)
    uid = client.user_id_from_username(username)
    medias = client.user_medias(uid, amount)
    return {"posts": [m.dict() for m in medias]}

# ----- Engagement -----
@app.post("/like")
async def like(req: LikeRequest):
    client = load_client(req.session_id)
    client.media_like(req.media_id)
    save_settings(client, req.session_id)
    return {"liked": req.media_id}

@app.post("/unlike")
async def unlike(req: LikeRequest):
    client = load_client(req.session_id)
    client.media_unlike(req.media_id)
    save_settings(client, req.session_id)
    return {"unliked": req.media_id}

@app.post("/comment")
async def comment(req: CommentRequest):
    client = load_client(req.session_id)
    comment_obj = client.media_comment(req.media_id, req.text)
    save_settings(client, req.session_id)
    return {"comment_id": comment_obj.pk}

@app.post("/delete_comment")
async def delete_comment(req: DeleteCommentRequest):
    client = load_client(req.session_id)
    client.comment_delete(req.media_id, req.comment_id)
    save_settings(client, req.session_id)
    return {"deleted_comment": req.comment_id}

@app.post("/follow")
async def follow(req: FollowRequest):
    client = load_client(req.session_id)
    target = client.user_id_from_username(req.username)
    client.user_follow(target)
    save_settings(client, req.session_id)
    return {"followed": req.username}

@app.post("/unfollow")
async def unfollow(req: FollowRequest):
    client = load_client(req.session_id)
    target = client.user_id_from_username(req.username)
    client.user_unfollow(target)
    save_settings(client, req.session_id)
    return {"unfollowed": req.username}

# ----- Stories & Reels -----
@app.get("/stories/{username}")
async def get_stories(username: str, session_id: str = Query(...)):
    client = load_client(session_id)
    uid = client.user_id_from_username(username)
    stories = client.user_stories(uid)
    return {"stories": [s.dict() for s in stories]}

@app.post("/upload_reel")
async def upload_reel(req: ReelRequest):
    client = load_client(req.session_id)
    r = requests.get(req.file_url, stream=True)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to download reel")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    for chunk in r.iter_content(1024):
        tmp.write(chunk)
    tmp.close()
    clip = client.clip_upload(tmp.name, caption=req.caption)
    os.unlink(tmp.name)
    save_settings(client, req.session_id)
    return {"reel_id": clip.pk}

# ----- Search & Discovery -----
@app.get("/search/users")
async def search_users(q: str, session_id: str = Query(...), amount: int = Query(10)):
    client = load_client(session_id)
    users = client.search_users(q)
    return {"users": [u.dict() for u in users[:amount]]}

@app.get("/search/hashtags/top")
async def search_hashtags(hashtag: str, session_id: str = Query(...), amount: int = Query(5)):
    client = load_client(session_id)
    top = client.hashtag_medias_top(hashtag, amount)
    return {"top_posts": [m.dict() for m in top]}

# ----- Threads -----
@app.get("/threads")
async def list_threads(session_id: str = Query(...)):
    client = load_client(session_id)
    threads = client.direct_threads()
    return {"threads": [t.dict() for t in threads]}

@app.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, session_id: str = Query(...)):
    client = load_client(session_id)
    thread = client.direct_thread(thread_id)
    return {"messages": [msg.dict() for msg in thread.messages]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3013, workers=4)
