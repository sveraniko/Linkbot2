# Lovender OpsBot - Анализ архитектуры и план реализации

## Executive Summary

Текущий **project-memory-bot** предоставляет отличную основу для создания **Lovender OpsBot**. Архитектура Clean Architecture, aiogram + PostgreSQL + Redis стек, система конфигурации с feature flags, и структура handlers/services идеально подходят для адаптации под ChatOps задачи управления.

**Совместимость: ~75%** - большинство компонентов можно переиспользовать с адаптацией.

---

## 1. Архитектурное сопоставление

### ✅ Что идеально подходит (переиспользуем без изменений)

#### 1.1 Технологический стек
- **aiogram 3.x** → подходит для ChatOps интерфейса
- **PostgreSQL** → для хранения состояний, ролей, аудит-логов
- **Redis** → для кэширования, FSM состояний, rate-limiting
- **Pydantic настройки** → расширим для OpsBot конфигурации
- **Structured logging** → критично для аудита операций

#### 1.2 Архитектурные паттерны
```
app/
├── domain/           # → Бизнес-логика OpsBot (роли, флаги, инциденты)
├── core/            # → Инфраструктура (безопасность, аудит, resilience)
├── bot/             # → Telegram handlers для ChatOps
└── services/        # → Интеграция с lovender API
```

#### 1.3 Готовые компоненты
- `app/config.py` → система настроек с FeatureFlags
- `app/services/cache.py` → кэширование (для метрик, флагов)
- `app/utils/logging_setup.py` → structured logging для аудита
- `app/handlers/menu.py` → inline keyboards подход
- `app/states.py` → FSM управление состояниями

### 🔄 Что нужно адаптировать

#### 1.4 Система состояний
**Текущие состояния** (memory-focused):
```python
class MemoryStates(StatesGroup):
    selecting_project = State()
    entering_context = State()
```

**Новые состояния OpsBot** (ops-focused):
```python
class OpsStates(StatesGroup):
    # Core states matching concept
    HOME = State()          # 📊 Статус · 🧰 Инструменты · ⚙️ Флаги  
    TOOLS = State()         # 👤 Пользователь · 📨 Очереди · 🧽 Сервис
    FLAGS = State()         # 🔎 Просмотр · 🚀 Раскатка · 🛑 Kill-switch
    MODERATION = State()    # 🚩 Жалобы · 🧱 Блокировки · 📵 Мут
    EVENTS_ADMIN = State()  # 📅 События · 👥 Заявки · ✏️ Редакт
    INCIDENTS = State()     # 🆘 Инцидент · 📈 Метрики · 🔔 Алерты
    BILLING = State()       # 💳 Кредиты · 💵 Рефанд · 📦 Подписки
```

#### 1.5 Handlers адаптация
**Текущий подход** (memory management):
```python
@router.message(Command("project"))
async def project_select(message: Message):
    # Project management logic
```

**Новый подход** (ChatOps commands):
```python
@router.message(Command("flags"))
async def flags_list(message: Message):
    # Feature flags management
    
@router.message(Command("rollout"))
async def rollout_feature(message: Message):
    # Gradual feature rollout with SLO checks
```

### ➕ Что нужно добавить новое

#### 1.6 Система ролей и ACL
```python
# app/domain/security.py
class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin" 
    MODERATOR = "moderator"
    SUPPORT = "support"
    ANALYST = "analyst"
    HOST = "host"

class ACLService:
    async def check_permission(self, user_id: int, action: str) -> bool:
        """Check if user has permission for action"""
        
    async def require_2fa(self, user_id: int) -> bool:
        """Check if 2FA required for sensitive operations"""
```

#### 1.7 Аудит система
```python
# app/domain/audit.py
@dataclass
class AuditLogEntry:
    who: int                    # user_id
    role: UserRole              # user role at time of action
    action: str                 # action performed
    target: Optional[str]       # target of action
    prev_value: Optional[str]   # previous value
    new_value: Optional[str]    # new value  
    reason: Optional[str]       # reason provided
    timestamp: datetime
```

