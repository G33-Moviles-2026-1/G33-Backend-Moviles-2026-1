import random
from collections import defaultdict
from datetime import date, time
from fastapi import Depends
from app.core.time_rules import clip_to_operating_hours
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Weekday
from app.schemas.rooms import (
    RoomSearchItemOut, 
    TimeWindowOut, 
    WeeklyAvailabilityWindowOut
)

from zoneinfo import ZoneInfo

BOGOTA_TZ = ZoneInfo("America/Bogota")

from app.db.repositories.interactions_repo import get_user_contextual_scores


from app.db.repositories.rooms_repo import (
    fetch_room_search_rows,
    fetch_weekly_availability_for_rooms
)

from app.services.rooms_service import (
    AVAILABILITY_WEIGHT,
    BUILDING_WEIGHT,
    CAPACITY_WEIGHT,
    FLOOR_WEIGHT,
    UTILITY_WEIGHT,
    _availability_similarity,
    _capacity_similarity,
    _compute_interest_score,
    _infer_floor,
    _utilities_similarity,
    list_user_room_preferences,
)
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
WEIGHT_RL_SCORE = 0.30   
WEIGHT_BASE_PREF = 0.70  
MAX_ROOMS_PER_BUILDING_SAMPLE = 5


def _recommendation_reason(
    item: dict,
    preferences: list,
    *,
    weekday: Weekday,
    rl_learning_score: float,
) -> str:
    weighted_components = {
        "booking_building": 0.0,
        "booking_floor": 0.0,
        "booking_capacity": 0.0,
        "booking_utilities": 0.0,
        "booking_availability": 0.0,
    }
    total_weight = 0
    candidate_floor = _infer_floor(item["room_id"])

    for pref in preferences:
        booking_weight = pref.booking_count
        total_weight += booking_weight
        booked_floor = _infer_floor(pref.room_id)

        same_building = item["building_code"] == pref.building_code
        same_floor = (
            candidate_floor is not None
            and booked_floor is not None
            and candidate_floor == booked_floor
        )

        weighted_components["booking_building"] += (
            BUILDING_WEIGHT * (1.0 if same_building else 0.0) * booking_weight
        )
        weighted_components["booking_floor"] += (
            FLOOR_WEIGHT * (1.0 if same_floor else 0.0) * booking_weight
        )
        weighted_components["booking_capacity"] += (
            CAPACITY_WEIGHT
            * _capacity_similarity(item["capacity"], pref.capacity)
            * booking_weight
        )
        weighted_components["booking_utilities"] += (
            UTILITY_WEIGHT
            * _utilities_similarity(item["utilities"], pref.utilities)
            * booking_weight
        )
        weighted_components["booking_availability"] += (
            AVAILABILITY_WEIGHT
            * _availability_similarity(
                item["matching_windows"],
                pref.availability_windows,
                weekday,
            )
            * booking_weight
        )

    if total_weight > 0:
        weighted_components = {
            key: (value / total_weight) * WEIGHT_BASE_PREF
            for key, value in weighted_components.items()
        }

    scores = {
        **weighted_components,
        "learned_interactions": max(0.0, rl_learning_score) * WEIGHT_RL_SCORE,
        "reliability": max(0.0, float(item.get("reliability") or 0.0)) * 0.05,
    }
    reason_key, reason_score = max(scores.items(), key=lambda entry: entry[1])

    if reason_score <= 0:
        return "Available for your selected date and time."

    if reason_key == "learned_interactions":
        return "Recommended because it matches rooms you saved or booked before."
    if reason_key in {
        "booking_building",
        "booking_floor",
        "booking_capacity",
        "booking_utilities",
        "booking_availability",
    }:
        return "Recommended because it matches rooms from your booking history."
    if reason_key == "reliability":
        return "Recommended because it is a reliable available room."

    return "Recommended for your selected date and time."


