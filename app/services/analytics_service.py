from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.analytics_repo import (
    ensure_session_exists,
    get_schedule_import_funnel_raw,
    insert_analytics_event,
)
from app.schemas.analytics import (
    AnalyticsEventIn,
    AnalyticsEventOut,
    FunnelStepStat,
    MethodFunnelOut,
    SCHEDULE_IMPORT_STEPS,
    ScheduleImportFunnelOut,
    ScheduleImportStepIn,
    ScheduleImportStepOut,
)


async def track_homepage_event(
    db: AsyncSession,
    payload: AnalyticsEventIn,
) -> AnalyticsEventOut:
    await ensure_session_exists(
        db,
        session_id=payload.session_id,
        device_id=payload.device_id,
        user_email=payload.user_email,
    )

    await insert_analytics_event(
        db,
        session_id=payload.session_id,
        user_email=payload.user_email,
        event_name=payload.event_name,
        screen=payload.screen,
        duration_ms=payload.duration_ms,
        props_json=payload.props_json,
    )

    await db.commit()
    return AnalyticsEventOut(ok=True)


# ── Schedule import funnel ────────────────────────────────────────────────────

async def track_schedule_import_step(
    db: AsyncSession,
    payload: ScheduleImportStepIn,
) -> ScheduleImportStepOut:
    await ensure_session_exists(
        db,
        session_id=payload.session_id,
        device_id=payload.device_id,
        user_email=payload.user_email,
    )

    await insert_analytics_event(
        db,
        session_id=payload.session_id,
        user_email=payload.user_email,
        event_name="schedule_import_step",
        screen="schedule_import",
        duration_ms=None,
        props_json={
            "method": payload.method,
            "step": payload.step,
            "step_number": payload.step_number,
            **payload.props_json,
        },
    )

    await db.commit()
    return ScheduleImportStepOut(ok=True)


async def get_schedule_import_funnel(
    db: AsyncSession,
) -> ScheduleImportFunnelOut:
    """
    Answers BQ: 'What is the most common way users upload/import their
    schedule, and which method has the highest drop-off by step?'
    """
    raw = await get_schedule_import_funnel_raw(db)

    # Build {method: {step_number: (step_name, user_count)}}
    data: dict[str, dict[int, tuple[str, int]]] = {}
    for method, step_number, step, users in raw:
        data.setdefault(method, {})[step_number] = (step, users)

    # Ensure all known methods appear even with zero data
    for method in SCHEDULE_IMPORT_STEPS:
        data.setdefault(method, {})

    method_funnels: list[MethodFunnelOut] = []
    for method, step_definitions in SCHEDULE_IMPORT_STEPS.items():
        step_stats: list[FunnelStepStat] = []
        prev_users: int | None = None

        for step_number, step_name in enumerate(step_definitions, start=1):
            step_data = data[method].get(step_number)
            users = step_data[1] if step_data else 0

            dropoff_pct: float | None = None
            if prev_users is not None and prev_users > 0:
                dropoff_pct = round(
                    (prev_users - users) / prev_users * 100, 1
                )
            elif prev_users == 0:
                dropoff_pct = None

            step_stats.append(
                FunnelStepStat(
                    step_number=step_number,
                    step=step_name,
                    users_reached=users,
                    dropoff_from_prev_pct=dropoff_pct,
                )
            )
            prev_users = users

        total_started = step_stats[0].users_reached if step_stats else 0
        total_completed = step_stats[-1].users_reached if step_stats else 0
        completion_rate = (
            round(total_completed / total_started * 100, 1)
            if total_started > 0
            else 0.0
        )

        method_funnels.append(
            MethodFunnelOut(
                method=method,
                total_started=total_started,
                total_completed=total_completed,
                completion_rate_pct=completion_rate,
                steps=step_stats,
            )
        )

    # Most common method = highest total_started
    most_common = max(
        method_funnels, key=lambda m: m.total_started, default=None)

    # Highest drop-off method = worst max step-to-step drop-off rate
    def _worst_dropoff(mf: MethodFunnelOut) -> float:
        rates = [
            s.dropoff_from_prev_pct
            for s in mf.steps
            if s.dropoff_from_prev_pct is not None
        ]
        return max(rates) if rates else 0.0

    highest_dropoff = max(method_funnels, key=_worst_dropoff, default=None)

    return ScheduleImportFunnelOut(
        most_common_method=most_common.method if most_common and most_common.total_started > 0 else None,
        highest_dropoff_method=highest_dropoff.method if highest_dropoff and _worst_dropoff(
            highest_dropoff) > 0 else None,
        methods=method_funnels,
    )
