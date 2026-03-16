import enum
import uuid
from sqlalchemy import (
    String, Integer, Boolean, Date, Time, Enum, ForeignKey,
    UniqueConstraint, Index, Text, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from datetime import datetime

# ---------- Enums ----------

class BookingPurpose(str, enum.Enum):
    study_alone = "study_alone"
    study_small_group = "study_small_group"
    chill_alone = "chill_alone"
    hangout_friends = "hangout_friends"
    tutoring_big_group = "tutoring_big_group"

class BookingStatus(str, enum.Enum):
    active = "active"
    cancelled = "cancelled"
    completed = "completed"

class UtilityType(str, enum.Enum):
    blackout = "blackout"
    power_outlet = "power_outlet"
    television = "television"
    interactive_classroom = "interactive_classroom"
    mobile_whiteboards = "mobile_whiteboards"
    computer = "computer"
    videobeam = "videobeam"

class ScheduleSource(str, enum.Enum):
    google_sync = "google_sync"
    ics_import = "ics_import"
    pdf_import = "pdf_import"
    manual = "manual"

class Weekday(str, enum.Enum):
    monday = "monday"
    tuesday = "tuesday"
    wednesday = "wednesday"
    thursday = "thursday"
    friday = "friday"
    saturday = "saturday"
    sunday = "sunday"

class ChatRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"

class NavNodeType(str, enum.Enum):
    outdoor = "outdoor"
    entrance = "entrance"
    hallway = "hallway"
    stairs = "stairs"
    elevator = "elevator"
    room_anchor = "room_anchor"

# ---------- Core Tables ----------

class User(Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String, primary_key=True) 
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    first_semester: Mapped[str] = mapped_column(String, nullable=False)

class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    user_email: Mapped[str | None] = mapped_column(ForeignKey("users.email"), nullable=True)

class Term(Base):
    __tablename__ = "terms"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    start_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

class Building(Base):
    __tablename__ = "buildings"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)

class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "ML 517"
    building_code: Mapped[str] = mapped_column(ForeignKey("buildings.code"), nullable=False)
    room_number: Mapped[str] = mapped_column(String, nullable=False)
    building_name: Mapped[str | None] = mapped_column(String, nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    reliability: Mapped[float] = mapped_column(nullable=False, default=100.0)

class RoomUtility(Base):
    __tablename__ = "room_utilities"
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    utility: Mapped[UtilityType] = mapped_column(Enum(UtilityType), primary_key=True)

# ---------- Availability Rules ----------

class RoomAvailabilityRule(Base):
    __tablename__ = "room_availability_rules"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    term_id: Mapped[str] = mapped_column(ForeignKey("terms.id"), nullable=False)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    day: Mapped[Weekday] = mapped_column(Enum(Weekday), nullable=False)
    start_time: Mapped[str] = mapped_column(Time, nullable=False)
    end_time: Mapped[str] = mapped_column(Time, nullable=False)
    valid_from: Mapped[Date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[Date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        Index("ix_avail_room_term_day", "room_id", "term_id", "day"),
        UniqueConstraint("room_id", "term_id", "day", "start_time", "end_time", "valid_from", "valid_to",
                         name="uq_avail_rule_full"),
    )

# ---------- Bookings / Favorites ----------

class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_email: Mapped[str] = mapped_column(ForeignKey("users.email"), nullable=False)
    term_id: Mapped[str] = mapped_column(ForeignKey("terms.id"), nullable=False)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), nullable=False)

    date: Mapped[Date] = mapped_column(Date, nullable=False)
    start_time: Mapped[str] = mapped_column(Time, nullable=False)
    end_time: Mapped[str] = mapped_column(Time, nullable=False)

    purpose: Mapped[BookingPurpose] = mapped_column(Enum(BookingPurpose), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), nullable=False, default=BookingStatus.active)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_booking_user_status", "user_email", "status"),
        Index("ix_booking_room_window", "room_id", "date", "start_time", "end_time"),
        Index("ix_booking_user_created", "user_email", "created_at"),
    )

class Favorite(Base):
    __tablename__ = "favorites"
    user_email: Mapped[str] = mapped_column(ForeignKey("users.email"), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), primary_key=True)

# ---------- Reports ----------

class Report(Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_email: Mapped[str | None] = mapped_column(ForeignKey("users.email"), nullable=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    reported_at: Mapped[str] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    has_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_missing_utilities: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    missing_utilities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_reports_room_time", "room_id", "reported_at"),
    )

# ---------- Schedules ----------

class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_email: Mapped[str] = mapped_column(ForeignKey("users.email"), nullable=False)
    source: Mapped[ScheduleSource] = mapped_column(Enum(ScheduleSource), nullable=False)

class ScheduleClass(Base):
    __tablename__ = "schedule_classes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedules.id"), nullable=False)

    title: Mapped[str | None] = mapped_column(String, nullable=True)
    location_text: Mapped[str | None] = mapped_column(String, nullable=True)
    building_code: Mapped[str | None] = mapped_column(ForeignKey("buildings.code"), nullable=True)
    room_id: Mapped[str | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)

    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Date] = mapped_column(Date, nullable=False)
    start_time: Mapped[str] = mapped_column(Time, nullable=False)
    end_time: Mapped[str] = mapped_column(Time, nullable=False)

class ScheduleClassWeekday(Base):
    __tablename__ = "schedule_class_weekdays"
    schedule_class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedule_classes.id"), primary_key=True)
    day: Mapped[Weekday] = mapped_column(Enum(Weekday), primary_key=True)

# ---------- Analytics ----------

class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[str] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    user_email: Mapped[str | None] = mapped_column(ForeignKey("users.email"), nullable=True)
    event_name: Mapped[str] = mapped_column(String, nullable=False)
    screen: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    props_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_ae_name_ts", "event_name", "ts"),
        Index("ix_ae_screen_ts", "screen", "ts"),
        Index("ix_ae_user_ts", "user_email", "ts"),
        Index("ix_ae_session_ts", "session_id", "ts"),
    )

# ---------- Chatbot ----------

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    user_email: Mapped[str | None] = mapped_column(ForeignKey("users.email"), nullable=True)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id"), nullable=False)
    ts: Mapped[str] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

class ChatAction(Base):
    __tablename__ = "chat_actions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id"), nullable=False)
    ts: Mapped[str] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

# ---------- Navigation Graph ----------

class NavNode(Base):
    __tablename__ = "nav_nodes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    building_code: Mapped[str | None] = mapped_column(ForeignKey("buildings.code"), nullable=True)
    floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lat: Mapped[float | None] = mapped_column(nullable=True)
    lon: Mapped[float | None] = mapped_column(nullable=True)
    x: Mapped[float | None] = mapped_column(nullable=True)
    y: Mapped[float | None] = mapped_column(nullable=True)
    node_type: Mapped[NavNodeType] = mapped_column(Enum(NavNodeType), nullable=False)

class NavEdge(Base):
    __tablename__ = "nav_edges"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nav_nodes.id"), nullable=False)
    to_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nav_nodes.id"), nullable=False)
    weight_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    accessible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    edge_type: Mapped[str | None] = mapped_column(String, nullable=True)

class RoomNavAnchor(Base):
    __tablename__ = "room_nav_anchor"
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nav_nodes.id"), nullable=False)