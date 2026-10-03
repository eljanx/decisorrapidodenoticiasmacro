"""Asistente de configuración para personas que no programan.

Pide las claves, las comprueba, detecta solo el chat de Telegram y guarda todo en .env.
Uso: python -m decisor.configurar
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import anthropic
import httpx2 as httpx

RAIZ = Path(__file__).resolve().parents[1]
ENV = RAIZ / ".env"


def titulo(texto: str) -> None:
    print("\n" + "=" * 60 + f"\n  {texto}\n" + "=" * 60)


def leer_env() -> dict[str, str]:
    datos = {}
    if ENV.exists():
        for linea in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.split("=", 1)
                datos[k.strip()] = v.strip()
    return datos


def guardar_env(datos: dict[str, str]) -> None:
    lineas = ["# Generado por el asistente. No compartas este fichero con nadie."]
    lineas += [f"{k}={v}" for k, v in datos.items()]
    ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def preguntar(texto: str, actual: str = "") -> str:
    if actual:
        r = input(f"{texto}\n(Ya hay una guardada. Pulsa Intro para mantenerla o pega una nueva)\n> ").strip()
        return r or actual
    while True:
        r = input(f"{texto}\n> ").strip()
        if r:
            return r


def comprobar_anthropic(clave: str) -> bool:
    try:
        cliente = anthropic.Anthropic(api_key=clave, max_retries=1, timeout=20)
        cliente.messages.create(
            model="claude-opus-5-5", max_tokens=1024,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Responde solo: OK"}],
        )
        print("✔ Clave de Anthropic correcta y con saldo.")
        return True
    except anthropic.AuthenticationError:
        print("✘ La clave de Anthropic no es válida. Revisa que la has copiado entera.")
    except anthropic.APIStatusError as e:
        if "credit balance" in str(e):
            print("⚠ La clave es correcta pero la cuenta NO TIENE SALDO.")
            print("  Recarga en console.anthropic.com → Billing. La app no analizará nada hasta entonces.")
            return True  # la clave vale; se guarda igualmente
        print(f"✘ Error de Anthropic: {e.message}")
    except anthropic.APIConnectionError:
        print("✘ No hay conexión con Anthropic. ¿Tienes internet?")
    return False


def comprobar_telegram(token: str) -> str | None:
    try:
        r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
    except Exception:
        print("✘ No hay conexión con Telegram. ¿Tienes internet?")
        return None
    if not r.get("ok"):
        print("✘ El código del bot no es válido. Cópialo de nuevo desde @BotFather.")
        return None
    nombre = r["result"]["username"]
    print(f"✔ Bot encontrado: @{nombre}")
    return nombre


def detectar_chat(token: str, nombre_bot: str) -> str | None:
    base = f"https://api.telegram.org/bot{token}"
    # Descartar mensajes antiguos
    viejos = httpx.get(f"{base}/getUpdates", params={"timeout": 0}, timeout=15).json().get("result", [])
    offset = viejos[-1]["update_id"] + 1 if viejos else 0
    print(f"\nAhora abre Telegram en el móvil, busca @{nombre_bot} y envíale la palabra: hola")
    print("Esperando tu mensaje (hasta 3 minutos)...")
    fin = time.time() + 180
    while time.time() < fin:
        r = httpx.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=35).json()
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message")
            if msg:
                chat_id = str(msg["chat"]["id"])
                nombre = msg["chat"].get("first_name", "")
                httpx.post(f"{base}/sendMessage", json={"chat_id": chat_id,
                           "text": f"✅ ¡Hola {nombre}! Este bot ya está vinculado contigo."}, timeout=15)
                # Confirmar los mensajes leídos para que la app no los procese al arrancar
                httpx.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 0}, timeout=15)
                print(f"✔ Chat detectado ({nombre}).")
                return chat_id
    print("✘ No llegó ningún mensaje. Vuelve a ejecutar el instalador e inténtalo de nuevo.")
    return None


def main() -> int:
    titulo("CONFIGURACIÓN DEL DECISOR")
    print("Para pegar en esta ventana: clic con el botón derecho del ratón (o Ctrl+V).")
    datos = leer_env()

    if not (RAIZ / "config.yaml").exists():
        shutil.copy(RAIZ / "config.example.yaml", RAIZ / "config.yaml")

    titulo("PASO 1 de 2: Clave de Anthropic (la inteligencia artificial)")
    print("La consigues en console.anthropic.com → API Keys → Create Key.")
    while True:
        clave = preguntar("Pega aquí la clave de Anthropic (empieza por sk-ant-):", datos.get("ANTHROPIC_API_KEY", ""))
        if comprobar_anthropic(clave):
            datos["ANTHROPIC_API_KEY"] = clave
            break
        datos.pop("ANTHROPIC_API_KEY", None)

    titulo("PASO 2 de 2: Bot de Telegram")
    print("El código te lo da @BotFather en Telegram (parece 123456789:ABCdef...).")
    while True:
        token = preguntar("Pega aquí el código del bot:", datos.get("TELEGRAM_BOT_TOKEN", ""))
        nombre_bot = comprobar_telegram(token)
        if nombre_bot:
            datos["TELEGRAM_BOT_TOKEN"] = token
            break
        datos.pop("TELEGRAM_BOT_TOKEN", None)

    if datos.get("TELEGRAM_CHAT_ID"):
        r = input("\nYa estás vinculado con el bot. ¿Volver a vincular? (s/N) > ").strip().lower()
        if r != "s":
            guardar_env(datos)
            titulo("¡LISTO! Ahora haz doble clic en ARRANCAR.bat")
            return 0
    chat_id = detectar_chat(token, nombre_bot)
    if not chat_id:
        guardar_env(datos)
        return 1
    datos["TELEGRAM_CHAT_ID"] = chat_id
    datos.setdefault("X_BEARER_TOKEN", "")
    guardar_env(datos)
    titulo("¡LISTO! Ahora haz doble clic en ARRANCAR.bat")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
