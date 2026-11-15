"""
Leaderboard and callsigns for the survival game (frontend/game.html).

    POST /api/game/players       {"name"}                     -> {"name", "token"}   claim a callsign (409 if taken)
    POST /api/game/scores        {"name", "token", ...run}    -> {"rank", "best", "improved", "board"}
    GET  /api/game/leaderboard   ?mission=<key>&limit=20      -> {"mission", "board", "players"}

Stored in one SQLite file (standard library, no new dependency) under MARSWALK_GAME_STATE_DIR, default
game_state/ next to this file. That folder is not in git.

Honest limits: scores are reported by the player's browser, so a determined person can post a made-up score.
The server only checks that the numbers are in range, that the callsign's secret token matches, and that one
callsign does not post more often than every few seconds. A callsign has no password: whoever claims it first
keeps it on that browser, and it cannot be recovered on another device.
"""
import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/game", tags=["game"])

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{1,14}[A-Za-z0-9]$")      # 3-16 characters
RESERVED = {"houston", "capcom", "flight", "surgeon", "admin", "nasa", "eva-1", "autopilot", "anonymous"}
GRADES = {"S", "A", "B", "C", "D"}
MIN_SECONDS_BETWEEN_SCORES = 4.0
MAX_ROWS_PER_PLAYER = 400

_lock = threading.Lock()
_conn = None
_conn_path = None


def state_dir():
    return Path(os.environ.get("MARSWALK_GAME_STATE_DIR") or Path(__file__).resolve().parent / "game_state")


def _db():
    """One shared connection; reopened if MARSWALK_GAME_STATE_DIR changes (tests point it at a temp folder)."""
    global _conn, _conn_path
    path = state_dir() / "leaderboard.sqlite3"
    if _conn is None or _conn_path != path:
        if _conn is not None:
            _conn.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript("""
            CREATE TABLE IF NOT EXISTS players (
                name_lc TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL,
                created REAL NOT NULL, last_score REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name_lc TEXT NOT NULL, mission TEXT NOT NULL,
                goal TEXT NOT NULL, vehicle TEXT NOT NULL, route INTEGER NOT NULL, difficulty TEXT NOT NULL,
                score REAL NOT NULL, grade TEXT NOT NULL, met_h REAL NOT NULL, samples INTEGER NOT NULL,
                created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS scores_mission ON scores (mission, score DESC);
            CREATE INDEX IF NOT EXISTS scores_player ON scores (name_lc);
        """)
        _conn_path = path
    return _conn


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def clean_name(raw):
    name = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not NAME_RE.match(name):
        raise HTTPException(400, "Callsign must be 3 to 16 letters, digits, spaces, hyphens or underscores, "
                                 "starting and ending with a letter or digit.")
    if name.lower() in RESERVED:
        raise HTTPException(400, "That callsign is reserved. Pick another.")
    return name


class PlayerRequest(BaseModel):
    name: str = Field(..., max_length=40)


class ScoreRequest(BaseModel):
    name: str = Field(..., max_length=40)
    token: str = Field(..., min_length=8, max_length=200)
    mission: str = Field(..., min_length=1, max_length=400)      # the game's mission key: goal|vehicle|season|priority|rN
    goal: str = Field("", max_length=300)
    vehicle: str = Field("", max_length=80)
    route: int = Field(1, ge=1, le=9)
    difficulty: str = Field("", max_length=20)
    score: float = Field(..., ge=0, le=100)
    grade: str = Field(..., max_length=2)
    met_h: float = Field(0, ge=0, le=200)
    samples: int = Field(0, ge=0, le=20)


