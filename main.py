import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

from database import create_document, get_documents, db
from schemas import StockFavorite

app = FastAPI(title="AI Stock Insights API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class StockQuery(BaseModel):
    symbol: str

class AIAnalysisResponse(BaseModel):
    symbol: str
    summary: str
    outlook: str
    risk_score: float
    key_points: List[str]

@app.get("/")
def read_root():
    return {"message": "AI Stock Insights Backend is running"}

@app.get("/test")
def test_database():
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
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
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

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response

# Public stock data via Stooq (no API key) as a fallback to show charts
# CSV format: https://stooq.com/q/d/l/?s=aapl&i=d

def fetch_historical_prices(symbol: str):
    url = f"https://stooq.com/q/d/l/?s={symbol.lower()}&i=d"
    r = requests.get(url, timeout=10)
    if r.status_code != 200 or not r.text or r.text.startswith("<!DOCTYPE"):
        raise HTTPException(status_code=404, detail="Symbol not found or data unavailable")
    # Parse CSV
    lines = r.text.strip().split("\n")
    header = lines[0].split(",")
    idx = {h: i for i, h in enumerate(header)}
    data = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        data.append({
            "date": parts[idx["Date"]],
            "open": float(parts[idx["Open"]]),
            "high": float(parts[idx["High"]]),
            "low": float(parts[idx["Low"]]),
            "close": float(parts[idx["Close"]]),
            "volume": int(parts[idx["Volume"]]) if parts[idx["Volume"]].isdigit() else 0,
        })
    if not data:
        raise HTTPException(status_code=404, detail="No price data available")
    return data[-200:]  # limit for performance

@app.get("/api/stocks/{symbol}/history")
def get_stock_history(symbol: str):
    return {"symbol": symbol.upper(), "prices": fetch_historical_prices(symbol)}

# Simple AI-like analysis without external LLM (rule-based heuristic)
# Keeps project self-contained; can be swapped for a real LLM later.

def generate_ai_insights(symbol: str, prices: List[dict]) -> AIAnalysisResponse:
    closes = [p["close"] for p in prices]
    if len(closes) < 10:
        summary = "Not enough data to analyze."
        outlook = "Neutral"
        risk = 0.5
        points = ["Collect more history for better insights."]
    else:
        recent = closes[-1]
        ma20 = sum(closes[-20:]) / min(20, len(closes))
        ma50 = sum(closes[-50:]) / min(50, len(closes))
        change_30 = (recent - closes[-30]) / closes[-30] if len(closes) >= 31 else 0
        volatility = (max(closes[-20:]) - min(closes[-20:])) / ma20 if ma20 else 0

        trend = "Uptrend" if ma20 > ma50 else "Downtrend" if ma20 < ma50 else "Sideways"
        risk = min(1.0, max(0.05, volatility))
        outlook = "Bullish" if change_30 > 0.05 and trend == "Uptrend" else "Bearish" if change_30 < -0.05 and trend == "Downtrend" else "Neutral"
        points = [
            f"20-day MA: {ma20:.2f}",
            f"50-day MA: {ma50:.2f}",
            f"30-day change: {change_30*100:.1f}%",
            f"Trend: {trend}",
            f"Volatility score: {volatility:.2f}",
        ]
        summary = f"{symbol.upper()} shows a {trend.lower()} with a {change_30*100:.1f}% move over 30 days."

    return AIAnalysisResponse(
        symbol=symbol.upper(),
        summary=summary,
        outlook=outlook,
        risk_score=round(risk, 2),
        key_points=points,
    )

@app.get("/api/stocks/{symbol}/analysis", response_model=AIAnalysisResponse)
def analyze_stock(symbol: str):
    prices = fetch_historical_prices(symbol)
    return generate_ai_insights(symbol, prices)

# Favorites endpoints (persisted in MongoDB)

@app.post("/api/favorites")
def add_favorite(fav: StockFavorite):
    inserted_id = create_document("stockfavorite", fav)
    return {"id": inserted_id}

@app.get("/api/favorites")
def list_favorites(user_id: Optional[str] = Query(None)):
    filter_q = {"user_id": user_id} if user_id else {}
    docs = get_documents("stockfavorite", filter_q, limit=100)
    # convert ObjectId to str
    for d in docs:
        if "_id" in d:
            d["id"] = str(d.pop("_id"))
    return {"items": docs}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