#### 1.8 Интеграции с Lovender
```python
# app/services/lovender_api.py
class LovenderAPIService:
    async def get_feature_flags(self) -> Dict[str, Any]:
        """Get current feature flags from lovender"""
        
    async def set_feature_flag(self, flag: str, value: Any) -> bool:
        """Set feature flag in lovender with validation"""
        
    async def get_metrics_sli(self) -> Dict[str, float]:
        """Get SLI metrics for rollout validation"""
        
    async def get_user_profile(self, user_id: int) -> Dict:
        """Get user profile from lovender for moderation"""
```

---

## 2. Детальный план реализации M0→M3

### M0 — Bootstrap (1 неделя)
**Цель**: Базовая инфраструктура и авторизация

#### M0.1 Адаптация конфигурации
```python
# app/config.py - добавить секции
class LovenderOpsSettings(BaseSettings):
    """OpsBot specific settings"""
    allowed_users: str = Field(default="", description="Comma-separated user IDs")
    main_bot_api_url: str = Field(description="Lovender main bot API endpoint")
    api_secret: SecretStr = Field(description="API secret for lovender integration")
    
    class Config:
        env_prefix = "LOVENDER_OPS_"

class SecurityOpsSettings(BaseSettings):
    """Enhanced security for ops"""
    require_2fa: bool = Field(default=True, description="Require 2FA for sensitive ops")
    session_timeout: int = Field(default=1800, description="Session timeout in seconds")
    ephemeral_screen_ttl: int = Field(default=300, description="Auto-delete screens after seconds")
```

#### M0.2 Базовая авторизация и роли
```python
# app/services/auth.py
class AuthService:
    def __init__(self, allowed_users: str):
        self.allowed_user_ids = set(map(int, allowed_users.split(',')))
    
    async def authenticate(self, user_id: int) -> Optional[UserRole]:
        """Basic authentication with allow-list"""
        if user_id not in self.allowed_user_ids:
            return None
        # TODO: Get role from database/config
        return UserRole.OWNER  # Placeholder for M0
```

#### M0.3 Базовые состояния и команды
- Адаптировать `app/states.py` под OpsStates
- Создать базовые handlers для /whoami, /status  
- Реализовать HOME состояние с 3-кнопочным док

**Acceptance Criteria M0**:
- ✅ Авторизация по allow-list работает
- ✅ /whoami показывает роль и окружение  
- ✅ /status показывает базовую сводку (заглушки)
- ✅ HOME состояние с кнопками "Статус · Инструменты · Флаги"
- ✅ Все действия логируются в audit_log

### M1 — Фичефлаги & Модерация (1–1.5 недели) 
**Цель**: Core ChatOps функциональность

#### M1.1 Feature Flags система
```python
# app/services/feature_flags.py
class FeatureFlagService:
    async def get_flags(self) -> Dict[str, Any]:
        """Get current flags from lovender API"""
        
    async def set_flag(self, flag: str, value: Any, user_id: int, reason: str) -> bool:
        """Set flag with validation and audit"""
        
    async def rollout_flag(self, flag: str, percentage: int, user_id: int) -> RolloutResult:
        """Gradual rollout with SLO checks"""
        
    async def kill_switch(self, flag: str, user_id: int, reason: str) -> bool:
        """Emergency flag disable"""
```

#### M1.2 Moderation система
```python  
# app/services/moderation.py
class ModerationService:
    async def get_reports_queue(self) -> List[Report]:
        """Get pending moderation reports"""
        
    async def process_report(self, report_id: int, decision: str, user_id: int, reason: str):
        """Process moderation decision with audit"""
        
    async def ban_user(self, target_user_id: int, duration: Optional[int], reason: str, moderator_id: int):
        """Ban user with audit and TTL"""
```

#### M1.3 User Operations (read-only)
- Поиск пользователей lovender
- Просмотр профилей, рейтинга, штрафов
- История действий (read-only в M1)

