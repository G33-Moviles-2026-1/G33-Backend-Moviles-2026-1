from __future__ import annotations

from typing import Any
import httpx


API_URL = "https://ofertadecursos.uniandes.edu.co/api/courses"
PAGE_SIZE = 10000


class UniandesCoursesClient:
    async def fetch_all_courses(self) -> list[dict[str, Any]]:
        all_courses: list[dict[str, Any]] = []
        offset = 0

        async with httpx.AsyncClient(timeout=120.0) as client:
            while True:
                resp = await client.get(API_URL, params={"offset": offset, "limit": PAGE_SIZE})
                resp.raise_for_status()
                data = resp.json()

                if not data:
                    break

                all_courses.extend(data)

                if len(data) < PAGE_SIZE:
                    break

                offset += PAGE_SIZE

        return all_courses