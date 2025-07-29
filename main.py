from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import imagehash
from PIL import Image, UnidentifiedImageError
import aiohttp
import io
import pytesseract
from tinydb import TinyDB, Query

app = FastAPI()
db = TinyDB("reference_hashes.json")
QueryRef = Query()

class SSUploadRequest(BaseModel):
    guild_id: int
    url: str

class OCRRequest(BaseModel):
    url: str

class ImageResponse(BaseModel):
    dhash: str
    phash: str
    text: str


async def download_image(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=400, detail="Failed to fetch image")
                return await resp.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Download error: {str(e)}")


def compute_hashes_and_ocr(img: Image.Image):
    return {
        "dhash": str(imagehash.dhash(img)),
        "phash": str(imagehash.phash(img)),
        "text": pytesseract.image_to_string(img)
    }


@app.post("/ss")
async def add_reference_ss(data: SSUploadRequest):
    img_bytes = await download_image(data.url)
    try:
        img = Image.open(io.BytesIO(img_bytes))
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Invalid image format")

    hashes = compute_hashes_and_ocr(img)
    db.insert({
        "guild_id": data.guild_id,
        "dhash": hashes["dhash"],
        "phash": hashes["phash"]
    })
    return {"message": "Reference screenshot stored", "guild_id": data.guild_id, "hashes": hashes}


@app.post("/ocr", response_model=List[ImageResponse])
async def ocr_endpoint(body: List[OCRRequest]):
    results = []
    for item in body:
        img_bytes = await download_image(item.url)
        try:
            img = Image.open(io.BytesIO(img_bytes))
        except UnidentifiedImageError:
            raise HTTPException(status_code=400, detail="Invalid image format")

        hashes = compute_hashes_and_ocr(img)
        results.append(hashes)
    return results


@app.get("/references/{guild_id}")
async def get_references(guild_id: int):
    refs = db.search(QueryRef.guild_id == guild_id)
    return {"guild_id": guild_id, "references": refs}


@app.delete("/references/{guild_id}")
async def clear_references(guild_id: int):
    db.remove(QueryRef.guild_id == guild_id)
    return {"message": "References cleared", "guild_id": guild_id}


@app.post("/compare/{guild_id}")
async def compare_screenshot(guild_id: int, req: OCRRequest):
    img_bytes = await download_image(req.url)
    try:
        img = Image.open(io.BytesIO(img_bytes))
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Invalid image format")

    dhash_new = imagehash.dhash(img)
    phash_new = imagehash.phash(img)

    references = db.search(QueryRef.guild_id == guild_id)
    for ref in references:
        if dhash_new - imagehash.hex_to_hash(ref["dhash"]) <= 5 and phash_new - imagehash.hex_to_hash(ref["phash"]) <= 5:
            return {"match": True, "matched_with": ref}

    return {"match": False}
