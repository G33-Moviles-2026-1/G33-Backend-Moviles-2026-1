import random
from collections import defaultdict
from datetime import date, time
from fastapi import Depends

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Weekday
from app.schemas.rooms import (
    RoomSearchItemOut, 
    TimeWindowOut, 
    WeeklyAvailabilityWindowOut
)

from app.db.repositories.interactions_repo import get_user_contextual_scores


from app.db.repositories.rooms_repo import (
    fetch_room_search_rows,
    fetch_weekly_availability_for_rooms
)

from app.services.rooms_service import _compute_interest_score, list_user_room_preferences
_PYTHON_WEEKDAY_MAP: dict[int, str] = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}

_DB_WEEKDAY: dict[str, Weekday] = {w.value: w for w in Weekday}


# --- Auto Search ML Constants ---
EPSILON = 0.20           
WEIGHT_RL_SCORE = 0.40   
WEIGHT_BASE_PREF = 0.60  
MAX_ROOMS_PER_BUILDING_SAMPLE = 5


async def get_auto_search_recommendations(
    db: AsyncSession,
    user_email: str,
    target_date: date,
    since: time,
    until: time,
    top_k: int = 3,
) -> list[RoomSearchItemOut]: # Assuming we reuse the RoomSearchItemOut schema
    """
    The Machine Learning "Auto Search" feature.
    Uses a Two-Stage Pipeline (Stratified Sampling -> Heavy Scoring) 
    and a Contextual Multi-Armed Bandit algorithm.
    """
    # 1. Resolve Time & Context
    weekday_str = _PYTHON_WEEKDAY_MAP[target_date.weekday()]
    db_weekday = _DB_WEEKDAY[weekday_str]

    # 2. STAGE 1: Candidate Generation (The Broad Filter)
    # Fetch all available rooms for this time block (reusing your existing repo function)
    all_available_rows = await fetch_room_search_rows(
        db,
        target_date=target_date,
        weekday=db_weekday,
        since=since,
        until=until,
        room_prefixes=[],
        building_codes=[],
        utilities=[]
    )

    # 3. STAGE 1: Stratified Sampling (In-Memory)
    # Group by building code to ensure geographic diversity
    rooms_by_building = defaultdict(list)
    for row in all_available_rows:
        rooms_by_building[row.building_code].append(row)

    sampled_rows = []
    for building_code, rows_in_building in rooms_by_building.items():
        # Randomly pick up to 5 rooms per building. 
        # This reduces 1000s of rooms down to a tiny, diverse subset!
        sample_size = min(len(rows_in_building), MAX_ROOMS_PER_BUILDING_SAMPLE)
        sampled_rows.extend(random.sample(rows_in_building, sample_size))

    if not sampled_rows:
        return [] # No rooms available at all

    # Group the sampled rows exactly like you do in `search_rooms`
    grouped: dict[str, dict] = {}
    for row in sampled_rows:
        if row.room_id not in grouped:
            grouped[row.room_id] = {
                "room_id": row.room_id,
                "building_code": row.building_code,
                "building_name": row.building_name,
                "room_number": row.room_number,
                "capacity": row.capacity,
                "reliability": row.reliability,
                "utilities": row.utilities,
                "matching_windows": [],
                "final_ml_score": 0.0, # Our new composite score
            }
        
        window = TimeWindowOut(start=row.rule_start_time, end=row.rule_end_time)
        if window not in grouped[row.room_id]["matching_windows"]:
            grouped[row.room_id]["matching_windows"].append(window)

    candidates = list(grouped.values())

    # 4. STAGE 2: Heavy Scoring (Preferences + Reinforcement Learning)
    # Fetch the user's historical booking preferences
    user_preferences = await list_user_room_preferences(db, user_email=user_email)
    
    # Fetch the Contextual RL Scores for this specific day and time
    rl_scores_map = await get_user_contextual_scores(
        db,
        user_email=user_email,
        weekday=weekday_str,
        slot_start=since
    )

    for item in candidates:
        # A. Calculate Base Heuristic Score (Using your existing function)
        base_interest_score = _compute_interest_score(
            item, 
            user_preferences, 
            weekday=db_weekday
        )
        
        # B. Get RL Learning Score (from SKIPs, BOOKs, FAVORITEs)
        rl_learning_score = rl_scores_map.get(item["room_id"], 0.0)

        # C. Composite Score
        item["final_ml_score"] = (
            (base_interest_score * WEIGHT_BASE_PREF) + 
            (rl_learning_score * WEIGHT_RL_SCORE)
        )

    # Sort strictly by the highest ML score (Exploitation)
    candidates.sort(key=lambda x: (
        -x["final_ml_score"],
        -x["reliability"],
        x["room_id"]
    ))

    # 5. EPSILON-GREEDY BANDIT LOGIC
    final_selection = []
    if len(candidates) > 0:
        if random.random() > EPSILON:
            # EXPLOITATION (80%): Take the best scored rooms
            final_selection = candidates[:top_k]
        else:
            # EXPLORATION (20%): Inject a random room from our diverse stratified sample
            exploration_pick = random.choice(candidates)
            final_selection.append(exploration_pick)
            
            # Fill the remaining slots with the highest scorers
            remaining = [c for c in candidates if c["room_id"] != exploration_pick["room_id"]]
            final_selection.extend(remaining[:top_k - 1])

    # 6. Fetch weekly availability just for our final winners (Saves DB time)
    weekly_map = await fetch_weekly_availability_for_rooms(
        db, room_ids=[i["room_id"] for i in final_selection]
    )

    # 7. Map to the final output schema
    response_items = [
        RoomSearchItemOut(
            **{k: v for k, v in item.items() if k not in ["matching_windows", "final_ml_score"]},
            distance_seconds=None, # Not using map distance for Auto Search
            matching_windows=sorted(item["matching_windows"], key=lambda w: w.start),
            weekly_availability=[
                WeeklyAvailabilityWindowOut(
                    day=w.day, start=w.start_time, end=w.end_time,
                    valid_from=w.valid_from, valid_to=w.valid_to
                ) for w in weekly_map.get(item["room_id"], [])
            ]
        ) for item in final_selection
    ]

    return response_items