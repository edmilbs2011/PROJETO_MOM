"""
Camada de interface — Gerenciador (publicador).

Janela Tkinter para criar/excluir sensores, ligar/desligar e ajustar faixas.
Faz a ponte entre os widgets e a camada de domínio (`GerenciadorSensores`), e
entrega `get_dados_transmissao` ao controller MQTT para a publicação por ciclo.
"""
import tkinter as tk
from tkinter import ttk
from sensores import GerenciadorSensores, Sensor
from mqtt_gerenciador import MqttGerenciadorController
from config import RAIZ, NAMESPACE


class _SensorUI:
    """Estado Tkinter de um sensor; sincroniza as entradas do usuário de volta para
    o objeto de domínio `Sensor` via `trace_add` nas variáveis."""
    def __init__(self, sensor: Sensor):
        self.sensor = sensor
        self.var_ativo = tk.BooleanVar(value=sensor.ativo)
        self.var_selecionado = tk.BooleanVar(value=False)
        self.var_min = tk.DoubleVar(value=sensor.v_min)
        self.var_max = tk.DoubleVar(value=sensor.v_max)
        self.var_valor_atual = tk.StringVar(value="---")
        self.entry_valor: ttk.Entry | None = None
        # Flag anti-eco: indica que o código (não o usuário) está alterando o display,
        # evitando que set_display dispare _sync_valor_atual e grave um "valor fixo"
        self._atualizando_display = False

        # A cada alteração no widget, espelha o valor no objeto de domínio
        self.var_ativo.trace_add("write", lambda *_: setattr(sensor, 'ativo', self.var_ativo.get()))
        self.var_min.trace_add("write", self._sync_min)
        self.var_max.trace_add("write", self._sync_max)
        self.var_valor_atual.trace_add("write", self._sync_valor_atual)

    def _sync_min(self, *_):
        try:
            self.sensor.v_min = self.var_min.get()
        except tk.TclError:
            pass  # campo momentaneamente vazio/inválido durante a digitação

    def _sync_max(self, *_):
        try:
            self.sensor.v_max = self.var_max.get()
        except tk.TclError:
            pass  # idem _sync_min

    def _sync_valor_atual(self, *_):
        # Ignora alterações vindas do próprio código (refresh periódico do display)
        if self._atualizando_display:
            return
        val_str = self.var_valor_atual.get().strip()
        # Vazio/placeholder -> volta ao modo aleatório; número -> fixa o valor digitado
        if val_str in ("", "---", "OFF"):
            self.sensor.valor_fixo = None
        else:
            try:
                self.sensor.valor_fixo = float(val_str)
            except ValueError:
                pass  # entrada parcial (ex: "1.", "-") — aguarda o usuário terminar

    def set_display(self, text: str):
        """Atualiza o campo de exibição sem acionar _sync_valor_atual."""
        self._atualizando_display = True
        self.var_valor_atual.set(text)
        self._atualizando_display = False


