# Ev_route_optimizer
An interactive web-based application that optimizes delivery routes for Electric Vehicles (EVs) by considering battery constraints, charging stations, and multiple delivery locations.  This project integrates real-world map data with advanced optimization algorithms to simulate intelligent route planning for EV logistics.


Features
1.  Interactive map using Leaflet.js
2.  Location search powered by OpenStreetMap (Nominatim API)
3.  Automatic EV charging station detection (Overpass API)
4. Supports multiple delivery stops with depot selection
5. Battery-aware routing with real-time energy tracking
6. Multiple optimization algorithms:
  -> Greedy (Nearest Neighbor)
  ->2-Opt Optimization
  ->Nearest Insertion
  ->Genetic Algorithm
  ->Ant Colony Optimization
7.  Algorithm comparison with performance metrics
8.  Dynamic route visualization with battery indicators


How It Works
User selects depot, delivery points, and charging stations
System applies routing algorithms to optimize the path
Battery consumption is simulated for each route
Charging stops are automatically inserted when required
Best route is selected based on efficiency metrics


Performance Metrics
Total distance (km)
Energy consumption (kWh)
Number of charging stops
Final battery percentage
Estimated travel time


Tech Stack
1. Frontend: HTML, CSS, JavaScript
2. Mapping: Leaflet.js
3. APIs:
  ->OpenStreetMap (Nominatim)
  ->Overpass API
4. Algorithms: Greedy, 2-Opt, Genetic, ACO

 
Real-World Applications
EV delivery systems (Amazon / Flipkart logistics)
Fleet management
Smart city transportation
Sustainable mobility planning


Future Improvements
Real-time traffic integration
Machine learning-based route prediction
Multi-vehicle routing
Mobile app version
