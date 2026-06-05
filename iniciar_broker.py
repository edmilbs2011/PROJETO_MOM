"""
Inicia o broker MQTT local (Mosquitto) antes de rodar as aplicações.

Uso:
    python iniciar_broker.py

O broker roda em localhost:1883 sem limites de conexões ou assinaturas.
Para parar, pressione Ctrl+C.
"""

import subprocess
import sys
import shutil
import time
import socket
from pathlib import Path


CONF = Path(__file__).parent / "mosquitto.conf"


def broker_respondendo(host="127.0.0.1", port=1883, tentativas=10) -> bool:
    for _ in range(tentativas):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main():
    if shutil.which("mosquitto") is None:
        print("Mosquitto não encontrado. Instale com:")
        print("  sudo apt install mosquitto        # Debian/Ubuntu")
        print("  sudo dnf install mosquitto        # Fedora")
        print("  brew install mosquitto            # macOS")
        sys.exit(1)

    print(f"Iniciando broker Mosquitto em localhost:1883...")
    proc = subprocess.Popen(
        ["mosquitto", "-c", str(CONF)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    if broker_respondendo():
        print("Broker pronto. Pressione Ctrl+C para encerrar.\n")
    else:
        print("Broker não respondeu a tempo. Verifique se a porta 1883 está livre.")
        proc.terminate()
        sys.exit(1)

    try:
        for linha in proc.stdout:
            print(linha.decode().rstrip())
    except KeyboardInterrupt:
        print("\nEncerrando broker...")
        proc.terminate()
        proc.wait()
        print("Broker encerrado.")


if __name__ == "__main__":
    main()
