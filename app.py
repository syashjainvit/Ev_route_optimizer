"""
app.py  —  EV Route Optimization System  Flask Backend  v2.0
=============================================================
Run:
    pip install -r requirements.txt
    cp .env.example .env          # fill in any keys you need
    python app.py

API Base: http://localhost:5000/api
"""

import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS

# Load .env if python-dotenv is available (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ .env loaded")
except ImportError:
    pass

from routes.optimize import optimize_bp
from routes.geocode  import geocode_bp
from routes.stations import stations_bp
from routes.graph    import graph_bp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ── Blueprints ───────────────────────────────────────────────────────────────
app.register_blueprint(optimize_bp, url_prefix="/api/optimize")
app.register_blueprint(geocode_bp,  url_prefix="/api/geocode")
app.register_blueprint(stations_bp, url_prefix="/api/stations")
app.register_blueprint(graph_bp,    url_prefix="/api/graph")


@app.route("/api/health")
def health():
    return jsonify({
        "status":  "ok",
        "version": "2.0.0",
        "algorithms": ["greedy", "twoopt", "insertion", "genetic", "aco"],
    })


@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e), "code": 400}), 400


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found", "code": 404}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": str(e), "code": 500}), 500


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    log.info("Starting EV Route Optimizer backend on %s:%s", host, port)
    app.run(debug=debug, host=host, port=port)
