import os

# Many tests call the app from the same address. Give the app's rate limit plenty of room.
# The rate limiter has its own tests with its own small apps.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

# The tests must not depend on the developer's own backend/.env (which has the agent switched on for local play).
os.environ["AGENT_ENABLED"] = "false"
os.environ["APP_ENV"] = "local"
os.environ["RESEARCH_MODE"] = "web"
os.environ["LLM_USAGE_LOG"] = ""  # tests never write the usage file
