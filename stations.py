"""
routes/stations.py
==================
GET  /api/stations/nearby?lat=&lng=&radius_km=   — fetch from Overpass (OSM)
GET  /api/stations/manual                         — list user-added stations
POST /api/stations/manual                         — add a station
DELETE /api/stations/manual/<id>                  — remove a station
"""

import uuid
import requests
import logging
from flask import Blueprint, request, jsonify

log = logging.getLogger(__name__)
stations_bp = Blueprint("stations", __name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
TIMEOUT      = 20

# In-memory store for manually added stations (replace with DB in production)
_manual_stations: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Nearby stations from OpenStreetMap (Overpass)
# ─────────────────────────────────────────────────────────────────────────────
@stations_bp.route("/nearby", methods=["GET"])
def nearby():
    """
    Query: ?lat=<float>&lng=<float>&radius_km=<float (default 30)>&limit=<int (default 25)>
    Returns: [{ id, lat, lng, name, operator, socket_types, source }, ...]
    """
    try:
        lat = float(request.args["lat"])
        lng = float(request.args["lng"])
    except (KeyError, ValueError):
        return jsonify({"error": "lat and lng are required"}), 400

    radius_km = float(request.args.get("radius_km", 30))
    limit     = int(request.args.get("limit", 25))
    radius_m  = int(radius_km * 1000)

    query = (
        f"[out:json][timeout:{TIMEOUT}];"
        f"("
        f'  node["amenity"="charging_station"](around:{radius_m},{lat},{lng});'
        f'  way["amenity"="charging_station"](around:{radius_m},{lat},{lng});'
        f");"
        f"out center body;"
    )

    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.error("Overpass error: %s", e)
        return jsonify({"error": "Overpass API unavailable", "detail": str(e)}), 502

    results = []
    for el in data.get("elements", [])[:limit]:
        # Nodes have lat/lon directly; ways have a 'center' object
        if el["type"] == "node":
            elat, elng = el["lat"], el["lon"]
        elif el["type"] == "way" and "center" in el:
            elat, elng = el["center"]["lat"], el["center"]["lon"]
        else:
            continue

        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("operator") or f"EV Station #{str(el['id'])[-4:]}"

        # Parse socket types if available
        sockets = []
        for key in tags:
            if "socket" in key or "plug" in key or "connector" in key:
                sockets.append(tags[key])

        results.append({
            "id": f"osm_{el['id']}",
            "lat": elat,
            "lng": elng,
            "name": name,
            "operator": tags.get("operator", ""),
            "socket_types": sockets or ["unknown"],
            "capacity": tags.get("capacity", ""),
            "fee": tags.get("fee", "unknown"),
            "opening_hours": tags.get("opening_hours", ""),
            "source": "osm",
            "type": "charging",
        })

    log.info("Overpass returned %d stations near %.4f,%.4f", len(results), lat, lng)
    return jsonify(results)


# ─────────────────────────────────────────────────────────────────────────────
# Manual (user-contributed) stations — in-memory CRUD
# ─────────────────────────────────────────────────────────────────────────────
@stations_bp.route("/manual", methods=["GET"])
def list_manual():
    return jsonify(list(_manual_stations.values()))


@stations_bp.route("/manual", methods=["POST"])
def add_manual():
    """
    Body:
    {
      "lat": 0.0, "lng": 0.0,
      "name": "My Station",
      "capacity": "22 kW",
      "socket_types": ["Type2"],
      "notes": ""
    }
    """
    body = request.get_json(force=True, silent=True) or {}
    try:
        lat = float(body["lat"])
        lng = float(body["lng"])
    except (KeyError, ValueError):
        return jsonify({"error": "lat and lng are required"}), 400

    sid = f"manual_{uuid.uuid4().hex[:8]}"
    station = {
        "id": sid,
        "lat": lat,
        "lng": lng,
        "name": body.get("name", "Custom Station"),
        "capacity": body.get("capacity", ""),
        "socket_types": body.get("socket_types", []),
        "notes": body.get("notes", ""),
        "source": "manual",
        "type": "charging",
    }
    _manual_stations[sid] = station
    log.info("Manual station added: %s", sid)
    return jsonify(station), 201


@stations_bp.route("/manual/<sid>", methods=["DELETE"])
def delete_manual(sid: str):
    if sid not in _manual_stations:
        return jsonify({"error": "Station not found"}), 404
    del _manual_stations[sid]
    return jsonify({"deleted": sid})


@stations_bp.route("/manual/<sid>", methods=["PUT"])
def update_manual(sid: str):
    if sid not in _manual_stations:
        return jsonify({"error": "Station not found"}), 404
    body = request.get_json(force=True, silent=True) or {}
    _manual_stations[sid].update({k: v for k, v in body.items() if k != "id"})
    return jsonify(_manual_stations[sid])
