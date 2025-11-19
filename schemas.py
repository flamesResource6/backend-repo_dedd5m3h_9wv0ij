"""
Database Schemas for Pickleball Analytics

Each Pydantic model corresponds to a MongoDB collection. The collection name is the lowercase of the class name.

Use these models for validation when creating documents.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

class Player(BaseModel):
    """
    Players collection schema
    Collection name: "player"
    """
    name: str = Field(..., description="Player full name")
    rating: Optional[float] = Field(None, ge=0, le=6.0, description="Skill rating (0-6)")
    handedness: Optional[Literal["left", "right"]] = Field(None, description="Dominant hand")

class Match(BaseModel):
    """
    Matches collection schema (singles)
    Collection name: "match"
    """
    player_a_id: str = Field(..., description="Player A id (ObjectId string)")
    player_b_id: str = Field(..., description="Player B id (ObjectId string)")
    location: Optional[str] = Field(None, description="Court/location")
    level: Optional[str] = Field(None, description="Division level or bracket")
    started_at: Optional[datetime] = Field(default=None, description="Match start time")
    completed_at: Optional[datetime] = Field(default=None, description="Match end time")

class Point(BaseModel):
    """
    Points collection schema
    Each document represents a single rally ending in a point.
    Collection name: "point"
    """
    match_id: str = Field(..., description="Match id (ObjectId string)")
    scorer_id: str = Field(..., description="Player who won the point (ObjectId string)")
    rally_length: int = Field(..., ge=1, le=100, description="Number of strokes in the rally")
    winner_shot: Optional[Literal["serve", "return", "drive", "drop", "dink", "lob", "volley", "smash", "other"]] = Field(
        None, description="Shot type that ended the rally")
    unforced_error: bool = Field(False, description="Whether rally ended by opponent unforced error")
    notes: Optional[str] = Field(None, description="Optional note about the rally")
