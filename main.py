from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from schemas import Event, EventBase
from memory import (
    add_event,
    events,
    set_admin_config,
    admin_config,
    online_users,
    add_to_queue,
    remove_from_queue,
    reserve_with_timeout,
    active_timers,
    check_timers,
    connection_last_activity,
    check_inactive_connections,
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
def configure_system(max_events: int, max_users: int, choice_time: int):
    set_admin_config(max_events, max_users, choice_time)
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
        "online_users": online_users[:admin_config["max_users"]],  # Usuários ativos
        "queue": online_users[admin_config["max_users"]:],  # Usuários na fila
    }

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


# Função para serializar timers ativos
def serialize_timers(timers):
    """
    Converte os timers ativos para um formato serializável em JSON.
    """
    return {
        user_id: {
            "event_id": timer["event_id"],
            "expires_at": timer["expires_at"].isoformat()  # Converte datetime para string ISO 8601
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
        """
        Envia mensagens para todas as conexões ativas.
        Serializa objetos datetime automaticamente para ISO 8601.
        """
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

# WebSocket para comunicação em tempo real
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    user_id = websocket.query_params.get("user_id")
    if not user_id:
        logging.warning("Conexão WebSocket recusada: user_id ausente.")
        await websocket.close(code=403)
        return

    logging.info(f"Usuário {user_id} conectado via WebSocket.")
    add_to_queue(user_id)
    await manager.connect(websocket)

    try:
        while True:
            connection_last_activity[user_id] = datetime.now()

            check_timers()

            data = {
                "events": events,
                "online_users": online_users[:admin_config["max_users"]],
                "queue": online_users[admin_config["max_users"]:],
                "timers": serialize_timers(active_timers),
            }

            await manager.broadcast(data)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logging.info(f"Usuário {user_id} desconectado.")
        manager.disconnect(websocket)
        remove_from_queue(user_id)
    finally:
        logging.info(f"Encerrando conexão com usuário {user_id}.")
        manager.disconnect(websocket)
        remove_from_queue(user_id)
        await websocket.close(code=1000)

@app.on_event("startup")
async def startup_event():
    async def monitor_inactive_connections():
        while True:
            check_inactive_connections(timeout_seconds=30)
            await asyncio.sleep(10)

    asyncio.create_task(monitor_inactive_connections())
