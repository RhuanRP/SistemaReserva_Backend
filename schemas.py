from pydantic import BaseModel

class EventBase(BaseModel):
    name: str
    total_slots: int

class Event(EventBase):
    id: int
    available_slots: int

class ReservationBase(BaseModel):
    event_id: int
    user_name: str
    user_phone: str

class AdminConfig(BaseModel):
    max_events: int
    max_users: int
    choice_time: int

class Reservation(ReservationBase):
    id: int
    status: str

class AdminConfig(BaseModel):
    max_events: int
    max_users: int
    choice_time: int

class ConfirmReservationRequest(BaseModel):
    event_id: int
    user_id: str
    name: str
    phone: str
