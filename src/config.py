"""
Namespace de tópicos MQTT gerado automaticamente a partir do usuário
e hostname da máquina, garantindo isolamento no broker público.

Exemplo de raiz gerada: edmil_meu_pc/sensores
"""
import getpass
import socket


def _slug(s: str) -> str:
    """Converte string para slug seguro em tópico MQTT."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in s).strip("_")


_usuario  = _slug(getpass.getuser())
_hostname = _slug(socket.gethostname())

NAMESPACE    = f"{_usuario}_{_hostname}"
RAIZ         = f"{NAMESPACE}/sensores"
TOPICO_CONFIG = f"{RAIZ}/config/lista_topicos"
# Todas as leituras de um ciclo são publicadas em UMA única mensagem neste tópico.
# Isso evita o limite de assinaturas e o throttling do broker público que ocorrem
# ao publicar/assinar dezenas de tópicos individuais.
TOPICO_DADOS = f"{RAIZ}/dados"
