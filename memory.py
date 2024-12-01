import asyncio
from datetime import datetime, timedelta, UTC
from collections import deque
from threading import Lock, Semaphore, Thread, RLock
import logging
import threading
import time

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

# Adicionar após as variáveis globais
event_locks = {}  # Lock por evento
global_lock = threading.RLock()  # Lock recursivo global
reservation_semaphore = Semaphore(10)  # Limita reservas simultâneas

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

class QueueManager:
    def __init__(self):
        self.active_users = set()
        self.waiting_queue = deque()
        self.user_queue_times = {}
        self.lock = threading.RLock()
        self.max_users = 3
        self.queue_timeout = 30
        
    def add_user(self, user_id):
        with self.lock:
            self._clean_expired_users()
            
            if len(self.active_users) < self.max_users:
                self.active_users.add(user_id)
                self.user_queue_times[user_id] = datetime.now(UTC)
                return True
                
            if user_id not in self.waiting_queue:
                self.waiting_queue.append(user_id)
                self.user_queue_times[user_id] = datetime.now(UTC)
            return False

    def remove_user(self, user_id):
        with self.lock:
            self.active_users.discard(user_id)
            if user_id in self.waiting_queue:
                self.waiting_queue.remove(user_id)
            self.user_queue_times.pop(user_id, None)
            self._process_queue()

    def _clean_expired_users(self):
        current_time = datetime.now(UTC)
        expired_users = []
        
        # Verifica usuários ativos
        for user_id in list(self.active_users):
            queue_time = self.user_queue_times.get(user_id)
            if queue_time:
                elapsed_time = (current_time - queue_time).total_seconds()
                if elapsed_time > self.queue_timeout:
                    expired_users.append(user_id)
                    
        # Move usuários expirados para o final da fila
        for user_id in expired_users:
            self.active_users.remove(user_id)
            self.waiting_queue.append(user_id)
            self.user_queue_times[user_id] = current_time
            
        # Processa próximo usuário da fila
        self._process_queue()
        
        return expired_users
        
    def _process_queue(self):
        if self.waiting_queue and len(self.active_users) < self.max_users:
            next_user = self.waiting_queue.popleft()
            self.active_users.add(next_user)
            self.user_queue_times[next_user] = datetime.now(UTC)
            return next_user
        return None
        
    def get_queue_position(self, user_id):
        try:
            return list(self.waiting_queue).index(user_id) + 1
        except ValueError:
            return None
            
    def get_remaining_time(self, user_id):
        queue_time = self.user_queue_times.get(user_id)
        if not queue_time:
            return None
        
        elapsed = (datetime.now(UTC) - queue_time).total_seconds()
        remaining = max(0, self.queue_timeout - elapsed)
        return int(remaining)

queue_manager = QueueManager()

# Gerenciamento de reservas temporárias
async def reserve_with_timeout(event_id: int, user_id: str, timeout: int):
    """Cria uma reserva temporária com timeout."""
    try:
        if not reservation_semaphore.acquire(timeout=1):  # timeout de 1 segundo para evitar bloqueio
            return {"error": "Sistema ocupado, tente novamente."}
            
        with global_lock:
            if user_id in reservation_timeouts:
                return {"error": "Usuário já tem uma reserva ativa."}

            event = get_event_by_id(event_id)
            if not event or event["available_slots"] <= 0:
                return {"error": "Não há vagas disponíveis."}

            expiration_time = datetime.now() + timedelta(seconds=timeout)
            active_timers[user_id] = {
                "event_id": event_id,
                "expires_at": expiration_time
            }

            reservation_timeouts[user_id] = asyncio.create_task(
                timeout_reservation(event_id, user_id, timeout)
            )
            
            return {"message": "Reserva temporária criada com sucesso."}
    finally:
        reservation_semaphore.release()

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

def check_inactive_connections(timeout_seconds: int = 30):
    """
    Verifica e remove usuários inativos com base no tempo limite.
    Move usuários inativos para o final da fila.
    """
    current_time = datetime.now()
    inactive_users = [
        user_id
        for user_id, last_activity in list(connection_last_activity.items())
        if (current_time - last_activity).total_seconds() > timeout_seconds
    ]

    for user_id in inactive_users:
        if user_id in online_users[:admin_config["max_users"]]:
            # Remove o usuário da lista
            online_users.remove(user_id)
            # Adiciona ao final da fila
            online_users.append(user_id)
            logging.info(f"Usuário {user_id} movido para o final da fila por inatividade.")
            
            # Cancela qualquer reserva temporária que o usuário possa ter
            if user_id in active_timers:
                cancel_reservation(active_timers[user_id]["event_id"], user_id)
            
            # Atualiza o timestamp para o momento atual
            connection_last_activity[user_id] = current_time

def confirm_reservation(event_id: int, user_id: str):
    """Confirma uma reserva temporária."""
    with global_lock:
        if user_id not in reservation_timeouts:
            return {"error": "Não há reserva temporária ativa para este usuário."}

        event = get_event_by_id(event_id)
        if not event:
            return {"error": "Evento não encontrado."}

        if active_timers[user_id]["event_id"] != event_id:
            return {"error": "O evento não corresponde à reserva temporária."}

        # Cancela o timer de timeout
        reservation_timeouts[user_id].cancel()
        reservation_timeouts.pop(user_id)
        active_timers.pop(user_id)

        # Adiciona à lista de reservas confirmadas
        reservation = {
            "event_id": event_id,
            "user_id": user_id,
            "confirmed_at": datetime.now()
        }
        reservations.append(reservation)

        return {"message": "Reserva confirmada com sucesso."}

def initialize_default_events():
    """
    Inicializa o sistema com eventos padrão
    """
    events.clear()  # Limpa eventos existentes
    
    default_events = [
        {"name": "DevFest", "total_slots": 100},
        {"name": "Campus Party", "total_slots": 1000},
        {"name": "Jogo Palmeiras", "total_slots": 40000},
        {"name": "Palestra", "total_slots": 50},
    ]
    
    for event_data in default_events:
        add_event(event_data["name"], event_data["total_slots"])

def get_remaining_time(user_id: str) -> int:
    """
    Calcula o tempo restante para um usuário baseado em sua última atividade.
    Retorna o tempo em segundos.
    """
    if user_id not in connection_last_activity:
        return 30
        
    elapsed_time = (datetime.now() - connection_last_activity[user_id]).total_seconds()
    remaining_time = max(0, 30 - int(elapsed_time))
    return remaining_time

def serialize_timers(timers):
    """
    Serializa os timers ativos para envio via WebSocket
    """
    return {
        user_id: {
            "event_id": timer["event_id"],
            "expires_at": timer["expires_at"].isoformat()
        }
        for user_id, timer in timers.items()
    }

def get_event_lock(event_id):
    """Obtém ou cria um lock para um evento específico"""
    with global_lock:
        if event_id not in event_locks:
            event_locks[event_id] = Lock()
        return event_locks[event_id]

class ResourceMonitor(Thread):
    def __init__(self, interval=5):
        super().__init__(daemon=True)
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            try:
                with global_lock:
                    check_timers()
                    check_inactive_connections()
            except Exception as e:
                logging.error(f"Erro no monitor de recursos: {e}")
            time.sleep(self.interval)

    def stop(self):
        self._stop_event.set()

# Inicializar o monitor de recursos apenas se ainda não estiver rodando
if not any(isinstance(t, ResourceMonitor) for t in threading.enumerate()):
    resource_monitor = ResourceMonitor()
    resource_monitor.start()