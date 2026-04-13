"""
routes/optimize.py  v2.0
========================
POST /api/optimize/route       — single algorithm
POST /api/optimize/compare     — run ALL algorithms and return comparison
POST /api/optimize/recalculate — mid-route recalculation from GPS position
"""

from flask import Blueprint, request, jsonify
import uuid
import logging

from ev_engine import (
    optimize_route,
    compare_all_routes,
    haversine,
    remaining_range_km,
    ALGORITHMS,
)

log = logging.getLogger(__name__)
optimize_bp = Blueprint("optimize", __name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _validate_node(node: dict, label: str):
    for k in ("lat", "lng"):
        if k not in node:
            return f"{label} missing '{k}'"
        try:
            float(node[k])
        except (TypeError, ValueError):
            return f"{label} '{k}' must be a number"
    return None


def _norm(node: dict, ntype: str, idx: int = 0) -> dict:
    node = dict(node)
    node.setdefault("id", f"{ntype}_{idx}_{uuid.uuid4().hex[:6]}")
    node["type"] = ntype
    node["lat"]  = float(node["lat"])
    node["lng"]  = float(node["lng"])
    node.setdefault("name", f"{ntype.capitalize()} {idx + 1}")
    return node


def _parse_body(body: dict):
    """Parse + validate the common request body shared by /route and /compare."""
    # Depot
    depot_raw = body.get("depot")
    if not depot_raw:
        return None, None, None, None, "Missing 'depot'"
    err = _validate_node(depot_raw, "depot")
    if err:
        return None, None, None, None, err

    # Deliveries
    deliveries_raw = body.get("deliveries", [])
    if not deliveries_raw:
        return None, None, None, None, "At least one delivery is required"
    for i, d in enumerate(deliveries_raw):
        err = _validate_node(d, f"deliveries[{i}]")
        if err:
            return None, None, None, None, err

    # Battery
    batt = body.get("battery", {})
    try:
        batt_params = {
            "battery_pct":   float(batt.get("current_pct", 80)),
            "max_range_km":  float(batt.get("max_range_km", 300)),
            "consumption_rate": float(batt.get("consumption_rate", 0.18)),
            "buffer_pct":    float(batt.get("buffer_pct", 10)),
        }
    except (TypeError, ValueError) as e:
        return None, None, None, None, f"Invalid battery parameter: {e}"

    if not (0 < batt_params["battery_pct"] <= 100):
        return None, None, None, None, "battery.current_pct must be 1-100"
    if batt_params["max_range_km"] <= 0:
        return None, None, None, None, "battery.max_range_km must be positive"

    depot      = _norm(depot_raw, "depot")
    deliveries = [_norm(d, "delivery", i) for i, d in enumerate(deliveries_raw)]
    stations   = [_norm(s, "charging", i) for i, s in enumerate(body.get("stations", []))]

    return depot, deliveries, stations, batt_params, None


# ── POST /api/optimize/route ─────────────────────────────────────────────────

@optimize_bp.route("/route", methods=["POST"])
def route():
    """
    Body:
    {
      "depot": { "lat": float, "lng": float, "name": str },
      "deliveries": [{ "lat": float, "lng": float, "name": str }, ...],
      "stations":   [{ "lat": float, "lng": float, "name": str }, ...],
      "battery": {
        "current_pct": 80,
        "max_range_km": 300,
        "consumption_rate": 0.18,
        "buffer_pct": 10
      },
      "algorithm": "greedy" | "twoopt" | "insertion" | "genetic" | "aco"
    }
    """
    body = request.get_json(force=True, silent=True) or {}
    depot, deliveries, stations, batt, err = _parse_body(body)
    if err:
        return jsonify({"error": err}), 400

    algorithm = body.get("algorithm", "greedy")
    if algorithm not in ALGORITHMS:
        algorithm = "greedy"

    log.info("Route [%s]: %d deliveries, %d stations, batt=%.0f%%",
             algorithm, len(deliveries), len(stations), batt["battery_pct"])
    try:
        result = optimize_route(
            depot=depot, deliveries=deliveries, stations=stations,
            **batt, algorithm=algorithm,
        )
    except Exception as e:
        log.exception("Engine error")
        return jsonify({"error": f"Optimization engine error: {e}"}), 500

    return jsonify(result)


# ── POST /api/optimize/compare ────────────────────────────────────────────────

@optimize_bp.route("/compare", methods=["POST"])
def compare():
    """
    Same body as /route (algorithm field is ignored — all are run).
    Returns a full comparison of all 5 algorithms plus a recommended best.
    """
    body = request.get_json(force=True, silent=True) or {}
    depot, deliveries, stations, batt, err = _parse_body(body)
    if err:
        return jsonify({"error": err}), 400

    log.info("Compare all: %d deliveries, %d stations", len(deliveries), len(stations))
    try:
        result = compare_all_routes(
            depot=depot, deliveries=deliveries, stations=stations, **batt
        )
    except Exception as e:
        log.exception("Compare engine error")
        return jsonify({"error": f"Comparison engine error: {e}"}), 500

    return jsonify(result)


# ── GET /api/optimize/algorithms ─────────────────────────────────────────────

@optimize_bp.route("/algorithms", methods=["GET"])
def list_algorithms():
    """Return the algorithm registry (for UI population)."""
    return jsonify([
        {
            "key":         k,
            "name":        v["name"],
            "label":       v["label"],
            "icon":        v["icon"],
            "description": v["description"],
            "user_tag":    v["user_tag"],
        }
        for k, v in ALGORITHMS.items()
    ])


# ── POST /api/optimize/recalculate ───────────────────────────────────────────

@optimize_bp.route("/recalculate", methods=["POST"])
def recalculate():
    """
    Dynamic mid-route recalculation.
    Extra fields:
    {
      "current_position": { "lat": float, "lng": float },
      "remaining_deliveries": [...],
      ... same battery / stations fields ...
    }
    """
    body = request.get_json(force=True, silent=True) or {}
    cur_pos = body.get("current_position")
    if not cur_pos:
        return jsonify({"error": "Missing 'current_position'"}), 400

    body["depot"] = {
        "lat": float(cur_pos["lat"]),
        "lng": float(cur_pos["lng"]),
        "name": "Current Vehicle Position",
        "type": "depot",
    }
    body["deliveries"] = body.get("remaining_deliveries", body.get("deliveries", []))

    depot, deliveries, stations, batt, err = _parse_body(body)
    if err:
        return jsonify({"error": err}), 400

    algorithm = body.get("algorithm", "greedy")
    if algorithm not in ALGORITHMS:
        algorithm = "greedy"

    try:
        result = optimize_route(
            depot=depot, deliveries=deliveries, stations=stations,
            **batt, algorithm=algorithm,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    result["recalculated"] = True
    return jsonify(result)
