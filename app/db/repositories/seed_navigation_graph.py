import asyncio
import re
import uuid
from typing import Iterable

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert

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
# CONFIG / ASSUMPTIONS
# -------------------------------------------------------------------

# Because DB floor is int:
# - "00" => -1
# - "0"  => 0
BASEMENT_FLOOR = -1

# Inferred vertical travel times per adjacent floor
STAIRS_SECONDS = 20
ELEVATOR_SECONDS = 28
ESCALATOR_SECONDS = 12

ROOM_ANCHOR_SECONDS = 8  # room anchor <-> floor hallway hub

# -------------------------------------------------------------------
# SOURCE DATA
# -------------------------------------------------------------------

BUILDING_INFO = {
    "C": {
        "name": "Edificio C",
        "latitude": 4.601330739930525,
        "longitude": -74.06518645792532,
        "stairs": True,
        "elevator": True,
        "escalator": False,
    },
    "ML": {
        "name": "Mario Laserna",
        "latitude": 4.602740727701917,
        "longitude": -74.064894135776,
        "stairs": True,
        "elevator": True,
        "escalator": True,
    },
    "AU": {
        "name": "AU",
        "latitude": 4.60269657901711,
        "longitude": -74.06624262448605,
        "stairs": True,
        "elevator": True,
        "escalator": False,
    },
    "SD": {
        "name": "SD",
        "latitude": 4.604461641057399,
        "longitude": -74.06589081085542,
        "stairs": True,
        "elevator": True,
        "escalator": False,
    },
    "RGD": {
        "name": "RGD",
        "latitude": 4.602224801671742,
        "longitude": -74.06609644469707,
        "stairs": True,
        "elevator": True,
        "escalator": False,
    },
    "O": {
        "name": "O",
        "latitude": 4.600764086893377,
        "longitude": -74.06493685370451,
        "stairs": True,
        "elevator": False,
        "escalator": False,
    },
    "LL": {
        "name": "LL",
        "latitude": 4.602047759286092,
        "longitude": -74.06521530180024,
        "stairs": True,
        "elevator": False,
        "escalator": False,
    },
    "S1": {
        "name": "S1",
        "latitude": 4.601729263879883,
        "longitude": -74.064003414734,
        "stairs": True,
        "elevator": True,
        "escalator": False,
    },
    "TX": {
        "name": "TX",
        "latitude": 4.601230202167898,
        "longitude": -74.0638638001437,
        "stairs": True,
        "elevator": True,
        "escalator": False,
    },
    "W": {
        "name": "W",
        "latitude": 4.60212130566382,
        "longitude": -74.06499438146862,
        "stairs": True,
        "elevator": True,
        "escalator": False,
    },
    "R": {
        "name": "R",
        "latitude": 4.601613912652378,
        "longitude": -74.06390310643792,
        "stairs": True,
        "elevator": False,
        "escalator": False,
    },
    "B": {
        "name": "B",
        "latitude": 4.601469056190428,
        "longitude": -74.06571842694981,
        "stairs": True,
        "elevator": True,
        "escalator": False,
    },
    "Q": {
        "name": "Q",
        "latitude": 4.600308432920325,
        "longitude": -74.06514035931738,
        "stairs": True,
        "elevator": False,
        "escalator": False,
    },
}

