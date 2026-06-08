# PROJETO MOM — Middleware Orientado a Mensagens

![Python](https://img.shields.io/badge/Python-3.13+-3776AB?logo=python&logoColor=white)
![paho-mqtt](https://img.shields.io/badge/paho--mqtt-2.1.0-brightgreen)
![matplotlib](https://img.shields.io/badge/matplotlib-3.7+-orange)
![QoS](https://img.shields.io/badge/QoS-1-blue)
![Broker](https://img.shields.io/badge/Broker-broker.emqx.io-blueviolet)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey)

Sistema distribuído de simulação de sensores IoT usando o protocolo **MQTT**. Composto por duas aplicações desktop independentes que se comunicam através do broker público `broker.emqx.io`: um **Gerenciador** que publica todas as leituras em uma mensagem por ciclo e um **Cliente** que recebe esse lote, exibe os dados em tempo real e emite alertas quando valores saem da faixa configurada.

> **Arquitetura de transmissão:** todas as leituras de um ciclo viajam em **uma única mensagem MQTT** (batch) sob um **namespace isolado por máquina/usuário**. Esse desenho contorna os limites do broker público (número de assinaturas e throttling) que faziam sensores de umidade/velocidade não chegarem ao cliente quando havia muitos sensores. Detalhes na seção [Arquitetura de comunicação](#arquitetura-de-comunicação).

---

# Especificações do Projeto

- Instanciar diversos sensores, cada um monitorando **um único parâmetro** (temperatura, umidade ou velocidade); múltiplos sensores do mesmo tipo são suportados com IDs distintos.
- Permitir **modificar o valor da leitura atual** de cada sensor individualmente (valor fixo) ou deixá-lo gerar leituras aleatórias dentro de uma faixa.
- Definir **limites máximo e mínimo** para cada sensor, alteráveis em tempo real.
- Ao atingir esses limites, o sensor inclui `"alerta": true` no payload; o cliente exibe o alerta visualmente.
- Instanciar diversos Clientes, cada um capaz de:
  - Listar os tópicos disponíveis no broker, **agrupados por tipo**.
  - Escolher quais tópicos assinar via checkboxes.
  - Exibir **Mín, Máx e leitura atual** de cada sensor assinado.
  - Destacar em vermelho a leitura e exibir **⚠ FORA DA FAIXA** quando em alerta.
  - Mostrar um **gráfico das últimas 10 leituras** por tipo, com pontos de alerta em losangos vermelhos.

---

## O que é MQTT?

**MQTT (Message Queuing Telemetry Transport)** é um protocolo de mensagens leve, baseado no modelo *publish/subscribe*, projetado para dispositivos com recursos limitados e redes de baixa largura de banda — sendo amplamente utilizado em aplicações **IoT**.

### Conceitos fundamentais usados neste projeto

| Conceito | Descrição |
|---|---|
| **Broker** | Servidor central que recebe e distribui mensagens — aqui: `broker.emqx.io:1883` |
| **Publisher** | Quem publica mensagens em um tópico (`gerenciador_app.py`) |
| **Subscriber** | Quem assina tópicos para receber mensagens (`cliente_app.py`) |
| **Tópico** | Endereço hierárquico da mensagem, ex: `<namespace>/sensores/dados` |
| **Namespace** | Prefixo único por usuário+máquina (`config.py`) que isola os tópicos no broker compartilhado |
| **Batch** | Estratégia onde todas as leituras de um ciclo são enviadas em uma única mensagem JSON |
| **Retain** | Flag que faz o broker armazenar a última mensagem do tópico para novos assinantes |
| **QoS 1** | Entrega garantida ao menos uma vez — remetente retransmite até receber confirmação (PUBACK) |
| **Keep-alive** | Heartbeat de 60 s para manter a conexão ativa |

---

## Visão Geral da Arquitetura

```
┌─────────────────────────┐         ┌──────────────────────────────┐         ┌─────────────────────────┐
│   gerenciador_app.py    │  QoS 1  │       broker.emqx.io         │  QoS 1  │    cliente_app.py       │
│                         │ publish │          porta 1883          │subscribe│                         │
│  Cria/gerencia sensores ├────────►│  <ns>/sensores/config/...    ├────────►│  Mín / Máx / Atual      │
│  Publica a cada 5 s:    │         │  <ns>/sensores/dados (BATCH) │         │  Alerta ⚠ FORA DA FAIXA │
│   • lista de tópicos    │         │                              │         │  Gráfico últimas 10      │
│   • 1 msg com TODAS as  │         │  <ns> = namespace isolado    │         │  leituras por tipo       │
│     leituras (batch)    │         │        por usuário+máquina   │         │                         │
└─────────────────────────┘         └──────────────────────────────┘         └─────────────────────────┘
```

### Camadas da aplicação

```
┌──────────────────────────────────────────────────────────────────┐
│  INTERFACE    gerenciador_app.py      │    cliente_app.py         │
│               Tkinter — UI e eventos do usuário                   │
├──────────────────────────────────────────────────────────────────┤
│  LÓGICA       sensores.py                                         │
│               Sensor (Python puro) · GerenciadorSensores          │
│               Geração de leituras · Detecção de alerta            │
├──────────────────────────────────────────────────────────────────┤
│  COMUNICAÇÃO  mqtt_gerenciador.py     │    mqtt_cliente.py        │
│               paho-mqtt · QoS 1 · batch único · namespace         │
├──────────────────────────────────────────────────────────────────┤
│  CONFIG       config.py — gera o namespace e os nomes de tópico   │
└──────────────────────────────────────────────────────────────────┘
```

### Fluxo de dados

1. **Gerenciador** cria sensores virtuais e chama `GerenciadorSensores.get_dados_transmissao()` a cada 5 s — que devolve `(lista_topicos, {topico: payload})`.
2. `Sensor.gerar_leitura()` calcula o valor (aleatório ou fixo) e avalia `alerta = valor < v_min or valor > v_max`.
3. `MqttGerenciadorController` publica **duas** mensagens QoS 1 retidas: a lista de tópicos em `TOPICO_CONFIG` e **todas as leituras do ciclo em uma única mensagem batch** em `TOPICO_DADOS`.
4. O **Cliente** faz apenas **2 assinaturas fixas** (`TOPICO_CONFIG` e `TOPICO_DADOS`) — independente do número de sensores.
5. `MqttClienteController` recebe o batch, **filtra em Python** os sensores que o usuário marcou (`_topicos_assinados`) e entrega `(topico, valor, v_min, v_max, alerta)` à interface via `root.after(0, ...)`.
6. A UI atualiza os labels, aciona o alerta visual e redesenha o gráfico.

---

## Estrutura do Projeto

```
PROJETO_MOM/
├── requirements.txt          # paho-mqtt e matplotlib
├── mosquitto.conf            # Configuração opcional para broker local
├── iniciar_broker.py         # Script opcional para iniciar o Mosquitto local
└── src/
    ├── config.py            # Namespace e nomes de tópico (gerados por usuário+máquina)
    ├── sensores.py           # Lógica: Sensor + GerenciadorSensores
    ├── gerenciador_app.py    # Interface: Gerenciador de Sensores (Tkinter)
    ├── mqtt_gerenciador.py   # Comunicação: controller MQTT do Gerenciador
    ├── cliente_app.py        # Interface: Cliente Receptor (Tkinter + matplotlib)
    ├── mqtt_cliente.py       # Comunicação: controller MQTT do Cliente
    └── __init__.py
```

### Responsabilidade de cada arquivo

| Arquivo | Camada | Responsabilidade |
|---|---|---|
| `config.py` | Config | Gera o `NAMESPACE` (slug de usuário+hostname) e os nomes `TOPICO_CONFIG` e `TOPICO_DADOS` |
| `sensores.py` | Lógica | `Sensor` (estado, geração, detecção de alerta) e `GerenciadorSensores` (CRUD thread-safe) |
| `gerenciador_app.py` | Interface | Criar/excluir sensores por tipo, editar Mín/Máx/Atual em tempo real; `_SensorUI` sincroniza Tkinter com `Sensor` |
| `mqtt_gerenciador.py` | Comunicação | Conexão ao broker, thread de transmissão a cada 5 s; publica lista + **batch** QoS 1 |
| `cliente_app.py` | Interface | Painel de disponíveis/assinados, labels Mín/Máx/Atual, alertas, gráfico matplotlib por tipo |
| `mqtt_cliente.py` | Comunicação | 2 assinaturas fixas (config + dados), processa o batch, filtra em Python e entrega à UI |

---

## Tecnologias e Dependências

| Item | Versão | Papel |
|---|---|---|
| Python | 3.13+ | Linguagem principal |
| paho-mqtt | 2.1.0 | Cliente MQTT com suporte a QoS 0/1/2 e reconexão automática |
| matplotlib | 3.7+ | Gráfico de leituras embutido na janela Tkinter via `FigureCanvasTkAgg` |
| tkinter | stdlib | Interface gráfica desktop (não requer instalação separada no Python) |
| broker.emqx.io | — | Broker MQTT público gratuito, sem instalação local |

---

## Pré-requisitos

- Python 3.10 ou superior (recomendado 3.13+)
- `pip` e `venv` disponíveis
- Acesso à internet (broker: `broker.emqx.io:1883`)

> **Linux — tkinter não instalado?**
> ```bash
> sudo apt install python3-tk      # Debian/Ubuntu
> sudo dnf install python3-tkinter  # Fedora
> ```

---

## Instalação

```bash
# 1. Entre no diretório do projeto
cd PROJETO_MOM

# 2. Crie e ative o ambiente virtual
python -m venv .venv
source .venv/bin/activate    # Linux/macOS
.venv\Scripts\activate       # Windows

# 3. Instale as dependências
pip install -r requirements.txt
```

---

## Executando as Aplicações

As aplicações conectam automaticamente ao `broker.emqx.io`. Execute em terminais separados com o venv ativo:

```bash
# Terminal 1 — Gerenciador de Sensores
cd src
python gerenciador_app.py

# Terminal 2, 3, ... — Cliente(s) Receptor(es)
cd src
python cliente_app.py
```

### Alternativa: broker local (Mosquitto)

Para rodar sem acesso à internet ou com total isolamento:

```bash
# Instalar Mosquitto (uma única vez)
sudo apt install mosquitto      # Debian/Ubuntu
brew install mosquitto          # macOS

# Terminal 1 — broker local
python iniciar_broker.py

# Terminais seguintes — apps normalmente (já configuradas para localhost)
```

Para trocar de broker, edite o parâmetro padrão em `mqtt_gerenciador.py` e `mqtt_cliente.py`:

```python
broker: str = "broker.emqx.io"  # altere para "localhost" ou outro endereço
```

---

## Como Usar

### Gerenciador (`gerenciador_app.py`)

| Elemento | Função |
|---|---|
| **Temperatura / Umidade / Velocidade (Qtd)** | Quantidade de sensores a criar de cada tipo |
| **Criar +** | Adiciona N sensores do tipo; cada um aparece na lista agrupado por tipo |
| **Excluir −** | Remove os últimos N sensores do tipo |
| **Checkbox esquerdo** (☐) | Seletor para operações em massa |
| **Checkbox direito** (☐) | Liga/desliga o sensor individualmente |
| **Mín / Máx** | Faixa de valores — editáveis em tempo real |
| **Atual** | Campo editável: vazio = modo aleatório; número = valor fixo (aplicado a cada keystroke) |
| **Selecionar Todos / Limpar Seleção** | Marca ou desmarca todos os checkboxes de seleção |
| **Ligar / Desligar Selecionados** | Ativa ou desativa todos os sensores selecionados |

> **Modo aleatório vs. valor fixo:** deixar "Atual" vazio ou com "---" faz o sensor gerar `random.uniform(v_min, v_max)` a cada ciclo. Digitando um número, o sensor publica exatamente aquele valor — mesmo que esteja fora da faixa Mín–Máx (o que aciona o alerta).

### Cliente (`cliente_app.py`)

| Elemento | Função |
|---|---|
| **Painel esquerdo** (estreito, 25%) | Checkboxes dos sensores disponíveis, agrupados por tipo |
| **Painel direito** (largo, 75%) | Sensores assinados com Mín, Máx, Atual e status de alerta |
| **Mín / Máx** | Faixa configurada no Gerenciador, atualizada a cada leitura |
| **Atual** (preto) | Leitura dentro da faixa |
| **Atual** (vermelho) + **⚠ FORA DA FAIXA** | Leitura fora da faixa Mín–Máx |
| **Gráfico** | Últimas 10 leituras por tipo; uma linha colorida por sensor; losangos vermelhos = alerta |

Múltiplos clientes podem rodar simultaneamente — cada instância gera um `client_id` único via UUID.

---

## Arquitetura de comunicação

A estratégia de transmissão foi desenhada para funcionar de forma confiável no broker **público** `broker.emqx.io`, que impõe dois limites severos:

| Limite do broker público | Sintoma observado | Solução adotada |
|---|---|---|
| **Número de assinaturas por cliente** (~10–20) | Cliente recebia só os primeiros sensores; umidade/velocidade ficavam em `—` | **2 assinaturas fixas** (config + dados) — independem da quantidade de sensores |
| **Throttling de publicação** (descarta mensagens em rajada) | Publicar 30+ mensagens por ciclo perdia umidade/velocidade | **Batch**: todas as leituras em **1 mensagem** por ciclo |
| **Tópicos compartilhados** entre todos os usuários | Dados de outros usuários colidiam nos tópicos genéricos | **Namespace** isolado por usuário+máquina |

### 1. Namespace isolado (`config.py`)

Os nomes de tópico recebem um prefixo único derivado do usuário e do hostname:

```python
NAMESPACE     = f"{usuario}_{hostname}"          # ex.: edmil_meu_pc
TOPICO_CONFIG = f"{NAMESPACE}/sensores/config/lista_topicos"
TOPICO_DADOS  = f"{NAMESPACE}/sensores/dados"
```

Gerenciador e Cliente na mesma máquina geram **o mesmo namespace automaticamente** — nenhuma configuração manual. O namespace aparece no título das duas janelas para conferência visual.

### 2. Batch — uma mensagem por ciclo

O Gerenciador publica **todas** as leituras de um ciclo em uma única mensagem JSON em `TOPICO_DADOS`:

```jsonc
// TOPICO_DADOS  (uma mensagem cobre TODOS os sensores)
{
  "<ns>/sensores/temperatura/temperatura_1": { "valor": 25.3, "v_min": 20, "v_max": 35, "alerta": false, ... },
  "<ns>/sensores/umidade/umidade_1":         { "valor": 62.0, "v_min": 50, "v_max": 80, "alerta": false, ... },
  "<ns>/sensores/velocidade/velocidade_1":   { "valor": 12.8, "v_min": 0,  "v_max": 20, "alerta": false, ... }
  // ... todos os demais sensores ativos
}
```

O Cliente assina apenas `TOPICO_CONFIG` e `TOPICO_DADOS`. Ao receber o batch, **filtra em Python** quais sensores exibir conforme os checkboxes marcados (`_topicos_assinados`). Assim, `assinar()` e `cancelar_assinatura()` apenas adicionam/removem do set local — **nenhuma chamada extra ao broker**.

> **Por que não 1 tópico por sensor?** Na arquitetura inicial observamos que com 30 sensores ele gerava 31 assinaturas e 31 publicações por ciclo (1 assinatura do TOPICO_CONFIG + 30 assinaturas de TOPICO_DADOS, uma para cada sensor), estourando os dois limites acima — gerando um bug em que umidade e velocidade não chegavam ao cliente.

### QoS 1 — entrega garantida

Todas as publicações e assinaturas usam **QoS 1** (`_QOS = 1` em ambos os controllers):

- O broker armazena a mensagem até receber confirmação do receptor (PUBACK).
- Em caso de queda de rede, mensagens pendentes são retransmitidas automaticamente na reconexão.
- Em redes muito instáveis, duplicatas são possíveis (QoS 1 garante *ao menos uma vez*, não *exatamente uma vez*).

### Separação de responsabilidades

- **`Sensor`** (`sensores.py`): Python puro, sem Tkinter. Calcula valor e alerta. Testável isoladamente.
- **`_SensorUI`** (`gerenciador_app.py`): encapsula as `tk.Var` de um sensor. Usa `trace_add` em `var_valor_atual` para atualizar `sensor.valor_fixo` a cada keystroke. O flag `_atualizando_display` (ativado por `set_display()`) impede que atualizações do código disparem o trace acidentalmente.
- **`MqttGerenciadorController`**: recebe apenas `get_dados_fn: Callable` — sem referência a objetos de domínio ou widgets.
- **`MqttClienteController`**: `assinar()`/`cancelar_assinatura()` gerenciam apenas o set Python `_topicos_assinados`; o broker recebe só as 2 assinaturas fixas feitas no `_on_connect`.

### Thread-safety

| Primitiva | Onde | Propósito |
|---|---|---|
| `threading.Lock` | `GerenciadorSensores._lock` | Protege o dict de sensores entre a main thread (UI) e a thread MQTT |
| `threading.Lock` | `MqttClienteController._lock` | Protege `_topicos_assinados` acessado por threads diferentes |
| `threading.Event` | `MqttGerenciadorController._conectado` | Pausa a transmissão enquanto desconectado; retoma automaticamente |
| `root.after(0, ...)` | `cliente_app.py` | Garante que toda atualização de widget ocorre na main thread (Tkinter não é thread-safe) |

### Reconexão automática

O paho-mqtt detecta quedas via `on_disconnect` e tenta reconectar via `loop_start()`. Na reconexão:
- O Gerenciador retoma as publicações — o `threading.Event` é setado em `_on_connect`.
- O Cliente refaz as 2 assinaturas fixas (`TOPICO_CONFIG` e `TOPICO_DADOS`) em `_on_connect`. Como as mensagens são retidas, o último estado chega imediatamente.

### Gráfico em tempo real (matplotlib)

Um gráfico por tipo é criado ao assinar o primeiro sensor daquele tipo e destruído ao cancelar o último. A cada nova leitura, `_atualizar_grafico` redesenha:

- **Linha** por sensor (cor da paleta `_CORES`, 10 cores distintas)
- **Pontos normais**: círculos (`scatter`, `s=18`) na cor da linha
- **Pontos em alerta**: losangos vermelhos (`scatter`, `marker='D'`, `s=40`, `zorder=5`)
- O histórico de alertas (`historico_alertas: deque(maxlen=10)`) é mantido em paralelo ao histórico de valores para identificar quais pontos colorir de vermelho

---

## Tópicos MQTT

Apenas **dois** tópicos, ambos sob o namespace `<ns>` (ex.: `edmil_meu_pc`):

| Tópico | Direção | QoS | Retain | Descrição |
|---|---|---|---|---|
| `<ns>/sensores/config/lista_topicos` | Gerenciador → Cliente | 1 | Sim | Lista JSON de todos os tópicos de sensores existentes |
| `<ns>/sensores/dados` | Gerenciador → Cliente | 1 | Sim | **Batch**: dicionário JSON com a leitura de todos os sensores ativos do ciclo |

### Formato da mensagem `TOPICO_DADOS` (batch)

A mensagem é um objeto JSON que mapeia **tópico do sensor → payload de leitura**:

```json
{
  "<ns>/sensores/velocidade/velocidade_1": {
    "valor": 120.0,
    "tipo": "velocidade",
    "v_min": 40.0,
    "v_max": 110.0,
    "alerta": true,
    "timestamp": 1748123456.789
  },
  "<ns>/sensores/temperatura/temperatura_1": {
    "valor": 25.3,
    "tipo": "temperatura",
    "v_min": 20.0,
    "v_max": 35.0,
    "alerta": false,
    "timestamp": 1748123456.789
  }
}
```

Cada payload de leitura (valor do dicionário) tem os campos:

| Campo | Tipo | Descrição |
|---|---|---|
| `valor` | `float` | Leitura atual (aleatória ou valor fixo definido pelo operador) |
| `tipo` | `str` | `"temperatura"`, `"umidade"` ou `"velocidade"` |
| `v_min` | `float` | Limite inferior configurado no Gerenciador |
| `v_max` | `float` | Limite superior configurado no Gerenciador |
| `alerta` | `bool` | `true` quando `valor < v_min` ou `valor > v_max` |
| `timestamp` | `float` | Unix timestamp da geração da leitura |

> Sensores **desligados** não entram no batch (`gerar_leitura()` retorna `None`), então o cliente simplesmente para de atualizá-los.

---

## Solução de Problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| Sensores não aparecem no Cliente | Gerenciador não está rodando ou sem sensores criados | Abra o Gerenciador e crie ao menos um sensor |
| Cliente e Gerenciador não se comunicam | Namespaces diferentes | Confira se o `ns:` no título das duas janelas é idêntico |
| Valores não atualizam no Cliente | Sensor desligado ou checkbox não marcado | Verifique o checkbox "ativo" no Gerenciador e o checkbox no painel esquerdo do Cliente |
| Alerta não aparece | Sensor em modo aleatório (nunca sai da faixa) | Use valor fixo fora da faixa Mín–Máx |
| Campo "Atual" não aplica valor fixo | O valor é aplicado a cada keystroke — aguarde o próximo ciclo | Aguarde 5 segundos após digitar |
| `ModuleNotFoundError: paho` ou `matplotlib` | venv não ativo ou dependências não instaladas | `source .venv/bin/activate && pip install -r requirements.txt` |
| `_tkinter.TclError` / janela não abre | tkinter não instalado no sistema | `sudo apt install python3-tk` |
| Importação falha | Executando fora do diretório `src/` | `cd src && python gerenciador_app.py` |

---

## Limitações Conhecidas

| Limitação | Descrição |
|---|---|
| Namespace por máquina | Gerenciador e Cliente devem rodar com o mesmo usuário+hostname para compartilhar o namespace (o caso normal). Para máquinas distintas, fixe o `NAMESPACE` manualmente em `config.py` |
| Sem persistência local | Sensores são perdidos ao fechar o Gerenciador |
| IDs sequenciais | O contador de sensores não é reutilizado após exclusões |
| QoS 1 pode duplicar | Em redes muito instáveis, a mesma leitura pode ser entregue mais de uma vez |
| Gráfico de tamanho fixo | O gráfico matplotlib (640×176 px) não redimensiona com a janela |
| Alerta somente via valor fixo | `random.uniform(v_min, v_max)` nunca gera valores fora da faixa |
| Latência do batch | Todas as leituras chegam juntas a cada 5 s; não há streaming individual por sensor |

---

## Próximos Passos

| # | Melhoria |
|---|---|
| 1 | Persistência de configuração dos sensores em JSON |
| 2 | Namespace configurável por linha de comando (compartilhar entre máquinas diferentes) |
| 3 | TLS + autenticação para uso em ambientes externos |
| 4 | Gráfico responsivo que redimensiona com a janela |
| 5 | Alerta sonoro ao entrar em estado de alerta |
| 6 | Painel de log de alertas com histórico |
| 7 | Exportação do histórico de leituras para CSV |
| 8 | Testes automatizados com `pytest` para `Sensor` e `GerenciadorSensores` |
| 9 | Empacotamento como executável com `PyInstaller` |

---

## FAQ

**Quantos sensores posso criar?**
Ilimitados. Todas as leituras viajam em uma única mensagem batch e o Cliente faz sempre as mesmas 2 assinaturas — a quantidade de sensores não afeta o broker.

**Por que umidade e velocidade não apareciam antes?**
No desenho antigo (1 tópico por sensor), com muitos sensores o broker público estourava o limite de assinaturas e o throttling de publicação, descartando justamente os tipos publicados por último. O batch + namespace resolveu isso — verificado com 30 sensores (10 de cada tipo) entregando 100%.

**Posso abrir vários Clientes ao mesmo tempo?**
Sim. Cada instância gera um `client_id` único, sem conflito. Todos recebem o mesmo batch.

**Por que o alerta só dispara com valor fixo?**
`random.uniform(v_min, v_max)` sempre gera valores dentro da faixa. O alerta — `valor < v_min or valor > v_max` — só ocorre quando o operador define um valor fixo fora do range.

**O que acontece se o broker cair?**
O paho-mqtt detecta a queda via `on_disconnect` e reconecta via `loop_start()`. O Gerenciador pausa a transmissão (aguarda o `threading.Event`); o Cliente refaz as 2 assinaturas e, como as mensagens são retidas, recebe o último estado imediatamente.

**Como adicionar um novo tipo de sensor?**

```python
# gerenciador_app.py — adicione em tipos_config e _contadores

tipos_config = [
    ("Temperatura", "temperatura", 20.0, 35.0),
    ("Umidade",     "umidade",     50.0, 80.0),
    ("Velocidade",  "velocidade",   0.0, 20.0),
    ("Pressão",     "pressao",    900.0, 1100.0),  # novo
]
self._contadores = {"temperatura": 0, "umidade": 0, "velocidade": 0, "pressao": 0}

# cliente_app.py — adicione a unidade
UNIDADES = {"temperatura": "°C", "umidade": "%", "velocidade": "Km/h", "pressao": "hPa"}
```

O batch e o namespace cobrem o novo tipo automaticamente — nenhuma outra alteração é necessária.

---

## Glossário

| Termo | Definição |
|---|---|
| **MOM** | Middleware Orientado a Mensagens — comunicação assíncrona e desacoplada entre sistemas |
| **MQTT** | Message Queuing Telemetry Transport — protocolo publish/subscribe para IoT |
| **Broker** | Servidor que recebe e distribui mensagens entre publishers e subscribers |
| **Namespace** | Prefixo `usuario_hostname` que isola os tópicos deste projeto no broker compartilhado |
| **Batch** | Todas as leituras de um ciclo enviadas em uma única mensagem JSON (tópico → payload) |
| **QoS 1** | At least once — entrega garantida, possível duplicata |
| **Retain** | Broker armazena a última mensagem para entrega imediata a novos assinantes |
| **valor_fixo** | Valor constante definido pelo operador que substitui a geração aleatória |
| **alerta** | `bool` no payload: `true` quando leitura está fora da faixa Mín–Máx |
| **trace_add** | Método Tkinter para callbacks disparados em mudanças de `tk.Var` |
| **FigureCanvasTkAgg** | Backend matplotlib para embutir figuras em widgets Tkinter |
| **daemon thread** | Thread encerrada automaticamente ao fim do processo principal |
| **threading.Event** | Primitiva de sincronização para sinalizar estado entre threads |

---

## Referências

- [MQTT.org — Especificação oficial](https://mqtt.org/)
- [Eclipse Paho MQTT Python](https://eclipse.dev/paho/files/paho.mqtt.python/html/index.html)
- [paho-mqtt no PyPI](https://pypi.org/project/paho-mqtt/)
- [EMQX — broker.emqx.io](https://www.emqx.com/en/mqtt/public-mqtt5-broker)
- [matplotlib](https://matplotlib.org/stable/index.html)
- [Tkinter — Python docs](https://docs.python.org/3/library/tkinter.html)
- [threading — Python docs](https://docs.python.org/3/library/threading.html)

---

## Licença

MIT License — Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
