import os, sys
# Простейший healthcheck: токен на месте? (допиши реальные проверки при желании)
sys.exit(0 if os.environ.get("BOT_TOKEN") else 1)
