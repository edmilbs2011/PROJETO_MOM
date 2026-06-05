import threading
import tkinter as tk
from tkinter import ttk
from collections import deque

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from mqtt_cliente import MqttClienteController
from config import NAMESPACE

UNIDADES = {
    "temperatura": "°C",
    "umidade":     "%",
    "velocidade":  "Km/h",
}

_CORES = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
          "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]


class ClienteMqttApp:
    def __init__(self, root):
        self.root = root

        self.mqtt_controller = MqttClienteController(
            on_lista_recebida_cb=self._disparar_atualizar_lista,
            on_sensor_atualizado_cb=self._disparar_atualizar_valor,
        )

        self.root.title(f"Receptor MQTT  |  ns: {NAMESPACE}  |  id: {self.mqtt_controller.client_id}")
        self.root.geometry("1100x620")
        self.root.minsize(750, 420)
        self.root.protocol("WM_DELETE_WINDOW", self._fechar)

        self._fechando = False

        # {topico: BooleanVar}
        self.topicos_vars: dict[str, tk.BooleanVar] = {}
        # {tipo: LabelFrame} — painéis esquerdo e direito
        self.frames_esq_tipo: dict[str, ttk.LabelFrame] = {}
        self.frames_dir_tipo: dict[str, ttk.LabelFrame] = {}
        # {topico: (frame_row, lbl_min, lbl_max, lbl_valor)}
        self.valores_rows: dict[str, tuple] = {}
        # {topico: deque(maxlen=10)} — histórico de leituras e flags de alerta
        self.historico: dict[str, deque] = {}
        self.historico_alertas: dict[str, deque] = {}
        # {tipo: {'fig', 'ax', 'canvas', 'frame'}} — um gráfico por tipo
        self.graficos_tipo: dict[str, dict] = {}

        self._build_ui()
        self.mqtt_controller.conectar()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        # Painel esquerdo ocupa 1/4, direito 3/4
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=3)
        self.root.rowconfigure(0, weight=1)

        # --- Painel esquerdo: Sensores Disponíveis ---
        frame_esq = ttk.LabelFrame(self.root, text=" Sensores Disponíveis ")
        frame_esq.grid(row=0, column=0, sticky="nsew", padx=(10, 4), pady=10)
        frame_esq.rowconfigure(0, weight=1)
        frame_esq.columnconfigure(0, weight=1)

        canvas_esq = tk.Canvas(frame_esq, borderwidth=0, highlightthickness=0)
        sb_esq = ttk.Scrollbar(frame_esq, orient="vertical", command=canvas_esq.yview)
        self.inner_esq = ttk.Frame(canvas_esq)
        self.inner_esq.bind(
            "<Configure>",
            lambda e: canvas_esq.configure(scrollregion=canvas_esq.bbox("all"))
        )
        canvas_esq.create_window((0, 0), window=self.inner_esq, anchor="nw")
        canvas_esq.configure(yscrollcommand=sb_esq.set)
        canvas_esq.grid(row=0, column=0, sticky="nsew")
        sb_esq.grid(row=0, column=1, sticky="ns")

        self._lbl_vazio_esq = ttk.Label(
            self.inner_esq, text="Aguardando lista do Gerenciador...", foreground="gray"
        )
        self._lbl_vazio_esq.pack(padx=10, pady=10)

        # --- Painel direito: Sensores Assinados ---
        frame_dir = ttk.LabelFrame(self.root, text=" Sensores Assinados ")
        frame_dir.grid(row=0, column=1, sticky="nsew", padx=(4, 10), pady=10)
        frame_dir.rowconfigure(0, weight=1)
        frame_dir.columnconfigure(0, weight=1)

        canvas_dir = tk.Canvas(frame_dir, borderwidth=0, highlightthickness=0)
        sb_dir = ttk.Scrollbar(frame_dir, orient="vertical", command=canvas_dir.yview)
        self.inner_dir = ttk.Frame(canvas_dir)
        self.inner_dir.bind(
            "<Configure>",
            lambda e: canvas_dir.configure(scrollregion=canvas_dir.bbox("all"))
        )
        canvas_dir.create_window((0, 0), window=self.inner_dir, anchor="nw")
        canvas_dir.configure(yscrollcommand=sb_dir.set)
        canvas_dir.grid(row=0, column=0, sticky="nsew")
        sb_dir.grid(row=0, column=1, sticky="ns")

        self._lbl_vazio_dir = ttk.Label(
            self.inner_dir, text="Nenhum sensor assinado.", foreground="gray"
        )
        self._lbl_vazio_dir.pack(padx=10, pady=10)

    # --------------------------------------------------------------- helpers --

    @staticmethod
    def _tipo(topico: str) -> str:
        # Funciona com e sem namespace: "ns/sensores/tipo/nome" ou "sensores/tipo/nome"
        parts = topico.split('/')
        return parts[-2] if len(parts) >= 3 else "outros"

    @staticmethod
    def _nome(topico: str) -> str:
        return topico.split('/')[-1]

    def _cor_sensor(self, topico: str) -> str:
        sensores_do_tipo = [t for t in self.historico if self._tipo(t) == self._tipo(topico)]
        idx = sensores_do_tipo.index(topico) if topico in sensores_do_tipo else 0
        return _CORES[idx % len(_CORES)]

    # ----------------------------------------------- callbacks (main thread) --

    def _fechar(self):
        self._fechando = True
        self.root.destroy()
        threading.Thread(target=self.mqtt_controller.desconectar, daemon=True).start()

    def _disparar_atualizar_lista(self, topicos: list[str]):
        if not self._fechando:
            self.root.after(0, self._atualizar_lista, topicos)

    def _disparar_atualizar_valor(self, topico: str, valor: float, v_min: float, v_max: float, alerta: bool):
        if not self._fechando:
            self.root.after(0, self._atualizar_valor, topico, valor, v_min, v_max, alerta)

    # -------------------------------------------------- atualização de lista --

    def _atualizar_lista(self, topicos: list[str]):
        novos = [t for t in topicos if t not in self.topicos_vars]
        if not novos:
            return

        if self._lbl_vazio_esq and self._lbl_vazio_esq.winfo_exists():
            self._lbl_vazio_esq.destroy()
            self._lbl_vazio_esq = None

        for topico in novos:
            tipo = self._tipo(topico)
            var = tk.BooleanVar(value=False)
            self.topicos_vars[topico] = var

            if tipo not in self.frames_esq_tipo:
                lf = ttk.LabelFrame(self.inner_esq, text=f"  {tipo.capitalize()}  ")
                lf.pack(fill="x", padx=6, pady=(6, 0))
                self.frames_esq_tipo[tipo] = lf

            ttk.Checkbutton(
                self.frames_esq_tipo[tipo],
                text=self._nome(topico),
                variable=var,
                command=lambda t=topico: self._toggle(t)
            ).pack(anchor="w", padx=12, pady=2)

    # -------------------------------------------------- assinatura / cancel --

    def _toggle(self, topico: str):
        if self.topicos_vars[topico].get():
            self._assinar(topico)
        else:
            self._cancelar(topico)

    def _assinar(self, topico: str):
        tipo = self._tipo(topico)
        nome = self._nome(topico)
        unid = UNIDADES.get(tipo, "")

        if self._lbl_vazio_dir and self._lbl_vazio_dir.winfo_exists():
            self._lbl_vazio_dir.destroy()
            self._lbl_vazio_dir = None

        tipo_novo = tipo not in self.frames_dir_tipo
        if tipo_novo:
            lf = ttk.LabelFrame(self.inner_dir, text=f"  {tipo.capitalize()}  ")
            lf.pack(fill="x", padx=6, pady=(6, 0))
            self.frames_dir_tipo[tipo] = lf

        # Linha do sensor
        row = ttk.Frame(self.frames_dir_tipo[tipo])
        row.pack(fill="x", padx=8, pady=2)

        ttk.Label(row, text=nome, width=16, anchor="w").pack(side="left")

        ttk.Label(row, text="Mín:", foreground="gray").pack(side="left", padx=(6, 0))
        lbl_min = ttk.Label(row, text="—", width=6, anchor="e", foreground="gray")
        lbl_min.pack(side="left", padx=(0, 2))

        ttk.Label(row, text="Máx:", foreground="gray").pack(side="left", padx=(6, 0))
        lbl_max = ttk.Label(row, text="—", width=6, anchor="e", foreground="gray")
        lbl_max.pack(side="left", padx=(0, 2))

        ttk.Label(row, text="Atual:", foreground="gray").pack(side="left", padx=(6, 0))
        lbl_valor = ttk.Label(
            row, text="—", width=8, anchor="e",
            foreground="gray", font=("Arial", 9, "bold")
        )
        lbl_valor.pack(side="left", padx=(0, 2))
        ttk.Label(row, text=unid, foreground="gray").pack(side="left")
        lbl_alerta = ttk.Label(row, text="", foreground="red", font=("Arial", 8, "bold"))
        lbl_alerta.pack(side="left", padx=(10, 0))

        self.valores_rows[topico] = (row, lbl_min, lbl_max, lbl_valor, lbl_alerta)
        self.historico[topico] = deque(maxlen=10)
        self.historico_alertas[topico] = deque(maxlen=10)

        if tipo_novo:
            self._criar_grafico(tipo)
        else:
            self._atualizar_grafico(tipo)

        self.mqtt_controller.assinar(topico)

    def _cancelar(self, topico: str):
        if topico in self.valores_rows:
            row, *_ = self.valores_rows.pop(topico)
            row.destroy()

        self.historico.pop(topico, None)
        self.historico_alertas.pop(topico, None)

        tipo = self._tipo(topico)
        if tipo in self.frames_dir_tipo:
            lf = self.frames_dir_tipo[tipo]
            if not lf.winfo_children():
                lf.destroy()
                del self.frames_dir_tipo[tipo]
                if tipo in self.graficos_tipo:
                    self.graficos_tipo[tipo]['frame'].destroy()
                    del self.graficos_tipo[tipo]
            else:
                self._atualizar_grafico(tipo)

        self.mqtt_controller.cancelar_assinatura(topico)

    # ----------------------------------------------------------- matplotlib --

    def _criar_grafico(self, tipo: str):
        frame_grafico = ttk.Frame(self.inner_dir)
        frame_grafico.pack(fill="x", padx=6, pady=(2, 10))

        fig = Figure(figsize=(8, 2.2), dpi=80)
        fig.subplots_adjust(left=0.07, right=0.98, top=0.80, bottom=0.20)
        ax = fig.add_subplot(111)
        ax.set_title(f"Últimas 10 leituras — {tipo.capitalize()}", fontsize=8, pad=4)
        ax.set_xlabel("Leitura", fontsize=7)
        ax.set_ylabel(UNIDADES.get(tipo, ""), fontsize=7)
        ax.tick_params(labelsize=7)
        ax.set_xlim(0.5, 10.5)
        ax.set_xticks(range(1, 11))

        canvas = FigureCanvasTkAgg(fig, master=frame_grafico)
        canvas.get_tk_widget().pack(fill="x")
        canvas.draw()

        self.graficos_tipo[tipo] = {
            'fig': fig, 'ax': ax, 'canvas': canvas, 'frame': frame_grafico,
        }

    def _atualizar_grafico(self, tipo: str):
        if tipo not in self.graficos_tipo:
            return

        ax: object = self.graficos_tipo[tipo]['ax']
        canvas = self.graficos_tipo[tipo]['canvas']

        ax.clear()
        ax.set_title(f"Últimas 10 leituras — {tipo.capitalize()}", fontsize=8, pad=4)
        ax.set_xlabel("Leitura", fontsize=7)
        ax.set_ylabel(UNIDADES.get(tipo, ""), fontsize=7)
        ax.tick_params(labelsize=7)
        ax.set_xlim(0.5, 10.5)
        ax.set_xticks(range(1, 11))

        tem_dados = False
        for i, (topico, hist) in enumerate(
            (t, h) for t, h in self.historico.items() if self._tipo(t) == tipo
        ):
            if not hist:
                continue
            xs = list(range(1, len(hist) + 1))
            ys = list(hist)
            alertas = list(self.historico_alertas.get(topico, []))
            cor = _CORES[i % len(_CORES)]

            ax.plot(xs, ys, linewidth=1.4, color=cor, label=self._nome(topico))

            # Pontos normais
            xs_ok = [x for x, a in zip(xs, alertas) if not a]
            ys_ok = [y for y, a in zip(ys, alertas) if not a]
            if xs_ok:
                ax.scatter(xs_ok, ys_ok, color=cor, s=18, zorder=4)

            # Pontos de alerta em vermelho
            xs_al = [x for x, a in zip(xs, alertas) if a]
            ys_al = [y for y, a in zip(ys, alertas) if a]
            if xs_al:
                ax.scatter(xs_al, ys_al, color="red", s=40, zorder=5, marker='D')

            tem_dados = True

        if tem_dados:
            ax.legend(fontsize=6, loc='upper left', framealpha=0.7)

        canvas.draw()

    # -------------------------------------------------- atualização de valor --

    def _atualizar_valor(self, topico: str, valor: float, v_min: float, v_max: float, alerta: bool):
        if topico not in self.valores_rows:
            return
        _, lbl_min, lbl_max, lbl_valor, lbl_alerta = self.valores_rows[topico]

        cor_atual = "red" if alerta else "black"
        if lbl_valor.winfo_exists():
            lbl_valor.config(text=str(valor), foreground=cor_atual)
        if lbl_min.winfo_exists() and v_min is not None:
            lbl_min.config(text=str(v_min), foreground="black")
        if lbl_max.winfo_exists() and v_max is not None:
            lbl_max.config(text=str(v_max), foreground="black")
        if lbl_alerta.winfo_exists():
            if alerta and v_min is not None and valor < v_min:
                msg = "⚠ Leitura inferior ao mínimo"
            elif alerta and v_max is not None and valor > v_max:
                msg = "⚠ Leitura superior ao máximo"
            else:
                msg = ""
            lbl_alerta.config(text=msg)

        if topico in self.historico:
            self.historico[topico].append(valor)
            self.historico_alertas[topico].append(alerta)
            self._atualizar_grafico(self._tipo(topico))


if __name__ == "__main__":
    root = tk.Tk()
    app = ClienteMqttApp(root)
    root.mainloop()