ROOMS_BY_BUILDING = {
    "C": [
        "C 105", "C 106", "C 107", "C 108", "C 201", "C 203", "C 204", "C 205",
        "C 206", "C 207", "C 209", "C 210", "C 211", "C 212", "C 213", "C 301",
        "C 302", "C 303", "C 303-4", "C 304", "C 305", "C 306", "C 307", "C 308",
        "C 309", "C 401-2", "C 403-4", "C 405", "C 406", "C 407", "C 408", "C 409",
        "C 409A", "C 409B", "C 410", "C 411", "C 501", "C 502", "C 503", "C 505",
        "C 507", "C 508", "C 605", "C 606", "C 607", "C 608", "C 609", "C 610",
        "C 701",
    ],
    "ML": [
        "ML 003", "ML 004", "ML 009", "ML 012", "ML 026", "ML 029", "ML 033",
        "ML 038", "ML 042", "ML 105", "ML 107", "ML 109", "ML 109A", "ML 109B",
        "ML 110", "ML 111", "ML 113", "ML 114", "ML 117", "ML 119", "ML 120",
        "ML 206", "ML 207", "ML 208", "ML 340", "ML 417", "ML 420", "ML 509",
        "ML 510", "ML 511", "ML 512", "ML 514", "ML 515", "ML 516", "ML 603",
        "ML 604", "ML 606", "ML 607", "ML 608", "ML 614", "ML 615", "ML 616A-B",
        "ML 616B", "ML 617",
    ],
    "AU": [
        "AU 0006", "AU 101", "AU 102", "AU 103-4", "AU 107", "AU 201", "AU 202",
        "AU 203", "AU 204", "AU 205", "AU 206", "AU 207", "AU 208", "AU 209",
        "AU 301", "AU 302", "AU 303", "AU 304", "AU 305", "AU 306", "AU 307",
        "AU 308", "AU 309", "AU 401", "AU 402", "AU 403", "AU 404",
    ],
    "SD": [
        "SD 201-2", "SD 203-4", "SD 205-6", "SD 301", "SD 302", "SD 303", "SD 304",
        "SD 305", "SD 306", "SD 307", "SD 401", "SD 402", "SD 403", "SD 404",
        "SD 405", "SD 702", "SD 703", "SD 715", "SD 716", "SD 801", "SD 802",
        "SD 803", "SD 804", "SD 805", "SD 806", "SD 807", "SD 809",
    ],
    "RGD": [
        "RGD 001", "RGD 002", "RGD 004", "RGD 005", "RGD 01", "RGD 02", "RGD 04",
        "RGD 05", "RGD 07", "RGD 106-7", "RGD 110-11", "RGD 112-13", "RGD 201",
        "RGD 202", "RGD 203", "RGD 206", "RGD 206-7", "RGD 210", "RGD 211",
        "RGD 212-13", "RGD 306-7", "RGD 308-9", "RGD 310", "RGD 311", "RGD 312-13",
    ],
    "O": [
        "O 101", "O 102", "O 103", "O 104", "O 105", "O 201", "O 202", "O 203",
        "O 204", "O 205", "O 301", "O 302", "O 303", "O 304", "O 305", "O 401",
        "O 402", "O 403", "O 404", "O 405",
    ],
    "LL": [
        "LL 003", "LL 101", "LL 102", "LL 103", "LL 104", "LL 105", "LL 106",
        "LL 107", "LL 108", "LL 201", "LL 202", "LL 203", "LL 204", "LL 205",
        "LL 206", "LL 301", "LL 302", "LL 303", "LL 304",
    ],
    "S1": [
        "S1 001", "S1 002", "S1 003", "S1 101", "S1 102", "S1 103", "S1 104",
        "S1 105", "S1 201", "S1 202", "S1 205", "S1 302", "S1 304",
    ],
    "TX": [
        "TX 104", "TX 303", "TX 304", "TX 401", "TX 402", "TX 404", "TX 501",
        "TX 503", "TX 504", "TX 505", "TX 601", "TX 602", "TX 603",
    ],
    "W": [
        "W 101", "W 201", "W 202", "W 203", "W 204", "W 205", "W 301", "W 302",
        "W 401", "W 402", "W 403", "W 404", "W 505T",
    ],
    "R": [
        "R 107", "R 109", "R 110", "R 111", "R 112", "R 113", "R 209", "R 210",
        "R 211", "R 212",
    ],
    "B": [
        "B 201", "B 202", "B 203", "B 301", "B 302", "B 304", "B 305", "B 401",
        "B 402",
    ],
    "Q": [
        "Q 306", "Q 307", "Q 308", "Q 405", "Q 605", "Q 606", "Q 704", "Q 705", "Q 706",
    ],
}

