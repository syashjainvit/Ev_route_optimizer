"""
ev_engine.py  —  EV Route Optimization Engine  v2.0
=====================================================
Algorithms implemented
  ─────────────────────────────────────────────────
  Classic graph search
    • Dijkstra         — optimal shortest-path between node pairs
    • A*               — heuristic-guided, faster than Dijkstra on sparse graphs

  TSP order heuristics  (tour ordering for multiple deliveries)
    • Greedy NN        — fast O(n²) nearest-neighbour sweep
    • 2-Opt            — local-search improvement on a greedy seed
    • Nearest Insertion — cheapest-insertion constructive heuristic

  Metaheuristics  (can escape local optima)
    • Genetic Algorithm — crossover + mutation on permutation chromosomes
    • Ant Colony Opt.  — pheromone-based probabilistic construction

  Battery simulation layer (wraps any TSP order result)
    → inserts charging stops, tracks kWh, returns full step-by-step route

  compare_all_routes()
    → runs every algorithm, returns unified comparison dict
"""

import math
import heapq
import random
import logging
from copy import deepcopy
from typing import List, Dict, Tuple, Optional, Any

log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# DISTANCE UTILITIES
# ────────────────────────────────────────────────────────────────────────────

def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres (WGS-84)."""
    R = 6_371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(d_lng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def node_dist(a: Dict, b: Dict) -> float:
    return haversine(a["lat"], a["lng"], b["lat"], b["lng"])


def remaining_range_km(battery_pct: float, max_range_km: float) -> float:
    return (battery_pct / 100.0) * max_range_km


def energy_needed_kwh(dist_km: float, rate: float) -> float:
    return dist_km * rate


def can_reach(dist_km: float, batt_km: float, buffer_pct: float = 0.0) -> bool:
    return batt_km * (1 - buffer_pct / 100.0) >= dist_km


# ────────────────────────────────────────────────────────────────────────────
# GRAPH
# ────────────────────────────────────────────────────────────────────────────

class EVGraph:
    """Weighted undirected complete graph for EV nodes."""

    def __init__(self, consumption_rate: float = 0.18):
        self.nodes: Dict[str, Dict] = {}
        self.adj: Dict[str, Dict[str, float]] = {}
        self.consumption_rate = consumption_rate

    def add_node(self, node: Dict) -> str:
        nid = node["id"]
        self.nodes[nid] = node
        self.adj.setdefault(nid, {})
        return nid

    def build_complete_graph(self, weight: str = "distance") -> None:
        ids = list(self.nodes.keys())
        for i, u in enumerate(ids):
            for v in ids[i + 1:]:
                d = node_dist(self.nodes[u], self.nodes[v])
                w = d if weight == "distance" else d * self.consumption_rate
                self.adj[u][v] = w
                self.adj[v][u] = w

    def edge_weight(self, u: str, v: str) -> float:
        return self.adj.get(u, {}).get(v, float("inf"))

    def to_dict(self) -> Dict:
        return {
            "nodes": list(self.nodes.values()),
            "edges": [
                {"from": u, "to": v, "weight": round(w, 4)}
                for u, nbrs in self.adj.items()
                for v, w in nbrs.items()
                if u < v
            ],
        }


# ────────────────────────────────────────────────────────────────────────────
# GRAPH SEARCH — DIJKSTRA
# ────────────────────────────────────────────────────────────────────────────

def dijkstra(graph: EVGraph, source: str, target: str) -> Tuple[float, List[str]]:
    """Classic Dijkstra. Returns (cost_km, path_ids)."""
    dist = {nid: float("inf") for nid in graph.nodes}
    prev: Dict[str, Optional[str]] = {nid: None for nid in graph.nodes}
    dist[source] = 0.0
    pq = [(0.0, source)]

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        if u == target:
            break
        for v, w in graph.adj.get(u, {}).items():
            alt = dist[u] + w
            if alt < dist[v]:
                dist[v] = alt
                prev[v] = u
                heapq.heappush(pq, (alt, v))

    path: List[str] = []
    cur: Optional[str] = target
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    if not path or path[0] != source:
        return float("inf"), []
    return dist[target], path


# ────────────────────────────────────────────────────────────────────────────
# GRAPH SEARCH — A*
# ────────────────────────────────────────────────────────────────────────────

def astar(graph: EVGraph, source: str, target: str) -> Tuple[float, List[str]]:
    """A* with straight-line distance heuristic."""
    target_node = graph.nodes[target]

    def h(nid: str) -> float:
        return node_dist(graph.nodes[nid], target_node)

    g: Dict[str, float] = {nid: float("inf") for nid in graph.nodes}
    g[source] = 0.0
    prev: Dict[str, Optional[str]] = {nid: None for nid in graph.nodes}
    open_set = [(g[source] + h(source), source)]

    while open_set:
        _, u = heapq.heappop(open_set)
        if u == target:
            break
        for v, w in graph.adj.get(u, {}).items():
            tent = g[u] + w
            if tent < g[v]:
                g[v] = tent
                prev[v] = u
                heapq.heappush(open_set, (tent + h(v), v))

    path: List[str] = []
    cur: Optional[str] = target
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    if not path or path[0] != source:
        return float("inf"), []
    return g[target], path


# ────────────────────────────────────────────────────────────────────────────
# TSP ORDER — GREEDY NEAREST NEIGHBOUR
# ────────────────────────────────────────────────────────────────────────────

def order_greedy(depot: Dict, deliveries: List[Dict]) -> List[Dict]:
    """O(n²) greedy nearest-neighbour tour starting from depot."""
    todo = list(deliveries)
    cur = depot
    result = []
    while todo:
        todo.sort(key=lambda d: node_dist(cur, d))
        result.append(todo.pop(0))
        cur = result[-1]
    return result


# ────────────────────────────────────────────────────────────────────────────
# TSP ORDER — 2-OPT LOCAL SEARCH
# ────────────────────────────────────────────────────────────────────────────

def _tour_dist(depot: Dict, order: List[Dict]) -> float:
    if not order:
        return 0.0
    d = node_dist(depot, order[0])
    for i in range(1, len(order)):
        d += node_dist(order[i - 1], order[i])
    return d


def order_two_opt(depot: Dict, deliveries: List[Dict], max_passes: int = 200) -> List[Dict]:
    """2-opt improvement on a greedy seed. Significantly reduces crossing paths."""
    if len(deliveries) <= 2:
        return list(deliveries)
    order = order_greedy(depot, deliveries)
    improved = True
    passes = 0
    while improved and passes < max_passes:
        improved = False
        passes += 1
        for i in range(len(order) - 1):
            for j in range(i + 2, len(order)):
                prev_i = depot if i == 0 else order[i - 1]
                next_j = order[j + 1] if j + 1 < len(order) else None
                before = node_dist(prev_i, order[i]) + (node_dist(order[j], next_j) if next_j else 0)
                after  = node_dist(prev_i, order[j]) + (node_dist(order[i], next_j) if next_j else 0)
                if after < before - 1e-6:
                    order[i:j + 1] = order[i:j + 1][::-1]
                    improved = True
    return order


# ────────────────────────────────────────────────────────────────────────────
# TSP ORDER — NEAREST INSERTION
# ────────────────────────────────────────────────────────────────────────────

def order_insertion(depot: Dict, deliveries: List[Dict]) -> List[Dict]:
    """Cheapest nearest-insertion constructive heuristic."""
    if not deliveries:
        return []
    if len(deliveries) == 1:
        return list(deliveries)
    # Start with farthest delivery from depot
    farthest = max(deliveries, key=lambda d: node_dist(depot, d))
    route = [farthest]
    remaining = [d for d in deliveries if d is not farthest]
    while remaining:
        # Find nearest unvisited to any routed node
        nearest = min(remaining, key=lambda u: min(node_dist(r, u) for r in route))
        # Find cheapest insertion position
        best_cost, best_pos = float("inf"), 0
        for k in range(len(route) + 1):
            prev = depot if k == 0 else route[k - 1]
            nxt  = route[k] if k < len(route) else None
            cost = (node_dist(prev, nearest)
                    + (node_dist(nearest, nxt) - node_dist(prev, nxt) if nxt else 0))
            if cost < best_cost:
                best_cost, best_pos = cost, k
        route.insert(best_pos, nearest)
        remaining.remove(nearest)
    return route


# ────────────────────────────────────────────────────────────────────────────
# METAHEURISTIC — GENETIC ALGORITHM (TSP variant)
# ────────────────────────────────────────────────────────────────────────────

def order_genetic(
    depot: Dict,
    deliveries: List[Dict],
    population_size: int = 80,
    generations: int = 300,
    mutation_rate: float = 0.15,
    elite_size: int = 10,
) -> List[Dict]:
    """
    Genetic Algorithm for TSP delivery ordering.

    Chromosome  : permutation of delivery indices
    Fitness     : 1 / tour_distance  (maximise)
    Selection   : rank-based tournament
    Crossover   : Order Crossover (OX1)
    Mutation    : swap + reverse-segment
    Elitism     : top-k carried forward unchanged
    """
    n = len(deliveries)
    if n <= 2:
        return order_greedy(depot, deliveries)

    def fitness(perm: List[int]) -> float:
        order = [deliveries[i] for i in perm]
        d = _tour_dist(depot, order)
        return 1.0 / (d + 1e-9)

    def ox1_crossover(p1: List[int], p2: List[int]) -> List[int]:
        a, b = sorted(random.sample(range(n), 2))
        child = [-1] * n
        child[a:b] = p1[a:b]
        segment = set(p1[a:b])
        fill = [x for x in p2 if x not in segment]
        ptr = 0
        for i in range(n):
            if child[i] == -1:
                child[i] = fill[ptr]; ptr += 1
        return child

    def mutate(perm: List[int]) -> List[int]:
        p = list(perm)
        if random.random() < 0.5:
            i, j = random.sample(range(n), 2)
            p[i], p[j] = p[j], p[i]
        else:
            i, j = sorted(random.sample(range(n), 2))
            p[i:j + 1] = p[i:j + 1][::-1]
        return p

    # Seed population with greedy + random
    seed = list(range(n))
    greedy_order = order_greedy(depot, deliveries)
    greedy_perm = [deliveries.index(d) for d in greedy_order]
    population = [greedy_perm] + [random.sample(seed, n) for _ in range(population_size - 1)]

    best_perm = greedy_perm
    best_fit = fitness(greedy_perm)

    for _ in range(generations):
        scored = sorted(population, key=fitness, reverse=True)
        if fitness(scored[0]) > best_fit:
            best_fit = fitness(scored[0])
            best_perm = scored[0]

        elite = scored[:elite_size]
        new_pop = list(elite)
        while len(new_pop) < population_size:
            # Tournament selection (k=3)
            p1 = max(random.sample(scored[:population_size // 2], 3), key=fitness)
            p2 = max(random.sample(scored[:population_size // 2], 3), key=fitness)
            child = ox1_crossover(p1, p2)
            if random.random() < mutation_rate:
                child = mutate(child)
            new_pop.append(child)
        population = new_pop

    return [deliveries[i] for i in best_perm]


# ────────────────────────────────────────────────────────────────────────────
# METAHEURISTIC — ANT COLONY OPTIMIZATION
# ────────────────────────────────────────────────────────────────────────────

def order_ant_colony(
    depot: Dict,
    deliveries: List[Dict],
    n_ants: int = 30,
    n_iterations: int = 100,
    alpha: float = 1.0,       # pheromone influence
    beta: float = 3.0,        # heuristic (1/dist) influence
    rho: float = 0.3,         # evaporation rate
    q: float = 100.0,         # pheromone deposit constant
) -> List[Dict]:
    """
    Ant Colony Optimization for TSP delivery ordering.

    Pheromone matrix τ[i][j] is updated each iteration.
    Heuristic η[i][j] = 1/dist(i,j).
    Ants choose next node probabilistically: (τ^α · η^β) / Σ.
    Best global tour reinforces pheromones.
    """
    n = len(deliveries)
    if n <= 2:
        return order_greedy(depot, deliveries)

    # Nodes: 0 = depot, 1..n = deliveries
    all_nodes = [depot] + deliveries

    def dist_idx(i: int, j: int) -> float:
        return node_dist(all_nodes[i], all_nodes[j])

    # Initialise pheromone matrix
    tau = [[1.0] * (n + 1) for _ in range(n + 1)]
    # Heuristic matrix (avoid division by zero)
    eta = [[0.0] * (n + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        for j in range(n + 1):
            if i != j:
                d = dist_idx(i, j)
                eta[i][j] = 1.0 / (d + 1e-9)

    best_order = order_greedy(depot, deliveries)
    best_dist = _tour_dist(depot, best_order)

    for iteration in range(n_iterations):
        all_tours: List[Tuple[float, List[int]]] = []

        for _ in range(n_ants):
            visited = [False] * (n + 1)
            visited[0] = True
            tour = []           # indices into all_nodes (deliveries only)
            current = 0         # start at depot

            for _ in range(n):
                candidates = [j for j in range(1, n + 1) if not visited[j]]
                if not candidates:
                    break
                # Probabilistic selection
                weights = []
                for j in candidates:
                    w = (tau[current][j] ** alpha) * (eta[current][j] ** beta)
                    weights.append(w)
                total = sum(weights)
                if total == 0:
                    chosen = random.choice(candidates)
                else:
                    r = random.uniform(0, total)
                    cumulative = 0.0
                    chosen = candidates[-1]
                    for idx, j in enumerate(candidates):
                        cumulative += weights[idx]
                        if cumulative >= r:
                            chosen = j
                            break
                tour.append(chosen)
                visited[chosen] = True
                current = chosen

            tour_nodes = [deliveries[j - 1] for j in tour]
            d = _tour_dist(depot, tour_nodes)
            all_tours.append((d, tour))

            if d < best_dist:
                best_dist = d
                best_order = tour_nodes

        # Evaporate pheromones
        for i in range(n + 1):
            for j in range(n + 1):
                tau[i][j] *= (1 - rho)
                tau[i][j] = max(tau[i][j], 1e-6)

        # Deposit pheromones on all tours (elitist: stronger for better tours)
        all_tours.sort(key=lambda x: x[0])
        for rank, (d, tour) in enumerate(all_tours[:max(1, n_ants // 3)]):
            deposit = q / (d + 1e-9)
            prev = 0
            for j in tour:
                tau[prev][j] += deposit
                tau[j][prev] += deposit
                prev = j

    return best_order


# ────────────────────────────────────────────────────────────────────────────
# BATTERY SIMULATION  (shared across all ordering algorithms)
# ────────────────────────────────────────────────────────────────────────────

def best_charging_station(
    current: Dict,
    next_node: Dict,
    stations: List[Dict],
    batt_km: float,
    buffer_pct: float = 10.0,
) -> Optional[Dict]:
    usable = batt_km * (1 - buffer_pct / 100.0)
    candidates = []
    for cs in stations:
        d_cur = node_dist(current, cs)
        if d_cur > usable:
            continue
        detour = d_cur + node_dist(cs, next_node)
        candidates.append((detour, cs))
    if not candidates:
        for cs in stations:
            d_cur = node_dist(current, cs)
            if d_cur <= batt_km:
                candidates.append((d_cur, cs))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def _simulate_battery(
    ordered_deliveries: List[Dict],
    depot: Dict,
    stations: List[Dict],
    battery_pct: float,
    max_range_km: float,
    consumption_rate: float,
    buffer_pct: float,
) -> Dict[str, Any]:
    """
    Given an ordered list of deliveries, simulate battery usage and insert
    charging stops as needed.  Returns a full route + stats dict.
    """
    batt_km = remaining_range_km(battery_pct, max_range_km)
    cur = depot
    route: List[Dict] = []
    total_km = 0.0
    charge_stops = 0
    warnings: List[str] = []

    # Depot step
    route.append({
        "node": depot, "type": "depot",
        "dist_from_prev": 0,
        "batt_after_km": round(batt_km, 3),
        "batt_after_pct": round(battery_pct, 1),
        "energy_used_kwh": 0,
        "cumulative_km": 0,
    })

    for delivery in ordered_deliveries:
        d = node_dist(cur, delivery)
        # Need to charge?
        if not can_reach(d, batt_km, buffer_pct):
            cs = best_charging_station(cur, delivery, stations, batt_km, buffer_pct)
            if cs is None:
                warnings.append(
                    f"Cannot reach a charging station from '{cur.get('name', '?')}'. "
                    f"Route may be incomplete."
                )
                break
            d_cs = node_dist(cur, cs)
            batt_km -= d_cs
            total_km += d_cs
            charge_stops += 1
            route.append({
                "node": cs, "type": "charging",
                "dist_from_prev": round(d_cs, 3),
                "batt_after_km": round(max_range_km, 3),
                "batt_after_pct": 100.0,
                "energy_used_kwh": round(d_cs * consumption_rate, 3),
                "cumulative_km": round(total_km, 3),
            })
            batt_km = max_range_km
            cur = cs
            d = node_dist(cur, delivery)

        batt_km -= d
        total_km += d
        route.append({
            "node": delivery, "type": "delivery",
            "dist_from_prev": round(d, 3),
            "batt_after_km": round(batt_km, 3),
            "batt_after_pct": round((batt_km / max_range_km) * 100, 1),
            "energy_used_kwh": round(d * consumption_rate, 3),
            "cumulative_km": round(total_km, 3),
        })
        cur = delivery

    delivered = sum(1 for s in route if s["type"] == "delivery")
    total_energy = round(sum(s["energy_used_kwh"] for s in route), 3)
    final_pct = route[-1]["batt_after_pct"] if route else battery_pct

    # Estimated time (city average 50 km/h + 30 min per charging stop)
    est_minutes = round((total_km / 50.0) * 60 + charge_stops * 30)

    stats = {
        "total_km": round(total_km, 2),
        "total_energy_kwh": total_energy,
        "deliveries_completed": delivered,
        "deliveries_total": len(ordered_deliveries),
        "charge_stops": charge_stops,
        "final_battery_pct": final_pct,
        "estimated_minutes": est_minutes,
    }
    return {"route": route, "stats": stats, "warnings": warnings}


# ────────────────────────────────────────────────────────────────────────────
# ALGORITHM REGISTRY  — maps key → (label, ordering function)
# ────────────────────────────────────────────────────────────────────────────

ALGORITHMS = {
    "greedy": {
        "name": "Quick Route",
        "label": "Greedy Nearest-Neighbour",
        "icon": "⚡",
        "description": "Fast O(n²) heuristic. Picks the closest unvisited delivery each step.",
        "user_tag": "fastest",
        "fn": order_greedy,
    },
    "twoopt": {
        "name": "Balanced Route",
        "label": "2-Opt Local Search",
        "icon": "🎯",
        "description": "Improves a greedy tour by reversing segments that reduce total distance.",
        "user_tag": "balanced",
        "fn": order_two_opt,
    },
    "insertion": {
        "name": "Safe Route",
        "label": "Nearest Insertion",
        "icon": "🛡️",
        "description": "Conservative constructive heuristic; minimises detour at each insertion.",
        "user_tag": "safe",
        "fn": order_insertion,
    },
    "genetic": {
        "name": "Smart AI Route",
        "label": "Genetic Algorithm",
        "icon": "🧬",
        "description": "Evolutionary optimisation: crossover + mutation over 300 generations.",
        "user_tag": "ai",
        "fn": order_genetic,
    },
    "aco": {
        "name": "Battery Efficient Route",
        "label": "Ant Colony Optimization",
        "icon": "🐜",
        "description": "Pheromone-based swarm intelligence. Excellent for energy-minimal tours.",
        "user_tag": "battery",
        "fn": order_ant_colony,
    },
}


# ────────────────────────────────────────────────────────────────────────────
# PUBLIC API — single algorithm
# ────────────────────────────────────────────────────────────────────────────

def optimize_route(
    depot: Dict,
    deliveries: List[Dict],
    stations: List[Dict],
    battery_pct: float,
    max_range_km: float,
    consumption_rate: float = 0.18,
    buffer_pct: float = 10.0,
    algorithm: str = "greedy",
) -> Dict[str, Any]:
    """
    Run one algorithm and return the full route result.

    Returns
    -------
    {
      "route"   : [step, ...],
      "stats"   : {...},
      "graph"   : {...},
      "warnings": [str, ...]
      "algorithm_key"  : str,
      "algorithm_name" : str,
      "algorithm_label": str,
    }
    """
    algo_key = algorithm if algorithm in ALGORITHMS else "greedy"
    algo = ALGORITHMS[algo_key]

    all_nodes = [depot] + deliveries + stations
    g = EVGraph(consumption_rate=consumption_rate)
    for n in all_nodes:
        g.add_node(n)
    g.build_complete_graph(weight="distance")

    ordered = algo["fn"](depot, deliveries)
    result = _simulate_battery(ordered, depot, stations, battery_pct, max_range_km, consumption_rate, buffer_pct)

    result["algorithm_key"]   = algo_key
    result["algorithm_name"]  = algo["name"]
    result["algorithm_label"] = algo["label"]
    result["algorithm_icon"]  = algo["icon"]
    result["stats"]["algorithm_used"] = algo["name"] + " (" + algo["label"] + ")"
    result["graph"] = g.to_dict()

    log.info("optimize_route [%s]: %.1f km, %d deliveries, %d charges",
             algo_key, result["stats"]["total_km"],
             result["stats"]["deliveries_completed"],
             result["stats"]["charge_stops"])
    return result


# ────────────────────────────────────────────────────────────────────────────
# PUBLIC API — compare ALL algorithms
# ────────────────────────────────────────────────────────────────────────────

def _score(stats: Dict) -> float:
    """Lower is better composite score (distance 50%, charges 30%, battery 20%)."""
    return (stats["total_km"] * 0.50
            + stats["charge_stops"] * 10 * 0.30
            - stats["final_battery_pct"] * 0.20)


def compare_all_routes(
    depot: Dict,
    deliveries: List[Dict],
    stations: List[Dict],
    battery_pct: float,
    max_range_km: float,
    consumption_rate: float = 0.18,
    buffer_pct: float = 10.0,
) -> Dict[str, Any]:
    """
    Run all five algorithms, rank them, and return a unified comparison.

    Returns
    -------
    {
      "results"     : { algo_key: { route, stats, algorithm_name, ... } },
      "ranking"     : [{ rank, algo_key, score, ... }],
      "best"        : algo_key,
      "recommendation": str,
      "graph"       : {...},
    }
    """
    all_nodes = [depot] + deliveries + stations
    g = EVGraph(consumption_rate=consumption_rate)
    for n in all_nodes:
        g.add_node(n)
    g.build_complete_graph(weight="distance")

    results: Dict[str, Dict] = {}
    for key, algo in ALGORITHMS.items():
        try:
            ordered = algo["fn"](depot, deliveries)
            res = _simulate_battery(ordered, depot, stations, battery_pct, max_range_km, consumption_rate, buffer_pct)
            res["algorithm_key"]   = key
            res["algorithm_name"]  = algo["name"]
            res["algorithm_label"] = algo["label"]
            res["algorithm_icon"]  = algo["icon"]
            res["stats"]["algorithm_used"] = algo["name"] + " (" + algo["label"] + ")"
            results[key] = res
        except Exception as exc:
            log.warning("Algorithm %s failed: %s", key, exc)

    # Rank by composite score
    ranked = sorted(results.items(), key=lambda kv: _score(kv[1]["stats"]))
    best_key = ranked[0][0] if ranked else "greedy"

    ranking = []
    for rank, (key, res) in enumerate(ranked, 1):
        sc = _score(res["stats"])
        ranking.append({
            "rank": rank,
            "algo_key": key,
            "algo_name": res["algorithm_name"],
            "algo_label": res["algorithm_label"],
            "algo_icon": res["algorithm_icon"],
            "score": round(sc, 2),
            "total_km": res["stats"]["total_km"],
            "total_energy_kwh": res["stats"]["total_energy_kwh"],
            "charge_stops": res["stats"]["charge_stops"],
            "deliveries_completed": res["stats"]["deliveries_completed"],
            "final_battery_pct": res["stats"]["final_battery_pct"],
            "estimated_minutes": res["stats"]["estimated_minutes"],
        })

    best = results[best_key]
    rec = (
        f"{best['algorithm_name']} ({best['algorithm_label']}) is the best route: "
        f"{best['stats']['total_km']:.1f} km, "
        f"{best['stats']['charge_stops']} charging stop(s), "
        f"{best['stats']['total_energy_kwh']:.1f} kWh used."
    )

    return {
        "results": results,
        "ranking": ranking,
        "best": best_key,
        "recommendation": rec,
        "graph": g.to_dict(),
        "algorithm_count": len(results),
    }