**Acceptance Criteria M1**:
- ✅ `/flags` показывает текущие флаги с историей
- ✅ `/rollout FEATURE_X to 50%` работает с чек-листом Go/No-Go  
- ✅ `/kill FEATURE_X` мгновенно отключает с аудитом
- ✅ FLAGS состояние: просмотр, раскатка, kill-switch
- ✅ MODERATION состояние: очередь жалоб, решения с пруфами
- ✅ User поиск и карточки (read-only)

### M2 — Пользователи/Биллинг/Events (1–1.5 недели)
**Цель**: Административные операции

#### M2.1 User Operations (write)
```python
# app/services/user_ops.py  
class UserOperationsService:
    async def reset_debts(self, user_id: int, operator_id: int, reason: str):
        """Reset user debts with audit"""
        
    async def apply_penalty(self, user_id: int, amount: float, reason: str, operator_id: int):
        """Apply penalty with policy validation"""
        
    async def adjust_rating(self, user_id: int, new_rating: float, reason: str, operator_id: int):
        """Adjust user rating with limits"""
```

#### M2.2 Billing Operations
```python
# app/services/billing.py
class BillingService:
    async def refund_user(self, user_id: int, amount: float, reason: str, operator_id: int) -> RefundResult:
        """Process refund with policy limits"""
        
    async def grant_credits(self, user_id: int, credits: int, reason: str, operator_id: int):
        """Grant credits with audit"""
        
    async def manage_subscription(self, user_id: int, action: str, sku: str, operator_id: int):
        """Manage user subscription"""
```

#### M2.3 Events Administration  
```python
# app/services/events_admin.py
class EventsAdminService:
    async def get_event_complaints(self) -> List[EventComplaint]:
        """Get event-related complaints"""
        
    async def manage_event_participants(self, event_id: int, action: str, user_id: int):
        """Manage event participants (remove, add from waitlist)"""
        
    async def notify_participants(self, event_id: int, message: str, operator_id: int):
        """Send message to event participants with rate-limit"""
```

**Acceptance Criteria M2**:
- ✅ User operations: корректировка рейтинга/штрафов/долгов с ограничениями по ролям
- ✅ Billing: рефанды с лимитами, кредиты, управление SKU
- ✅ Events: управление заявками/квотами, сообщения участникам
- ✅ Все денежные операции идемпотентны с audit trail
- ✅ Рассылки с rate-limit и логированием

### M3 — Инциденты/Runbooks/Автопилот (1 неделя)
**Цель**: Продвинутая автоматизация и incident management

#### M3.1 Incident Management
```python
# app/services/incidents.py
class IncidentService:
    async def create_incident(self, level: str, description: str, operator_id: int) -> IncidentId:
        """Create incident with auto-metrics collection"""
        
    async def get_incident_status(self, incident_id: str) -> IncidentStatus:
        """Get incident status and timeline"""
        
    async def run_runbook(self, runbook: str, operator_id: int, params: Dict) -> RunbookResult:
        """Execute automated runbook with confirmation"""
```

#### M3.2 Auto-rollout система
```python
# app/services/auto_rollout.py
class AutoRolloutService:
    async def check_rollout_gates(self, flag: str, current_percentage: int) -> GateCheckResult:
        """Check SLI/SLO metrics for rollout gates"""
        
    async def suggest_next_step(self, flag: str) -> RolloutSuggestion:
        """AI-assisted rollout recommendations based on metrics"""
        
    async def auto_rollback(self, flag: str, reason: str) -> bool:
        """Auto-rollback on metric degradation"""
```

#### M3.3 Advanced Monitoring Integration
```python
# app/services/monitoring.py  
class MonitoringService:
    async def get_sli_metrics(self) -> Dict[str, float]:
        """Get current SLI: feed p95/p99, error rate, etc"""
        
    async def check_alerts(self) -> List[Alert]:
        """Get active alerts and recommended actions"""
        
    async def create_dashboard_link(self, incident_id: str) -> str:
        """Generate dashboard link for incident analysis"""
```

