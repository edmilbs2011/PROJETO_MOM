import random
import threading
import time


class Sensor:
    def __init__(self, topico: str, tipo: str, v_min: float, v_max: float):
        self.topico = topico
        self.tipo = tipo
        self._ativo = True
        self._v_min = v_min
        self._v_max = v_max
        self._valor_fixo: float | None = None
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
        if not self._ativo:
            self._ultimo_valor = None
            return None
        if self._valor_fixo is not None:
            valor = round(self._valor_fixo, 2)
        else:
            try:
                valor = round(random.uniform(self._v_min, self._v_max), 2)
            except ValueError as e:
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
    def __init__(self):
        self._sensores: dict[str, Sensor] = {}
        self._lock = threading.Lock()

    def criar(self, topico: str, tipo: str, v_min: float, v_max: float) -> Sensor:
        sensor = Sensor(topico, tipo, v_min, v_max)
        with self._lock:
            self._sensores[topico] = sensor
        return sensor

    def excluir_ultimos(self, tipo: str, qtd: int) -> list[str]:
        with self._lock:
            topicos = [t for t in self._sensores if f"sensores/{tipo}/" in t]
            removidos = topicos[-qtd:]
            for t in removidos:
                del self._sensores[t]
        return removidos

    def snapshot(self) -> list[Sensor]:
        with self._lock:
            return list(self._sensores.values())

    def get_dados_transmissao(self) -> tuple[list[str], dict[str, dict]]:
        with self._lock:
            items = list(self._sensores.items())
        lista_topicos = [t for t, _ in items]
        payloads = {t: p for t, s in items if (p := s.gerar_leitura())}
        return lista_topicos, payloads