# Explicit inter-building / cross-building / cross-core connectors:
# (building_a, floor_a, building_b, floor_b, seconds, edge_type, accessible)
CONNECTIONS = [
    ("C", 1, "B", 4, 10, "connector", True),
    ("C", 2, "O", 1, 30, "connector", True),
    ("C", 4, "O", 1, 20, "connector", True),
    ("C", 1, "LL", 3, 20, "connector", True),
    ("C", 1, "W", 4, 30, "connector", True),
    ("C", 1, "W", 3, 20, "connector", True),
    ("C", 1, "W", 6, 40, "connector", True),
    ("C", 2, "W", 3, 30, "connector", True),
    ("C", 2, "W", 4, 20, "connector", True),
    ("C", 2, "W", 6, 30, "connector", True),
    ("C", 4, "W", 6, 30, "connector", True),
    ("C", 4, "S1", 1, 80, "connector", True),
    ("C", 2, "S1", 1, 100, "connector", True),

    ("ML", 2, "LL", 1, 30, "connector", True),
    ("ML", 2, "W", 1, 30, "connector", True),
    ("ML", 5, "W", 5, 15, "connector", True),
    ("ML", 2, "SD", 1, 50, "connector", True),
    ("ML", 2, "AU", 1, 40, "connector", True),
    ("ML", 2, "RGD", 1, 40, "connector", True),
    ("ML", 2, "RGD", 0, 35, "connector", True),

    ("AU", 1, "RGD", 1, 25, "connector", True),
    ("AU", 1, "RGD", 0, 20, "connector", True),
    ("AU", 4, "RGD", 3, 10, "connector", True),
    ("AU", 1, "SD", 1, 45, "connector", True),

    ("SD", 1, "RGD", 0, 60, "connector", True),
    ("SD", 1, "RGD", 1, 75, "connector", True),

    ("RGD", 1, "B", 1, 30, "connector", True),

    ("O", 1, "Q", 1, 25, "connector", True),
    ("O", 1, "S1", 1, 120, "connector", True),

    ("LL", 1, "W", 1, 5, "connector", True),
    ("LL", 2, "W", 2, 5, "connector", True),
    ("LL", 3, "W", 3, 10, "connector", True),
    ("LL", 1, "B", 3, 15, "connector", True),

    ("S1", 1, "W", 6, 30, "connector", True),
    ("S1", 1, "R", 1, 20, "connector", True),
    ("S1", 1, "TX", 1, 20, "connector", True),

    ("TX", 1, "R", 1, 10, "connector", True),
    ("TX", 2, "R", 2, 10, "connector", True),
]

# Optional floor hints, but explicit rooms and connections take precedence.
DECLARED_FLOORS = {
    "C": [1, 2, 3, 4, 5],
    "ML": [0, 1, 2, 3, 4, 5, 6],
    "AU": [0, 1, 2, 3, 4],
    "SD": [2, 3, 4, 7, 8],
    "RGD": [BASEMENT_FLOOR, 0, 1, 2, 3],
    "O": [1, 2, 3, 4],
    "LL": [0, 1, 2, 3],
    "S1": [0, 1, 2, 3],
    "TX": [1, 3, 4, 5, 6],
    "W": [1, 2, 3, 4, 5],
    "R": [1, 2],
    "B": [2, 3, 4],
    "Q": [3, 4, 6, 7],
}

# -------------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------------

UUID_NAMESPACE = uuid.UUID("bdf7db98-68d5-4c1a-a7da-ef5f1f7622c1")


def stable_uuid(kind: str, *parts: object) -> uuid.UUID:
    joined = ":".join([kind, *[str(p) for p in parts]])
    return uuid.uuid5(UUID_NAMESPACE, joined)


def room_number_from_room_id(room_id: str) -> str:
    return room_id.split(" ", 1)[1].strip()


def infer_floor_from_room_id(room_id: str) -> int:
    """
    Examples:
      AU 0006 -> 0
      ML 003  -> 0
      RGD 001 -> -1 (floor 00)
      RGD 01  -> 0
      ML 512  -> 5
      C 409A  -> 4
      C 303-4 -> 3
    """
    room_num = room_number_from_room_id(room_id)
    match = re.match(r"^(\d+)", room_num)
    if not match:
        raise ValueError(f"Cannot infer floor from room id: {room_id}")

    digits = match.group(1)

    # Basement-ish "00x" case for RGD-like labels
    if len(digits) >= 3 and digits.startswith("00"):
        return BASEMENT_FLOOR

    # Any leading 0 non-basement -> floor 0
    if digits.startswith("0"):
        return 0

    return int(digits[0])


def floor_sort_key(floor: int) -> tuple[int, int]:
    return (0 if floor == BASEMENT_FLOOR else 1, floor)


def hallway_node_id(building_code: str, floor: int) -> uuid.UUID:
    return stable_uuid("hallway", building_code, floor)


def room_anchor_node_id(room_id: str) -> uuid.UUID:
    return stable_uuid("room_anchor", room_id)


def directed_edge_id(
    from_node_id: uuid.UUID,
    to_node_id: uuid.UUID,
    edge_type: str,
    accessible: bool,
    weight_seconds: int,
) -> uuid.UUID:
    return stable_uuid("edge", from_node_id, to_node_id, edge_type, accessible, weight_seconds)


