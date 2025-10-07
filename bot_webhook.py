from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"


def send_message(chat_id, text):
    """Отправка сообщения пользователю"""
    try:
        requests.post(WEBHOOK_URL + "sendMessage", json={"chat_id": chat_id, "text": text})
    except Exception as e:
        print("❌ Ошибка при отправке сообщения:", e)


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/webhook":
            self.send_response(404)
            self.end_headers()
            return

        # читаем тело запроса
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            update = json.loads(body)
        except Exception as e:
            print("❌ Ошибка при разборе JSON:", e)
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid JSON")
            return

        print("🔥 Получено обновление:", json.dumps(update, indent=2, ensure_ascii=False))

        # если пришло текстовое сообщение
        if "message" in update and "text" in update["message"]:
            chat_id = update["message"]["chat"]["id"]
            text = update["message"]["text"]
            send_message(chat_id, f"Ты написал: {text}")

        # Telegram ждёт быстрый ответ
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")


if __name__ == "__main__":
    port = 8080
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"Слушаю Telegram webhook на порту {port}")

    # --- УДАЛЯЕМ СТАРЫЙ ВЕБХУК + СТАВИМ НОВЫЙ ---
    public_url = input("Введи публичный URL (например https://yourdomain/webhook): ").strip()
    delete_hook = requests.get(WEBHOOK_URL + "deleteWebhook", params={"drop_pending_updates": "true"})
    print("Очистка старого вебхука:", delete_hook.json())
    set_hook = requests.get(WEBHOOK_URL + "setWebhook", params={"url": public_url})
    print("Регистрация нового вебхука:", set_hook.json())

    server.serve_forever()
