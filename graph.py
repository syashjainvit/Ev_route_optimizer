"""
routes/graph.py  v2.0
=====================
POST /api/graph/build  — build graph and return shortest paths (Dijkstra + A*)
GET  /api/graph/info   — list of supported algorithms
"""

import uuid
import logging
from flask import Blueprint, request, jsonify
from ev_engine import EVGraph, dijkstra, astar, ALGORITHMS

log = logging.getLogger(__name__)
graph_bp = Blueprint("graph", __name__)


def _norm(node: dict, ntype: str, idx: int = 0) -> dict:
    n = dict(node)
    n.setdefault("id", f"{ntype}_{idx}_{uuid.uuid4().hex[:4]}")
    n["type"] = ntype
    n["lat"]  = float(n["lat"])
    n["lng"]  = float(n["lng"])
    return n


@graph_bp.route("/build", methods=["POST"])
def build():
    """
    Body: same shape as /api/optimize/route
    Returns graph nodes + edges + shortest paths from depot to each delivery.
    """
    body = request.get_json(force=True, silent=True) or {}
    depot_raw      = body.get("depot")
    deliveries_raw = body.get("deliveries", [])
    stations_raw   = body.get("stations", [])
    consumption    = float(body.get("battery", {}).get("consumption_rate", 0.18))

    if not depot_raw:
        return jsonify({"error": "Missing depot"}), 400

    depot      = _norm(depot_raw, "depot")
    deliveries = [_norm(d, "delivery", i) for i, d in enumerate(deliveries_raw)]
    stations   = [_norm(s, "charging", i) for i, s in enumerate(stations_raw)]
    all_nodes  = [depot] + deliveries + stations

    g = EVGraph(consumption_rate=consumption)
    for n in all_nodes:
        g.add_node(n)
    g.build_complete_graph(weight="distance")

    # Shortest paths from depot to each delivery
    shortest_paths = {}
    for d in deliveries:
        d_cost, d_path = dijkstra(g, depot["id"], d["id"])
        a_cost, a_path = astar(g, depot["id"], d["id"])
        shortest_paths[d["id"]] = {
            "dijkstra": {"cost_km": round(d_cost, 3), "path": d_path},
            "astar":    {"cost_km": round(a_cost, 3), "path": a_path},
        }

    graph_dict = g.to_dict()
    for edge in graph_dict["edges"]:
        edge["energy_kwh"] = round(edge["weight"] * consumption, 4)

    return jsonify({
        "graph":          graph_dict,
        "shortest_paths": shortest_paths,
        "node_count":     len(all_nodes),
        "edge_count":     len(graph_dict["edges"]),
    })


@graph_bp.route("/info", methods=["GET"])
def info():
    return jsonify({
        "algorithms": [
            {
                "id":          k,
                "name":        v["name"],
                "label":       v["label"],
                "icon":        v["icon"],
                "description": v["description"],
                "user_tag":    v["user_tag"],
            }
            for k, v in ALGORITHMS.items()
        ],
        "weight_types": ["distance", "energy"],
    })
