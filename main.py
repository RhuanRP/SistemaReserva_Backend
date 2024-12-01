from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from schemas import Event, EventBase, AdminConfig
from memory import (
    queue_manager,
    add_event,
    events,
    set_admin_config,
    admin_config,
    reserve_with_timeout,
    active_timers,
    check_timers,
    reservations,
    confirm_reservation,
    initialize_default_events,
    serialize_timers,
)
import asyncio
import logging
from datetime import datetime
from pydantic import BaseModel

# Configuração do log
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# Middleware para CORS (necessário para comunicação com React)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Alterar para o domínio do React em produção
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurar parâmetros administrativos
@app.post("/admin/config/")
def configure_system(config: AdminConfig):
    set_admin_config(config.max_events, config.max_users, config.choice_time)
    logging.info("Configuração administrativa atualizada.")
    return {"message": "Configuração atualizada com sucesso.", "config": admin_config}

# Criar eventos
@app.post("/admin/events/", response_model=Event)
def create_event(event: EventBase):
    new_event = add_event(event.name, event.total_slots)
    if not new_event:
        logging.warning("Tentativa de criar evento além do limite permitido.")
        raise HTTPException(status_code=400, detail="Limite de eventos atingido.")
    logging.info(f"Evento '{new_event['name']}' criado com sucesso.")
    return new_event

# Listar eventos
@app.get("/events/")
def list_events():
    logging.info("Listagem de eventos solicitada.")
    return events

# Listar usuários online e na fila
@app.get("/users/")
def get_users():
    logging.info("Solicitação de usuários online e fila.")
    return {
        "online_users": online_users[:admin_config["max_users"]],
        "queue": online_users[admin_config["max_users"]:],
    }

# Modelo para criar reservas temporárias
class ReservationRequest(BaseModel):
    event_id: int
    user_id: str

@app.post("/reservations/")
async def create_reservation(reservation: ReservationRequest):
    event_id = reservation.event_id
    user_id = reservation.user_id

    logging.info(f"Tentativa de reserva por {user_id} para o evento {event_id}.")
    for event in events:
        if event["id"] == event_id:
            if event["available_slots"] > 0:
                event["available_slots"] -= 1
                await reserve_with_timeout(event_id, user_id, admin_config["choice_time"])
                logging.info(f"Reserva temporária criada para o usuário {user_id} no evento {event['name']}.")
                return {"message": "Reserva temporária criada com sucesso.", "event": event}
            else:
                logging.warning(f"Reserva falhou: Evento {event['name']} está cheio.")
                raise HTTPException(status_code=400, detail="Evento cheio.")
    logging.error(f"Reserva falhou: Evento {event_id} não encontrado.")
    raise HTTPException(status_code=404, detail="Evento não encontrado.")

# Modelo para confirmar reservas
class ConfirmReservationRequest(BaseModel):
    event_id: int
    user_id: str
    name: str
    phone: str

@app.post("/confirm-reservation/")
async def confirm_reservation_endpoint(request: ConfirmReservationRequest):
    user_id = request.user_id
    event_id = request.event_id

    logging.info(f"Tentativa de confirmação de reserva para {user_id} no evento {event_id}.")

    # Usar a função confirm_reservation do memory.py
    result = confirm_reservation(event_id, user_id)
    if "error" in result:
        logging.warning(f"Erro na confirmação: {result['error']}")
        raise HTTPException(status_code=400, detail=result["error"])

    # Adicionar informações adicionais à reserva
    for reservation in reservations:
        if reservation["user_id"] == user_id and reservation["event_id"] == event_id:
            reservation["name"] = request.name
            reservation["phone"] = request.phone
            break

    logging.info(f"Reserva confirmada com sucesso para {user_id} no evento {event_id}.")
    return {"message": "Reserva confirmada com sucesso."}

# Serializar timers ativos
def serialize_timers(timers):
    return {
        user_id: {
            "event_id": timer["event_id"],
            "expires_at": timer["expires_at"].isoformat()
        }
        for user_id, timer in timers.items()
    }

# Classe para gerenciar conexões WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logging.info("Nova conexão WebSocket aceita.")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logging.info("Conexão WebSocket encerrada.")

    async def broadcast(self, message: dict):
        invalid_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logging.error(f"Erro ao enviar mensagem via WebSocket: {e}")
                invalid_connections.append(connection)

        for connection in invalid_connections:
            self.disconnect(connection)

# Instância global do gerenciador de conexões
manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user_id: str = None):
    if not user_id:
        user_id = f"user_{datetime.now().strftime('%H:%M:%S')}"
    
    logging.info(f"Usuário {user_id} conectado via WebSocket.")
    
    # Aceitar a conexão WebSocket
    await websocket.accept()
    
    # Adicionar usuário à fila e verificar se está ativo
    is_active = queue_manager.add_user(user_id)
    
    # Enviar estado inicial
    initial_data = {
        "events": events,
        "online_users": list(queue_manager.active_users),
        "queue": list(queue_manager.waiting_queue),
        "timers": serialize_timers(active_timers),
        "user_status": "active" if is_active else f"queue_{queue_manager.get_queue_position(user_id)}",
        "interaction_timeout": queue_manager.get_remaining_time(user_id)
    }
    await websocket.send_json(initial_data)

    try:
        while True:
            try:
                # Aguardar mensagem do cliente
                await websocket.receive_text()
                
                # Verificar usuários expirados e processar fila
                expired_users = queue_manager._clean_expired_users()
                
                # Preparar dados atualizados
                data = {
                    "events": events,
                    "online_users": list(queue_manager.active_users),
                    "queue": list(queue_manager.waiting_queue),
                    "timers": serialize_timers(active_timers),
                    "user_status": "active" if user_id in queue_manager.active_users else f"queue_{queue_manager.get_queue_position(user_id)}",
                    "interaction_timeout": queue_manager.get_remaining_time(user_id)
                }
                
                # Enviar atualizações
                await websocket.send_json(data)
                
            except WebSocketDisconnect:
                raise
            
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        logging.info(f"Usuário {user_id} desconectado.")
        queue_manager.remove_user(user_id)
        
        # Notificar outros usuários da desconexão
        broadcast_data = {
            "events": events,
            "online_users": list(queue_manager.active_users),
            "queue": list(queue_manager.waiting_queue),
            "timers": serialize_timers(active_timers)
        }
        
        # Broadcast para outros usuários
        for connection in manager.active_connections:
            if connection != websocket:
                await connection.send_json(broadcast_data)

@app.on_event("startup")
async def startup_event():
    # Inicializa eventos padrão
    initialize_default_events()
    
    async def monitor_inactive_connections():
        while True:
            check_inactive_connections(timeout_seconds=30)
            await asyncio.sleep(10)

    asyncio.create_task(monitor_inactive_connections())