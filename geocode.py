"""
routes/geocode.py
=================
GET  /api/geocode/search?q=<address>    — address → coordinates (Nominatim)
GET  /api/geocode/reverse?lat=&lng=     — coordinates → address
"""

import requests
import logging
from flask import Blueprint, request, jsonify

log = logging.getLogger(__name__)
geocode_bp = Blueprint("geocode", __name__)

NOMINATIM_BASE  = "https://nominatim.openstreetmap.org"
HEADERS         = {"User-Agent": "EVRouteOptimizer/1.0"}
TIMEOUT         = 10


# ─────────────────────────────────────────────────────────────────────────────
# Forward geocoding
# ─────────────────────────────────────────────────────────────────────────────
@geocode_bp.route("/search", methods=["GET"])
def search():
    """
    Query: ?q=<address>&limit=5
    Returns: [{ lat, lng, display_name, place_id }, ...]
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    limit = min(int(request.args.get("limit", 5)), 10)

    try:
        resp = requests.get(
            f"{NOMINATIM_BASE}/search",
            params={"q": q, "format": "json", "limit": limit, "addressdetails": 1},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.error("Nominatim search error: %s", e)
        return jsonify({"error": "Geocoding service unavailable", "detail": str(e)}), 502

    results = [
        {
            "lat": float(r["lat"]),
            "lng": float(r["lon"]),
            "display_name": r.get("display_name", ""),
            "place_id": r.get("place_id"),
            "type": r.get("type", ""),
        }
        for r in data
    ]
    return jsonify(results)


# ─────────────────────────────────────────────────────────────────────────────
# Reverse geocoding
# ─────────────────────────────────────────────────────────────────────────────
@geocode_bp.route("/reverse", methods=["GET"])
def reverse():
    """
    Query: ?lat=<float>&lng=<float>
    Returns: { display_name, address, lat, lng }
    """
    try:
        lat = float(request.args["lat"])
        lng = float(request.args["lng"])
    except (KeyError, ValueError):
        return jsonify({"error": "lat and lng are required float parameters"}), 400

    try:
        resp = requests.get(
            f"{NOMINATIM_BASE}/reverse",
            params={"lat": lat, "lon": lng, "format": "json", "zoom": 16},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return jsonify({"error": "Reverse geocoding failed", "detail": str(e)}), 502

    if "error" in data:
        return jsonify({"error": data["error"]}), 404

    return jsonify({
        "lat": lat,
        "lng": lng,
        "display_name": data.get("display_name", ""),
        "address": data.get("address", {}),
    })