def _board(db, mission, limit):
    """Best run of each player on one mission, or (mission None) each player's total of best scores."""
    if mission:
        rows = db.execute("""
            SELECT p.name, s.score, s.grade, s.met_h, s.samples, s.difficulty, s.vehicle, s.created
            FROM scores s JOIN players p ON p.name_lc = s.name_lc
            WHERE s.mission = ? AND s.id = (
                SELECT id FROM scores WHERE mission = s.mission AND name_lc = s.name_lc
                ORDER BY score DESC, met_h ASC, id ASC LIMIT 1)
            ORDER BY s.score DESC, s.met_h ASC, s.id ASC LIMIT ?""", (mission, limit)).fetchall()
        return [dict(rank=i + 1, name=r[0], score=round(r[1], 1), grade=r[2], met_h=round(r[3], 2), samples=r[4],
                     difficulty=r[5], vehicle=r[6], when=int(r[7])) for i, r in enumerate(rows)]
    rows = db.execute("""
        SELECT p.name, SUM(b.best), COUNT(*), MAX(b.best) FROM (
            SELECT name_lc, mission, MAX(score) AS best FROM scores GROUP BY name_lc, mission) b
        JOIN players p ON p.name_lc = b.name_lc
        GROUP BY b.name_lc ORDER BY SUM(b.best) DESC, COUNT(*) DESC, p.name ASC LIMIT ?""", (limit,)).fetchall()
    return [dict(rank=i + 1, name=r[0], points=round(r[1], 1), missions=r[2], best=round(r[3], 1))
            for i, r in enumerate(rows)]


@router.post("/players")
def claim_player(req: PlayerRequest):
    name = clean_name(req.name)
    token = secrets.token_urlsafe(24)
    with _lock:
        db = _db()
        try:
            db.execute("INSERT INTO players (name_lc, name, token_hash, created) VALUES (?, ?, ?, ?)",
                       (name.lower(), name, _hash(token), time.time()))
            db.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(409, f"Callsign '{name}' is taken. Pick another.")
    return {"name": name, "token": token}


@router.post("/scores")
def post_score(req: ScoreRequest):
    name = clean_name(req.name)
    grade = req.grade.strip().upper()
    if grade not in GRADES:
        raise HTTPException(400, "grade must be one of S, A, B, C, D")
    now = time.time()
    with _lock:
        db = _db()
        row = db.execute("SELECT token_hash, last_score FROM players WHERE name_lc = ?", (name.lower(),)).fetchone()
        if row is None:
            raise HTTPException(404, "Unknown callsign. Claim it first.")
        if not secrets.compare_digest(row[0], _hash(req.token)):
            raise HTTPException(403, "This browser does not hold that callsign.")
        if now - row[1] < MIN_SECONDS_BETWEEN_SCORES:
            raise HTTPException(429, "Slow down: one score every few seconds.")
        before = db.execute("SELECT MAX(score) FROM scores WHERE name_lc = ? AND mission = ?",
                            (name.lower(), req.mission)).fetchone()[0]
        db.execute("""INSERT INTO scores (name_lc, mission, goal, vehicle, route, difficulty, score, grade, met_h,
                                          samples, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   (name.lower(), req.mission, req.goal, req.vehicle, req.route, req.difficulty, float(req.score),
                    grade, float(req.met_h), int(req.samples), now))
        db.execute("UPDATE players SET last_score = ? WHERE name_lc = ?", (now, name.lower()))
        db.execute("""DELETE FROM scores WHERE name_lc = ? AND id NOT IN (
                          SELECT id FROM scores WHERE name_lc = ? ORDER BY id DESC LIMIT ?)""",
                   (name.lower(), name.lower(), MAX_ROWS_PER_PLAYER))
        db.commit()
        board = _board(db, req.mission, 200)
        best = max(float(req.score), before or 0.0)
    rank = next((b["rank"] for b in board if b["name"].lower() == name.lower()), None)
    return {"rank": rank, "best": round(best, 1), "improved": before is None or req.score > before,
            "players": len(board), "board": board[:10]}


@router.get("/leaderboard")
def leaderboard(mission: str = Query("", max_length=400), limit: int = Query(20, ge=1, le=100)):
    with _lock:
        db = _db()
        board = _board(db, mission or None, limit)
        players = db.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    return {"mission": mission or None, "board": board, "players": players}