async def get_auto_search_recommendations(
    db: AsyncSession,
    user_email: str,
    target_date: date,
    target_time: time, 
    top_k: int = 3,
    exclude_ids: list[str] = None
) -> list[RoomSearchItemOut]: 
    
    if exclude_ids is None:
        exclude_ids = []
    
    # 1. Resolve Time & Context
    weekday_str = _PYTHON_WEEKDAY_MAP[target_date.weekday()]
    if weekday_str == "sunday":
        return []

    db_weekday = _DB_WEEKDAY[weekday_str]
    is_saturday = (weekday_str == "saturday")
    campus_open = time(6, 0) if is_saturday else time(5, 30)
    campus_close = time(18, 0) if is_saturday else time(22, 0)

    if target_time >= campus_close:
        return [] 
        
    search_since = max(target_time, campus_open)

    all_available_rows = await fetch_room_search_rows(
        db,
        target_date=target_date,
        weekday=db_weekday,
        since=search_since, 
        until=campus_close,  
        room_prefixes=[],
        building_codes=[],
        utilities=[]
    )

    all_available_rows = [row for row in all_available_rows if row.room_id not in exclude_ids]

    if not all_available_rows:
        return []

    # 4. Stratified Sampling (In-Memory)
    rooms_by_building = defaultdict(list)
    for row in all_available_rows:
        rooms_by_building[row.building_code].append(row)

    sampled_rows = []
    MAX_ROOMS_PER_BUILDING_SAMPLE = 5
    for building_code, rows_in_building in rooms_by_building.items():
        sample_size = min(len(rows_in_building), MAX_ROOMS_PER_BUILDING_SAMPLE)
        sampled_rows.extend(random.sample(rows_in_building, sample_size))

    grouped: dict[str, dict] = {}
    
    # Ensure you have your enum mapped (e.g., Weekday.monday)
    # Assuming weekday_str is a string like "monday"
    enum_weekday = getattr(Weekday, weekday_str) 

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
                "final_ml_score": 0.0, 
            }
        
        # --- THE FIX: SANITIZE THE DB RAW TIMES HERE ---
        clipped_window = clip_to_operating_hours(
            enum_weekday, 
            row.rule_start_time, 
            row.rule_end_time
        )
        
        if clipped_window:
            c_start, c_end = clipped_window
            
            # Only add the window if the CLIPPED end time hasn't passed today!
            if c_end > target_time:
                window = TimeWindowOut(start=c_start, end=c_end)
                if window not in grouped[row.room_id]["matching_windows"]:
                    grouped[row.room_id]["matching_windows"].append(window)

    # Filter out any rooms that ended up having no future windows today
    candidates = [c for c in grouped.values() if len(c["matching_windows"]) > 0]

    # 5. STAGE 2: Heavy Scoring (Preferences + RL)
    user_preferences = await list_user_room_preferences(db, user_email=user_email)
    
    # We pass the CURRENT time to the RL engine so it learns what they like *at this time of day*
    rl_scores_map = await get_user_contextual_scores(
        db, user_email=user_email, weekday=weekday_str, slot_start=search_since
    )

    for item in candidates:
        base_interest_score = _compute_interest_score(item, user_preferences, weekday=db_weekday)
        rl_learning_score = rl_scores_map.get(item["room_id"], 0.0)
        item["final_ml_score"] = (base_interest_score * WEIGHT_BASE_PREF) + (rl_learning_score * WEIGHT_RL_SCORE)
        item["recommendation_reason"] = _recommendation_reason(
            item,
            user_preferences,
            weekday=db_weekday,
            rl_learning_score=rl_learning_score,
        )

    candidates.sort(key=lambda x: (-x["final_ml_score"], -x["reliability"], x["room_id"]))

    # 6. Epsilon-Greedy Logic
    final_selection = []
    if len(candidates) > 0:
        if random.random() > EPSILON:
            final_selection = candidates[:top_k]
        else:
            exploration_pick = random.choice(candidates)
            final_selection.append(exploration_pick)
            remaining = [c for c in candidates if c["room_id"] != exploration_pick["room_id"]]
            final_selection.extend(remaining[:top_k - 1])

    # 7. Final Mapping
    response_items = []
    for item in final_selection:
        sorted_windows = sorted(item["matching_windows"], key=lambda w: w.start)
        
        response_items.append(RoomSearchItemOut(
            **{k: v for k, v in item.items() if k not in ["matching_windows", "final_ml_score"]},
            distance_seconds=None, 
            matching_windows=sorted_windows
        ))

    return response_items
