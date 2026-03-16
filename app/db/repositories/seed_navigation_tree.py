import asyncio
import re
import uuid
from typing import Iterable

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert

# Asumo que estos son tus imports de proyecto
from app.db.session import AsyncSessionLocal
from app.db.models import (
    Building,
    NavEdge,
    NavNode,
    NavNodeType,
    Room,
    RoomNavAnchor,
)

# -------------------------------------------------------------------
# CONFIGURACIÓN DE TIEMPOS
# -------------------------------------------------------------------
BASEMENT_FLOOR = -1
STAIRS_SECONDS = 20    # por cada piso de diferencia
ELEVATOR_WAIT = 15     # tiempo base de espera del ascensor
ELEVATOR_PER_FLOOR = 13 # segundos por cada piso de viaje
ROOM_ANCHOR_SECONDS = 8

# -------------------------------------------------------------------
# DATA FUENTE (BUILDINGS & CONNECTIONS)
# -------------------------------------------------------------------
BUILDING_INFO = {
    "C": {"name": "Edificio C", "latitude": 4.6013307, "longitude": -74.065186, "stairs": True, "elevator": True},
    "ML": {"name": "Mario Laserna", "latitude": 4.6027407, "longitude": -74.064894, "stairs": True, "elevator": True},
    "AU": {"name": "AU", "latitude": 4.6026965, "longitude": -74.066242, "stairs": True, "elevator": True},
    "SD": {"name": "SD", "latitude": 4.6044616, "longitude": -74.065890, "stairs": True, "elevator": True},
    "RGD": {"name": "RGD", "latitude": 4.6022248, "longitude": -74.066096, "stairs": True, "elevator": True},
    "O": {"name": "O", "latitude": 4.6007640, "longitude": -74.064936, "stairs": True, "elevator": False},
    "LL": {"name": "LL", "latitude": 4.6020477, "longitude": -74.065215, "stairs": True, "elevator": False},
    "S1": {"name": "S1", "latitude": 4.6017292, "longitude": -74.064003, "stairs": True, "elevator": True},
    "TX": {"name": "TX", "latitude": 4.6012302, "longitude": -74.063863, "stairs": True, "elevator": True},
    "W": {"name": "W", "latitude": 4.6021213, "longitude": -74.064994, "stairs": True, "elevator": True},
    "R": {"name": "R", "latitude": 4.6016139, "longitude": -74.063903, "stairs": True, "elevator": False},
    "B": {"name": "B", "latitude": 4.6014690, "longitude": -74.065718, "stairs": True, "elevator": True},
    "Q": {"name": "Q", "latitude": 4.6003084, "longitude": -74.065140, "stairs": True, "elevator": False},
}

CONNECTIONS = [
    ("C", 1, "B", 4, 10, "connector", True),
    ("C", 2, "O", 1, 30, "connector", True),
    ("C", 4, "O", 1, 20, "connector", True),
    ("C", 1, "LL", 3, 20, "connector", True),
    ("C", 1, "W", 4, 30, "connector", True),
    ("ML", 2, "SD", 1, 50, "connector", True),
    ("SD", 1, "RGD", 0, 60, "connector", True),
    ("S1", 1, "R", 1, 20, "connector", True),
    ("TX", 1, "R", 1, 10, "connector", True),
    # ... añade aquí el resto de tus conexiones de la lista anterior
]

# -------------------------------------------------------------------
# HELPERS (UUIDs & NORMALIZACIÓN)
# -------------------------------------------------------------------
UUID_NAMESPACE = uuid.UUID("bdf7db98-68d5-4c1a-a7da-ef5f1f7622c1")

def stable_uuid(kind: str, *parts: object) -> uuid.UUID:
    joined = ":".join([kind, *[str(p) for p in parts]])
    return uuid.uuid5(UUID_NAMESPACE, joined)

def hallway_node_id(building: str, floor: int) -> uuid.UUID:
    return stable_uuid("hallway", building, floor)

def room_anchor_node_id(room_id: str) -> uuid.UUID:
    return stable_uuid("room_anchor", room_id)

def bidirectional_edges(node_a, node_b, seconds, etype, acc) -> list[dict]:
    res = []
    for (f, t) in [(node_a, node_b), (node_b, node_a)]:
        eid = stable_uuid("edge", f, t, etype, acc, seconds)
        res.append({"id": eid, "from_node_id": f, "to_node_id": t, 
                    "weight_seconds": seconds, "edge_type": etype, "accessible": acc})
    return res