**Acceptance Criteria M3**:
- ✅ Incident creation с автоматическим сбором метрик и уведомлениями
- ✅ Runbooks выполняются с подтверждением (перезапуск воркеров, откат раскаток)
- ✅ Автопилот раскаток: бот сам проверяет гейты и предлагает next step
- ✅ Авто-роллбек при красных флагах в метриках
- ✅ Интеграция с дашбордами и алертингом

---

## 3. Интеграционная архитектура

### 3.1 API интеграция с основным Lovender ботом
```python
# app/infrastructure/lovender_client.py
class LovenderClient:
    """HTTP client for lovender main bot API"""
    
    async def get_feature_flags(self) -> Dict[str, FeatureFlag]:
        """GET /api/ops/flags"""
        
    async def set_feature_flag(self, flag: str, value: Any) -> bool:
        """POST /api/ops/flags/{flag}"""
        
    async def get_user_profile(self, user_id: int) -> UserProfile:
        """GET /api/ops/users/{user_id}"""
        
    async def get_metrics(self) -> SystemMetrics:
        """GET /api/ops/metrics"""
        
    async def process_refund(self, user_id: int, amount: float, reason: str) -> RefundResult:
        """POST /api/ops/billing/refund"""
```

### 3.2 Shared Infrastructure
**Общие компоненты**:
- **Redis namespace separation**: `lovender:main:*` vs `lovender:ops:*`
- **Database**: отдельные схемы или префиксы таблиц 
- **Logging**: общий ELK стек с разными индексами
- **Monitoring**: общие дашборды с фильтрацией по сервису

### 3.3 Event-driven интеграция (опционально для M4+)
```python
# app/infrastructure/events.py
class EventBus:
    """Event bus for real-time coordination between main and ops bots"""
    
    async def publish_flag_change(self, flag: str, old_value: Any, new_value: Any, operator_id: int):
        """Notify main bot about flag changes"""
        
    async def subscribe_to_incidents(self, callback):
        """Subscribe to incident notifications from main bot"""
```

---

## 4. Безопасность и operational concerns

### 4.1 Эфемерность экранов
```python
# app/core/ephemeral.py
class EphemeralScreenManager:
    """Auto-delete sensitive screens with PII"""
    
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self.active_screens = {}
    
    async def schedule_deletion(self, chat_id: int, message_id: int, user_id: int):
        """Schedule message deletion after TTL"""
        asyncio.create_task(self._delete_after_ttl(chat_id, message_id, user_id))
    
    async def _delete_after_ttl(self, chat_id: int, message_id: int, user_id: int):
        await asyncio.sleep(self.ttl)
        try:
            # Delete message and clear from state
            await bot.delete_message(chat_id, message_id)
        except Exception as e:
            logger.warning("Failed to delete ephemeral screen", error=str(e))
```

### 4.2 2FA Implementation 
```python
# app/core/two_factor.py
class TwoFactorAuth:
    """Simple PIN-based 2FA for sensitive operations"""
    
    async def require_2fa_pin(self, user_id: int) -> str:
        """Generate and return 6-digit PIN for user"""
        pin = f"{random.randint(100000, 999999)}"
        await cache_service.set(f"2fa_pin:{user_id}", pin, ttl=300)  # 5 min TTL
        return pin
    
    async def verify_2fa_pin(self, user_id: int, provided_pin: str) -> bool:
        """Verify provided PIN against stored PIN"""
        expected_pin = await cache_service.get(f"2fa_pin:{user_id}")
        if expected_pin and expected_pin == provided_pin:
            await cache_service.delete(f"2fa_pin:{user_id}")
            return True
        return False
```

### 4.3 Rate Limiting для админ-операций
```python  
# app/core/rate_limiting.py
class AdminRateLimiter:
    """Rate limiting for sensitive admin operations"""
    
    async def check_rate_limit(self, user_id: int, operation: str) -> bool:
        """Check if user is within rate limits for operation"""
        
        limits = {
            "flag_change": 20,      # max 20 flag changes per hour
            "user_ban": 10,         # max 10 bans per hour  
            "refund": 5,            # max 5 refunds per hour
            "mass_message": 2,      # max 2 mass messages per hour
        }
        
        limit = limits.get(operation, 100)
        key = f"rate_limit:{user_id}:{operation}"
        
        current = await cache_service.get(key) or 0
        if current >= limit:
            return False
            
        await cache_service.increment(key)
        await cache_service.expire(key, 3600)  # 1 hour window
        return True
```

