import asyncio
from datetime import datetime, timedelta
import logging

# Simulação de banco de dados em memória
events = []
reservations = []
online_users = []  # Lista de usuários online
reservation_timeouts = {}  # Temporizadores de reservas temporárias
admin_config = {
    "max_events": 5,  # Máximo de eventos disponíveis
    "max_users": 3,   # Número máximo de usuários simultâneos
    "choice_time": 120  # Tempo de escolha em segundos
}
active_timers = {}  # Armazena timers ativos com horários de expiração
connection_last_activity = {}  # Rastreia a última atividade de cada usuário

# Funções utilitárias para administração
def set_admin_config(max_events: int, max_users: int, choice_time: int):
    admin_config["max_events"] = max_events
    admin_config["max_users"] = max_users
    admin_config["choice_time"] = choice_time

def add_event(name: str, total_slots: int):
    if len(events) >= admin_config["max_events"]:
        return None  # Limite de eventos atingido
    event_id = len(events) + 1
    new_event = {
        "id": event_id,
        "name": name,
        "total_slots": total_slots,
        "available_slots": total_slots,
    }
    events.append(new_event)
    return new_event

def get_event_by_id(event_id: int):
    for event in events:
        if event["id"] == event_id:
            return event
    return None

def add_to_queue(user_id: str):
    if user_id not in online_users:
        online_users.append(user_id)
    connection_last_activity[user_id] = datetime.now()  # Atualiza última atividade

def remove_from_queue(user_id: str):
    if user_id in online_users:
        online_users.remove(user_id)
        logging.info(f"Usuário {user_id} removido da lista. Usuários online: {online_users}")
    connection_last_activity.pop(user_id, None)  # Remove do rastreamento de atividade

def get_current_queue():
    # Retorna usuários fora do limite de interação simultânea
    return online_users[admin_config["max_users"]:]

def get_active_users():
    # Retorna os usuários atualmente interagindo com os cards
    return online_users[:admin_config["max_users"]]

# Gerenciamento de reservas temporárias
async def reserve_with_timeout(event_id: int, user_id: str, timeout: int):
    """
    Cria uma reserva temporária com timeout.
    """
    if user_id in reservation_timeouts:
        return {"error": "Usuário já tem uma reserva ativa."}

    expiration_time = datetime.now() + timedelta(seconds=timeout)
    active_timers[user_id] = {
        "event_id": event_id,
        "expires_at": expiration_time
    }

    reservation_timeouts[user_id] = asyncio.create_task(
        timeout_reservation(event_id, user_id, timeout)
    )
    return {"message": "Reserva temporária criada com sucesso."}

async def timeout_reservation(event_id: int, user_id: str, timeout: int):
    """
    Libera uma vaga automaticamente após o tempo limite.
    """
    await asyncio.sleep(timeout)

    # Remove a reserva temporária do usuário
    if user_id in reservation_timeouts:
        reservation_timeouts.pop(user_id)
        active_timers.pop(user_id, None)

    # Libera a vaga no evento correspondente
    event = get_event_by_id(event_id)
    if event:
        event["available_slots"] += 1

# Função para cancelar reserva temporária manualmente
def cancel_reservation(event_id: int, user_id: str):
    """
    Cancela uma reserva temporária manualmente.
    """
    if user_id in reservation_timeouts:
        reservation_timeouts[user_id].cancel()
        reservation_timeouts.pop(user_id)
        active_timers.pop(user_id, None)
    event = get_event_by_id(event_id)
    if event:
        event["available_slots"] += 1

# Função para verificar timers expirados
def check_timers():
    """
    Verifica se algum timer expirou e libera as vagas correspondentes.
    """
    current_time = datetime.now()
    expired_users = []

    for user_id, timer in list(active_timers.items()):
        if timer["expires_at"] < current_time:
            expired_users.append(user_id)

    for user_id in expired_users:
        event = get_event_by_id(active_timers[user_id]["event_id"])
        if event:
            event["available_slots"] += 1
        active_timers.pop(user_id, None)
        reservation_timeouts.pop(user_id, None)

# Função para verificar conexões inativas
def check_inactive_connections(timeout_seconds: int = 30):
    """
    Verifica e remove usuários inativos com base no tempo limite.
    """
    current_time = datetime.now()
    inactive_users = [
        user_id
        for user_id, last_activity in list(connection_last_activity.items())
        if (current_time - last_activity).total_seconds() > timeout_seconds
    ]

    for user_id in inactive_users:
        remove_from_queue(user_id)
        connection_last_activity.pop(user_id, None)
        if user_id in active_timers:
            cancel_reservation(active_timers[user_id]["event_id"], user_id)
        logging.info(f"Usuário {user_id} removido por inatividade.")
