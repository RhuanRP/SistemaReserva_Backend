import React, { useState, useEffect } from 'react'
import { useRealTimeUpdates } from '../hooks/useRealTimeUpdates'
import styles from '../styles/UserPage.module.css'
import { v4 as uuidv4 } from 'uuid'

const UserPage = () => {
  // Gerar user_id único
  const [userId] = useState(() => {
    const existingUserId = localStorage.getItem('user_id')
    if (existingUserId) {
      return existingUserId
    } else {
      const newUserId = uuidv4()
      localStorage.setItem('user_id', newUserId)
      return newUserId
    }
  })

  const {
    events,
    online_users,
    queue,
    timers,
    user_status,
    interaction_timeout,
    was_moved_to_queue: wasMovedToQueue,
    isConnected,
    isActive,
    timeLeft,
    userStatus
  } = useRealTimeUpdates(userId)

  // Estado para mensagens de feedback
  const [feedback, setFeedback] = useState('')
  const [confirmingEvent, setConfirmingEvent] = useState(null) // Evento atual para confirmação
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')

  // Estado local para o timer
  const [localTimer, setLocalTimer] = useState(30)

  // Efeito para atualizar o timer local
  useEffect(() => {
    if (interaction_timeout > 0) {
      setLocalTimer(interaction_timeout)
    }
  }, [interaction_timeout])

  // Timer visual que atualiza a cada segundo
  useEffect(() => {
    let interval
    if (user_status === 'active' && localTimer > 0) {
      interval = setInterval(() => {
        setLocalTimer(prev => Math.max(0, prev - 1))
      }, 1000)
    }
    return () => clearInterval(interval)
  }, [user_status, localTimer])

  // Componente para exibir o status do usuário e timer
  const UserStatus = () => {
    if (isActive && timeLeft > 0) {
      const timerColor = timeLeft < 10 ? '#ff4444' : '#4CAF50'
      return (
        <div
          className={`${styles.statusBar} ${
            timeLeft < 10 ? styles.warning : ''
          }`}
        >
          <div className={styles.statusContent}>
            <span className={styles.statusText}>{userStatus.message}</span>
            <span className={styles.timer}>Tempo restante: {timeLeft}s</span>
          </div>
          <div
            className={styles.timerBar}
            style={{
              width: `${(timeLeft / 30) * 100}%`,
              backgroundColor: timerColor,
              transition: 'all 1s linear'
            }}
          />
        </div>
      )
    } else if (userStatus.type === 'queue') {
      return (
        <div className={styles.statusBar}>
          <span>{userStatus.message}</span>
          <div className={styles.queueInfo}>Aguarde sua vez...</div>
        </div>
      )
    }
    return null
  }

  const handleReservation = async eventId => {
    try {
      const response = await fetch('http://localhost:8000/reservations/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          event_id: eventId,
          user_id: userId
        })
      })

      if (response.ok) {
        const data = await response.json()
        setFeedback(
          `Reserva criada com sucesso para o evento: ${data.event.name}`
        )
      } else {
        const error = await response.json()
        setFeedback(`Erro: ${error.detail}`)
      }
    } catch (error) {
      setFeedback('Erro ao realizar a reserva. Tente novamente mais tarde.')
    }
  }

  const handleConfirmReservation = async () => {
    if (!name || !phone) {
      setFeedback('Por favor, preencha seu nome e telefone.')
      return
    }

    try {
      const response = await fetch(
        'http://localhost:8000/confirm-reservation/',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            event_id: confirmingEvent,
            user_id: userId,
            name,
            phone
          })
        }
      )

      if (response.ok) {
        setFeedback('Reserva confirmada com sucesso!')
        setConfirmingEvent(null) // Fecha o modal
        setName('')
        setPhone('')
      } else {
        const error = await response.json()
        setFeedback(`Erro: ${error.detail}`)
      }
    } catch (error) {
      setFeedback('Erro ao confirmar a reserva. Tente novamente mais tarde.')
    }
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.header}>Sistema de Reserva de Eventos</h1>

      {/* Status de Conexão e UserStatus permanecem no topo */}
      <div
        className={`${styles.connectionStatus} ${
          isConnected ? styles.connected : styles.disconnected
        }`}
      >
        <span className={styles.statusDot} />
        {isConnected ? 'Conectado' : 'Reconectando...'}
      </div>
      <UserStatus />

      {/* Layout principal com grid */}
      <div className={styles.mainLayout}>
        {/* Coluna principal com eventos */}
        <div className={styles.mainContent}>
          <div className={styles.section}>
            <h2>Eventos Disponíveis</h2>
            <div className={styles.gridContainer}>
              {events.map(event => (
                <div key={event.id} className={styles.card}>
                  <h3>{event.name}</h3>
                  <p>Vagas disponíveis: {event.available_slots}</p>
                  <button
                    className={styles.button}
                    onClick={() => handleReservation(event.id)}
                  >
                    Reservar
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Sidebar direita */}
        <div className={styles.sidebar}>
          <div className={styles.section}>
            <h2>Usuários Online</h2>
            <p>Total: {online_users.length}</p>
          </div>

          <div className={styles.section}>
            <h2>Fila de Espera</h2>
            <ul className={styles.list}>
              {queue.map((user, index) => (
                <li key={index}>{user}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      {/* Feedback de movimento para fila com animação */}
      {wasMovedToQueue && (
        <div
          className={`${styles.feedback} ${styles.warning} ${styles.slideIn}`}
        >
          <span className={styles.warningIcon}>⚠️</span>
          Você foi movido para o final da fila por inatividade.
        </div>
      )}

      {/* Mensagem de Feedback */}
      {feedback && <div className={styles.feedback}>{feedback}</div>}

      {/* Seção de Timers - só aparece quando há timers ativos */}
      {Object.keys(timers).length > 0 && (
        <div className={`${styles.section} ${styles.timerSection}`}>
          <h2>Seu Timer Ativo</h2>
          <div className={styles.timerContainer}>
            {Object.entries(timers)
              .sort(
                ([, a], [, b]) =>
                  new Date(b.expires_at) - new Date(a.expires_at)
              )
              .map(([timerUserId, timer]) => {
                const expiresAt = new Date(timer.expires_at)
                const timeLeft = Math.max(0, (expiresAt - new Date()) / 1000)

                return (
                  <div key={timerUserId} className={styles.timer}>
                    <div className={styles.timerInfo}>
                      <span className={styles.timerIcon}>⏳</span>
                      <span className={styles.timerText}>
                        {timerUserId === userId
                          ? 'Seu timer'
                          : `Usuário ${timerUserId}`}
                      </span>
                      <span className={styles.timerCountdown}>
                        {Math.floor(timeLeft)}s restantes
                      </span>
                    </div>
                    {timerUserId === userId && (
                      <button
                        className={styles.timerButton}
                        onClick={() => setConfirmingEvent(timer.event_id)}
                      >
                        Confirmar Reserva
                      </button>
                    )}
                  </div>
                )
              })}
          </div>
        </div>
      )}

      {/* Modal de confirmação */}
      {confirmingEvent && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2 className={styles.modalTitle}>Confirme sua Reserva</h2>
              <p className={styles.modalSubtitle}>
                Preencha seus dados para finalizar a reserva
              </p>
            </div>
            <div className={styles.modalForm}>
              <div className={styles.inputGroup}>
                <label className={styles.inputLabel}>Nome Completo</label>
                <input
                  type="text"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  className={styles.input}
                  placeholder="Digite seu nome completo"
                />
              </div>
              <div className={styles.inputGroup}>
                <label className={styles.inputLabel}>Telefone</label>
                <input
                  type="tel"
                  value={phone}
                  onChange={e => setPhone(e.target.value)}
                  className={styles.input}
                  placeholder="(00) 00000-0000"
                />
              </div>
              <div className={styles.modalButtons}>
                <button
                  className={styles.confirmButton}
                  onClick={handleConfirmReservation}
                >
                  Confirmar Reserva
                </button>
                <button
                  className={styles.cancelButton}
                  onClick={() => setConfirmingEvent(null)}
                >
                  Cancelar
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default UserPage
