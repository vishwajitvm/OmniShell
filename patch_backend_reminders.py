import re

with open("backend/main.py", "r") as f:
    text = f.read()

# 1. Imports and DB Init
if "import asyncpg" not in text:
    text = text.replace("import redis.asyncio as redis", "import redis.asyncio as redis\nimport asyncpg\nimport os")

db_init_code = """
DB_POOL = None

async def init_db():
    global DB_POOL
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@postgres:5432/nl_automation")
    DB_POOL = await asyncpg.create_pool(db_url)
    async with DB_POOL.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                message TEXT NOT NULL,
                trigger_time TIMESTAMP NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

@app.on_event("startup")
async def startup_event():
    await init_db()
"""

# Find a good place to insert db_init_code, e.g. after redis_client init
if "redis_client = None" in text and "DB_POOL" not in text:
    text = text.replace("redis_client = None", db_init_code + "\nredis_client = None")

# 2. Update Pydantic Model
pydantic_old = """class LLMResponse(BaseModel):
    intent_analysis: str
    requires_browser: bool
    target_url: Optional[str] = None
    expected_process: Optional[str] = None
    shell_script: Optional[str] = None
    security_flag: bool
    risk_level: str"""

pydantic_new = """class LLMResponse(BaseModel):
    intent_analysis: str
    requires_browser: bool
    target_url: Optional[str] = None
    expected_process: Optional[str] = None
    shell_script: Optional[str] = None
    security_flag: bool
    risk_level: str
    is_reminder: bool = False
    reminder_time: Optional[str] = None
    reminder_message: Optional[str] = None"""

text = text.replace(pydantic_old, pydantic_new)

# 3. Update System Prompt
old_calendar_rule_regex = r"\- REMINDERS & SCHEDULING:.*?Make sure `pyautogui` is installed or handled!"
new_calendar_rule = """- REMINDERS & SCHEDULING: If the user asks to "remind me to...", "schedule", or do something at a specific future time:
         * DO NOT write a bash script. DO NOT open Google Calendar.
         * INSTEAD, set `is_reminder=true`.
         * Set `reminder_message` to the task (e.g. "Call manager").
         * Set `reminder_time` to the EXACT future time in ISO 8601 format (e.g., "2026-10-01T16:00:00"). CALCULATE this based on the CURRENT SYSTEM TIME provided above.
         * Set `shell_script` to a simple comment: "# Reminder scheduled in database"."""

text = re.sub(old_calendar_rule_regex, new_calendar_rule, text, flags=re.DOTALL)

# 4. Handle Reminder Insertion in Endpoint
hook_old = """structured_data = json.loads(content)"""
hook_new = """structured_data = json.loads(content)
            
            if structured_data.get("is_reminder") and structured_data.get("reminder_time"):
                async with DB_POOL.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO reminders (message, trigger_time) VALUES ($1, $2::timestamp)",
                        structured_data["reminder_message"],
                        structured_data["reminder_time"].replace("Z", "")
                    )
                logger.info(f"Scheduled reminder saved to DB: {structured_data['reminder_message']} at {structured_data['reminder_time']}")"""

text = text.replace(hook_old, hook_new)

# 5. Add /api/reminders endpoints
endpoints_code = """
@app.get("/api/reminders")
async def get_reminders():
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT id, message, trigger_time, status FROM reminders WHERE status = 'pending' ORDER BY trigger_time ASC")
        return [{"id": r["id"], "message": r["message"], "trigger_time": r["trigger_time"].isoformat(), "status": r["status"]} for r in rows]

@app.post("/api/reminders/{reminder_id}/complete")
async def complete_reminder(reminder_id: int):
    async with DB_POOL.acquire() as conn:
        await conn.execute("UPDATE reminders SET status = 'completed' WHERE id = $1", reminder_id)
        return {"status": "success"}
"""

if "@app.get(\"/api/reminders\")" not in text:
    text += endpoints_code

with open("backend/main.py", "w") as f:
    f.write(text)