def bidirectional_edges(
    node_a: uuid.UUID,
    node_b: uuid.UUID,
    seconds: int,
    edge_type: str,
    accessible: bool,
) -> list[dict]:
    return [
        {
            "id": directed_edge_id(node_a, node_b, edge_type, accessible, seconds),
            "from_node_id": node_a,
            "to_node_id": node_b,
            "weight_seconds": seconds,
            "accessible": accessible,
            "edge_type": edge_type,
        },
        {
            "id": directed_edge_id(node_b, node_a, edge_type, accessible, seconds),
            "from_node_id": node_b,
            "to_node_id": node_a,
            "weight_seconds": seconds,
            "accessible": accessible,
            "edge_type": edge_type,
        },
    ]


def collect_floors() -> dict[str, set[int]]:
    floors = {code: set(vals) for code, vals in DECLARED_FLOORS.items()}

    # Floors implied by rooms
    for building_code, rooms in ROOMS_BY_BUILDING.items():
        for room_id in rooms:
            floors.setdefault(building_code, set()).add(infer_floor_from_room_id(room_id))

    # Floors implied by explicit connections
    for b1, f1, b2, f2, *_ in CONNECTIONS:
        floors.setdefault(b1, set()).add(f1)
        floors.setdefault(b2, set()).add(f2)

    return floors


# -------------------------------------------------------------------
# MAIN SEED LOGIC
# -------------------------------------------------------------------

async def seed_navigation_graph() -> None:
    floors_by_building = collect_floors()
    listed_room_ids = [room_id for rooms in ROOMS_BY_BUILDING.values() for room_id in rooms]

    async with AsyncSessionLocal() as db:
        # -----------------------------------------------------------
        # 1) Load current rooms in DB, so anchors only point to valid FK rooms
        # -----------------------------------------------------------
        existing_rooms_result = await db.execute(select(Room.id))
        existing_room_ids = set(existing_rooms_result.scalars().all())

        valid_anchor_room_ids = [r for r in listed_room_ids if r in existing_room_ids]
        skipped_room_ids = sorted(set(listed_room_ids) - existing_room_ids)

        # -----------------------------------------------------------
        # 2) Upsert / update buildings (coords + fallback names)
        # -----------------------------------------------------------
        existing_buildings_result = await db.execute(select(Building))
        existing_buildings = {b.code: b for b in existing_buildings_result.scalars().all()}

        building_rows = []
        for code, info in BUILDING_INFO.items():
            existing_name = existing_buildings.get(code).name if code in existing_buildings else None
            building_rows.append(
                {
                    "code": code,
                    "name": existing_name or info["name"],
                    "latitude": info["latitude"],
                    "longitude": info["longitude"],
                }
            )

        await db.execute(
            insert(Building)
            .values(building_rows)
            .on_conflict_do_update(
                index_elements=[Building.code],
                set_={
                    "name": insert(Building).excluded.name,
                    "latitude": insert(Building).excluded.latitude,
                    "longitude": insert(Building).excluded.longitude,
                },
            )
        )

        # -----------------------------------------------------------
        # 3) Build node rows
        # -----------------------------------------------------------
        node_rows = []

        # Hallway hub per building-floor
        for building_code, floors in floors_by_building.items():
            info = BUILDING_INFO[building_code]
            for floor in sorted(floors, key=floor_sort_key):
                node_rows.append(
                    {
                        "id": hallway_node_id(building_code, floor),
                        "building_code": building_code,
                        "floor": floor,
                        "lat": info["latitude"],
                        "lon": info["longitude"],
                        "x": None,
                        "y": None,
                        "node_type": NavNodeType.hallway,
                    }
                )

        # Room anchors only for rooms that exist in DB
        for room_id in valid_anchor_room_ids:
            building_code = room_id.split(" ", 1)[0]
            info = BUILDING_INFO[building_code]
            floor = infer_floor_from_room_id(room_id)

            node_rows.append(
                {
                    "id": room_anchor_node_id(room_id),
                    "building_code": building_code,
                    "floor": floor,
                    "lat": info["latitude"],
                    "lon": info["longitude"],
                    "x": None,
                    "y": None,
                    "node_type": NavNodeType.room_anchor,
                }
            )

        # -----------------------------------------------------------
        # 4) Build edge rows
        # -----------------------------------------------------------
        edge_rows: list[dict] = []

        # 4a) Room anchor <-> hallway hub on same floor
        for room_id in valid_anchor_room_ids:
            building_code = room_id.split(" ", 1)[0]
            floor = infer_floor_from_room_id(room_id)

            edge_rows.extend(
                bidirectional_edges(
                    room_anchor_node_id(room_id),
                    hallway_node_id(building_code, floor),
                    ROOM_ANCHOR_SECONDS,
                    "room_anchor",
                    True,
                )
            )

        # 4b) Internal vertical movement per building (adjacent floors)
