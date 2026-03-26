import asyncio
import uuid
from sqlalchemy import select
from app.db.models import NavEdge, RoomNavAnchor
from app.db.session import AsyncSessionLocal
from app.services.rooms_service import get_dijkstra_map

async def debug_path(origin_room: str, dest_room: str):
    async with AsyncSessionLocal() as db:
        # 1. Buscar los nodos ancla de ambos salones
        orig_anchor = (await db.execute(select(RoomNavAnchor).where(RoomNavAnchor.room_id == origin_room))).scalar_one_or_none()
        dest_anchor = (await db.execute(select(RoomNavAnchor).where(RoomNavAnchor.room_id == dest_room))).scalar_one_or_none()

        if not orig_anchor or not dest_anchor:
            print(f"❌ Error: Uno de los salones no tiene ancla. ML: {orig_anchor}, B: {dest_anchor}")
            return

        print(f"📍 Origen: {origin_room} (Nodo: {orig_anchor.node_id})")
        print(f"📍 Destino: {dest_room} (Nodo: {dest_anchor.node_id})")

        # 2. Correr Dijkstra desde el origen
        distances = await get_dijkstra_map(db, orig_anchor.node_id)

        # 3. Verificar si el destino es alcanzable
        cost = distances.get(dest_anchor.node_id)
        
        if cost is None or cost == float('inf'):
            print(f"🚨 ¡GRAFO ROTO! No hay conexión entre {origin_room} y {dest_room}.")
            # Verificar si el nodo destino tiene aristas de entrada
            edges_to_dest = (await db.execute(select(NavEdge).where(NavEdge.to_node_id == dest_anchor.node_id))).scalars().all()
            print(f"🔍 El nodo destino tiene {len(edges_to_dest)} conexiones de entrada.")
        else:
            print(f"✅ Conexión encontrada: {cost} segundos.")

if __name__ == "__main__":
    asyncio.run(debug_path("ML-340", "B-201")) # Cambia por tus IDs reales