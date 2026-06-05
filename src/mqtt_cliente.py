import json
import threading
import uuid
from collections.abc import Callable
from paho.mqtt import client as mqtt_client
from config import TOPICO_CONFIG as _TOPICO_CONFIG, TOPICO_DADOS as _TOPICO_DADOS, NAMESPACE

_QOS = 1


class MqttClienteController:
    """Recebe as leituras de todos os sensores em UMA mensagem por ciclo.

    O gerenciador publica todas as leituras de um ciclo no tópico único TOPICO_DADOS
    (namespace isolado). O cliente faz apenas 2 assinaturas — config e dados — e filtra
    em Python quais sensores exibir, conforme o usuário marcou na UI.

    Esse desenho evita dois problemas do broker público:
      • limite de assinaturas por cliente (antes: 1 subscribe por sensor);
      • throttling/descarte de mensagens (antes: dezenas de publicações por ciclo).
    """
    def __init__(
        self,
        on_lista_recebida_cb: Callable[[list[str]], None],
        on_sensor_atualizado_cb: Callable[[str, float, float, float, bool], None],
        broker: str = "broker.emqx.io",
        port: int = 1883,
    ):
        self.broker = broker
        self.port = port
        self.client_id = f"cliente_{NAMESPACE[:12]}_{uuid.uuid4().hex[:6]}"

        self._on_lista_recebida = on_lista_recebida_cb
        self._on_sensor_atualizado = on_sensor_atualizado_cb

        self._lock = threading.Lock()
        self._topicos_assinados: set[str] = set()

        self.client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, self.client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    # ----------------------------------------------------------------- MQTT --

    def conectar(self):
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            print(f"[{self.client_id}] Erro inicial de rede: {e}. O loop tentará reconectar...")

    def _on_connect(self, client, userdata, flags, rc, properties=None):  # noqa: N803
        _ = client, userdata, flags, properties
        if rc == 0:
            print(f"[{self.client_id}] Conectado a {self.broker}:{self.port} (QoS {_QOS})")
            print(f"[{self.client_id}] Namespace: {NAMESPACE}")
            # Apenas 2 assinaturas fixas — cobre todos os sensores
            self.client.subscribe(_TOPICO_CONFIG, qos=_QOS)
            self.client.subscribe(_TOPICO_DADOS, qos=_QOS)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):  # noqa: N803
        _ = client, userdata, flags, properties
        print(f"[{self.client_id}] Desconectado (código {rc}). Reconectando...")

    def _on_message(self, client, userdata, msg):  # noqa: N803
        _ = client, userdata
        try:
            payload_str = msg.payload.decode('utf-8')
        except UnicodeDecodeError as e:
            print(f"[{self.client_id}] Payload indecodificável em '{msg.topic}': {e}")
            return

        if msg.topic == _TOPICO_CONFIG:
            try:
                self._on_lista_recebida(json.loads(payload_str))
            except json.JSONDecodeError as e:
                print(f"[{self.client_id}] JSON inválido na lista de tópicos: {e}")
            return

        if msg.topic == _TOPICO_DADOS:
            try:
                batch = json.loads(payload_str)
            except json.JSONDecodeError as e:
                print(f"[{self.client_id}] JSON inválido no batch de dados: {e}")
                return
            # Filtra apenas os sensores que o usuário marcou na UI
            with self._lock:
                assinados = set(self._topicos_assinados)
            for topico, dados in batch.items():
                if topico not in assinados:
                    continue
                valor = dados.get('valor')
                if valor is None:
                    continue
                self._on_sensor_atualizado(
                    topico,
                    valor,
                    dados.get('v_min'),
                    dados.get('v_max'),
                    bool(dados.get('alerta', False)),
                )

    # --------------------------------------------------- subscrição pública --

    def assinar(self, topico: str):
        """Registra o sensor para exibição (filtro local — sem chamada ao broker)."""
        with self._lock:
            self._topicos_assinados.add(topico)

    def cancelar_assinatura(self, topico: str):
        """Remove o sensor da exibição (filtro local — sem chamada ao broker)."""
        with self._lock:
            self._topicos_assinados.discard(topico)

    def desconectar(self):
        self.client.loop_stop()
        self.client.disconnect()
