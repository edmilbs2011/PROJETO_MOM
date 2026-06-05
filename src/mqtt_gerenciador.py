import json
import threading
import time
import uuid
from collections.abc import Callable
from paho.mqtt import client as mqtt_client
from config import TOPICO_CONFIG, TOPICO_DADOS

_QOS = 1


class MqttGerenciadorController:
    def __init__(
        self,
        get_dados_fn: Callable[[], tuple[list[str], dict[str, dict]]],
        broker: str = "broker.emqx.io",
        port: int = 1883,
    ):
        self._get_dados = get_dados_fn
        self.broker = broker
        self.port = port
        client_id = f"gerenciador_sensores_{uuid.uuid4().hex[:8]}"
        self.client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        self._conectado = threading.Event()
        self._rodando = False
        self._thread = None

    def conectar(self):
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            print(f"[Gerenciador MQTT] Falha inicial ao conectar: {e}. Tentando reconectar...")

        self._rodando = True
        self._thread = threading.Thread(target=self._loop_transmissao, daemon=True)
        self._thread.start()

    def _on_connect(self, client, userdata, flags, rc, properties=None):  # noqa: N803
        _ = client, userdata, flags, properties
        if rc == 0:
            print(f"[Gerenciador MQTT] Conectado ao broker {self.broker}:{self.port} (QoS {_QOS})")
            self._conectado.set()
        else:
            print(f"[Gerenciador MQTT] Falha de conexão. Código: {rc}")
            self._conectado.clear()

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):  # noqa: N803
        _ = client, userdata, flags, properties
        print(f"[Gerenciador MQTT] Conexão perdida (Código: {rc}). Aguardando reconexão automática...")
        self._conectado.clear()

    def _loop_transmissao(self):
        while self._rodando:
            if self._conectado.is_set():
                try:
                    lista_topicos, payloads = self._get_dados()
                    # Lista de tópicos disponíveis (retida, para novos clientes)
                    self.client.publish(
                        TOPICO_CONFIG,
                        json.dumps(lista_topicos),
                        qos=_QOS,
                        retain=True,
                    )
                    # TODAS as leituras do ciclo em UMA única mensagem.
                    # Publicar dezenas de tópicos individuais por ciclo estoura o
                    # throttling do broker público (umidade/velocidade eram descartados).
                    self.client.publish(
                        TOPICO_DADOS,
                        json.dumps(payloads),
                        qos=_QOS,
                        retain=True,
                    )
                except Exception as e:
                    print(f"[Gerenciador MQTT] Erro ao transmitir: {e}")
            time.sleep(5)

    def desconectar(self):
        self._rodando = False
        self._conectado.clear()
        self.client.loop_stop()
        self.client.disconnect()
