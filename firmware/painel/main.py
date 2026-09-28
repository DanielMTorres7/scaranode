# Boot do nó ScaraNode: drivers desabilitados e servidor do painel web (no.py).
# Ctrl+C (ou mpremote) para o servidor, solta o motor e cai no REPL; Ctrl+D reinicia.
from machine import Pin
Pin(0, Pin.OUT, value=1)   # EN do TMC2209 (ativo baixo)
Pin(8, Pin.OUT, value=0)   # ENA do DM556 (GP8 alto = habilitado): solto no boot
try:
    import no
    no.rodar()
except KeyboardInterrupt:
    pass