def infer_floor(room_id: str) -> int:
    num = room_id.split(" ", 1)[1].strip()
    match = re.match(r"^(\d+)", num)
    if not match: return 0
    digits = match.group(1)
    if digits.startswith("00"): return BASEMENT_FLOOR
    if digits.startswith("0"): return 0
    return int(digits[0])

# -------------------------------------------------------------------
# LÓGICA DE SEMBRADO
# -------------------------------------------------------------------
async def seed_navigation_graph():
    # 1. Recolectar todos los pisos por edificio
    floors_by_building = {code: set() for code in BUILDING_INFO}
    for b1, f1, b2, f2, *_ in CONNECTIONS:
        floors_by_building[b1].add(f1)
        floors_by_building[b2].add(f2)

    async with AsyncSessionLocal() as db:
        # Cargar salones reales de la DB para no crear anchors huérfanos
        rooms_in_db = (await db.execute(select(Room.id, Room.building_code))).all()
        
        node_rows = []
        edge_rows = []
        anchor_links = []

        # 2. Generar Nodos de Hallway y Anchors de Salones
        for r_id, b_code in rooms_in_db:
            if b_code not in BUILDING_INFO: continue
            f = infer_floor(r_id)
            floors_by_building[b_code].add(f)
            
            # Nodo Anchor
            a_id = room_anchor_node_id(r_id)
            node_rows.append({
                "id": a_id, "building_code": b_code, "floor": f,
                "node_type": NavNodeType.room_anchor, "lat": BUILDING_INFO[b_code]["latitude"],
                "lon": BUILDING_INFO[b_code]["longitude"]
            })
            # Link salón <-> hallway
            edge_rows.extend(bidirectional_edges(a_id, hallway_node_id(b_code, f), ROOM_ANCHOR_SECONDS, "room_anchor", True))
            anchor_links.append({"room_id": r_id, "node_id": a_id})

        # 3. Nodos de Hallway (Hubs de piso)
        for b_code, floors in floors_by_building.items():
            for f in floors:
                node_rows.append({
                    "id": hallway_node_id(b_code, f), "building_code": b_code, "floor": f,
                    "node_type": NavNodeType.hallway, "lat": BUILDING_INFO[b_code]["latitude"],
                    "lon": BUILDING_INFO[b_code]["longitude"]
                })

        # 4. Movimiento Vertical (Pisos adyacentes con Delta)
        for b_code, floors in floors_by_building.items():
            sorted_f = sorted(list(floors))
            info = BUILDING_INFO[b_code]
            for i in range(len(sorted_f) - 1):
                f1, f2 = sorted_f[i], sorted_f[i+1]
                delta = abs(f2 - f1)
                n1, n2 = hallway_node_id(b_code, f1), hallway_node_id(b_code, f2)
                
                if info["stairs"]:
                    edge_rows.extend(bidirectional_edges(n1, n2, STAIRS_SECONDS * delta, "stairs", False))
                if info["elevator"]:
                    e_time = ELEVATOR_WAIT + (ELEVATOR_PER_FLOOR * delta)
                    edge_rows.extend(bidirectional_edges(n1, n2, e_time, "elevator", True))

        # 5. Conectores Inter-Edificios
        for b1, f1, b2, f2, secs, etype, acc in CONNECTIONS:
            edge_rows.extend(bidirectional_edges(hallway_node_id(b1, f1), hallway_node_id(b2, f2), secs, etype, acc))

        # 6. Limpiar e Insertar
        # (Se recomienda borrar NavEdge, luego RoomNavAnchor, luego NavNode por FKs)
        await db.execute(delete(NavEdge))
        await db.execute(delete(RoomNavAnchor))
        await db.execute(delete(NavNode))
        
        db.add_all([NavNode(**n) for n in node_rows])
        await db.flush()
        db.add_all([NavEdge(**e) for e in edge_rows])
        db.add_all([RoomNavAnchor(**a) for a in anchor_links])
        
        await db.commit()
        print(f"Grafo poblado: {len(node_rows)} nodos, {len(edge_rows)} arcos.")

if __name__ == "__main__":
    asyncio.run(seed_navigation_graph())