#        for building_code, floors in floors_by_building.items():
#            sorted_floors = sorted(floors, key=floor_sort_key)
#            info = BUILDING_INFO[building_code]

#            for idx in range(len(sorted_floors) - 1):
#                f1 = sorted_floors[idx]
#                f2 = sorted_floors[idx + 1]
#                node_a = hallway_node_id(building_code, f1)
#                node_b = hallway_node_id(building_code, f2)

#                if info["stairs"]:
#                    edge_rows.extend(
#                        bidirectional_edges(node_a, node_b, STAIRS_SECONDS, "stairs", False)
#                    )

#                if info["elevator"]:
#                    edge_rows.extend(
#                        bidirectional_edges(node_a, node_b, ELEVATOR_SECONDS, "elevator", True)
#                    )

#                if info["escalator"]:
#                    edge_rows.extend(
#                        bidirectional_edges(node_a, node_b, ESCALATOR_SECONDS, "escalator", False)
#                    )
        for building_code, floors in floors_by_building.items():
            sorted_floors = sorted(floors, key=floor_sort_key)
            info = BUILDING_INFO[building_code]

            for idx in range(len(sorted_floors) - 1):
                f1 = sorted_floors[idx]
                f2 = sorted_floors[idx + 1]
            # CALCULAMOS LA DIFERENCIA REAL DE PISOS
                delta = abs(f2 - f1) 
                node_a = hallway_node_id(building_code, f1)
                node_b = hallway_node_id(building_code, f2)
                if info["stairs"]:
            # Multiplicamos el tiempo base por la cantidad de pisos
                    edge_rows.extend(
                            bidirectional_edges(node_a, node_b, STAIRS_SECONDS * delta, "stairs", False)
            )

                if info["elevator"]:
            # Para el ascensor, podrías sumar un tiempo base (espera) + tiempo por piso
            # Ejemplo: 15s de espera + 10s por piso
                    elevator_time = 15 + (13 * delta) 
                    edge_rows.extend(
                bidirectional_edges(node_a, node_b, elevator_time, "elevator", True)
            )
        # 4c) Explicit cross-building connectors
        for b1, f1, b2, f2, secs, edge_type, accessible in CONNECTIONS:
            edge_rows.extend(
                bidirectional_edges(
                    hallway_node_id(b1, f1),
                    hallway_node_id(b2, f2),
                    secs,
                    edge_type,
                    accessible,
                )
            )

        # -----------------------------------------------------------
        # 5) Build room_nav_anchor rows
        # -----------------------------------------------------------
        anchor_rows = [
            {
                "room_id": room_id,
                "node_id": room_anchor_node_id(room_id),
            }
            for room_id in valid_anchor_room_ids
        ]

        # -----------------------------------------------------------
        # 6) Clear only the graph scope touched by this script
        # -----------------------------------------------------------
        touched_node_ids = {row["id"] for row in node_rows}
        touched_room_ids = set(valid_anchor_room_ids)

        if touched_node_ids:
            await db.execute(
                delete(NavEdge).where(
                    or_(
                        NavEdge.from_node_id.in_(touched_node_ids),
                        NavEdge.to_node_id.in_(touched_node_ids),
                    )
                )
            )

        if touched_room_ids:
            await db.execute(
                delete(RoomNavAnchor).where(RoomNavAnchor.room_id.in_(touched_room_ids))
            )

        if touched_node_ids:
            await db.execute(delete(NavNode).where(NavNode.id.in_(touched_node_ids)))

        # -----------------------------------------------------------
        # 7) Insert fresh graph data
        # -----------------------------------------------------------
        if node_rows:
            await db.execute(insert(NavNode).values(node_rows))

        if edge_rows:
            await db.execute(insert(NavEdge).values(edge_rows))

        if anchor_rows:
            await db.execute(insert(RoomNavAnchor).values(anchor_rows))

        await db.commit()

        print("=" * 60)
        print("Navigation graph seed completed")
        print(f"Buildings touched: {len(BUILDING_INFO)}")
        print(f"Hallway/anchor nodes inserted: {len(node_rows)}")
        print(f"Directed edges inserted: {len(edge_rows)}")
        print(f"Room anchors inserted: {len(anchor_rows)}")
        print(f"Rooms skipped because they do not exist in DB: {len(skipped_room_ids)}")
        if skipped_room_ids:
            print("Sample skipped rooms:", skipped_room_ids[:20])
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed_navigation_graph())
