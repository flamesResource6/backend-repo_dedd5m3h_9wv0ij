import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

# Local database helpers
from database import db, create_document, get_documents
from schemas import Player as PlayerSchema, Match as MatchSchema, Point as PointSchema

app = FastAPI(title="Pickleball Analytics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------- Utility helpers ---------

def oid(oid_str: str) -> ObjectId:
    try:
        return ObjectId(oid_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

def to_serializable(doc: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(doc)
    if doc.get("_id") is not None:
        doc["id"] = str(doc.pop("_id"))
    # stringify any ObjectId fields we know
    for k, v in list(doc.items()):
        if isinstance(v, ObjectId):
            doc[k] = str(v)
    return doc


# --------- Health & Schema ---------

@app.get("/")
def read_root():
    return {"message": "Pickleball Analytics API is running"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from Pickleball Analytics!"}

@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

@app.get("/schema")
def get_schema():
    """Expose Pydantic schemas for external tools/viewers."""
    return {
        "player": PlayerSchema.model_json_schema(),
        "match": MatchSchema.model_json_schema(),
        "point": PointSchema.model_json_schema(),
    }


# --------- Players ---------

class PlayerCreate(PlayerSchema):
    pass

@app.post("/api/players")
def create_player(player: PlayerCreate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    player_id = create_document("player", player)
    return {"id": player_id}

@app.get("/api/players")
def list_players():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    docs = get_documents("player")
    return [to_serializable(d) for d in docs]


# --------- Matches ---------

class MatchCreate(MatchSchema):
    pass

@app.post("/api/matches")
def create_match(match: MatchCreate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    data = match.model_dump()
    # Ensure IDs are stored as ObjectId
    data["player_a_id"] = oid(data["player_a_id"])
    data["player_b_id"] = oid(data["player_b_id"])
    inserted_id = db["match"].insert_one(data).inserted_id
    return {"id": str(inserted_id)}

@app.get("/api/matches/recent")
def recent_matches(limit: int = 10):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    pipeline = [
        {"$sort": {"started_at": -1, "_id": -1}},
        {"$limit": limit},
        {"$lookup": {
            "from": "player",
            "localField": "player_a_id",
            "foreignField": "_id",
            "as": "player_a"
        }},
        {"$lookup": {
            "from": "player",
            "localField": "player_b_id",
            "foreignField": "_id",
            "as": "player_b"
        }},
        {"$unwind": {"path": "$player_a", "preserveNullAndEmptyArrays": True}},
        {"$unwind": {"path": "$player_b", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "player_a": "$player_a.name",
            "player_b": "$player_b.name",
            "location": 1,
            "level": 1,
            "started_at": 1,
            "completed_at": 1,
        }},
    ]
    rows = list(db["match"].aggregate(pipeline))
    return [to_serializable(r) for r in rows]


# --------- Points (Rallies) ---------

class PointCreate(PointSchema):
    pass

@app.post("/api/points")
def create_point(point: PointCreate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    data = point.model_dump()
    data["match_id"] = oid(data["match_id"])
    data["scorer_id"] = oid(data["scorer_id"])
    if data.get("winner_shot") is None:
        data.pop("winner_shot", None)
    inserted_id = db["point"].insert_one(data).inserted_id
    return {"id": str(inserted_id)}


# --------- Analytics ---------

@app.get("/api/analytics/leaderboard")
def leaderboard(limit: int = 10):
    """Top players by total points won and average rally length."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    pipeline = [
        {"$group": {"_id": "$scorer_id", "points_won": {"$sum": 1}, "avg_rally": {"$avg": "$rally_length"}}},
        {"$lookup": {"from": "player", "localField": "_id", "foreignField": "_id", "as": "player"}},
        {"$unwind": {"path": "$player", "preserveNullAndEmptyArrays": True}},
        {"$project": {"player_id": {"$toString": "$_id"}, "name": "$player.name", "points_won": 1, "avg_rally": 1}},
        {"$sort": {"points_won": -1}},
        {"$limit": limit}
    ]
    rows = list(db["point"].aggregate(pipeline))
    return rows

@app.get("/api/analytics/player/{player_id}")
def player_analytics(player_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    player_oid = oid(player_id)

    # Get matches the player participated in
    matches = list(db["match"].find({"$or": [{"player_a_id": player_oid}, {"player_b_id": player_oid}]}))
    match_ids = [m["_id"] for m in matches]

    if not match_ids:
        player_doc = db["player"].find_one({"_id": player_oid})
        return {
            "player": player_doc.get("name") if player_doc else None,
            "totals": {"points_won": 0, "points_lost": 0, "avg_rally": None},
            "shot_distribution": {},
            "matches": 0,
        }

    # Points won by this player in these matches
    won_count = db["point"].count_documents({"match_id": {"$in": match_ids}, "scorer_id": player_oid})
    # Points lost = points in those matches not scored by player
    lost_count = db["point"].count_documents({"match_id": {"$in": match_ids}, "scorer_id": {"$ne": player_oid}})

    # Average rally length for this player's points (won or total?) we'll compute overall in those matches
    pipeline_avg = [
        {"$match": {"match_id": {"$in": match_ids}}},
        {"$group": {"_id": None, "avg": {"$avg": "$rally_length"}}}
    ]
    avg_cursor = list(db["point"].aggregate(pipeline_avg))
    avg_rally = avg_cursor[0]["avg"] if avg_cursor else None

    # Shot distribution for this player's winning shots
    pipeline_shots = [
        {"$match": {"match_id": {"$in": match_ids}, "scorer_id": player_oid, "winner_shot": {"$exists": True}}},
        {"$group": {"_id": "$winner_shot", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    shot_rows = list(db["point"].aggregate(pipeline_shots))
    shot_distribution = {r["_id"]: r["count"] for r in shot_rows if r.get("_id")}

    player_doc = db["player"].find_one({"_id": player_oid})

    return {
        "player": player_doc.get("name") if player_doc else None,
        "totals": {"points_won": won_count, "points_lost": lost_count, "avg_rally": avg_rally},
        "shot_distribution": shot_distribution,
        "matches": len(matches),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
