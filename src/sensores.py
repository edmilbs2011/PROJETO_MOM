"""
Camada de domínio (lógica) — Python puro, sem Tkinter nem MQTT.

`Sensor` modela um sensor individual e sabe gerar uma leitura; `GerenciadorSensores`
guarda a coleção de sensores e monta o pacote de dados para transmissão. Manter esta
camada livre de UI e rede a torna testável isoladamente.
"""
import random
import threading
import time


class Sensor:
    """Um sensor simulado. Gera leituras aleatórias na faixa [v_min, v_max],
    ou repete um valor fixo quando o usuário digita um valor manual na UI."""
    def __init__(self, topico: str, tipo: str, v_min: float, v_max: float):
        self.topico = topico
        self.tipo = tipo
        self._ativo = True
        self._v_min = v_min
        self._v_max = v_max
        # Quando != None, a leitura repete este valor em vez de sortear (modo manual)
        self._valor_fixo: float | None = None
        # Cache da última leitura — usado pela UI do gerenciador para exibir o valor atual
        self._ultimo_valor = None

    @property
    def ativo(self) -> bool:
        return self._ativo

    @ativo.setter
    def ativo(self, value: bool):
        self._ativo = bool(value)

    @property
    def v_min(self) -> float:
        return self._v_min

    @v_min.setter
    def v_min(self, value: float):
        self._v_min = float(value)

    @property
    def v_max(self) -> float:
        return self._v_max

    @v_max.setter
    def v_max(self, value: float):
        self._v_max = float(value)

    @property
    def valor_fixo(self) -> float | None:
        return self._valor_fixo

    @valor_fixo.setter
    def valor_fixo(self, value: float | None):
        self._valor_fixo = float(value) if value is not None else None

    @property
    def ultimo_valor(self):
        return self._ultimo_valor

    def gerar_leitura(self) -> dict | None:
        """Retorna o payload de uma leitura, ou None se o sensor estiver desligado.

        O campo `alerta` já vem calculado (valor fora da faixa) para o cliente
        não precisar reaplicar a regra de negócio.
        """
        if not self._ativo:
            self._ultimo_valor = None
            return None
        if self._valor_fixo is not None:
            valor = round(self._valor_fixo, 2)
        else:
            try:
                valor = round(random.uniform(self._v_min, self._v_max), 2)
            except ValueError as e:
                # random.uniform falha se v_min > v_max (faixa inválida digitada na UI)
                print(f"[Sensor {self.topico}] Erro ao gerar leitura: {e}")
                return None
        self._ultimo_valor = valor
        return {
            "valor": valor,
            "tipo": self.tipo,
            "v_min": self._v_min,
            "v_max": self._v_max,
            "alerta": valor < self._v_min or valor > self._v_max,
            "timestamp": time.time(),
        }


class GerenciadorSensores:
    """Coleção de sensores indexada por tópico.

    O `_lock` protege o dict porque ele é lido pela thread MQTT (transmissão) ao
    mesmo tempo em que a main thread (UI) cria/exclui sensores.
    """
    def __init__(self):
        self._sensores: dict[str, Sensor] = {}
        self._lock = threading.Lock()

    def criar(self, topico: str, tipo: str, v_min: float, v_max: float) -> Sensor:
        sensor = Sensor(topico, tipo, v_min, v_max)
        with self._lock:
            self._sensores[topico] = sensor
        return sensor

    def excluir_ultimos(self, tipo: str, qtd: int) -> list[str]:
        """Remove os `qtd` últimos sensores do tipo dado e devolve seus tópicos."""
        with self._lock:
            topicos = [t for t in self._sensores if f"sensores/{tipo}/" in t]
            removidos = topicos[-qtd:]
            for t in removidos:
                del self._sensores[t]
        return removidos

    def snapshot(self) -> list[Sensor]:
        """Cópia da lista de sensores para iteração segura fora do lock."""
        with self._lock:
            return list(self._sensores.values())

    def get_dados_transmissao(self) -> tuple[list[str], dict[str, dict]]:
        """Monta o que vai ao broker por ciclo: a lista de tópicos disponíveis e o
        batch {tópico: payload} com TODAS as leituras (uma só mensagem — ver README).

        Copia os itens dentro do lock e só então gera as leituras, para segurar o
        lock o mínimo possível. Sensores desligados retornam None e ficam de fora do batch.
        """
        with self._lock:
            items = list(self._sensores.items())
        lista_topicos = [t for t, _ in items]
        payloads = {t: p for t, s in items if (p := s.gerar_leitura())}
        return lista_topicos, payloads