---

## 5. Маппинг компонентов memory-bot → OpsBot

### 5.1 Прямое переиспользование (без изменений)

| memory-bot | OpsBot | Назначение |
|------------|--------|-----------|
| `app/config.py` | `app/config.py` | Конфигурация (добавим секции для OpsBot) |
| `app/services/cache.py` | `app/services/cache.py` | Кэширование метрик, флагов, состояний |
| `app/utils/logging_setup.py` | `app/utils/logging_setup.py` | Structured logging для аудита |
| `app/db.py` | `app/db.py` | SQLAlchemy сессии и подключения |
| `app/ui.py` | `app/ui.py` | Эфемерные панели с авто-удалением |

### 5.2 Адаптация с изменениями

| memory-bot компонент | OpsBot адаптация | Изменения |
|---------------------|------------------|-----------|
| `app/states.py` → `MemoryStates` | `app/states.py` → `OpsStates` | Новые состояния для ChatOps workflow |
| `app/handlers/menu.py` | `app/handlers/ops_menu.py` | Адаптация keyboard под операторский интерфейс |
| `app/services/memory.py` | `app/services/ops_context.py` | Контекст операций вместо проектов |
| `app/models.py` | `app/models.py` | Добавить модели: roles, audit_logs, incidents |

### 5.3 Новые компоненты (создать с нуля)

| Компонент | Файл | Назначение |
|-----------|------|-----------|
| Авторизация | `app/services/auth.py` | Allow-list, роли, 2FA |
| Аудит | `app/domain/audit.py` | Логирование всех админ-действий |
| Feature Flags | `app/services/feature_flags.py` | Управление флагами lovender |
| Moderation | `app/services/moderation.py` | Обработка жалоб и банов |
| Billing Ops | `app/services/billing.py` | Рефанды и финансовые операции |
| Incidents | `app/services/incidents.py` | Incident management и runbooks |
| Lovender API | `app/infrastructure/lovender_client.py` | HTTP клиент для основного бота |

---

## 6. Database Schema изменения

### 6.1 Новые таблицы для OpsBot

```sql
-- Роли пользователей
CREATE TABLE user_roles (
    user_id BIGINT PRIMARY KEY,
    role VARCHAR(50) NOT NULL,
    granted_by BIGINT,
    granted_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- Аудит лог
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    user_role VARCHAR(50) NOT NULL, 
    action VARCHAR(100) NOT NULL,
    target VARCHAR(200),
    prev_value TEXT,
    new_value TEXT,
    reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    INDEX idx_audit_user_time (user_id, created_at),
    INDEX idx_audit_action (action, created_at)
);

-- Инциденты
CREATE TABLE incidents (
    id VARCHAR(50) PRIMARY KEY,
    level VARCHAR(10) NOT NULL, -- P1, P2, P3
    title VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'open',
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP NULL,
    metrics_snapshot JSONB,
    INDEX idx_incidents_status_time (status, created_at)
);

-- 2FA пины (альтернативно - можно использовать Redis)
CREATE TABLE user_2fa_pins (
    user_id BIGINT PRIMARY KEY,
    pin_hash VARCHAR(100) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    attempts INT DEFAULT 0
);
```

### 6.2 Адаптация существующих таблиц

```sql
-- Расширяем user_state для OpsBot контекста
ALTER TABLE user_state ADD COLUMN current_ops_context VARCHAR(50);
ALTER TABLE user_state ADD COLUMN last_2fa_verified_at TIMESTAMP;
ALTER TABLE user_state ADD COLUMN session_expires_at TIMESTAMP;
```

---

## 7. Environment конфигурация

### 7.1 Новые переменные окружения

