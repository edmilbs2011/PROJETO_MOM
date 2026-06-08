"""
Camada de comunicação (lado publicador).

Conecta ao broker e, em uma thread própria, publica a cada ciclo: (1) a lista de
tópicos disponíveis e (2) o batch com todas as leituras. Não conhece sensores nem
widgets — recebe apenas `get_dados_fn`, mantendo a rede desacoplada do domínio/UI.
"""
import json
import threading
import time
import uuid
from collections.abc import Callable
from paho.mqtt import client as mqtt_client
from config import TOPICO_CONFIG, TOPICO_DADOS

_QOS = 1  # QoS 1 = entrega garantida (ao menos uma vez), com retransmissão na reconexão


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
        # Sufixo aleatório evita colisão de client_id no broker público (desconectaria o outro)
        client_id = f"gerenciador_sensores_{uuid.uuid4().hex[:8]}"
        self.client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        # Event ligado/desligado pelos callbacks de conexão; pausa a transmissão offline
        self._conectado = threading.Event()
        self._rodando = False
        self._thread = None

    def conectar(self):
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            # loop_start: thread interna do paho cuida de I/O de rede e reconexão automática
            self.client.loop_start()
        except Exception as e:
            # Falha inicial não é fatal: o loop_start segue tentando reconectar em background
            print(f"[Gerenciador MQTT] Falha inicial ao conectar: {e}. Tentando reconectar...")

        # Thread separada para publicar sem travar a UI (daemon: morre junto com o app)
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
        """Laço principal de publicação: a cada 5s publica config + batch de dados.
        Só transmite enquanto `_conectado` está setado (pausa automaticamente offline)."""
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
            time.sleep(5)  # intervalo entre ciclos de leitura

    def desconectar(self):
        """Encerramento limpo: para o laço, para o loop de rede e fecha a conexão."""
        self._rodando = False
        self._conectado.clear()
        self.client.loop_stop()
        self.client.disconnect()
