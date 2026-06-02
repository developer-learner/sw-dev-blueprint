# CONVENTIONS.md — Code Style & Patterns

> Aider reads this file. These rules apply to every code change in this project.

---

## Python Style

```python
# ✅ Type hints on everything
def get_user(user_id: int) -> User | None:
    ...

# ✅ Pydantic for data shapes
class CreateProjectRequest(BaseModel):
    name: str
    description: str | None = None

# ✅ Loguru for logging
from loguru import logger
logger.info("User {user_id} created project {project_id}", user_id=1, project_id=2)

# ❌ Never print()
print("something happened")  # NO

# ❌ Never bare except
try:
    do_something()
except:             # NO — catch specific exceptions
    pass

# ✅ Specific exceptions
try:
    do_something()
except ValueError as e:
    logger.error("Validation failed: {e}", e=e)
    raise
```

---

## Function Design

```python
# ✅ One thing per function, named as a verb phrase
def calculate_project_completion_rate(project_id: int) -> float:
    ...

def send_welcome_email(user: User) -> bool:
    ...

# ❌ Functions that do multiple unrelated things
def process(data):   # too vague, too broad
    ...
```

---

## API Patterns (FastAPI)

```python
# ✅ Route handlers are thin — delegate to services
@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    body: CreateProjectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    return await project_service.create(db, current_user.id, body)

# ❌ Business logic in route handlers
@router.post("/projects")
async def create_project(body: CreateProjectRequest):
    # 50 lines of logic here — NO
```

---

## Error Handling

```python
# ✅ Custom exceptions for domain errors
class ProjectNotFoundError(Exception):
    def __init__(self, project_id: int):
        self.project_id = project_id
        super().__init__(f"Project {project_id} not found")

# ✅ HTTP exceptions at the API layer only
@router.get("/projects/{project_id}")
async def get_project(project_id: int) -> ProjectResponse:
    try:
        return await project_service.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
```

---

## Testing Patterns

```python
# ✅ Arrange / Act / Assert structure, always
def test_create_project_returns_correct_name():
    # Arrange
    request = CreateProjectRequest(name="My Project")
    
    # Act
    result = project_service.create(user_id=1, body=request)
    
    # Assert
    assert result.name == "My Project"

# ✅ Test names describe behavior, not implementation
def test_get_project_raises_when_not_found():    # ✅
def test_get_project_line_42():                  # ❌

# ✅ One assertion concept per test
# ❌ Asserting 10 different things in one test
```

---

## Git Commit Messages

```
# Format: <type>: <short description>
# Types: feat | fix | test | refactor | docs | chore

feat: add project archiving endpoint
fix: handle null description in project creation
test: add coverage for archive status transitions
refactor: extract project validation to separate service
docs: update ARCHITECTURE with new status flow
chore: bump pydantic to 2.7
```

---

## File Naming

```
src/services/project_service.py     # snake_case
src/models/user.py                  # singular model name
tests/services/test_project_service.py
scripts/seed_database.py
```

---

## Environment & Config

```python
# ✅ All config via environment variables
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    secret_key: str
    debug: bool = False
    
    class Config:
        env_file = ".env"

settings = Settings()

# ❌ Never
DATABASE_URL = "postgresql://localhost/mydb"  # hardcoded — NO
```