```bash
# .env для OpsBot
# Основная конфигурация
BOT_TOKEN=<ops_bot_token>          # Отдельный токен для OpsBot
ENVIRONMENT=production             # production|staging|development

# Авторизация  
LOVENDER_OPS_ALLOWED_USERS=123456,789012,345678
LOVENDER_OPS_MAIN_BOT_API_URL=https://api.lovender.com
LOVENDER_OPS_API_SECRET=<shared_secret>

# Безопасность
SECURITY_OPS_REQUIRE_2FA=true
SECURITY_OPS_SESSION_TIMEOUT=1800
SECURITY_OPS_EPHEMERAL_SCREEN_TTL=300

# Redis (общий, но разные namespaces)
REDIS_URL=redis://localhost:6379/1

# PostgreSQL (общий, можно отдельные схемы)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/lovender_ops

# Feature Flags
FEATURE_USE_CACHE=true
FEATURE_USE_RATE_LIMITING=true
FEATURE_USE_2FA=true
FEATURE_AUTO_ROLLOUT=false    # Отключить автопилот до M3
```

---

## 8. Риски и митигации

### 8.1 Технические риски

| Риск | Вероятность | Воздействие | Митигация |
|------|-------------|-------------|-----------|
| **Общая база данных с main bot** | Средняя | Высокое | Отдельные схемы/префиксы таблиц, изоляция транзакций |
| **Redis конфликты** | Низкая | Среднее | Namespace separation, разные DB в Redis |
| **API интеграция ошибки** | Высокая | Высокое | Circuit breakers, retry logic, fallback modes |
| **Эскалация прав** | Средняя | Критическое | Allow-list, audit logging, регулярный review ролей |

### 8.2 Операционные риски

| Риск | Вероятность | Воздействие | Митигация |
|------|-------------|-------------|-----------|
| **Случайное изменение критичного флага** | Средняя | Высокое | 2FA для sensitive операций, подтверждения, undo функции |
| **Утечка PII через чаты** | Средняя | Высокое | Эфемерные экраны, auto-delete, redaction, запрет forwards |
| **DDoS на API lovender** | Низкая | Среднее | Rate limiting, circuit breakers, monitoring |

### 8.3 План снижения рисков

1. **M0**: Базовая безопасность (allow-list, audit logging)
2. **M1**: 2FA для sensitive операций, эфемерные экраны  
3. **M2**: Rate limiting, enhanced monitoring
4. **M3**: Circuit breakers, automated rollback

---

## 9. Финальные рекомендации

### 9.1 Преимущества использования memory-bot как основы

✅ **Быстрый старт**: ~75% архитектуры готово  
✅ **Проверенные паттерны**: aiogram + SQLAlchemy + Redis стек работает  
✅ **Качественный код**: Clean Architecture, типизация, логирование  
✅ **Feature flags**: уже есть система для safe rollout  
✅ **Кэширование**: готовая Redis интеграция  

### 9.2 Ключевые решения для принятия

🔄 **Database strategy**: 
- Опция A: Общая БД, отдельные схемы (`lovender_main`, `lovender_ops`)
- Опция B: Отдельные БД с репликацией общих справочников
- **Рекомендация**: Опция A для простоты интеграции

🔄 **API интеграция**:
- Опция A: REST API между ботами
- Опция B: Прямое подключение к общим сервисам
- **Рекомендация**: Опция A для изоляции

🔄 **Deployment strategy**:
- Опция A: Отдельный контейнер, общая инфраструктура  
- Опция B: Общий кластер с service mesh
- **Рекомендация**: Опция A для M0-M2, потом Опция B

### 9.3 Следующие шаги

1. **Подтверждение плана** с командой lovender
2. **Настройка инфраструктуры**: копия memory-bot → lovender-opsbot
3. **M0 реализация**: авторизация + базовые состояния  
4. **Интеграция с staging lovender** для тестирования
5. **M1-M3 итеративная разработка**

**Готов к началу реализации M0 после подтверждения архитектурных решений.**

---

*Документ создан: 2025-09-21 | Статус: Ready for Review | Следующий этап: M0 Implementation*
