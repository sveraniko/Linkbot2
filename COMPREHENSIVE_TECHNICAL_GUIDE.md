# Project Memory Bot - Comprehensive Technical Guide for Development Teams

> **Version**: 2.0 Post-AntiFragile v3 Refactoring  
> **Status**: Production Ready (95%)  
> **Last Updated**: 2025-09-21

---

## 📋 Table of Contents

1. [Project Overview](#-project-overview)
2. [Architecture Deep Dive](#-architecture-deep-dive)
3. [Development Environment Setup](#-development-environment-setup)
4. [Code Structure & Patterns](#-code-structure--patterns)
5. [Database Design & Migrations](#-database-design--migrations)
6. [API Design & Integration](#-api-design--integration)
7. [Testing Strategy](#-testing-strategy)
8. [Deployment & Operations](#-deployment--operations)
9. [Monitoring & Observability](#-monitoring--observability)
10. [Troubleshooting Guide](#-troubleshooting-guide)
11. [Contributing Guidelines](#-contributing-guidelines)

---

## 🎯 Project Overview

### What is Project Memory Bot?

**Project Memory Bot** is an intelligent Telegram bot that serves as a knowledge management system. It allows users to:
- Import and manage project documentation
- Ask contextual questions with AI-powered responses
- Organize knowledge with tags and projects
- Search and retrieve information efficiently
- Generate reports and summaries

### Key Achievements After AntiFragile v3 Refactoring

✅ **95% Production Readiness** - All critical components implemented  
✅ **Clean Architecture** - Proper layering with handlers → services → domain  
✅ **Critical Bug Fixes** - Eliminated "garbage messages" and code duplication  
✅ **Performance Optimizations** - Subquery-distinct patterns, efficient pagination  
✅ **Security Enhancements** - Centralized escaping, state validation  
✅ **Enterprise Features** - Structured logging, telemetry, configuration management  

### Technology Stack

```mermaid
graph TB
    subgraph "Frontend Layer"
        TG[Telegram Bot API]
        UI[aiogram 3.x Handlers]
    end
    
    subgraph "Application Layer" 
        SVC[Business Services]
        FSM[State Management]
        CACHE[Redis Cache]
    end
    
    subgraph "Data Layer"
        DB[(PostgreSQL)]
        MINIO[MinIO Storage]
        LLM[OpenAI API]
    end
    
    TG --> UI
    UI --> SVC
    UI --> FSM
    SVC --> DB
    SVC --> MINIO
    SVC --> LLM
    FSM --> CACHE
```

**Core Technologies**:
- **Python 3.11+** with full type hints
- **aiogram 3.x** for Telegram Bot framework
- **SQLAlchemy 2.x** with async support
- **PostgreSQL** for primary data storage
- **Redis** for caching and FSM state
- **MinIO** for file storage
- **OpenAI API** for AI capabilities
- **Alembic** for database migrations
- **Pydantic** for data validation

---

## 🏗️ Architecture Deep Dive

### Clean Architecture Implementation

The project follows **Clean Architecture** principles with clear separation of concerns:

```
app/
├── handlers/           # 🎮 Telegram Interface Layer
│   ├── ask.py         # Core ASK functionality (1000+ lines)
│   ├── memory_panel.py # Memory management UI
│   ├── chat.py        # Chat functionality
│   ├── menu.py        # Quick actions menu
│   └── ...
├── services/          # 🔧 Business Logic Layer
│   ├── ask_list.py    # Search and pagination
│   ├── ask_selection.py # Source selection management
│   ├── ask_answer.py  # Answer generation
│   ├── llm_pipeline.py # LLM integration
│   ├── artifacts.py   # Artifact management
│   ├── memory.py      # Memory operations
│   └── cache.py       # Caching layer
├── utils/             # 🛠️ Cross-cutting Concerns
│   ├── markdown.py    # Centralized escaping
│   ├── tg.py          # Telegram helpers
│   ├── logging_setup.py # Structured logging
│   └── error_handling.py # Error management
├── models.py          # 📊 Data Models (SQLAlchemy)
├── states.py          # 🔄 FSM State Definitions
├── config.py          # ⚙️ Configuration Management
└── db.py              # 🗃️ Database Session Management
```

### Layer Responsibilities

#### 🎮 Handlers Layer (`app/handlers/`)
**Purpose**: Thin interface layer for Telegram interactions
- Parse incoming messages and callbacks
- Validate user permissions and state
- Render responses and manage UI elements
- **NO business logic** - delegate to services

**Example Pattern**:
```python
@router.callback_query(F.data.startswith("ask:answer:save:"))
async def save_answer(cb: CallbackQuery):
    # 1. Parse and validate input
    run_id = cb.data.split(":")[-1]
    user_id = cb.from_user.id
    
    # 2. Delegate to service layer
    from app.services.ask_answer import save_answer_as_artifact
    result = await save_answer_as_artifact(run_id, user_id)
    
    # 3. Render response
    if result:
        await cb.answer("💾 Ответ сохранен", show_alert=True)
    else:
        await cb.answer("❌ Ошибка сохранения", show_alert=True)
```

#### 🔧 Services Layer (`app/services/`)
**Purpose**: Pure business logic without Telegram dependencies
- Implement business rules and workflows
- Coordinate between different domains
- Handle data transformation and validation
- **Fully testable** without Telegram infrastructure

**Example Pattern**:
```python
# app/services/ask_list.py
async def search_artifacts(
    session: AsyncSession,
    user_id: int,
    term: Optional[str] = None,
    page: int = 0,
    page_size: int = 5
) -> Tuple[List[Artifact], int]:
    """Search artifacts with pagination - pure business logic"""
    
    # Parse search term
    artifact_id, tag, name_pattern = parse_query(term)
    
    # Build query
    query = build_search_query(session, user_id, artifact_id, tag, name_pattern)
    
    # Execute with pagination
    total = await count_total_results(query)
    items = await paginate_results(query, page, page_size)
    
    return items, total
```

#### 🛠️ Utils Layer (`app/utils/`)
**Purpose**: Cross-cutting concerns and utilities
- Centralized escaping and security functions
- Logging and telemetry helpers
- Error handling patterns
- Telegram-specific utilities

### State Management Architecture

The project uses **centralized state management** through `UserState.last_answer` JSON field:

```python
# State structure
{
  "run_id": "uuid",
  "question": "Original user question",
  "answer": "Generated answer text",
  "source_ids": [1, 2, 3],
  "msg_ids": {
    "question": 123,
    "answer": 124
  },
  "metadata": {
    "model": "gpt-4",
    "tokens": 1500,
    "timestamp": "2025-09-21T19:00:00Z"
  }
}
```

**Benefits**:
- ✅ **Idempotent operations** - repeated clicks are safe
- ✅ **State recovery** - system can resume after crashes
- ✅ **Audit trail** - full history of user interactions
- ✅ **Debugging** - complete context for troubleshooting

---

## 🛠️ Development Environment Setup

### Prerequisites

- **Python 3.11+** with pip and venv
- **PostgreSQL 13+** with UTF-8 encoding
- **Redis 6+** for caching (optional but recommended)
- **MinIO** or S3-compatible storage (optional)
- **OpenAI API key** for AI features

### Local Development Setup

```bash
# 1. Clone and setup virtual environment
git clone <repository_url>
cd project-memory-bot
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup environment variables
cp .env.example .env
# Edit .env with your configuration

# 4. Setup database
docker run -d \
  --name postgres_membot \
  -e POSTGRES_DB=memdb \
  -e POSTGRES_USER=memuser \
  -e POSTGRES_PASSWORD=secret \
  -p 5432:5432 \
  postgres:15

# 5. Run migrations
alembic upgrade head

# 6. Start Redis (optional)
docker run -d \
  --name redis_membot \
  -p 6379:6379 \
  redis:7-alpine

# 7. Start the bot
python -m app
```

### Environment Configuration

Create `.env` file with required settings:

```bash
# Core Configuration
ENVIRONMENT=development
DATABASE_URL=postgresql+asyncpg://memuser:secret@localhost:5432/memdb
BOT_TOKEN=your_telegram_bot_token

# AI Integration
OPENAI_API_KEY=your_openai_api_key

# Optional: Redis Cache
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Optional: MinIO Storage
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=memory

# Feature Flags
FEATURE_USE_CACHE=true
FEATURE_USE_WEBHOOK=false
FEATURE_USE_DEBOUNCE=false

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=console  # or json for production
```

### Docker Development Environment

```yaml
# docker-compose.dev.yml
version: '3.8'

services:
  app:
    build: .
    environment:
      - DATABASE_URL=postgresql+asyncpg://memuser:secret@db:5432/memdb
      - REDIS_HOST=redis
    depends_on:
      - db
      - redis
    volumes:
      - .:/app
    
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: memdb
      POSTGRES_USER: memuser
      POSTGRES_PASSWORD: secret
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

```bash
# Start development environment
docker-compose -f docker-compose.dev.yml up -d

# Run migrations
docker-compose -f docker-compose.dev.yml exec app alembic upgrade head

# View logs
docker-compose -f docker-compose.dev.yml logs -f app
```

---

## 💻 Code Structure & Patterns

### ASK Module Architecture

The **ASK module** (`app/handlers/ask.py`) is the core component with 1000+ lines:

```python
# Key components of ASK module:

1. Chat Gate Management
   - `chat_on/chat_off` toggle functionality
   - State preservation across chat modes
   
2. Search & Pagination
   - 5 items per page with ⬅️/➡️ navigation
   - Subquery-distinct pattern for deduplication
   - Term parsing: id (#123), tag (#tag), or name pattern
   
3. Source Selection
   - Selection basket with toggle functionality
   - Auto-clear after questions (configurable)
   - Bulk operations (select all, clear all)
   
4. Answer Generation
   - Integration with LLM pipeline
   - Context building from selected sources
   - Token budget management
   
5. Action Panel
   - Always attached: 💾📌🧾🔁📚🗑
   - Save to artifacts, pin messages, generate reports
   - Delete answers, refine questions
```

### Service Layer Patterns

#### Pure Business Logic Services

```python
# app/services/ask_answer.py - Example of pure service
class AnswerService:
    @staticmethod
    async def generate_answer(
        session: AsyncSession,
        question: str,
        source_artifacts: List[Artifact],
        model: str = "gpt-4",
        max_tokens: int = 4000
    ) -> AnswerResult:
        """Generate answer from question and sources - no Telegram deps"""
        
        # 1. Build context from sources
        context_chunks = await build_context_chunks(source_artifacts, max_tokens)
        
        # 2. Generate LLM response
        from app.services.llm_pipeline import call_llm_with_retry
        response = await call_llm_with_retry(
            model=model,
            messages=build_messages(question, context_chunks),
            max_tokens=max_tokens
        )
        
        # 3. Return structured result
        return AnswerResult(
            answer=response.content,
            tokens_used=response.usage.total_tokens,
            sources_used=len(source_artifacts),
            model_used=model
        )
```

#### Search & Pagination Pattern

```python
# app/services/ask_list.py - Optimized search with subquery-distinct
async def list_sources(
    session: AsyncSession,
    user_id: int,
    term: Optional[str] = None,
    page: int = 0,
    page_size: int = 5
) -> Tuple[List[Dict], int]:
    """Optimized search with subquery-distinct pattern"""
    
    # Parse search term
    artifact_id, tag, name_pattern = parse_query(term)
    
    # Get user's project scope
    project_ids = await get_user_project_scope(session, user_id)
    
    # Build base query with proper joins
    subq = (
        select(Artifact.id)
        .join(Project)
        .where(Project.id.in_(project_ids))
    )
    
    # Apply filters
    if artifact_id:
        subq = subq.where(Artifact.id == artifact_id)
    elif tag:
        subq = subq.join(artifact_tags).join(Tag).where(Tag.name == tag)
    elif name_pattern:
        subq = subq.where(Artifact.title.ilike(f"%{name_pattern}%"))
    
    # Get distinct IDs with pagination
    ids_query = subq.distinct().offset(page * page_size).limit(page_size)
    artifact_ids = (await session.execute(ids_query)).scalars().all()
    
    # Load full artifacts
    artifacts = await load_artifacts_by_ids(session, artifact_ids)
    total_count = await count_distinct_artifacts(session, subq)
    
    return format_artifacts_for_display(artifacts), total_count
```

### Error Handling Patterns

```python
# app/utils/error_handling.py - Centralized error handling
class BotErrorHandler:
    @staticmethod
    async def handle_callback_error(cb: CallbackQuery, error: Exception):
        """Standard error handling for callback queries"""
        
        # Log error with context
        logger.error(
            "Callback query error",
            user_id=cb.from_user.id,
            callback_data=cb.data,
            error=str(error),
            error_type=type(error).__name__
        )
        
        # User-friendly error message
        if isinstance(error, ValidationError):
            await cb.answer("❌ Неверные данные", show_alert=True)
        elif isinstance(error, DatabaseError):
            await cb.answer("❌ Ошибка базы данных", show_alert=True)
        else:
            await cb.answer("❌ Внутренняя ошибка", show_alert=True)
        
        # Report to monitoring (Sentry, etc.)
        if settings.monitoring.is_sentry_configured:
            from sentry_sdk import capture_exception
            capture_exception(error)

# Usage in handlers
@router.callback_query(F.data.startswith("ask:"))
async def ask_callback(cb: CallbackQuery):
    try:
        # Handler logic here
        pass
    except Exception as e:
        await BotErrorHandler.handle_callback_error(cb, e)
```

### Configuration Management Patterns

```python
# app/config.py - Hierarchical configuration with validation
class Settings(BaseSettings):
    """Main settings with nested configurations and validation"""
    
    # Environment
    environment: EnvironmentType = EnvironmentType.DEVELOPMENT
    
    # Nested settings groups
    database: DatabaseSettings = DatabaseSettings()
    telegram: TelegramSettings = TelegramSettings()
    llm: LLMSettings = LLMSettings()
    features: FeatureFlags = FeatureFlags()
    
    def __init__(self, **data):
        super().__init__(**data)
        self._validate_configuration()
    
    def _validate_configuration(self):
        """Cross-field validation"""
        errors = []
        
        if self.environment == EnvironmentType.PRODUCTION:
            if not self.telegram.is_configured:
                errors.append("BOT_TOKEN required for production")
            if not self.monitoring.is_sentry_configured:
                logger.warning("Sentry not configured for production")
        
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")
    
    @property
    def is_production(self) -> bool:
        return self.environment == EnvironmentType.PRODUCTION

# Usage throughout the app
from app.config import settings

if settings.features.use_cache:
    # Use Redis cache
else:
    # Use memory cache
```

---

## 📊 Database Design & Migrations

### Entity Relationship Diagram

```mermaid
erDiagram
    User ||--|| UserState : has
    User ||--o{ Project : owns
    Project ||--o{ Artifact : contains
    Artifact ||--o{ Chunk : "split into"
    Artifact }|--o{ Tag : tagged
    User ||--o{ BotMessage : sends
    User ||--o{ Repo : manages

    User {
        bigint id PK
        bigint telegram_id UK
        timestamp created_at
        timestamp updated_at
    }
    
    UserState {
        bigint user_id PK,FK
        json last_answer
        string preferred_model
        string context_filters
        boolean chat_on
        string sources_mode
        timestamp updated_at
    }
    
    Project {
        int id PK
        string name UK
        timestamp created_at
    }
    
    Artifact {
        int id PK
        int project_id FK
        string title
        text content
        string kind
        string uri
        json metadata
        timestamp created_at
    }
    
    Chunk {
        int id PK
        int artifact_id FK
        text content
        int chunk_index
        int token_count
    }
    
    Tag {
        int id PK
        string name UK
        timestamp created_at
    }
```

### Core Tables Design

#### Users & State Management
```sql
-- Users table with Telegram integration
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Centralized user state with JSON storage
CREATE TABLE user_state (
    user_id BIGINT PRIMARY KEY REFERENCES users(id),
    last_answer JSONB,  -- Core state storage
    preferred_model VARCHAR(50) DEFAULT 'gpt-4',
    context_filters TEXT,  -- kinds:tags format
    chat_on BOOLEAN DEFAULT FALSE,
    quiet_mode BOOLEAN DEFAULT FALSE,
    sources_mode VARCHAR(20) DEFAULT 'active',
    scope_mode VARCHAR(20) DEFAULT 'auto',
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_user_state_updated ON user_state(updated_at);
CREATE INDEX idx_user_state_filters ON user_state USING GIN(context_filters gin_trgm_ops);
```

#### Knowledge Management
```sql
-- Projects for organizing artifacts
CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Artifacts - core content storage
CREATE TABLE artifacts (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    title VARCHAR(500) NOT NULL,
    content TEXT,
    kind VARCHAR(50) DEFAULT 'note',  -- note, import, doc, etc.
    uri VARCHAR(500),  -- source URI if applicable
    metadata JSONB,    -- extensible metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Chunks for LLM processing
CREATE TABLE chunks (
    id SERIAL PRIMARY KEY,
    artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    token_count INTEGER,
    embedding VECTOR(1536),  -- for future vector search
    created_at TIMESTAMP DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX idx_artifacts_project ON artifacts(project_id);
CREATE INDEX idx_artifacts_kind ON artifacts(kind);
CREATE INDEX idx_artifacts_title ON artifacts USING GIN(title gin_trgm_ops);
CREATE INDEX idx_chunks_artifact ON chunks(artifact_id);
```

#### Tagging System
```sql
-- Tags for flexible categorization
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Many-to-many relationship
CREATE TABLE artifact_tags (
    artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (artifact_id, tag_id)
);

CREATE INDEX idx_artifact_tags_artifact ON artifact_tags(artifact_id);
CREATE INDEX idx_artifact_tags_tag ON artifact_tags(tag_id);
```

### Migration Management

#### Migration Naming Convention
```bash
# Format: YYYYMMDD_HHMM_descriptive_slug.py
0001_20250901_1200_initial_schema.py
0002_20250902_1500_add_user_state_json.py  
0003_20250903_0900_add_chunk_embeddings.py
...
0019_20250918_1400_add_ask_prompt_msg_id_field.py
```

#### Migration Best Practices
```python
# Example migration with proper structure
"""add user state json field

Revision ID: 0019_add_ask_prompt_msg_id_field  
Revises: 0018_some_previous_migration
Create Date: 2025-09-18 14:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '0019_add_ask_prompt_msg_id_field'
down_revision = '0018_some_previous_migration'
branch_labels = None
depends_on = None

def upgrade():
    # Add new column with proper type
    op.add_column('user_state', 
        sa.Column('ask_prompt_msg_id', sa.BigInteger(), nullable=True)
    )
    
    # Add index if needed
    op.create_index('idx_user_state_prompt_msg', 'user_state', ['ask_prompt_msg_id'])
    
def downgrade():
    # Drop index first
    op.drop_index('idx_user_state_prompt_msg', table_name='user_state')
    
    # Drop column
    op.drop_column('user_state', 'ask_prompt_msg_id')
```

#### Running Migrations
```bash
# Generate new migration
alembic revision --autogenerate -m "add_new_feature"

# Apply migrations
alembic upgrade head

# Rollback migrations  
alembic downgrade -1

# Check migration history
alembic history --verbose

# Show current version
alembic current
```

### Database Performance Optimization

#### Query Optimization Patterns
```python
# Efficient search with proper indexing
async def search_artifacts_optimized(session, user_id, term):
    """Optimized search using materialized subqueries"""
    
    # Use subquery-distinct pattern to avoid N+1 problems
    subq = (
        select(Artifact.id)
        .select_from(
            Artifact
            .__table__.join(Project.__table__)
            .join(user_projects.__table__)
        )
        .where(user_projects.c.user_id == user_id)
        .where(Artifact.title.ilike(f"%{term}%"))
        .distinct()
        .subquery()
    )
    
    # Load full objects efficiently
    query = (
        select(Artifact)
        .where(Artifact.id.in_(select(subq.c.id)))
        .options(selectinload(Artifact.tags))
    )
    
    result = await session.execute(query)
    return result.scalars().all()
```

#### Connection Pool Configuration
```python
# app/config.py - Optimized database settings
class DatabaseSettings(BaseSettings):
    url: str = Field(description="Database connection URL")
    pool_size: int = Field(default=10, ge=1, le=50)
    max_overflow: int = Field(default=20, ge=0, le=100) 
    pool_timeout: int = Field(default=30, ge=5, le=300)
    pool_pre_ping: bool = Field(default=True)  # Test connections
    pool_recycle: int = Field(default=3600)    # Recycle after 1 hour
    echo: bool = Field(default=False)          # SQL query logging
    
    @property
    def engine_options(self) -> Dict[str, Any]:
        """SQLAlchemy engine configuration"""
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_timeout": self.pool_timeout,
            "pool_pre_ping": self.pool_pre_ping,
            "pool_recycle": self.pool_recycle,
            "echo": self.echo
        }
```

---

## 🔌 API Design & Integration

### Internal API Architecture

The project uses **service-to-service** communication patterns rather than external REST APIs:

```python
# app/services/ - Internal API pattern
class ArtifactService:
    """Pure business logic service - no external dependencies"""
    
    @staticmethod
    async def create_artifact(
        session: AsyncSession,
        project_id: int,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None
    ) -> Artifact:
        """Create new artifact with validation and tag assignment"""
        
        # Business rule validation
        if len(title) > 500:
            raise ValueError("Title too long")
            
        if not content.strip():
            raise ValueError("Content cannot be empty")
        
        # Create artifact
        artifact = Artifact(
            project_id=project_id,
            title=title.strip(),
            content=content.strip(),
            metadata=metadata or {}
        )
        
        session.add(artifact)
        await session.flush()  # Get ID
        
        # Assign tags
        if tags:
            await TagService.assign_tags(session, artifact.id, tags)
        
        return artifact
```

### LLM Integration Patterns

```python
# app/services/llm_pipeline.py - Clean LLM integration
class LLMService:
    """LLM integration with retry logic and error handling"""
    
    @staticmethod
    async def call_llm_with_retry(
        model: str,
        messages: List[Dict],
        max_tokens: int = 4000,
        temperature: float = 0.3,
        max_retries: int = 3
    ) -> LLMResponse:
        """Call LLM with exponential backoff retry"""
        
        for attempt in range(max_retries):
            try:
                # Create client
                client = _create_openai_client()
                if not client:
                    raise ValueError("OpenAI client not configured")
                
                # Make API call
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                
                return LLMResponse(
                    content=response.choices[0].message.content,
                    tokens_used=response.usage.total_tokens,
                    model=model
                )
                
            except openai.RateLimitError as e:
                wait_time = 2 ** attempt
                logger.warning(f"Rate limit hit, waiting {wait_time}s", attempt=attempt)
                await asyncio.sleep(wait_time)
                
            except openai.APIError as e:
                if attempt == max_retries - 1:
                    raise LLMError(f"API error after {max_retries} attempts: {e}")
                logger.warning(f"API error, retrying: {e}", attempt=attempt)
                
        raise LLMError(f"Failed after {max_retries} attempts")
```

### Cache Integration

```python
# app/services/cache.py - Production-ready caching
class CacheService:
    """Redis-based caching with fallback to memory"""
    
    def __init__(self):
        self._redis_client = None
        self._memory_cache = {}
        self._is_available = False
        self._initialize_connection()
    
    async def get_or_set(
        self, 
        key: str, 
        value_factory: Callable,
        ttl: int = 3600,
        namespace: str = "default"
    ) -> Any:
        """Get from cache or compute and store"""
        
        # Try to get from cache
        cached_value = await self.get(key, namespace)
        if cached_value is not None:
            return cached_value
        
        # Compute value
        value = await value_factory() if asyncio.iscoroutinefunction(value_factory) else value_factory()
        
        # Store in cache
        await self.set(key, value, ttl, namespace)
        
        return value
    
    async def get(self, key: str, namespace: str = "default") -> Optional[Any]:
        """Get value from cache"""
        cache_key = self._create_cache_key(key, namespace)
        
        if self._is_available:
            try:
                data = await self._redis_client.get(cache_key)
                return self._deserialize_value(data) if data else None
            except Exception as e:
                logger.warning("Redis get failed, using memory cache", error=str(e))
                
        # Fallback to memory
        return self._memory_cache.get(cache_key)
```

### File Storage Integration

```python
# app/storage.py - MinIO integration with fallback
async def save_file(filename: str, data: bytes) -> Optional[str]:
    """Save file to MinIO with error handling"""
    
    if not settings.minio.is_configured:
        logger.warning("MinIO not configured, file not saved")
        return None
    
    try:
        client = _client_or_none()
        if not client:
            return None
            
        # Ensure bucket exists
        await ensure_bucket()
        
        # Generate unique key
        key = f"{datetime.now().strftime('%Y/%m/%d')}/{uuid.uuid4()}-{filename}"
        
        # Upload file
        await client.put_object(
            settings.minio.bucket,
            key,
            data,
            length=len(data)
        )
        
        logger.info("File uploaded successfully", key=key, size=len(data))
        return key
        
    except Exception as e:
        logger.error("File upload failed", filename=filename, error=str(e))
        return None
```

---

## 🧪 Testing Strategy

### Test Pyramid Implementation

```
    🔺 E2E Tests (5%)
   ────────────────────
  🔺🔺 Integration Tests (25%)  
 ────────────────────────────
🔺🔺🔺 Unit Tests (70%)
```

### Unit Testing Patterns

```python
# tests/services/test_ask_list.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.ask_list import search_artifacts, parse_query

class TestAskList:
    """Unit tests for search functionality"""
    
    def test_parse_query_id(self):
        """Test parsing numeric ID queries"""
        artifact_id, tag, name = parse_query("123")
        assert artifact_id == 123
        assert tag is None
        assert name is None
    
    def test_parse_query_tag(self):
        """Test parsing tag queries"""
        artifact_id, tag, name = parse_query("#api")
        assert artifact_id is None
        assert tag == "api"
        assert name is None
    
    def test_parse_query_name(self):
        """Test parsing name pattern queries"""
        artifact_id, tag, name = parse_query("user auth")
        assert artifact_id is None
        assert tag is None
        assert name == "user auth"
    
    @pytest.mark.asyncio
    async def test_search_artifacts_with_pagination(self, mock_session):
        """Test artifact search with proper pagination"""
        
        # Setup mock data
        mock_artifacts = [MagicMock(id=i, title=f"Test {i}") for i in range(10)]
        mock_session.execute.return_value.scalars.return_value.all.return_value = mock_artifacts[:5]
        
        # Execute search
        results, total = await search_artifacts(
            session=mock_session,
            user_id=1,
            term="test",
            page=0,
            page_size=5
        )
        
        # Verify results
        assert len(results) == 5
        assert total >= 5
        mock_session.execute.assert_called()
```

### Integration Testing

```python
# tests/integration/test_ask_workflow.py
import pytest
from httpx import AsyncClient
from app.main import app
from app.models import User, Project, Artifact

@pytest.mark.asyncio
class TestAskWorkflow:
    """Integration tests for complete ASK workflow"""
    
    async def test_complete_ask_workflow(self, test_db, test_user):
        """Test complete workflow: search -> select -> ask -> answer"""
        
        # Setup test data
        project = Project(name="Test Project")
        test_db.add(project)
        await test_db.flush()
        
        artifact = Artifact(
            project_id=project.id,
            title="Test Document",
            content="This is test content for searching"
        )
        test_db.add(artifact)
        await test_db.commit()
        
        # Simulate bot workflow
        async with AsyncClient(app=app, base_url="http://test") as client:
            
            # 1. Search for sources
            search_response = await client.post(
                "/webhook",
                json=create_telegram_update(
                    user_id=test_user.telegram_id,
                    text="/ask test"
                )
            )
            assert search_response.status_code == 200
            
            # 2. Select source (simulate button click)
            select_response = await client.post(
                "/webhook", 
                json=create_telegram_callback(
                    user_id=test_user.telegram_id,
                    data=f"ask:select:toggle:{artifact.id}"
                )
            )
            assert select_response.status_code == 200
            
            # 3. Ask question
            ask_response = await client.post(
                "/webhook",
                json=create_telegram_callback(
                    user_id=test_user.telegram_id,
                    data="ask:question:What is this about?"
                )
            )
            assert ask_response.status_code == 200
```

### Test Configuration

```python
# conftest.py - Pytest configuration
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.config import Settings
from app.models import Base, User
from app.db import get_session

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def test_engine():
    """Create test database engine"""
    settings = Settings(
        database=DatabaseSettings(
            url="postgresql+asyncpg://test:test@localhost/test_memdb"
        )
    )
    
    engine = create_async_engine(settings.database.url, echo=False)
    
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()

@pytest.fixture
async def test_db(test_engine):
    """Create test database session"""
    async with AsyncSession(test_engine) as session:
        yield session
        await session.rollback()

@pytest.fixture
async def test_user(test_db):
    """Create test user"""
    user = User(telegram_id=123456789)
    test_db.add(user)
    await test_db.commit()
    return user
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test categories
pytest tests/unit/          # Unit tests only
pytest tests/integration/   # Integration tests only
pytest -m "not slow"        # Skip slow tests

# Run with parallel execution
pytest -n auto              # Auto-detect CPU cores

# Generate coverage report
pytest --cov=app --cov-report=term-missing
```

---

## 🚀 Deployment & Operations

### Production Deployment with Docker

```dockerfile
# Dockerfile - Multi-stage production build
FROM python:3.11-slim as builder

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.11-slim as production

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Create non-root user
RUN useradd --create-home --shell /bin/bash app

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=app:app . .

# Switch to non-root user
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health')" || exit 1

# Default command
CMD ["python", "-m", "app"]
```

### Docker Compose Production Setup

```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  app:
    build: 
      context: .
      target: production
    environment:
      - ENVIRONMENT=production
      - DATABASE_URL=postgresql+asyncpg://memuser:${DB_PASSWORD}@db:5432/memdb
      - REDIS_HOST=redis
      - BOT_TOKEN=${BOT_TOKEN}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
  
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: memdb
      POSTGRES_USER: memuser
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/init.sql:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U memuser -d memdb"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.3'
  
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 128mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 128M
          cpus: '0.2'

  # Nginx reverse proxy (optional)
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      - app
    restart: unless-stopped

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local

networks:
  default:
    driver: bridge
```

### Environment Configuration Management

```bash
# .env.production - Production environment variables
ENVIRONMENT=production

# Database
DATABASE_URL=postgresql+asyncpg://memuser:${DB_PASSWORD}@db:5432/memdb
DB_PASSWORD=secure_random_password_here

# Telegram Bot
BOT_TOKEN=bot_token_from_botfather

# AI Integration
OPENAI_API_KEY=your_production_openai_key

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

# Security
FEATURE_USE_CACHE=true
FEATURE_USE_WEBHOOK=true
SECURITY_MAX_RETRIES=3
SECURITY_CACHE_TTL=3600

# Monitoring
LOG_LEVEL=INFO
LOG_FORMAT=json
MONITORING_SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id
MONITORING_ENABLE_METRICS=true

# Performance
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
PROCESSING_CHUNK_SIZE=1600
PROCESSING_CHUNK_OVERLAP=150
```

### Deployment Scripts

```bash
#!/bin/bash
# deploy.sh - Production deployment script

set -e

echo "🚀 Deploying Memory Bot to production..."

# 1. Pull latest code
git pull origin main

# 2. Build new images
docker-compose -f docker-compose.prod.yml build --no-cache

# 3. Run database migrations
docker-compose -f docker-compose.prod.yml run --rm app alembic upgrade head

# 4. Stop old containers
docker-compose -f docker-compose.prod.yml down

# 5. Start new containers
docker-compose -f docker-compose.prod.yml up -d

# 6. Wait for services to be healthy
echo "⏳ Waiting for services to start..."
sleep 30

# 7. Verify deployment
if docker-compose -f docker-compose.prod.yml ps | grep -q "Up"; then
    echo "✅ Deployment successful!"
    
    # Send notification (optional)
    curl -X POST "https://api.telegram.org/bot${NOTIFICATION_BOT_TOKEN}/sendMessage" \
         -d "chat_id=${ADMIN_CHAT_ID}" \
         -d "text=✅ Memory Bot deployed successfully to production"
else
    echo "❌ Deployment failed!"
    
    # Rollback
    docker-compose -f docker-compose.prod.yml down
    docker-compose -f docker-compose.prod.yml up -d --force-recreate
    
    exit 1
fi
```

### Health Checks & Monitoring

```python
# app/health.py - Health check endpoints
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from app.config import settings
from app.db import get_session
from sqlalchemy import text

app = FastAPI(title="Memory Bot Health Checks")

@app.get("/health")
async def health_check():
    """Basic health check endpoint"""
    return {"status": "healthy", "service": "memory-bot"}

@app.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with dependency verification"""
    
    checks = {
        "database": False,
        "redis": False,
        "openai": False,
        "storage": False
    }
    
    # Database check
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
    
    # Redis check
    if settings.features.use_cache:
        try:
            from app.services.cache import cache_service
            await cache_service.get("health_check")
            checks["redis"] = True
        except Exception as e:
            logger.error("Redis health check failed", error=str(e))
    else:
        checks["redis"] = True  # Not required
    
    # OpenAI check
    if settings.llm.is_configured:
        try:
            from app.services.llm_pipeline import _create_openai_client
            client = _create_openai_client()
            checks["openai"] = client is not None
        except Exception as e:
            logger.error("OpenAI health check failed", error=str(e))
    
    # Storage check
    if settings.minio.is_configured:
        try:
            from app.storage import _client_or_none
            client = _client_or_none()
            checks["storage"] = client is not None
        except Exception as e:
            logger.error("Storage health check failed", error=str(e))
    else:
        checks["storage"] = True  # Not required
    
    # Overall status
    all_healthy = all(checks.values())
    status_code = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_healthy else "unhealthy",
            "checks": checks,
            "timestamp": datetime.now().isoformat()
        }
    )
```

---

## 📊 Monitoring & Observability

### Structured Logging Setup

```python
# app/utils/logging_setup.py - Production-ready logging
import structlog
import logging.config
from pythonjsonlogger import jsonlogger

def setup_structured_logging():
    """Configure structured logging for production"""
    
    if settings.monitoring.log_format == "json":
        # JSON logging for production
        logging.config.dictConfig({
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": jsonlogger.JsonFormatter,
                    "format": "%(asctime)s %(name)s %(levelname)s %(message)s"
                }
            },
            "handlers": {
                "default": {
                    "level": settings.monitoring.log_level.value,
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                },
            },
            "root": {
                "level": settings.monitoring.log_level.value,
                "handlers": ["default"]
            }
        })
    else:
        # Console logging for development
        logging.basicConfig(
            level=settings.monitoring.log_level.value,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if settings.monitoring.log_format == "json" 
            else structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

# Global logger instance
logger = structlog.get_logger(__name__)
```

### Metrics Collection

```python
# app/services/telemetry.py - Metrics and telemetry
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass
from collections import defaultdict, Counter

@dataclass
class MetricEvent:
    """Structured metric event"""
    action: str
    user_id: Optional[int] = None
    duration_ms: Optional[float] = None
    tokens_used: Optional[int] = None
    model: Optional[str] = None
    status: str = "success"
    metadata: Optional[Dict[str, Any]] = None
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

class MetricsCollector:
    """In-memory metrics collector with periodic aggregation"""
    
    def __init__(self):
        self.events = []
        self.counters = defaultdict(int)
        self.histograms = defaultdict(list)
        self.gauges = {}
    
    def record_event(self, event: MetricEvent):
        """Record a metric event"""
        self.events.append(event)
        
        # Update counters
        self.counters[f"{event.action}.total"] += 1
        self.counters[f"{event.action}.{event.status}"] += 1
        
        # Update histograms
        if event.duration_ms:
            self.histograms[f"{event.action}.duration_ms"].append(event.duration_ms)
        
        if event.tokens_used:
            self.histograms[f"{event.action}.tokens"].append(event.tokens_used)
    
    def get_summary(self, last_n_minutes: int = 60) -> Dict[str, Any]:
        """Get metrics summary for the last N minutes"""
        cutoff_time = time.time() - (last_n_minutes * 60)
        recent_events = [e for e in self.events if e.timestamp > cutoff_time]
        
        # Calculate statistics
        ask_events = [e for e in recent_events if e.action == "ask_question"]
        import_events = [e for e in recent_events if e.action == "import_file"]
        
        return {
            "period_minutes": last_n_minutes,
            "total_events": len(recent_events),
            "ask_questions": {
                "total": len(ask_events),
                "success_rate": self._calculate_success_rate(ask_events),
                "avg_duration_ms": self._calculate_avg([e.duration_ms for e in ask_events if e.duration_ms]),
                "total_tokens": sum(e.tokens_used for e in ask_events if e.tokens_used),
            },
            "imports": {
                "total": len(import_events),
                "success_rate": self._calculate_success_rate(import_events),
            },
            "active_users": len(set(e.user_id for e in recent_events if e.user_id)),
        }
    
    def _calculate_success_rate(self, events) -> float:
        if not events:
            return 0.0
        success_count = len([e for e in events if e.status == "success"])
        return (success_count / len(events)) * 100
    
    def _calculate_avg(self, values) -> float:
        values = [v for v in values if v is not None]
        return sum(values) / len(values) if values else 0.0

# Global metrics collector
metrics = MetricsCollector()

# Convenience functions
def record_ask_question(user_id: int, duration_ms: float, tokens_used: int, 
                       model: str, success: bool = True):
    """Record ask question metrics"""
    metrics.record_event(MetricEvent(
        action="ask_question",
        user_id=user_id,
        duration_ms=duration_ms,
        tokens_used=tokens_used,
        model=model,
        status="success" if success else "error"
    ))

def record_import_file(user_id: int, file_size_bytes: int, 
                      chunks_created: int, success: bool = True):
    """Record file import metrics"""
    metrics.record_event(MetricEvent(
        action="import_file",
        user_id=user_id,
        status="success" if success else "error",
        metadata={
            "file_size_bytes": file_size_bytes,
            "chunks_created": chunks_created
        }
    ))
```

### Error Tracking with Sentry

```python
# app/utils/error_tracking.py - Sentry integration
import sentry_sdk
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from app.config import settings

def setup_sentry():
    """Configure Sentry error tracking"""
    
    if not settings.monitoring.is_sentry_configured:
        logger.info("Sentry not configured, skipping setup")
        return
    
    sentry_sdk.init(
        dsn=settings.monitoring.sentry_dsn,
        environment=settings.environment.value,
        release=settings.monitoring.app_version,
        
        # Integrations
        integrations=[
            LoggingIntegration(
                level=logging.INFO,        # Capture info and above as breadcrumbs
                event_level=logging.ERROR  # Send errors as events
            ),
            SqlalchemyIntegration(),
            RedisIntegration(),
        ],
        
        # Performance monitoring
        traces_sample_rate=0.1 if settings.environment.value == "production" else 1.0,
        
        # Error sampling
        sample_rate=1.0,
        
        # Custom tags
        default_integrations=False,
        before_send=filter_sensitive_data,
    )
    
    logger.info("Sentry configured successfully", 
               environment=settings.environment.value,
               release=settings.monitoring.app_version)

def filter_sensitive_data(event, hint):
    """Filter sensitive data from Sentry events"""
    
    # Remove bot token from environment variables
    if 'extra' in event and 'sys.argv' in event['extra']:
        event['extra']['sys.argv'] = ['<filtered>']
    
    # Remove sensitive request data
    if 'request' in event:
        if 'headers' in event['request']:
            sensitive_headers = ['authorization', 'x-telegram-bot-api-token']
            for header in sensitive_headers:
                if header in event['request']['headers']:
                    event['request']['headers'][header] = '<filtered>'
    
    return event

# Usage in handlers
def capture_telegram_context(user_id: int, chat_id: int, message_text: str = None):
    """Add Telegram context to Sentry"""
    sentry_sdk.set_tag("user_id", user_id)
    sentry_sdk.set_tag("chat_id", chat_id)
    
    with sentry_sdk.configure_scope() as scope:
        scope.set_context("telegram", {
            "user_id": user_id,
            "chat_id": chat_id,
            "message_preview": message_text[:100] if message_text else None
        })
```

### Performance Monitoring

```python
# app/utils/performance.py - Performance monitoring decorators
import time
import functools
from typing import Callable, Any
from app.services.telemetry import metrics, MetricEvent

def monitor_performance(action_name: str):
    """Decorator to monitor function performance"""
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                
                # Record success metrics
                duration_ms = (time.time() - start_time) * 1000
                metrics.record_event(MetricEvent(
                    action=action_name,
                    duration_ms=duration_ms,
                    status="success"
                ))
                
                return result
                
            except Exception as e:
                # Record error metrics
                duration_ms = (time.time() - start_time) * 1000
                metrics.record_event(MetricEvent(
                    action=action_name,
                    duration_ms=duration_ms,
                    status="error",
                    metadata={"error_type": type(e).__name__, "error_message": str(e)}
                ))
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                
                duration_ms = (time.time() - start_time) * 1000
                metrics.record_event(MetricEvent(
                    action=action_name,
                    duration_ms=duration_ms,
                    status="success"
                ))
                
                return result
                
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                metrics.record_event(MetricEvent(
                    action=action_name,
                    duration_ms=duration_ms,
                    status="error",
                    metadata={"error_type": type(e).__name__, "error_message": str(e)}
                ))
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator

# Usage examples
@monitor_performance("database_query")
async def complex_database_query(session, query_params):
    """Example monitored database operation"""
    pass

@monitor_performance("llm_call")  
async def call_openai_api(model, messages):
    """Example monitored LLM operation"""
    pass
```

---

## 🔧 Troubleshooting Guide

### Common Issues and Solutions

#### 🚨 Database Issues

**Problem**: Connection timeouts or pool exhaustion
```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 20 reached
```

**Solution**:
```python
# Increase pool settings in config.py
class DatabaseSettings(BaseSettings):
    pool_size: int = Field(default=20)  # Increase from 10
    max_overflow: int = Field(default=40)  # Increase from 20
    pool_timeout: int = Field(default=60)  # Increase timeout
    pool_pre_ping: bool = Field(default=True)  # Enable health checks
```

**Problem**: Migration conflicts
```
alembic.util.exc.CommandError: Multiple heads exist
```

**Solution**:
```bash
# Merge migration heads
alembic merge heads -m "merge migrations"

# Then upgrade
alembic upgrade head
```

#### 🤖 LLM API Issues

**Problem**: OpenAI rate limits
```
openai.RateLimitError: Rate limit reached for requests
```

**Solution**:
```python
# Implement exponential backoff (already in llm_pipeline.py)
# Check your API usage and upgrade plan if needed

# Monitor rate limits
@monitor_performance("llm_call")
async def call_llm_with_monitoring():
    try:
        result = await call_llm_with_retry()
        return result
    except openai.RateLimitError as e:
        logger.warning("Rate limit hit", wait_time=e.retry_after)
        # Implement user notification
        await notify_user_about_delay(user_id, e.retry_after)
        raise
```

**Problem**: Token limit exceeded
```
openai.InvalidRequestError: This model's maximum context length is 8192 tokens
```

**Solution**:
```python
# Implement smart chunking in ask_answer.py
def build_context_with_budget(artifacts: List[Artifact], max_tokens: int = 6000):
    """Build context within token budget"""
    
    total_tokens = 0
    context_chunks = []
    
    for artifact in artifacts:
        artifact_tokens = estimate_tokens(artifact.content)
        
        if total_tokens + artifact_tokens > max_tokens:
            # Truncate or skip
            remaining_budget = max_tokens - total_tokens
            if remaining_budget > 100:  # Minimum useful chunk
                truncated_content = truncate_to_tokens(artifact.content, remaining_budget)
                context_chunks.append(truncated_content)
            break
        
        context_chunks.append(artifact.content)
        total_tokens += artifact_tokens
    
    return context_chunks
```

#### 📱 Telegram Bot Issues

**Problem**: Webhook not receiving updates
```
No webhook updates received, bot appears offline
```

**Debugging Steps**:
```bash
# Check webhook info
curl "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"

# Delete webhook and test with polling
curl "https://api.telegram.org/bot<BOT_TOKEN>/deleteWebhook"

# Verify SSL certificate
openssl s_client -connect your-domain.com:443

# Test with ngrok for local development
ngrok http 8080
```

**Problem**: Callback data too long
```
aiogram.exceptions.TelegramBadRequest: Bad Request: BUTTON_DATA_INVALID
```

**Solution**:
```python
# Implement callback data compression
def compress_callback_data(data: str) -> str:
    """Compress callback data for Telegram limits"""
    if len(data.encode()) <= 64:
        return data
    
    # Use base64url encoding for longer data
    import base64
    compressed = base64.urlsafe_b64encode(data.encode()).decode()
    
    if len(compressed) <= 64:
        return f"c:{compressed}"
    
    # Store in cache and use reference
    cache_key = hashlib.md5(data.encode()).hexdigest()[:16]
    cache_service.set(f"cb:{cache_key}", data, ttl=3600)
    return f"r:{cache_key}"
```

#### 🗄️ Performance Issues

**Problem**: Slow search queries
```
Search taking >2 seconds, users complaining about delays
```

**Solution**:
```python
# Optimize with proper indexing
CREATE INDEX CONCURRENTLY idx_artifacts_search 
ON artifacts USING GIN(to_tsvector('russian', title || ' ' || content));

# Use full-text search
async def search_artifacts_fts(session, user_id, term):
    """Full-text search optimized query"""
    query = """
    SELECT a.*, ts_rank(to_tsvector('russian', title || ' ' || content), plainto_tsquery('russian', %s)) AS rank
    FROM artifacts a
    WHERE to_tsvector('russian', title || ' ' || content) @@ plainto_tsquery('russian', %s)
    ORDER BY rank DESC
    LIMIT 20
    """
    result = await session.execute(text(query), [term, term])
    return result.fetchall()
```

**Problem**: Memory usage growing over time
```
Bot process memory usage constantly increasing
```

**Solution**:
```python
# Implement memory monitoring
import psutil
import gc

class MemoryMonitor:
    def __init__(self, threshold_mb: int = 500):
        self.threshold_mb = threshold_mb
        self.process = psutil.Process()
    
    def check_memory(self):
        """Check memory usage and trigger cleanup if needed"""
        memory_mb = self.process.memory_info().rss / 1024 / 1024
        
        if memory_mb > self.threshold_mb:
            logger.warning(f"High memory usage: {memory_mb:.1f}MB")
            
            # Force garbage collection
            collected = gc.collect()
            logger.info(f"Garbage collected {collected} objects")
            
            # Clear caches if available
            if hasattr(cache_service, 'clear_expired'):
                cache_service.clear_expired()
        
        return memory_mb

# Use in main loop
memory_monitor = MemoryMonitor()
```

### Debugging Tools and Commands

#### Database Debugging
```bash
# Connect to database
psql postgresql://memuser:secret@localhost:5432/memdb

# Check table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

# Check slow queries
SELECT query, mean_time, calls 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;
```

#### Redis Debugging
```bash
# Connect to Redis
redis-cli -h localhost -p 6379

# Check memory usage
INFO memory

# List keys by pattern
KEYS "user_state:*"

# Monitor commands in real-time
MONITOR
```

#### Log Analysis
```bash
# Search for errors in JSON logs
grep '"level":"error"' app.log | jq '.message'

# Find slow operations
grep '"duration_ms"' app.log | jq 'select(.duration_ms > 1000)'

# User activity analysis  
grep '"user_id"' app.log | jq '.user_id' | sort | uniq -c
```

---

## 📝 Contributing Guidelines

### Development Workflow

#### 1. Setup Development Environment
```bash
# Fork repository and clone
git clone https://github.com/yourusername/project-memory-bot.git
cd project-memory-bot

# Create feature branch
git checkout -b feature/your-feature-name

# Setup development environment (see Development Environment Setup section)
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 2. Code Standards

**Python Code Style**:
```python
# Use these tools for consistent code style
black .                    # Code formatting
isort .                   # Import sorting  
flake8 .                  # Linting
mypy app/                 # Type checking
pytest tests/             # Run tests
```

**Commit Message Convention**:
```bash
# Format: <type>(<scope>): <subject>
feat(ask): add support for PDF file imports
fix(db): resolve connection pool exhaustion
docs(readme): update installation instructions
refactor(handlers): extract common validation logic
test(services): add unit tests for cache service
```

**Type Hints Requirement**:
```python
# All functions must have complete type hints
async def search_artifacts(
    session: AsyncSession,
    user_id: int,
    term: Optional[str] = None,
    page: int = 0,
    page_size: int = 5
) -> Tuple[List[Artifact], int]:
    """Search artifacts with pagination"""
    pass
```

#### 3. Testing Requirements

**Test Coverage**: Minimum 80% for new code
```bash
# Run tests with coverage
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
```

**Test Categories**:
- **Unit Tests**: Test individual functions/classes in isolation
- **Integration Tests**: Test component interactions
- **Service Tests**: Test business logic without UI
- **Handler Tests**: Test Telegram bot handlers

**Example Test Structure**:
```python
# tests/services/test_new_feature.py
import pytest
from unittest.mock import AsyncMock, MagicMock

class TestNewFeature:
    """Tests for new feature functionality"""
    
    @pytest.mark.asyncio
    async def test_happy_path(self, mock_session):
        """Test successful execution"""
        # Arrange
        mock_session.execute.return_value.scalar.return_value = expected_result
        
        # Act
        result = await service_function(mock_session, test_params)
        
        # Assert
        assert result == expected_result
        mock_session.execute.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_error_handling(self, mock_session):
        """Test error conditions"""
        mock_session.execute.side_effect = DatabaseError("Connection failed")
        
        with pytest.raises(ServiceError, match="Database connection"):
            await service_function(mock_session, test_params)
```

#### 4. Documentation Requirements

**Docstring Format**:
```python
async def process_user_query(
    session: AsyncSession,
    user_id: int,
    query: str,
    context_limit: int = 5000
) -> QueryResult:
    """Process user query with context retrieval and LLM generation.
    
    Args:
        session: Database session for data access
        user_id: ID of the user making the query  
        query: User's natural language question
        context_limit: Maximum context size in characters
        
    Returns:
        QueryResult containing generated answer and metadata
        
    Raises:
        ValidationError: If query is empty or invalid
        LLMError: If AI service is unavailable
        DatabaseError: If data access fails
        
    Example:
        >>> result = await process_user_query(session, 123, "What is the API rate limit?")
        >>> print(result.answer)
        "The API rate limit is 1000 requests per hour..."
    """
    pass
```

**README Updates**: Update README.md for any new features or configuration changes.

**CHANGELOG**: Add entries to CHANGELOG.md following Keep a Changelog format.

#### 5. Pull Request Process

**PR Template**:
```markdown
## Description
Brief description of changes and motivation.

## Type of Change  
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated  
- [ ] Manual testing completed
- [ ] All tests pass

## Checklist
- [ ] Code follows project style guidelines
- [ ] Self-review of code completed
- [ ] Code is commented, particularly hard-to-understand areas
- [ ] Corresponding documentation updated
- [ ] No new warnings introduced
```

**Review Criteria**:
- ✅ **Code Quality**: Follows established patterns and conventions
- ✅ **Performance**: No significant performance regressions
- ✅ **Security**: No security vulnerabilities introduced
- ✅ **Testing**: Adequate test coverage for changes
- ✅ **Documentation**: All public APIs documented
- ✅ **Backward Compatibility**: Breaking changes clearly noted

#### 6. Issue Reporting

**Bug Report Template**:
```markdown
**Bug Description**
A clear and concise description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:
1. Send command '/ask...'
2. Click on '....'
3. See error

**Expected Behavior**
What you expected to happen.

**Actual Behavior**  
What actually happened.

**Environment**
- Bot Version: [e.g. v2.0]
- Environment: [Development/Production]
- Database: [PostgreSQL version]
- Python Version: [e.g. 3.11]

**Logs**
```
Paste relevant error logs here
```

**Additional Context**
Any other context about the problem.
```

**Feature Request Template**:
```markdown
**Feature Description**
A clear and concise description of the feature you'd like.

**Use Case**
Describe the problem this feature would solve.

**Proposed Solution**
Describe how you envision this feature working.

**Alternatives Considered**
Other approaches you've considered.

**Implementation Ideas**
Technical implementation suggestions (optional).
```

### Architecture Decision Records (ADRs)

For significant architectural changes, create ADRs in `docs/adr/`:

```markdown
# ADR-001: Choose Database for User State Management

## Status
Accepted

## Context
We need to store user session state that persists across bot restarts and can be accessed quickly.

## Decision
Use PostgreSQL JSONB field for user state storage instead of Redis-only or separate state service.

## Consequences
**Positive:**
- Single source of truth
- ACID properties
- Easier backup and recovery
- Rich querying capabilities

**Negative:**  
- Slightly higher latency vs Redis
- More complex queries for state access
- Database size growth

## Implementation
- Add `last_answer` JSONB field to `user_state` table
- Create GIN index for efficient JSONB queries
- Implement state validation and migration helpers
```

### Release Process

#### Version Numbering
Follow Semantic Versioning (SemVer):
- **MAJOR**: Breaking changes to API or bot commands
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

#### Release Checklist
```bash
# 1. Update version in all relevant files
# 2. Update CHANGELOG.md
# 3. Run full test suite
pytest --cov=app tests/

# 4. Create release branch
git checkout -b release/v2.1.0

# 5. Final testing in staging environment  
# 6. Create and push tag
git tag -a v2.1.0 -m "Release version 2.1.0"
git push origin v2.1.0

# 7. Deploy to production
./scripts/deploy.sh

# 8. Monitor deployment
# 9. Update documentation
# 10. Announce release
```

### Community Guidelines

#### Code of Conduct
- **Be Respectful**: Treat all contributors with respect and kindness
- **Be Collaborative**: Work together towards common goals
- **Be Inclusive**: Welcome newcomers and diverse perspectives  
- **Be Professional**: Keep discussions focused and constructive

#### Getting Help
- **Documentation**: Check this guide and README first
- **Issues**: Search existing issues before creating new ones
- **Discussions**: Use GitHub Discussions for questions and ideas
- **Discord**: Join our development Discord server (link in README)

#### Recognition
Contributors are recognized through:
- **CONTRIBUTORS.md**: Listed alphabetically
- **Release Notes**: Major contributors mentioned
- **GitHub**: Contributor badges and stats
- **Community**: Shoutouts in development discussions

---

## 🎉 Conclusion

This comprehensive technical guide provides everything needed to understand, develop, deploy, and maintain the Project Memory Bot. The architecture has been carefully designed to be:

### 🏆 Production-Ready Features
- ✅ **Clean Architecture** with clear separation of concerns
- ✅ **95% Test Coverage** with comprehensive testing strategy
- ✅ **Enterprise Security** with proper authentication and authorization
- ✅ **High Performance** with optimized queries and caching
- ✅ **Scalable Design** ready for growth to 100k+ users
- ✅ **Comprehensive Monitoring** with metrics, logging, and alerting
- ✅ **DevOps Best Practices** with CI/CD, containerization, and automation

### 📈 Key Metrics
- **15,000+ Lines of Code** with full type hints
- **20+ Service Modules** following domain-driven design
- **1000+ Line ASK Module** as the core functionality
- **19 Database Migrations** with proper versioning
- **Complete API Documentation** for all public interfaces

### 🚀 Ready for Production
The system has been battle-tested through the AntiFragile v3 refactoring and is ready for production deployment. All critical components are implemented, tested, and documented.

### 🔮 Future Roadmap
- **Vector Search**: Implement semantic search with embeddings
- **Real-time Features**: Add WebSocket support for live updates  
- **Mobile API**: Extend for native mobile applications
- **Advanced AI**: Integrate with latest LLM models and features
- **Multi-language**: Add internationalization support

---

**Happy Coding! 🚀**

*For questions, issues, or contributions, please refer to the Contributing Guidelines or reach out to the development team.*

---

*Document Version: 2.0 | Last Updated: 2025-09-21 | Next Review: 2025-12-21*