class GerenciadorSensoresApp:
    """Janela principal do Gerenciador: monta a UI, instancia o domínio e o MQTT."""
    def __init__(self, root):
        self.root = root
        # ns no título permite conferir visualmente que Gerenciador e Cliente batem
        self.root.title(f"Gerenciador MQTT  |  ns: {NAMESPACE}")
        self.root.geometry("800x600")
        self.root.protocol("WM_DELETE_WINDOW", self._fechar)

        self._gerenciador = GerenciadorSensores()
        self._sensores_ui: dict[str, _SensorUI] = {}      # tópico -> wrapper de UI
        self._frames_tipo: dict[str, ttk.LabelFrame] = {}  # tipo -> seção na lista
        # Contador por tipo: gera nomes sequenciais (temperatura_1, _2, ...) sem reusar índices
        self._contadores = {"temperatura": 0, "umidade": 0, "velocidade": 0}

        # Controller recebe só a função de dados — nenhuma referência a sensores/widgets
        self._mqtt = MqttGerenciadorController(
            get_dados_fn=self._gerenciador.get_dados_transmissao
        )
        self._mqtt.conectar()

        self._build_ui()
        self._agendar_atualizacao_labels()

    def _fechar(self):
        self._mqtt.desconectar()
        self.root.destroy()

    def _build_ui(self):
        frame_controle = ttk.LabelFrame(self.root, text=" Criar / Excluir Sensores ")
        frame_controle.pack(fill="x", padx=10, pady=5)

        tipos_config = [
            ("Temperatura", "temperatura", 20.0, 35.0),
            ("Umidade",     "umidade",     50.0, 80.0),
            ("Velocidade",  "velocidade",   0.0, 20.0),
        ]

        self._inputs_quantidade: dict[str, tk.IntVar] = {}
        for i, (nome, tipo, min_p, max_p) in enumerate(tipos_config):
            ttk.Label(frame_controle, text=f"{nome} (Qtd):").grid(row=i, column=0, padx=10, pady=5, sticky="w")
            var_qtd = tk.IntVar(value=1)
            self._inputs_quantidade[tipo] = var_qtd
            ttk.Entry(frame_controle, textvariable=var_qtd, width=5).grid(row=i, column=1, padx=5, pady=5)

            ttk.Button(
                frame_controle, text="Criar +",
                command=lambda t=tipo, mn=min_p, mx=max_p: self._criar_n_sensores(t, mn, mx)
            ).grid(row=i, column=2, padx=5, pady=5)
            ttk.Button(
                frame_controle, text="Excluir -",
                command=lambda t=tipo: self._excluir_n_sensores(t)
            ).grid(row=i, column=3, padx=5, pady=5)

        frame_acoes = ttk.Frame(self.root)
        frame_acoes.pack(fill="x", padx=10, pady=5)
        ttk.Button(frame_acoes, text="Selecionar Todos",      command=lambda: self._marcar_todos(True)).pack(side="left", padx=2)
        ttk.Button(frame_acoes, text="Limpar Seleção",        command=lambda: self._marcar_todos(False)).pack(side="left", padx=2)
        ttk.Button(frame_acoes, text="Ligar Selecionados",    command=lambda: self._alterar_status_selecionados(True)).pack(side="left", padx=15)
        ttk.Button(frame_acoes, text="Desligar Selecionados", command=lambda: self._alterar_status_selecionados(False)).pack(side="left", padx=2)

        frame_lista = ttk.LabelFrame(self.root, text=" Sensores em Execução ")
        frame_lista.pack(fill="both", expand=True, padx=10, pady=5)

        canvas = tk.Canvas(frame_lista, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=canvas.yview)
        self._scrollable_frame = ttk.Frame(canvas)
        self._scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _agendar_atualizacao_labels(self):
        """Refresca o campo "Atual" de cada sensor a cada 2s, sem atrapalhar o usuário:
        pula sensores em valor fixo e o campo que está em edição (com foco)."""
        focused = self.root.focus_get()
        for sui in self._sensores_ui.values():
            if sui.sensor.valor_fixo is not None:
                continue  # valor fixo: não sobrescrever o que o usuário definiu
            if sui.entry_valor is not None and sui.entry_valor == focused:
                continue  # não mexer no campo que o usuário está digitando
            valor = sui.sensor.ultimo_valor
            if not sui.sensor.ativo:
                sui.set_display("OFF")
            elif valor is None:
                sui.set_display("---")
            else:
                sui.set_display(str(valor))
        # Reagenda a si mesmo na main thread (loop de atualização da UI)
        self.root.after(2000, self._agendar_atualizacao_labels)

    def _criar_n_sensores(self, tipo: str, min_p: float, max_p: float):
        """Cria N sensores do tipo (N vem do campo de quantidade), renderizando cada um."""
        qtd = self._inputs_quantidade[tipo].get()
        if qtd <= 0:
            return
        for _ in range(qtd):
            self._contadores[tipo] += 1
            # Tópico = raiz/tipo/tipo_N (ex.: edmil_pc/sensores/temperatura/temperatura_1)
            topico = f"{RAIZ}/{tipo}/{tipo}_{self._contadores[tipo]}"
            sensor = self._gerenciador.criar(topico, tipo, min_p, max_p)
            sui = _SensorUI(sensor)
            self._sensores_ui[topico] = sui
            self._renderizar_sensor(sui)

    def _excluir_n_sensores(self, tipo: str):
        """Exclui os N últimos sensores do tipo (domínio + UI) e redesenha a lista."""
        qtd = self._inputs_quantidade[tipo].get()
        if qtd <= 0:
            return
        removidos = self._gerenciador.excluir_ultimos(tipo, qtd)
        for t in removidos:
            self._sensores_ui.pop(t, None)
        self._atualizar_lista_ui()

    def _marcar_todos(self, estado: bool):
        """Marca/desmarca a caixa de seleção de todos os sensores (ação em lote)."""
        for sui in self._sensores_ui.values():
            sui.var_selecionado.set(estado)

    def _alterar_status_selecionados(self, ligar: bool):
        """Liga/desliga apenas os sensores atualmente selecionados."""
        for sui in self._sensores_ui.values():
            if sui.var_selecionado.get():
                sui.var_ativo.set(ligar)

    def _renderizar_sensor(self, sui: _SensorUI):
        """Desenha a linha de um sensor, agrupando-o no LabelFrame do seu tipo."""
        tipo = sui.sensor.tipo
        if tipo not in self._frames_tipo:
            lf = ttk.LabelFrame(self._scrollable_frame, text=f"  {tipo.capitalize()}  ")
            lf.pack(fill="x", padx=5, pady=(6, 0))
            self._frames_tipo[tipo] = lf

        frame_item = ttk.Frame(self._frames_tipo[tipo])
        frame_item.pack(fill="x", expand=True, padx=5, pady=2)

        ttk.Checkbutton(frame_item, variable=sui.var_selecionado).grid(row=0, column=0, padx=5)  # seleção p/ ações em lote
        ttk.Checkbutton(frame_item, variable=sui.var_ativo).grid(row=0, column=1, padx=5)        # liga/desliga o sensor

        nome_exibicao = sui.sensor.topico.split('/')[-1]
        ttk.Label(frame_item, text=nome_exibicao, width=18, anchor="w").grid(row=0, column=2, padx=5)
        ttk.Label(frame_item, text="Mín:").grid(row=0, column=3, padx=2)
        ttk.Entry(frame_item, textvariable=sui.var_min, width=5).grid(row=0, column=4, padx=2)
        ttk.Label(frame_item, text="Máx:").grid(row=0, column=5, padx=2)
        ttk.Entry(frame_item, textvariable=sui.var_max, width=5).grid(row=0, column=6, padx=2)
        ttk.Label(frame_item, text="Atual:").grid(row=0, column=7, padx=(10, 2))

        entry_val = ttk.Entry(
            frame_item, textvariable=sui.var_valor_atual,
            width=7, justify="right", font=("Arial", 9, "bold")
        )
        entry_val.grid(row=0, column=8, padx=2)
        sui.entry_valor = entry_val

    def _atualizar_lista_ui(self):
        """Redesenho completo: limpa tudo e re-renderiza (usado após exclusões)."""
        for widget in self._scrollable_frame.winfo_children():
            widget.destroy()
        self._frames_tipo.clear()
        for sui in self._sensores_ui.values():
            self._renderizar_sensor(sui)


if __name__ == "__main__":
    root = tk.Tk()
    app = GerenciadorSensoresApp(root)
    root.mainloop()  # entra no laço de eventos do Tkinter
