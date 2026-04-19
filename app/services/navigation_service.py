import heapq
import math
import re
from uuid import UUID
from sqlalchemy import select
from fastapi import HTTPException
from app.db.models import NavNode, NavEdge, RoomNavAnchor
from math import asin, cos, radians, sin, sqrt

class NavigationService:
    def __init__(self, db_session):
        self.db = db_session

    # --- UTILIDADES GEOGRÁFICAS ---
    def _haversine_meters(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        earth_radius_m = 6371000.0
        d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
        a = sin(d_lat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2)**2
        return earth_radius_m * 2 * asin(sqrt(a))

    async def find_node_for_room(self, room_id: str) -> NavNode:
        # Insert space between letters and digits if missing: "LL303" → "LL 303"
        normalized = re.sub(r'([A-Za-z])(\d)', r'\1 \2', room_id.strip()).upper()
        normalized = " ".join(normalized.split())
        anchor_res = await self.db.execute(
            select(RoomNavAnchor).where(RoomNavAnchor.room_id == normalized)
        )
        anchor = anchor_res.scalar_one_or_none()
        if anchor is None:
            raise HTTPException(status_code=404, detail=f"No navigation node found for room '{normalized}'")
        node_res = await self.db.execute(select(NavNode).where(NavNode.id == anchor.node_id))
        return node_res.scalar_one()

    async def find_nearest_node(self, lat: float, lon: float) -> NavNode:
        result = await self.db.execute(select(NavNode))
        nodes = result.scalars().all()
        if not nodes:
            raise HTTPException(status_code=500, detail="No navigation nodes found")
        
        # Usamos Haversine para consistencia en todo el sistema
        return min(nodes, key=lambda n: self._haversine_meters(lat, lon, n.lat, n.lon))

    # --- ALGORITMOS DE GRAFOS ---
    async def get_cost_map(self, start_node_id: UUID) -> dict[UUID, float]:
        """Calcula el costo mínimo a todos los nodos (para el sorting de búsqueda)."""
        edges_res = await self.db.execute(select(NavEdge))
        edges = edges_res.scalars().all()

        graph = {}
        for edge in edges:
            if edge.from_node_id not in graph:
                graph[edge.from_node_id] = []
            graph[edge.from_node_id].append((edge.to_node_id, edge.weight_seconds))

        distances = {start_node_id: 0.0}
        pq = [(0.0, start_node_id)]
        visited = set()

        while pq:
            curr_dist, curr_node = heapq.heappop(pq)
            if curr_node in visited: continue
            visited.add(curr_node)

            for neighbor, weight in graph.get(curr_node, []):
                new_dist = curr_dist + weight
                if new_dist < distances.get(neighbor, float('inf')):
                    distances[neighbor] = new_dist
                    heapq.heappush(pq, (new_dist, neighbor))
        return distances

    async def get_route(self, start_node_id: UUID, end_node_id: UUID):
        """Calcula la ruta más corta y genera instrucciones humanas."""
        nodes_res = await self.db.execute(select(NavNode))
        edges_res = await self.db.execute(select(NavEdge))
        
        nodes = {n.id: n for n in nodes_res.scalars().all()}
        adj = {n_id: [] for n_id in nodes}
        for e in edges_res.scalars().all():
            adj[e.from_node_id].append(e)

        distances = {n_id: float('inf') for n_id in nodes}
        prev_nodes = {n_id: None for n_id in nodes}
        prev_edges = {n_id: None for n_id in nodes}
        distances[start_node_id] = 0
        pq = [(0, start_node_id)]

        while pq:
            curr_dist, curr_node = heapq.heappop(pq)
            if curr_node == end_node_id: break
            if curr_dist > distances[curr_node]: continue

            for edge in adj.get(curr_node, []):
                new_dist = curr_dist + edge.weight_seconds
                if new_dist < distances[edge.to_node_id]:
                    distances[edge.to_node_id] = new_dist
                    prev_nodes[edge.to_node_id] = curr_node
                    prev_edges[edge.to_node_id] = edge
                    heapq.heappush(pq, (new_dist, edge.to_node_id))

        return self._build_instructions(end_node_id, prev_nodes, prev_edges, nodes)

    def _build_instructions(self, target_id, prev_nodes, prev_edges, nodes):
        path_edges = []
        curr = target_id
        while curr and prev_nodes.get(curr) is not None:
            path_edges.append(prev_edges[curr])
            curr = prev_nodes[curr]
        path_edges.reverse()

        if not path_edges:
            return None

        raw_steps = []
        for i, edge in enumerate(path_edges):
            u, v = nodes[edge.from_node_id], nodes[edge.to_node_id]
            if edge.edge_type == "stairs":
                direction = "Go up" if v.floor > u.floor else "Go down"
                raw_steps.append(f"{direction} the stairs to floor {v.floor} of building {v.building_code}.")
            elif edge.edge_type == "elevator":
                raw_steps.append(f"Take the elevator to floor {v.floor} of building {v.building_code}.")
            elif edge.edge_type == "connector":
                if u.building_code != v.building_code:
                    msg = f"Cross over to building {v.building_code}"
                else:
                    msg = "Continue through the corridor"
                raw_steps.append(f"{msg} on floor {u.floor}.")
            elif edge.edge_type == "room_anchor":
                if i == len(path_edges) - 1:
                    raw_steps.append("You have arrived at your destination.")
                else:
                    raw_steps.append("Exit the room.")

        return {
            "total_time_seconds": sum(e.weight_seconds for e in path_edges),
            "steps": self._collapse_instructions(raw_steps)
        }

    def _collapse_instructions(self, steps):
        if not steps: return []
        collapsed = [steps[0]]
        for i in range(1, len(steps)):
            if steps[i] != steps[i-1]: collapsed.append(steps[i])
        return collapsed