# Nó ScaraNode — firmware do painel web (MicroPython 1.29, testado também no 1.19; RP2040-Zero + TMC2209 em UART)
# Protocolo pela USB: uma linha JSON por comando {"c": nome, "id": n, ...}, uma linha JSON por resposta.
# Os passos saem da PIO1 SM0 alimentada por DMA (canal 11): ler o TMC não atrapalha o movimento.
# O fim de curso que bloqueia o sentido do movimento é lido pela própria PIO a cada passo: a parada
# não depende do laço em Python (GC, USB, leitura do TMC); a varredura em Python fica de reserva.
# A revisão da placa vem do placa.py (REV = "v17"), gravado pelo painel; sem ele, v17.
# config.json (comando "salva"): driver, TMC, fins de curso e o bloco "robo" do painel (eixos ligados nesta
# placa, reduções, limites, referência). Lido na partida: a placa já liga configurada, com os motores soltos.
# Pinos comuns: EN GP0 · VSENSE GP1 · ENA do DM556 GP8 (alto = habilitado) · FIM1 GP27 · FIM2 GP15 · NTC GP29
# v18 também tem o NTC2 (motor do DM556) no GP26.
# v14–v17: UART GP5 (fio até o pino 4 do módulo) · STEP GP6 · DIR GP7, que vão ao mesmo tempo para o
#          TMC (soquete) e para o 74ACT245 -> J4 (DM556).
# v18:     TMC STEP GP4 · DIR GP5 · UART GP2 (pino 4); DM556 STEP GP6 · DIR GP7 pelo 74ACT245, independentes.
#          O STEP que não está em uso fica parado em nível baixo.
# Modo "dm556": o TMC fica desabilitado (EN alto), o GP8 liga/solta o DM556 e o STEP do DM556 pode sair
# invertido (!gpio6 no Klipper). Modo "tmc": GP8 baixo, o DM556 não segue os passos.
# Modo "ambos" (só até a v17): os dois habilitados recebendo os mesmos pulsos (para comparar motores/drivers).
# Modo "dois" (v18): TMC e DM556 habilitados, cada um no seu motor. jog/mover/ir/zero escolhem o canal
# pelo "k" ("tmc" ou "dm556"); cada canal guarda a sua posição e cada fim de curso pertence a um canal (k1, k2).
# Trajetória (tjini/tj): segmentos sincronizados em um ou nos dois canais, mandados aos poucos pelo painel
# (robô desenhando). Cada canal tem a sua SM (PIO1 SM1/SM2) lendo um anel de palavras por DMA (canais 9/10);
# as duas SMs partem no mesmo ciclo e o painel calcula os atrasos para os dois canais andarem juntos.
import sys, os, time, math, array, json, select, uctypes, micropython, gc, struct, binascii
from machine import Pin, ADC, mem32, unique_id
from rp2 import PIO, StateMachine, asm_pio

FW = "painel 1.14"
try:
    from placa import REV
except ImportError:
    REV = "v17"
PLACAS = {           # UART, STEP e DIR do TMC, STEP e DIR do DM556
    "v17": (5, 6, 7, 6, 7),
    "v18": (2, 4, 5, 6, 7),
}
CANAIS = ("tmc", "dm556")
REV_OK = REV in PLACAS
UID = binascii.hexlify(unique_id()).decode()
BOOT = binascii.hexlify(os.urandom(4)).decode()            # muda a cada partida: o painel sabe se a placa reiniciou
PIN_UART, PIN_STEP_TMC, PIN_DIR_TMC, PIN_STEP_DM, PIN_DIR_DM = PLACAS[REV if REV_OK else "v17"]
COMUM = PIN_STEP_TMC == PIN_STEP_DM     # STEP/DIR compartilhados: permite o modo "ambos"
PINOS = {"tmc": (PIN_STEP_TMC, PIN_DIR_TMC), "dm556": (PIN_STEP_DM, PIN_DIR_DM)}
PIN_EN, PIN_VS, PIN_ENA = 0, 1, 8
PIN_FIM1, PIN_FIM2 = 27, 15
PIN_NTC, PIN_NTC2 = 29, (26 if REV == "v18" else None)
PIN_LED = 16                # WS2812 do RP2040-Zero (GRB)
BAUD = 115200             # UART do TMC: ~1,2 ms por leitura de registrador
RSENSE = 0.110
IMAX_RUN = 1.4             # A RMS: teto do módulo StepStick (um TMC queimou a 1,7 A)
VMAX = 100000              # passos/s
WDT_JOG = 1000             # ms sem mensagem do painel -> o jog para sozinho
FREQ = 10_000_000          # relógio do gerador de passos: período ajustável de 0,2 em 0,2 us
CPU = FREQ // 1_000_000    # ciclos por us

GCONF, GSTAT, IFCNT, IOIN = 0x00, 0x01, 0x02, 0x06
IHOLD_IRUN, TPOWERDOWN, TSTEP, TPWMTHRS, TCOOLTHRS, VACTUAL = 0x10, 0x11, 0x12, 0x13, 0x14, 0x22
SG_RESULT, CHOPCONF, DRV_STATUS, PWMCONF = 0x41, 0x6C, 0x6F, 0x70
MRES = {256: 0, 128: 1, 64: 2, 32: 3, 16: 4, 8: 5, 4: 6, 2: 7, 1: 8}

DMA_CH = 11
DMA = 0x50000000 + DMA_CH * 0x40
PIO1_TXF0 = 0x50300010
DREQ_PIO1_TX0 = 8
GPIO_DM_CTRL = 0x40014000 + 8 * PIN_STEP_DM + 4    # IO_BANK0: OUTOVER (bits 9:8) = 1 inverte a saída
# Endereços acima de 2**30 viram inteiro longo no MicroPython: cada conta aloca e pode disparar
# o coletor de lixo no meio de um corte. Tudo pré-calculado uma vez aqui.
R_DMA_READ, R_DMA_WRITE, R_DMA_COUNT, R_DMA_TRIG, R_DMA_AL1 = (DMA, DMA + 4, DMA + 8, DMA + 0xC, DMA + 0x10)
V_DMA_CTRL = 1 | (2 << 2) | (1 << 4) | (DMA_CH << 11) | (DREQ_PIO1_TX0 << 15)
R_SM0_EXECCTRL, R_SM0_ADDR = 0x503000CC, 0x503000D4
R_PIO1_IRQ, R_PIO1_INSTR = 0x50300030, 0x50300048


# ---------- PIO ----------

@asm_pio(set_init=PIO.IN_HIGH, out_init=PIO.IN_HIGH, out_shiftdir=PIO.SHIFT_RIGHT)
def _uart_tx():
    label("topo")
    pull()
    set(pindirs, 1)
    set(x, 7)
    set(pins, 0)        [7]
    label("bit")
    out(pins, 1)        [6]
    jmp(x_dec, "bit")
    set(pins, 1)        [6]
    out(y, 1)
    jmp(not_y, "topo")
    set(pindirs, 0)


@asm_pio(in_shiftdir=PIO.SHIFT_RIGHT, fifo_join=PIO.JOIN_RX)
def _uart_rx():
    label("start")
    wait(0, pin, 0)
    set(x, 7)           [10]
    label("bit")
    in_(pins, 1)
    jmp(x_dec, "bit")   [6]
    jmp(pin, "ok")
    wait(1, pin, 0)
    jmp("start")
    label("ok")
    push(block)


# WS2812 a 8 MHz (mesmo programa do demo de fábrica do RP2040-Zero): 24 bits GRB no topo da palavra
@asm_pio(sideset_init=PIO.OUT_LOW, out_shiftdir=PIO.SHIFT_LEFT, autopull=True, pull_thresh=24)
def _ws2812():
    wrap_target()
    label("bitloop")
    out(x, 1)               .side(0)    [2]
    jmp(not_x, "do_zero")   .side(1)    [1]
    jmp("bitloop")          .side(1)    [4]
    label("do_zero")
    nop()                   .side(0)    [4]
    wrap()


# segmento = (n-1, d): n passos com período 2d+9 ciclos de FREQ; +3 ciclos por segmento.
# Depois de cada passo (STEP já baixo) as instruções I_FIM e I_FIM+1, reescritas a cada movimento
# por _fim_pio, testam o fim de curso do sentido (jmp pin): acionado -> irq 0 e a SM para ali, sem
# pulso pela metade e com X = passos que faltavam. Os três jeitos gastam 3 ciclos: o período não muda.
@asm_pio(set_init=PIO.OUT_LOW)
def _passos():
    pull()
    mov(x, osr)
    pull()
    label("passo")
    set(pins, 1)
    mov(y, osr)
    label("alto")
    jmp(y_dec, "alto")
    set(pins, 0)
    mov(y, osr)
    label("baixo")
    jmp(y_dec, "baixo")
    jmp("segue")        [1]     # I_FIM: sem fim de curso neste sentido
    jmp("trava")                # I_FIM + 1
    label("trava")
    irq(block, 0)
    label("segue")
    jmp(x_dec, "passo")


I_PASSO, I_FIM, I_TRAVA, I_SEGUE = 3, 9, 11, 12      # posições das instruções no _passos
J_PIN, J_D1 = 6 << 5, 1 << 8                          # jmp: condição "pin" e 1 ciclo de atraso


# Trajetória: uma palavra por segmento = d (bits 0-19) | DIR (bit 20) | n passos (bits 21-31).
# n > 0: DIR, depois n passos de período 2d+7 ciclos (baixo d+5, alto d+2): 5 + n(2d+7) ciclos.
# n = 0: espera, d+9 ciclos. n = 0 e d = 0: sentinela, a SM levanta o irq (1 ou 2) e para ali.
# O anel sempre termina num sentinela: faltou palavra = a SM para no fim do que chegou.
@asm_pio(set_init=PIO.OUT_LOW, out_init=PIO.OUT_LOW, out_shiftdir=PIO.SHIFT_RIGHT)
def _traj():
    wrap_target()
    label("topo")
    pull()
    out(isr, 20)
    out(pins, 1)
    out(x, 11)
    jmp(x_dec, "passo")
    mov(y, isr)
    jmp(not_y, "para")
    label("espera")
    jmp(y_dec, "espera")
    jmp("topo")
    label("passo")
    mov(y, isr)
    label("baixo")
    jmp(y_dec, "baixo")
    set(pins, 1)
    mov(y, isr)
    label("alto")
    jmp(y_dec, "alto")
    set(pins, 0)
    jmp(x_dec, "passo")
    wrap()
    label("para")
    irq(block, rel(0))
    jmp("para")                 # não sai do sentinela nem se o irq for limpo com a SM ligada


T_PASSO, T_ALTO, T_PARA = 9, 12, 16       # posições no _traj: início do passo, depois do set(pins, 1), sentinela
TJ_N = 512                  # palavras por anel e por canal (5 s com segmentos de 10 ms)
TJ_MARGEM = 16              # palavras já lidas que não são sobrescritas (a contagem no corte ainda as usa)
TJ_DMIN = 50                # d mínimo: pulso alto >= 5 us e DIR >= 5 us antes do 1º passo (DM556)
TJ_TC = 0x3FFFFFFF          # TRANS_COUNT do DMA ("infinito"; inteiro curto, sem alocar)
TJ_SM = (5, 6)              # PIO1 SM1 e SM2
TJ_DMA = (9, 10)


# ---------- TMC2209 ----------

def _tabelas_crc():
    # CRC8 do TMC (polinômio 0x07, bits de cada byte do LSB para o MSB): é o CRC8 comum sobre o
    # byte espelhado, então dá para usar tabela (bit a bit em Python levava ~1 ms por quadro)
    tab = bytearray(256)
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
        tab[i] = c
    rev = bytearray(256)
    for i in range(256):
        r = 0
        for k in range(8):
            if i & (1 << k):
                r |= 0x80 >> k
        rev[i] = r
    return bytes(tab), bytes(rev)


CRC_TAB, CRC_REV = _tabelas_crc()


def _crc8(dados):
    crc = 0
    for b in dados:
        crc = CRC_TAB[crc ^ CRC_REV[b]]
    return crc


class TMC:
    def __init__(self):
        Pin(PIN_UART, Pin.IN, Pin.PULL_UP)
        p = Pin(PIN_UART)
        self.rx = StateMachine(1, _uart_rx, freq=8 * BAUD, in_base=p, jmp_pin=p)
        self.tx = StateMachine(0, _uart_tx, freq=8 * BAUD, set_base=p, out_base=p)
        self.rx.active(1)
        self.tx.active(1)
        self.addr = None
        self._req = {}

    def _limpa(self):
        while self.rx.rx_fifo():
            self.rx.get()

    def _envia(self, q):
        ult = len(q) - 1
        for i, b in enumerate(q):
            self.tx.put(b | (0x100 if i == ult else 0))

    def _recebe(self, n, timeout_ms):
        buf = []
        t0 = time.ticks_ms()
        while len(buf) < n and time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
            if self.rx.rx_fifo():
                buf.append(self.rx.get() >> 24)
        return buf

    def le(self, reg, addr=None, tentativas=2):
        a = self.addr if addr is None else addr
        q = self._req.get((a, reg))
        if q is None:                   # quadro de leitura é sempre o mesmo: monta uma vez
            q = [0x05, a, reg]
            q.append(_crc8(q))
            self._req[(a, reg)] = q
        for _ in range(tentativas):
            self._limpa()
            self._envia(q)
            buf = self._recebe(12, 12)
            for i in range(len(buf) - 7):
                r = buf[i:i + 8]
                if r[0] == 0x05 and r[1] == 0xFF and r[2] == reg and _crc8(r[:7]) == r[7]:
                    return (r[3] << 24) | (r[4] << 16) | (r[5] << 8) | r[6]
        return None

    def escreve(self, reg, val):
        q = [0x05, self.addr, reg | 0x80,
             (val >> 24) & 0xFF, (val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF]
        q.append(_crc8(q))
        self._limpa()
        self._envia(q)
        self._recebe(8, 8)

    def procura(self):
        for a in (3, 0, 1, 2):
            v = self.le(IOIN, a, 1)
            if v is not None:
                self.addr = a
                return a, v
        self.addr = None
        return None, None


# ---------- estado ----------

en = Pin(PIN_EN, Pin.OUT, value=1)
ena = Pin(PIN_ENA, Pin.OUT, value=0)     # DM556 desabilitado até o painel pedir
dirp = None                              # DIR do driver em uso (_pinos)
vs = Pin(PIN_VS, Pin.IN)
fim = (Pin(PIN_FIM1, Pin.IN, Pin.PULL_UP), Pin(PIN_FIM2, Pin.IN, Pin.PULL_UP))
# ADC pelo Pin: pelo número do canal (ADC(3)) o MicroPython 1.29 deixa o pull-down do GPIO ligado,
# que carrega o divisor de 100k e fazia o NTC marcar ~60 °C no ar.
adc_ntc = ADC(Pin(PIN_NTC))
adc_ntc2 = ADC(Pin(PIN_NTC2)) if PIN_NTC2 is not None else None
adc_t = ADC(4)

cfg = {"run": 0.8, "hold": 0.4, "micro": 16, "modo": "stealth", "vthr": 0,
       "intpol": True, "hdelay": 8, "tpd": 20, "shaft": False}    # shaft inverte só o motor do TMC
fimcfg = {"f1": 0, "f2": 0, "inv": False,     # f: 0 só mostra, -1 bloqueia o -, 1 bloqueia o +, 2 os dois
          "k1": "tmc", "k2": "dm556",            # canal de cada fim de curso (só no modo dois)
          "r25": 100000, "beta": 3950,           # NTC1; o pull-up R3 da placa é 100k
          "r25_2": 100000, "beta2": 3950}        # NTC2 (v18); pull-up R15 de 100k
drv = {"tipo": "tmc", "inv_step": False, "inv_dir": False,
       "segura": False}    # segura: a emergência corta os pulsos mas NÃO solta o motor (Z com fuso)
tmc = None
tmc_info = {"ok": False}
# StallGuard pelo UART (o módulo não expõe o DIAG): vmin em passos/s, n = leituras baixas seguidas
sgcfg = {"on": False, "lim": 50, "vmin": 800.0, "n": 2}
sg_min = None                          # menor SG_RESULT do movimento atual/último, acima da vmin
rampa_s = False                        # True: rampa em S (cossenoidal) em vez de trapezoidal
tmc_quente = False                     # pré-aquecimento (>120 °C) visto no último DRV_STATUS
tmc_falha = False                      # superaquecimento/curto: TMC desligado até reconfigurar ou energizar
corr_reduzida = False
t_erro = None                          # ticks_ms do último erro (emergência, falha, 24 V caiu)
t_trava = None                         # ticks_ms da última parada por fim de curso ou StallGuard
ult_tmc_chk = 0
led_sm = None
led_ult = None
led_chk = 0
sg_baixos = 0
sg_ult = 0
sm = None
fim_pio = 0                            # FIM (1/2) que a PIO vigia no movimento atual; 0 = nenhum
canal = "tmc"                          # canal do gerador de passos (SM0): "tmc" ou "dm556"
pos = 0                                # posição do canal da SM0
posk = {"tmc": 0, "dm556": 0}          # posição de cada canal (a do canal da SM0 fica em pos)
tj = None                              # trajetória em andamento (Traj)
tj_mem = None                          # anéis da trajetória, alocados uma vez
robo = {}                              # dados do painel do robô, só guardados no config.json
ARQ_CFG = "config.json"
mov = None
vact = 0
eventos = []
ult_rx = 0
ult_busca = 0


def ev(msg):
    eventos.append(msg)
    if len(eventos) > 20:
        eventos.pop(0)


def _cs(i, vfs):
    return int(32 * 1.41421356 * i * (RSENSE + 0.020) / vfs - 1 + 0.5)


def aplica_cfg():
    if tmc is None or tmc.addr is None:
        tmc_info["ok"] = False
        return False
    c = cfg
    global tmc_falha, corr_reduzida
    if float(c["run"]) > IMAX_RUN:
        ev("corrente limitada a %.1f A RMS: acima disso o módulo StepStick superaquece" % IMAX_RUN)
        c["run"] = IMAX_RUN
    tmc_falha = False
    corr_reduzida = False
    run = min(max(float(c["run"]), 0.05), IMAX_RUN)
    hold = min(max(float(c["hold"]), 0.0), run)
    vsense, vfs = 1, 0.180
    cs = _cs(run, vfs)
    if cs > 31:
        vsense, vfs = 0, 0.325
        cs = _cs(run, vfs)
    cs = max(0, min(31, cs))
    ch = max(0, min(31, _cs(hold, vfs)))
    tp = 0
    if c["modo"] == "auto" and c["vthr"] > 0:
        tp = min(0xFFFFF, int(12e6 * c["micro"] / (256 * c["vthr"])))
    regs = ((GSTAT, 7),
            (GCONF, (1 << 6) | (1 << 7) | (1 << 8) | ((1 << 2) if c["modo"] == "spread" else 0)
             | ((1 << 3) if c["shaft"] else 0)),
            (CHOPCONF, 3 | (5 << 4) | (2 << 15) | (vsense << 17) | (MRES[c["micro"]] << 24)
             | ((1 if c["intpol"] else 0) << 28)),
            (IHOLD_IRUN, ch | (cs << 8) | ((int(c["hdelay"]) & 15) << 16)),
            (TPOWERDOWN, int(c["tpd"]) & 255),
            (PWMCONF, 0xC10D0024),
            (TPWMTHRS, tp),
            (TCOOLTHRS, 0xFFFFF),
            (VACTUAL, vact & 0xFFFFFF))
    a = tmc.le(IFCNT)
    for r, v in regs:
        tmc.escreve(r, v)
    b = tmc.le(IFCNT)
    ok = a is not None and b is not None and (b - a) & 0xFF == len(regs)
    k = 32 * 1.41421356 * (RSENSE + 0.020)
    tmc_info.update(ok=ok, irun=round((cs + 1) * vfs / k, 3), ihold=round((ch + 1) * vfs / k, 3),
                    vsense=vsense, cs=cs, ch=ch)
    if not ok:
        ev("TMC: escrita da configuração não confirmada (IFCNT %s -> %s)" % (a, b))
    return ok


def busca_tmc():
    global tmc
    if not vs.value():
        tmc_info["ok"] = False
        return False
    if tmc is None:
        tmc = TMC()
    a, ioin = tmc.procura()
    if a is None:
        tmc_info["ok"] = False
        return False
    tmc_info.update(addr=a, ver=ioin >> 24)
    return aplica_cfg()


def _tmc_on():
    return bool(tmc and tmc.addr is not None and tmc_info.get("ok"))


def _tmc_resumo():
    d = dict(tmc_info)
    d["on"] = _tmc_on()
    return d


# ---------- movimento ----------

PIO1 = 0x50300000
prog_ini = 0


def _sm_novo():
    global sm, prog_ini
    if sm:
        sm.active(0)
    sm = StateMachine(4, _passos, freq=FREQ, set_base=Pin(pin_step))   # init limpa as FIFOs
    _inv_step()
    sm.active(1)
    time.sleep_us(20)
    prog_ini = mem32[R_SM0_ADDR] & 0x1F      # SM0_ADDR parada no pull() = início do programa


def _inv_step():
    # o init da SM regrava o registrador do pino e zera a inversão: reaplicar depois de cada _sm_novo
    v = mem32[GPIO_DM_CTRL] & ~(3 << 8)
    mem32[GPIO_DM_CTRL] = v | ((1 << 8) if drv["inv_step"] else 0)


def _pinos():
    """STEP/DIR do canal da SM0. Na v18 cada driver tem os seus: os do outro ficam parados em
    nível baixo. Chamar com a SM parada e, se o STEP mudou, recriar a SM (_sm_novo) em seguida."""
    global dirp, pin_step
    ps, pd = PINOS[canal]
    for p in (PIN_STEP_TMC, PIN_DIR_TMC, PIN_STEP_DM, PIN_DIR_DM):
        if p != ps and p != pd:
            Pin(p, Pin.OUT, value=0)
    dirp = Pin(pd, Pin.OUT, value=0)
    pin_step = ps
    RES[4] = 1 << ps                    # para o _troca olhar o STEP certo


def _fim_pio(d):
    """aponta o jmp pin da SM para o fim de curso que bloqueia o sentido d e reescreve o teste.
    Só com a SM parada no pull (entre movimentos). Se os dois bloqueiam o mesmo sentido, a PIO
    vigia o primeiro e o segundo fica só na varredura do _vigia."""
    global fim_pio
    o = prog_ini
    a, b, fim_pio = J_D1 | (o + I_SEGUE), o + I_TRAVA, 0
    for i, k in ((0, "f1"), (1, "f2")):
        if fimcfg[k] and (fimcfg[k] == d or fimcfg[k] == 2) and _fim_meu(i, canal):
            if fimcfg["inv"]:                   # acionado = nível alto
                a, b = J_PIN | (o + I_TRAVA), o + I_SEGUE
            else:                               # acionado = nível baixo (chave para o GND)
                a, b = J_D1 | J_PIN | (o + I_SEGUE), o + I_TRAVA
            v = mem32[R_SM0_EXECCTRL] & ~(0x1F << 24)
            mem32[R_SM0_EXECCTRL] = v | ((PIN_FIM1, PIN_FIM2)[i] << 24)
            fim_pio = i + 1
            break
    mem32[R_PIO1_INSTR + 4 * (o + I_FIM)] = a
    mem32[R_PIO1_INSTR + 4 * (o + I_FIM + 1)] = b


RES = array.array("I", [0, 0, 0, 0, 1 << PIN_STEP_TMC])   # _troca devolve: READ_ADDR do DMA, nível da
pin_step = PIN_STEP_TMC                                    # TX FIFO, X e PC da SM; [4] = máscara do STEP


@micropython.viper
def _troca(addr: uint, n: uint, ini: uint, res: ptr32):
    """corta os passos e, se n > 0, já dispara o próximo perfil. Nativo: poucos us sem pulso
    (em Python levava 100-400 us, o bastante para o motor perder passo em alta rotação)."""
    pio = ptr32(uint(0x50300000))
    pset = ptr32(uint(0x50302000))
    pclr = ptr32(uint(0x50303000))
    pxor = ptr32(uint(0x50301000))
    dma = ptr32(uint(0x500002C0))         # canal 11
    abort = ptr32(uint(0x50000444))
    # corta com o STEP baixo: no meio do pulso sobraria um pulso curto que o DM556 (>= 2,5 us)
    # pode não ver, e a posição contada ficaria 1 passo à frente. Espera no máximo ~30 ms
    # (meio período a 20 passos/s); se o pulso subir entre o teste e o desligar, deixa terminar.
    k = 4000000
    msk = res[4]                          # bit do pino STEP em uso
    while True:
        while (pio[15] & msk) and k > 0:  # DBG_PADOUT: saída da PIO1 no STEP, antes da inversão
            k -= 1
        pclr[0] = 1                       # CTRL: desliga a SM0
        if k <= 0 or (pio[15] & msk) == 0:
            break
        pset[0] = 1
    dma[4] = 0                            # AL1_CTRL: desliga o canal
    abort[0] = 1 << 11
    while abort[0] & (1 << 11):
        pass
    res[0] = dma[0]                       # até onde o DMA leu
    res[1] = pio[3] & 15                  # FLEVEL: palavras ainda na TX FIFO da SM0
    pio[54] = 0xA0C1                      # mov(isr, x): passos que faltavam no segmento atual
    pio[54] = 0x8000                      # push(noblock)
    res[2] = pio[8]                       # RXF0
    res[3] = pio[53] & 31                 # SM0_ADDR: onde a SM parou
    pio[12] = 1                           # IRQ: limpa o flag 0 (parada por fim de curso)
    fj = uint(0x40000000)
    pxor[52] = fj                         # SM0_SHIFTCTRL: FJOIN_RX ida e volta esvazia as FIFOs
    pxor[52] = fj
    pset[0] = 16                          # SM0_RESTART
    pio[54] = 0xE000                      # SM0_INSTR: set(pins, 0)
    pio[54] = ini                         # SM0_INSTR: jmp para o início do programa
    if n:
        dma[0] = addr
        dma[1] = uint(0x50300010)         # TXF0 da PIO1
        dma[2] = n
        dma[3] = 284697                   # EN | 32 bits | INCR_READ | CHAIN_TO=11 | DREQ PIO1 TX0
    pset[0] = 1                           # liga a SM0


def _dma(addr, n):
    mem32[R_DMA_AL1] = 0                     # desliga sem disparar
    mem32[R_DMA_READ] = addr
    mem32[R_DMA_WRITE] = PIO1_TXF0
    mem32[R_DMA_COUNT] = n
    mem32[R_DMA_TRIG] = V_DMA_CTRL


def _dma_ocupado():
    return (mem32[R_DMA_TRIG] >> 24) & 1


class Perfil:
    def __init__(self, cc, vv, dirn, tipo, a, n_env=None, idesc=0):
        """cc/vv: passos e velocidade (passos/s) de cada segmento, já com a desaceleração.
        Só os n_env primeiros vão para o DMA (no jog a desaceleração fica guardada para o Parar);
        idesc = onde a desaceleração começa. Tudo pré-alocado: nada de lista crescendo no meio
        dos temporários (fragmentava a memória do MicroPython)."""
        m = len(cc)
        buf = array.array("I", range(2 * m))
        ts, ss, pp = [0] * m, [0] * m, [0] * m
        t = s = 0
        for j in range(m):
            c = cc[j]
            d = max(0, int((FREQ / vv[j] - 9) / 2 + 0.5))
            q = 2 * d + 9
            buf[2 * j] = c - 1
            buf[2 * j + 1] = d
            t += 3
            ts[j] = t
            ss[j] = s
            pp[j] = q
            t += c * q
            s += c
        self.buf, self.ts, self.ss, self.pp, self.cc = buf, ts, ss, pp, cc
        self.Tt, self.St = t, s               # totais em ciclos e passos
        self.dir, self.tipo, self.a = dirn, tipo, a
        self.idesc = idesc
        self._janela(0, m if n_env is None else n_env)

    def _janela(self, j0, j1):
        """o DMA manda os segmentos j0..j1-1; tempo e passos contam a partir de j0"""
        n = len(self.ts)
        self.j0, self.j1 = j0, j1
        self.t0 = self.ts[j0] - 3 if j0 < n else self.Tt
        self.s0 = self.ss[j0] if j0 < n else self.St
        tf = self.ts[j1] - 3 if j1 < n else self.Tt
        sf = self.ss[j1] if j1 < n else self.St
        self.T, self.S = tf - self.t0, sf - self.s0
        self.Tus = self.T // CPU + 1
        self.j = j0
        self.el = 0
        self.base = 0
        self.last = 0

    def endereco(self):
        self.addr0 = uctypes.addressof(self.buf) + 8 * self.j0
        return self.addr0, 2 * (self.j1 - self.j0)

    def passos_feitos(self, w, x, pc):
        """passos exatos a partir de w palavras puxadas pela SM, do X e do PC no corte"""
        m = w // 2
        if m <= 0:
            return 0
        jc = self.j0 + m - 1
        c = self.cc[jc]
        feitos = self.ss[jc] - self.s0
        if w & 1 or x >= c:                  # segmento terminado (x vira 0xFFFFFFFF no último jmp)
            return feitos + c
        # parada antes do set(pins, 1): o jmp x_dec já descontou um passo que não saiu
        return feitos + c - x - (1 if pc == prog_ini + I_PASSO else 0)

    def estado(self, t):
        """(passos já dados, velocidade atual em passos/s) no tempo t (us desde o início)"""
        t *= CPU
        if t >= self.T:
            return self.S, 0.0
        t += self.t0
        ts = self.ts
        j = self.j
        while j + 1 < self.j1 and ts[j + 1] <= t:
            j += 1
        self.j = j
        if t < ts[j]:
            return self.ss[j] - self.s0, 0.0
        k = (t - ts[j]) // self.pp[j] + 1
        return self.ss[j] - self.s0 + min(k, self.cc[j]), FREQ / self.pp[j]

    def desacel(self, v):
        """o mesmo perfil a partir do 1º segmento da desaceleração com velocidade <= v (já montado)"""
        lo, hi = max(self.idesc, self.j), len(self.pp)
        if v <= 0 or lo >= hi:
            return None
        alvo = FREQ / v
        while lo < hi:                        # na desaceleração o período só cresce
            m = (lo + hi) // 2
            if self.pp[m] >= alvo:
                hi = m
            else:
                lo = m + 1
        if lo >= len(self.pp):
            return None
        q = Perfil(VAZIO_I, VAZIO_F, self.dir, "parando", self.a)
        q.buf, q.ts, q.ss, q.pp, q.cc = self.buf, self.ts, self.ss, self.pp, self.cc
        q.Tt, q.St, q.idesc = self.Tt, self.St, lo
        q._janela(lo, len(self.pp))
        return q


VAZIO_I = array.array("I")
VAZIO_F = array.array("f")


def _sobe_s(v1, a):
    """rampa em S (cossenoidal): v(t) = v1/2·(1 - cos(pi·t/T)), T = pi·v1/(2a). A aceleração vai de 0
    ao pico a e volta a 0 (sem tranco); dura 57% mais que a trapezoidal com o mesmo pico.
    Blocos com número inteiro de passos e o tempo exato de cada um (inverte a posição por Newton),
    para a velocidade não serrilhar por arredondamento. Devolve (passos, velocidades, total)."""
    cc, vv = array.array("I"), array.array("f")
    T = math.pi * v1 / (2 * a)
    n = int(v1 * T / 2)
    if n <= 0:
        return cc, vv, 0
    k = math.pi / T
    h = v1 / 2
    dt = max(0.002, T / 300)
    tol = max(1e-3, n * 2e-7)             # float32: a posição só tem ~7 dígitos
    i = 0
    t0 = 0.0
    while i < n:
        vel = h * (1 - math.cos(k * t0))
        c = min(n - i, max(1, int(max(vel, a * dt) * dt)))
        alvo = i + c
        lo, hi = t0, T
        t1 = min(T, t0 + (c / vel if vel > 1 else dt))
        for _ in range(30):
            f = h * (t1 - math.sin(k * t1) / k) - alvo
            if -tol < f < tol:
                break
            if f > 0:
                hi = t1
            else:
                lo = t1
            d = h * (1 - math.cos(k * t1))
            tn = t1 - f / d if d > 1e-9 else lo
            t1 = tn if lo < tn < hi else (lo + hi) / 2
        cc.append(c)
        vv.append(max(20.0, c / (t1 - t0)) if t1 > t0 else 20.0)
        i = alvo
        t0 = t1
    return cc, vv, n


def _sobe(v1, a):
    """segmentos de ~0 até v1 (passos/s) com aceleração a (passos/s²; pico, na rampa em S)"""
    if rampa_s:
        return _sobe_s(v1, a)
    # blocos de duração ~igual (dt): o salto de velocidade entre blocos fica a*dt do começo ao fim
    cc, vv = array.array("I"), array.array("f")
    n = int(v1 * v1 / (2 * a))
    dt = max(0.002, v1 / a / 300)
    i = 0
    while i < n:
        v0 = max(math.sqrt(2 * a * i), a * dt)
        c = min(max(1, int(v0 * dt)), n - i)
        cc.append(c)
        vv.append(max(20.0, math.sqrt(2 * a * (i + c / 2))))
        i += c
    return cc, vv, n


def _espelha(cc, vv, k):
    """acrescenta a desaceleração: os k primeiros segmentos (a subida) ao contrário"""
    for i in range(k - 1, -1, -1):
        cc.append(cc[i])
        vv.append(vv[i])


def _segs_mover(n, v, a):
    """(passos, velocidades, índice onde começa a desaceleração)"""
    cc, vv, r = _sobe(v, a)
    vc = v
    if 2 * r > n:                          # não dá tempo de chegar em v: pico menor
        cc = vv = None
        gc.collect()
        cc, vv, r = _sobe(math.sqrt(2 * a * n / math.pi) if rampa_s else math.sqrt(a * n), a)
        vc = vv[-1] if len(vv) else max(20.0, math.sqrt(a))
    k = len(cc)
    if n > 2 * r:
        cc.append(n - 2 * r)
        vv.append(vc)
    idesc = len(cc)
    _espelha(cc, vv, k)
    return cc, vv, idesc


def _tick():
    if mov:
        n = time.ticks_us()
        mov.el += time.ticks_diff(n, mov.last)
        mov.last = n


def _agora():
    if mov is None:
        return pos, 0.0
    _tick()
    s, v = mov.estado(mov.el)
    return mov.base + mov.dir * s, mov.dir * v


def _usa_tmc():
    return drv["tipo"] in ("tmc", "ambos", "dois")


def _usa_dm():
    return drv["tipo"] in ("dm556", "ambos", "dois")


def _canal_de(tipo):
    return "dm556" if tipo == "dm556" else "tmc"


def _troca_canal(k):
    """modo dois: passa a SM0 (jog/mover/ir) para o canal k, guardando a posição do outro"""
    global canal, pos
    if k == canal:
        return
    _livre()
    posk[canal] = pos
    canal = k
    pos = posk[k]
    _pinos()
    _sm_novo()


def _usa_k(m):
    """canal pedido pelo comando ("k"): no modo dois troca a SM0 para ele; nos outros, tem que ser o ativo"""
    k = m.get("k")
    if k is None or k == canal:
        return
    if k not in CANAIS:
        raise ValueError("canal inválido: %s" % k)
    if drv["tipo"] == "dois":
        _troca_canal(k)
    elif drv["tipo"] != "ambos":
        raise ValueError("canal %s desligado no modo %s" % (k, drv["tipo"]))


def _pos_k():
    """posição de cada canal agora"""
    if tj:
        return tj.posicoes()
    d = dict(posk)
    d[canal] = _agora()[0]
    return d


def _energizado():
    return (not _usa_tmc() or en.value() == 0) and (not _usa_dm() or ena.value() == 1)


def _energiza(v):
    en.value(0 if v and _usa_tmc() else 1)
    ena.value(1 if v and _usa_dm() else 0)
    if v:
        # stealthChop calibra com o motor parado e energizado; o DM556 pede um tempo entre ENA e pulso
        time.sleep_ms(150 if _usa_tmc() else 50)


def _dispara(p):
    global mov
    if not _energizado():
        _energiza(True)
    nd = (1 if p.dir > 0 else 0) ^ (1 if drv["inv_dir"] else 0)
    if dirp.value() != nd:
        dirp.value(nd)
        time.sleep_us(30)              # DM556 pede DIR estável >= 5 us antes do pulso
    _fim_pio(p.dir)
    p.base = pos
    mov = p
    if p.tipo != "parando":
        _zera_sg()
    _dma(*p.endereco())
    p.last = time.ticks_us()           # depois do disparo: o _dma leva ~0,2 ms (endereços long)


def _zera_sg():
    global sg_min, sg_baixos
    sg_min = None
    sg_baixos = 0


def abortar(msg=None, q=None):
    """para na hora; com q (perfil já montado, mesmo sentido) emenda direto nele sem buraco"""
    global mov, pos
    if mov is None:
        return 0.0, 0, 0
    a, n = q.endereco() if q else (0, 0)
    _troca(a, n, prog_ini, RES)
    t = time.ticks_us()
    _tick()
    _, v = mov.estado(mov.el)
    s = mov.passos_feitos((RES[0] - mov.addr0) // 4 - RES[1], RES[2], RES[3])
    pos = mov.base + mov.dir * s
    r = (v, mov.dir, mov.a)
    mov = None
    if q:
        q.base = pos
        q.last = t
        mov = q
    if msg:
        ev(msg)
    return r


def parar():
    # a desaceleração já está montada no perfil: só troca o DMA para ela (sem buraco nos pulsos)
    if mov is None or mov.tipo == "parando":
        return
    _tick()
    _, v = mov.estado(mov.el)
    abortar(q=mov.desacel(v))


def _fim(i):
    v = fim[i].value()
    return v == 1 if fimcfg["inv"] else v == 0


def _fim_meu(i, k):
    """o FIM i (0/1) vale para o canal k? Só no modo dois cada chave tem dono"""
    return drv["tipo"] != "dois" or fimcfg[("k1", "k2")[i]] == k


def _fim_bloqueia(d):
    for i, k in ((0, "f1"), (1, "f2")):
        if fimcfg[k] and (fimcfg[k] == d or fimcfg[k] == 2) and _fim_meu(i, canal) and _fim(i):
            return i + 1
    return 0


def _vigia():
    global mov, pos
    if mov is None:
        return
    global t_erro, t_trava
    if mem32[R_PIO1_IRQ] & 1:                          # a PIO parou no fim de curso
        t_trava = time.ticks_ms()
        abortar("FIM%d acionado: parada no passo (PIO)" % fim_pio)
        return
    _tick()
    if mov.el >= mov.Tus:
        # o tempo é estimado: só termina com a SM de volta ao 1º pull, senão uma troca de DIR
        # logo em seguida pegaria os últimos passos ainda saindo
        if _dma_ocupado() or sm.tx_fifo() or (mem32[R_SM0_ADDR] & 0x1F) != prog_ini:
            return
        pos = mov.base + mov.dir * mov.S
        mov = None
        return
    if _usa_tmc() and not vs.value():                 # o DM556 tem fonte própria
        t_erro = time.ticks_ms()
        abortar("24 V caiu durante o movimento: parada imediata")
        return
    f = _fim_bloqueia(mov.dir)
    if f:
        t_trava = time.ticks_ms()
        abortar("FIM%d acionado: parada imediata" % f)
        return
    if _vigia_sg():
        return
    if mov.tipo == "jog" and time.ticks_diff(time.ticks_ms(), ult_rx) > WDT_JOG:
        ev("jog parado: painel sem comunicação")
        parar()


def _vigia_sg():
    """lê o SG_RESULT a cada ~2 ms durante o movimento; True se parou por travamento"""
    global sg_min, sg_baixos, sg_ult, t_trava
    if not (_usa_tmc() and canal == "tmc" and tmc and tmc.addr is not None) or cfg["modo"] == "spread":
        return False
    agora = time.ticks_us()
    if time.ticks_diff(agora, sg_ult) < 2000:
        return False
    sg_ult = agora
    _, v = mov.estado(mov.el)
    # o StallGuard4 só mede em stealthChop: no automático, só abaixo da velocidade de troca
    if v < sgcfg["vmin"] or (cfg["modo"] == "auto" and cfg["vthr"] > 0 and v > cfg["vthr"]):
        sg_baixos = 0
        return False
    sg = tmc.le(SG_RESULT, None, 1)
    if sg is None:
        return False
    if sg_min is None or sg < sg_min:
        sg_min = sg
    if sgcfg["on"] and sg < sgcfg["lim"]:
        sg_baixos += 1
        if sg_baixos >= sgcfg["n"]:
            t_trava = time.ticks_ms()
            abortar("travamento detectado pelo StallGuard (SG = %d, %.0f passos/s)" % (sg, v))
            return True
    else:
        sg_baixos = 0
    return False


# ---------- trajetória (dois canais sincronizados) ----------

R_DMA_ABORT = 0x50000444
R_PIO1_CTRL_SET = 0x50302000
R_PIO1_FLEVEL = 0x5030000C
TJ_RING = 11                              # log2 do anel em bytes (4 * TJ_N = 2048), para o RING_SIZE do DMA
tj_ult = None                             # resultado da última trajetória: {"tid", "ok", "msg"}


@micropython.viper
def _tj_corta_v(pinos: int, sms: int):
    """desliga as SMs da trajetória com os STEP baixos (sem pulso pela metade); espera no máximo ~30 ms"""
    pio = ptr32(uint(0x50300000))
    pset = ptr32(uint(0x50302000))
    pclr = ptr32(uint(0x50303000))
    k = 4000000
    while True:
        while (pio[15] & pinos) and k > 0:    # DBG_PADOUT
            k -= 1
        pclr[0] = sms                         # CTRL: desliga as SMs juntas
        if k <= 0 or (pio[15] & pinos) == 0:
            break
        pset[0] = sms                         # um pulso subiu entre o teste e o desligar: deixa terminar


def _tj_mem():
    """anéis alinhados ao próprio tamanho (o DMA dá a volta pelos bits baixos do endereço)"""
    global tj_mem
    if tj_mem is None:
        gc.collect()
        nb = 4 * TJ_N
        m = []
        for _ in TJ_SM:
            bruto = bytearray(2 * nb)
            a = (uctypes.addressof(bruto) + nb - 1) & ~(nb - 1)
            anel = uctypes.struct(a, {"w": (uctypes.ARRAY | 0, uctypes.UINT32 | TJ_N)}).w
            m.append((bruto, a, anel, array.array("i", range(TJ_N))))
        tj_mem = m
    return tj_mem


class _Canal:
    """um canal da trajetória: SM (PIO1 SM1/SM2), DMA em anel e posição depois de cada palavra"""

    def __init__(self, k, i, mem):
        self.k = k
        _, self.addr, self.anel, self.pr = mem
        self.i = i + 1                                    # número da SM dentro da PIO1
        self.ch = TJ_DMA[i]
        d = 0x50000000 + self.ch * 0x40
        self.r_read, self.r_write, self.r_tc, self.r_trig, self.r_al1 = d, d + 4, d + 8, d + 0xC, d + 0x10
        self.r_txf = 0x50300010 + 4 * self.i
        self.v_ctrl = (1 | (2 << 2) | (1 << 4) | (TJ_RING << 6) | (self.ch << 11)
                       | ((DREQ_PIO1_TX0 + self.i) << 15))
        self.r_addr = 0x503000D4 + 0x18 * self.i          # SMn_ADDR
        ps, pd = PINOS[k]
        self.step = ps
        self.sm = StateMachine(TJ_SM[i], _traj, freq=FREQ, set_base=Pin(ps), out_base=Pin(pd))
        self.ini = mem32[self.r_addr] & 0x1F              # SM parada no pull = início do programa
        self.p0 = posk[k]
        self.anel[0] = 0                                  # começa no sentinela
        mem32[self.r_al1] = 0
        mem32[self.r_read] = self.addr
        mem32[self.r_write] = self.r_txf
        mem32[self.r_tc] = TJ_TC

    def lidas(self):
        """palavras que o DMA já passou para a FIFO"""
        return TJ_TC - mem32[self.r_tc]

    def fifo(self):
        return (mem32[R_PIO1_FLEVEL] >> (8 * self.i)) & 15

    def feitas(self):
        """palavras terminadas (com a SM rodando: estimativa)"""
        return max(0, self.lidas() - self.fifo() - 1)

    def pos_est(self):
        n = self.feitas()
        return self.pr[(n - 1) & (TJ_N - 1)] if n else self.p0

    def pos_corte(self, inv, lidas):
        """posição exata com a SM parada; lidas = contagem do DMA tirada ANTES do abort (o abort zera o
        TRANS_COUNT no RP2040)"""
        fl = self.fifo()
        pc = (mem32[self.r_addr] & 0x1F) - self.ini
        n_ok = lidas - fl - (0 if pc == 0 else 1)         # no pull: a palavra atual nem saiu da FIFO
        parc = 0
        if T_PASSO <= pc < T_PARA:
            w = self.anel[n_ok & (TJ_N - 1)]
            self.sm.exec("mov(isr, x)")
            self.sm.exec("push(noblock)")
            parc = (w >> 21) - self.sm.get() - (1 if pc < T_ALTO else 0)
            if not ((w ^ inv) >> 20) & 1:              # DIR lógico (sem a inversão do inv_dir)
                parc = -parc
        p = self.pr[(n_ok - 1) & (TJ_N - 1)] if n_ok > 0 else self.p0
        return p + parc


class Traj:
    def __init__(self, ks, ident):
        mem = _tj_mem()
        self.cs = [_Canal(k, i, mem[i]) for i, k in enumerate(ks)]
        self.id = ident
        self.esc = 0              # palavras escritas: a próxima entra no lugar do sentinela
        self.fim = False          # o painel já mandou a última palavra
        self.on = False
        self.inv = (1 << 20) if drv["inv_dir"] else 0
        self.t_meio = None
        self.pinos = self.sms = 0
        for c in self.cs:
            self.pinos |= 1 << c.step
            self.sms |= 1 << c.i
        self.tmc = any(c.k == "tmc" for c in self.cs) and _usa_tmc()

    def livre(self):
        lidas = min(c.lidas() for c in self.cs) if self.on else 0
        return max(0, TJ_N - TJ_MARGEM - 1 - (self.esc - lidas))

    def resumo(self):
        f = min(c.feitas() for c in self.cs) if self.on else 0
        return {"tid": self.id, "on": self.on, "feitas": min(f, self.esc), "esc": self.esc,
                "livre": self.livre(), "fim": self.fim}

    def posicoes(self):
        d = dict(posk)
        for c in self.cs:
            d[c.k] = c.pos_est() if self.on else c.p0
        return d

    def acrescenta(self, ws):
        """ws: bytes de cada canal, palavras de 32 bits little-endian, o mesmo número em todos"""
        if self.fim:
            raise ValueError("trajetória já recebeu o fim")
        if len(ws) != len(self.cs):
            raise ValueError("trajetória com %d canais" % len(self.cs))
        m = len(ws[0]) // 4
        if any(len(b) != 4 * m for b in ws):
            raise ValueError("trajetória: canais com número de palavras diferente")
        if m == 0:
            return
        if m > self.livre():
            raise ValueError("trajetória: anel cheio (%d livres)" % self.livre())
        vals = [struct.unpack("<%dI" % m, b) for b in ws]
        for a in vals:            # confere tudo antes de escrever: um erro no meio não estraga o anel
            for w in a:
                d = w & 0xFFFFF
                if (w >> 21 and d < TJ_DMIN) or d == 0:
                    raise ValueError("trajetória: palavra inválida 0x%08X (passo rápido demais?)" % w)
        e0, N1, inv = self.esc, TJ_N - 1, self.inv
        for c, a in zip(self.cs, vals):
            anel, pr = c.anel, c.pr
            p = pr[(e0 - 1) & N1] if e0 else c.p0
            anel[(e0 + m) & N1] = 0                       # o sentinela novo antes de tirar o velho
            for j in range(m):
                w = a[j]
                n = w >> 21
                if n:
                    p += n if w & 0x100000 else -n
                pr[(e0 + j) & N1] = p
                if j:
                    anel[(e0 + j) & N1] = w ^ inv
        for c, a in zip(self.cs, vals):                   # por último, e juntos, os sentinelas velhos
            c.anel[e0 & N1] = a[0] ^ inv
        self.esc = e0 + m

    def acionado(self):
        """fim de curso configurado (f1/f2 != 0) acionado num canal desta trajetória"""
        ks = [c.k for c in self.cs]
        for i, f in ((0, "f1"), (1, "f2")):
            if fimcfg[f] and _fim(i) and (drv["tipo"] != "dois" or fimcfg[("k1", "k2")[i]] in ks):
                return i + 1
        return 0

    def comeca(self):
        if self.on:
            return
        if not self.esc:
            raise ValueError("trajetória vazia")
        f = self.acionado()
        if f:
            raise ValueError("FIM%d acionado: trajetória não começa" % f)
        if self.tmc and not vs.value():
            raise ValueError("sem 24 V")
        if not _energizado():
            _energiza(True)
        mem32[R_PIO1_IRQ] = 6                             # limpa os irq 1 e 2 (sentinelas)
        for c in self.cs:
            mem32[c.r_trig] = c.v_ctrl                    # o DMA enche as FIFOs
        time.sleep_us(20)
        mem32[R_PIO1_CTRL_SET] = self.sms | (self.sms << 8)   # liga as SMs e zera os divisores no mesmo ciclo
        self.on = True

    def vigia(self):
        global t_trava, t_erro
        if not self.on:
            return
        irq = mem32[R_PIO1_IRQ]
        paradas = 0
        for c in self.cs:
            if irq & (1 << c.i):
                paradas += 1
        if paradas:
            if paradas == len(self.cs):
                if self.fim and min(c.feitas() for c in self.cs) >= self.esc:
                    self.corta(None, True)
                else:
                    t_erro = time.ticks_ms()
                    self.corta("trajetória: faltaram dados (USB atrasou), parada no fim do que chegou")
            elif not self.fim:
                t_erro = time.ticks_ms()
                self.corta("trajetória: faltaram dados (USB atrasou), parada no fim do que chegou")
            elif self.t_meio is None:
                self.t_meio = time.ticks_ms()
            elif time.ticks_diff(time.ticks_ms(), self.t_meio) > 100:
                t_erro = time.ticks_ms()
                self.corta("trajetória: canais terminaram fora de sincronia")
            return
        f = self.acionado()
        if f:
            t_trava = time.ticks_ms()
            self.corta("FIM%d acionado: trajetória cortada" % f)
        elif self.tmc and not vs.value():
            t_erro = time.ticks_ms()
            self.corta("24 V caiu durante a trajetória: parada imediata")

    def corta(self, msg=None, ok=False):
        """para (ou termina) a trajetória, acerta as posições e devolve o STEP à SM0"""
        global tj, pos, tj_ult
        if self.on:
            _tj_corta_v(self.pinos, self.sms)
        # SMs paradas: a FIFO enche e o DMA fica esperando, a contagem não muda mais. Lê antes do abort.
        lidas = [c.lidas() for c in self.cs] if self.on else None
        m = 0
        for c in self.cs:
            mem32[c.r_al1] = 0
            m |= 1 << c.ch
        mem32[R_DMA_ABORT] = m
        while mem32[R_DMA_ABORT] & m:
            pass
        for j, c in enumerate(self.cs):
            posk[c.k] = c.pos_corte(self.inv, lidas[j]) if self.on else c.p0
            c.sm.active(0)
        mem32[R_PIO1_IRQ] = 6
        tj = None
        pos = posk[canal]
        _pinos()
        _sm_novo()
        if msg:
            ev(msg)
        tj_ult = {"tid": self.id, "ok": ok, "msg": msg or ""}


def _tj_solta():
    """sem contar posição: SMs e DMA da trajetória desligados (saída do firmware, erro no corte)"""
    global tj
    if tj is None:
        return
    _tj_corta_v(tj.pinos, tj.sms)
    m = 0
    for c in tj.cs:
        mem32[c.r_al1] = 0
        m |= 1 << c.ch
    mem32[R_DMA_ABORT] = m
    tj = None


def _carrega_cfg():
    """config.json -> drv/cfg/fimcfg/sgcfg/robo, antes de montar os pinos; valores ruins ficam no padrão"""
    global robo, rampa_s, canal
    try:
        with open(ARQ_CFG) as f:
            d = json.load(f)
    except OSError:
        return
    except ValueError:
        ev("config.json ilegível: configuração padrão")
        return
    try:
        for alvo, k in ((cfg, "cfg"), (fimcfg, "fimcfg"), (sgcfg, "sgcfg")):
            for c, v in d.get(k, {}).items():
                if c not in alvo:
                    continue
                num = (int, float)
                if type(v) == type(alvo[c]) or (type(alvo[c]) in num and type(v) in num):
                    alvo[c] = v
        if cfg["micro"] not in MRES or cfg["modo"] not in ("stealth", "spread", "auto"):
            cfg["micro"], cfg["modo"] = 16, "stealth"
        cfg["run"] = min(float(cfg["run"]), IMAX_RUN)
        for k in ("k1", "k2"):
            if fimcfg[k] not in CANAIS:
                fimcfg[k] = "tmc"
        dv = d.get("drv", {})
        tipo = dv.get("tipo", "tmc")
        if tipo in ("tmc", "dm556") or (tipo == "dois" and not COMUM) or (tipo == "ambos" and COMUM):
            drv["tipo"] = tipo
            canal = _canal_de(tipo)
        for k in ("inv_step", "inv_dir", "segura"):
            if k in dv:
                drv[k] = bool(dv[k])
        rampa_s = bool(d.get("rampa_s", False))
        robo = d.get("robo") or {}
    except Exception as e:
        ev("config.json: %s" % e)


def c_salva(m):
    """grava a configuração atual (e o bloco "robo", se vier) no config.json; "apaga": volta ao padrão"""
    global robo
    _livre()                            # gravar o flash para o Python por alguns ms
    if m.get("apaga"):
        try:
            os.remove(ARQ_CFG)
        except OSError:
            pass
        robo = {}
        return {"salvo": False}
    if "robo" in m:
        robo = m["robo"] or {}
    s = json.dumps({"v": 1, "drv": drv, "cfg": cfg, "fimcfg": fimcfg, "sgcfg": sgcfg, "rampa_s": rampa_s,
                    "robo": robo})
    with open(ARQ_CFG + ".tmp", "w") as f:
        f.write(s)
    try:
        os.remove(ARQ_CFG)
    except OSError:
        pass
    os.rename(ARQ_CFG + ".tmp", ARQ_CFG)
    return {"salvo": True, "bytes": len(s)}


def _tem_cfg():
    try:
        os.stat(ARQ_CFG)
        return True
    except OSError:
        return False


def c_tjini(m):
    """prepara uma trajetória nos canais k (ordem dos dados no tj), tid = número dado pelo painel; não mexe no motor"""
    global tj
    if tj and not tj.on:
        tj.corta()                         # a anterior nem começou: descarta
    _livre()
    if vact:
        raise ValueError("pare o giro por UART (VACTUAL) antes")
    ks = m.get("k") or [canal]
    if not 1 <= len(ks) <= 2 or len(set(ks)) != len(ks) or any(k not in CANAIS for k in ks):
        raise ValueError("canais inválidos: %s" % ks)
    if drv["tipo"] != "dois":
        if len(ks) != 1:
            raise ValueError("dois canais ao mesmo tempo só no modo dois (v18)")
        if ks[0] != canal and drv["tipo"] != "ambos":
            raise ValueError("canal %s desligado no modo %s" % (ks[0], drv["tipo"]))
        ks = [canal]
    posk[canal] = pos
    sm.active(0)                           # SM0 ociosa no pull: a trajetória assume os pinos
    try:
        tj = Traj(ks, m.get("tid"))
        _inv_step()
    except Exception:
        tj = None
        _pinos()
        _sm_novo()
        raise
    return tj.resumo()


def c_tj(m):
    """acrescenta palavras ("w": base64 por canal), "fim": última remessa, "go": começa"""
    if tj is None:
        raise ValueError("sem trajetória (tjini)")
    ws = m.get("w")
    if ws:
        tj.acrescenta([binascii.a2b_base64(b) for b in ws])
    if m.get("fim"):
        tj.fim = True
    if m.get("go"):
        tj.comeca()
    return tj.resumo()


# ---------- sensores ----------

def _ntc(adc=adc_ntc, r25="r25", beta="beta"):
    r = adc.read_u16()
    if r > 64000 or r < 300:
        return None, r
    R = 100000 * r / (65535 - r)
    return round(1 / (1 / 298.15 + math.log(R / fimcfg[r25]) / fimcfg[beta]) - 273.15, 1), r


def _trp():
    return round(27 - (adc_t.read_u16() * 3.3 / 65535 - 0.706) / 0.001721, 1)


# ---------- comandos ----------

def _livre():
    if mov:
        raise ValueError("motor em movimento")
    if tj:
        raise ValueError("trajetória em andamento")


def c_info(m):
    return {"fw": FW, "placa": REV, "ambos": COMUM, "cfg": cfg, "fimcfg": fimcfg, "drv": drv, "sgcfg": sgcfg, "tmc": _tmc_resumo(),
            "tem_ntc2": adc_ntc2 is not None, "pos": pos, "vmax": VMAX, "rampa_s": rampa_s, "imax": IMAX_RUN,
            "uid": UID, "boot": BOOT, "robo": robo, "salvo": _tem_cfg(), "dois": not COMUM, "k": canal, "pk": _pos_k(), "tjn": TJ_N, "tjmin": TJ_DMIN, "freq": FREQ}


def c_rampa(m):
    global rampa_s
    _livre()
    rampa_s = bool(m.get("s"))
    return {"s": rampa_s}


def c_sgzera(m):
    _zera_sg()
    return {}


def c_irun(m):
    """muda só a corrente de rodar, com o motor girando (teste de margem); não mexe no cfg"""
    if not (tmc and tmc.addr is not None and tmc_info.get("ok")):
        raise ValueError("TMC sem UART")
    vfs = 0.180 if tmc_info["vsense"] else 0.325
    cs = max(0, min(31, _cs(min(float(m["run"]), IMAX_RUN), vfs)))
    ch = min(tmc_info["ch"], cs)
    tmc.escreve(IHOLD_IRUN, ch | (cs << 8) | ((int(cfg["hdelay"]) & 15) << 16))
    k = 32 * 1.41421356 * (RSENSE + 0.020)
    return {"irun": round((cs + 1) * vfs / k, 3), "cs": cs}


def c_sg(m):
    if "on" in m:
        sgcfg["on"] = bool(m["on"])
    if "lim" in m:
        sgcfg["lim"] = max(0, min(510, int(m["lim"])))
    if "vmin" in m:
        sgcfg["vmin"] = max(1.0, float(m["vmin"]))
    if "n" in m:
        sgcfg["n"] = max(1, min(20, int(m["n"])))
    return {"sgcfg": sgcfg}


def c_drv(m):
    global pos, vact, canal
    _livre()
    tipo = m.get("tipo", drv["tipo"])
    if tipo not in ("tmc", "dm556", "ambos", "dois"):
        raise ValueError("driver inválido")
    if tipo == "ambos" and not COMUM:
        raise ValueError("modo Ambos só nas placas até a v17 (STEP/DIR compartilhados)")
    if tipo == "dois" and COMUM:
        raise ValueError("modo Dois só na v18 (STEP/DIR separados para cada driver)")
    velho_k = canal
    if tipo != drv["tipo"]:
        pos = posk["tmc"] = posk["dm556"] = 0
        if tipo != "dois":
            canal = _canal_de(tipo)
    if tipo not in ("tmc", "dois"):
        if vact and tmc and tmc.addr is not None:
            tmc.escreve(VACTUAL, 0)
        vact = 0
    if tipo != drv["tipo"]:
        en.value(1)                    # troca de driver: os dois soltos até o próximo movimento
        ena.value(0)
    drv["tipo"] = tipo
    for k in ("inv_step", "inv_dir", "segura"):
        if k in m:
            drv[k] = bool(m[k])
    if canal != velho_k and not COMUM:
        _pinos()
        _sm_novo()                     # o STEP mudou de pino (também reaplica a inversão)
    else:
        _inv_step()
    return {"drv": drv, "pos": pos, "k": canal, "pk": _pos_k()}


def c_cfg(m):
    global pos
    _livre()
    velho = cfg["micro"]
    novo = dict(cfg)
    for k in cfg:
        if k in m:
            novo[k] = m[k]
    novo["micro"] = int(novo["micro"])
    if novo["micro"] not in MRES:
        raise ValueError("micropassos inválido")
    if novo["modo"] not in ("stealth", "spread", "auto"):
        raise ValueError("modo inválido")
    cfg.update(novo)
    if cfg["micro"] != velho:          # a resolução muda só para o motor do TMC
        if canal == "tmc":
            pos = int(round(pos * cfg["micro"] / velho))
        else:
            posk["tmc"] = int(round(posk["tmc"] * cfg["micro"] / velho))
    if tmc and tmc.addr is not None and vs.value():
        aplica_cfg()
    else:
        busca_tmc()
    return {"cfg": cfg, "tmc": _tmc_resumo(), "pos": pos}


def c_en(m):
    global tmc_falha
    if m.get("v"):
        tmc_falha = False
        _energiza(True)
    else:
        if tj:
            tj.corta("trajetória cortada: motores soltos")
        abortar()
        _energiza(False)
    return {}


def _mover(n, v, a):
    _livre()
    if vact:
        raise ValueError("pare o giro por UART (VACTUAL) antes")
    if n == 0:
        return {}
    d = 1 if n > 0 else -1
    f = _fim_bloqueia(d)
    if f:
        raise ValueError("FIM%d acionado bloqueia esse sentido" % f)
    v = min(VMAX, abs(float(v)))
    a = abs(float(a))
    if v <= 0 or a <= 0:
        raise ValueError("velocidade e aceleração têm que ser > 0")
    gc.collect()                       # perfis grandes: evita MemoryError por fragmentação
    cc, vv, idesc = _segs_mover(abs(n), v, a)
    gc.collect()                       # solta os temporários antes de montar o buffer do DMA
    _dispara(Perfil(cc, vv, d, "mover", a, None, idesc))
    return {}


def c_mover(m):
    _usa_k(m)
    return _mover(int(m["n"]), m["v"], m["a"])


def c_ir(m):
    _usa_k(m)
    return _mover(int(m["p"]) - pos, m["v"], m["a"])


def c_jog(m):
    _usa_k(m)
    _livre()
    if vact:
        raise ValueError("pare o giro por UART (VACTUAL) antes")
    v = float(m["v"])
    a = abs(float(m["a"]))
    d = 1 if v > 0 else -1
    v = min(VMAX, abs(v))
    if v <= 0 or a <= 0:
        raise ValueError("velocidade e aceleração têm que ser > 0")
    f = _fim_bloqueia(d)
    if f:
        raise ValueError("FIM%d acionado bloqueia esse sentido" % f)
    gc.collect()
    cc, vv, _ = _sobe(v, a)
    k = len(cc)
    cc.append(1 << 31)                 # regime "infinito"; o Parar pula para a desaceleração
    vv.append(v)
    _espelha(cc, vv, k)
    gc.collect()
    _dispara(Perfil(cc, vv, d, "jog", a, k + 1, k + 1))
    return {}


def c_parar(m):
    global vact
    if vact and tmc and tmc.addr is not None:
        vact = 0
        tmc.escreve(VACTUAL, 0)
    if tj:                             # a trajetória não tem desaceleração guardada: corta no passo
        tj.corta("trajetória parada")
    parar()
    return {}


def c_emerg(m):
    global vact, t_erro
    t_erro = time.ticks_ms()
    if tj:
        tj.corta("EMERGÊNCIA: trajetória cortada")
    if drv["segura"]:
        abortar("EMERGÊNCIA: pulsos cortados, motor mantido energizado")
    else:
        abortar("EMERGÊNCIA: motor solto")
        en.value(1)
        ena.value(0)
    if vact and tmc and tmc.addr is not None:
        tmc.escreve(VACTUAL, 0)
    vact = 0
    return {}


def c_zero(m):
    """zera (ou define) a posição do canal k, sem trocar a SM0 de canal"""
    global pos
    _livre()
    k = m.get("k", canal)
    if k not in CANAIS:
        raise ValueError("canal inválido: %s" % k)
    p = int(m.get("p", 0))
    if k == canal:
        pos = p
    else:
        posk[k] = p
    return {"pos": pos, "pk": _pos_k()}


def _fim_algum():
    """algum fim de curso configurado para bloquear está acionado (o sentido do VACTUAL não é
    conhecido: depende do shaft e da ligação do motor)"""
    return _fim_bloqueia(1) or _fim_bloqueia(-1)


def _vigia_vact():
    """o giro por VACTUAL não passa pelo _vigia: mesmas proteções do jog"""
    global vact, t_trava, t_erro
    if not vact:
        return
    if not vs.value():                 # o TMC reinicia com VACTUAL = 0: não religar sozinho na volta
        vact = 0
        t_erro = time.ticks_ms()
        ev("24 V caiu com o giro por VACTUAL: giro cancelado")
        return
    f = _fim_algum()
    if f:
        t_trava = time.ticks_ms()
        msg = "FIM%d acionado: giro por VACTUAL parado" % f
    elif time.ticks_diff(time.ticks_ms(), ult_rx) > WDT_JOG:
        msg = "giro por VACTUAL parado: painel sem comunicação"
    else:
        return
    vact = 0
    if tmc and tmc.addr is not None:
        tmc.escreve(VACTUAL, 0)
    ev(msg)


def c_vact(m):
    global vact
    _livre()
    if drv["tipo"] != "tmc":
        raise ValueError("VACTUAL só no modo TMC2209 (gira só o motor do TMC, sem os pulsos)")
    if not (tmc and tmc.addr is not None):
        raise ValueError("TMC sem UART")
    v = int(float(m["v"]) / 0.715)
    f = _fim_algum()
    if v and f:
        raise ValueError("FIM%d acionado: giro por VACTUAL bloqueado" % f)
    if v and en.value():
        en.value(0)
        time.sleep_ms(150)
    vact = max(-0x7FFFFF, min(0x7FFFFF, v))
    tmc.escreve(VACTUAL, vact & 0xFFFFFF)
    return {"vact": vact}


def c_fim(m):
    for k in ("f1", "f2"):
        if k in m:
            fimcfg[k] = max(-1, min(2, int(m[k])))
    if "inv" in m:
        fimcfg["inv"] = bool(m["inv"])
    for k in ("k1", "k2"):
        if k in m:
            if m[k] not in CANAIS:
                raise ValueError("canal inválido: %s" % m[k])
            fimcfg[k] = m[k]
    for k in ("r25", "beta", "r25_2", "beta2"):
        if k in m and float(m[k]) > 0:
            fimcfg[k] = float(m[k])
    return {"fimcfg": fimcfg}


def c_st(m):
    global ult_busca
    p, v = _agora()
    ntc, ntcr = _ntc()
    d = {"pos": p, "v": v, "mov": mov.tipo if mov else ("tj" if tj else "vact" if vact else ""), "drv": drv["tipo"],
         "k": canal, "pk": _pos_k(), "boot": BOOT,
         "en": 1 if _energizado() else 0, "vm": vs.value(), "f1": int(_fim(0)), "f2": int(_fim(1)),
         "fr1": fim[0].value(), "fr2": fim[1].value(), "ntc": ntc, "ntcr": ntcr, "trp": _trp(), "vact": vact}
    if adc_ntc2 is not None:
        d["ntc2"], d["ntcr2"] = _ntc(adc_ntc2, "r25_2", "beta2")
    t = None
    if vs.value() and _usa_tmc():
        if not _tmc_on() and time.ticks_diff(time.ticks_ms(), ult_busca) > 2000:
            ult_busca = time.ticks_ms()
            if busca_tmc():
                ev("TMC encontrado no endereço %d e configurado" % tmc.addr)
        if tmc and tmc.addr is not None:
            ds = tmc.le(DRV_STATUS)
            if ds is None:
                tmc_info["ok"] = False
            else:
                g = tmc.le(GSTAT)
                if g is not None and g & 1:
                    aplica_cfg()
                    ev("TMC reiniciou (VM caiu?): configuração regravada")
                t = {"drv": ds, "sg": tmc.le(SG_RESULT), "tstep": tmc.le(TSTEP), "gstat": g,
                     "ioin": tmc.le(IOIN)}
    elif not vs.value():
        tmc_info["ok"] = False
    d["tmc"] = t
    d["tmci"] = _tmc_resumo()
    d["sgmin"] = sg_min
    if tj:
        d["tj"] = tj.resumo()
    d["tjf"] = tj_ult
    d["quente"] = tmc_quente
    d["falha"] = tmc_falha
    if eventos:
        d["ev"] = eventos[:]
        del eventos[:]
    return d


def c_reg(m):
    if not (tmc and tmc.addr is not None):
        raise ValueError("TMC sem UART")
    r = int(m["r"])
    if "w" in m:
        tmc.escreve(r, int(m["w"]) & 0xFFFFFFFF)
    return {"r": r, "v": tmc.le(r)}


CMD = {"info": c_info, "cfg": c_cfg, "en": c_en, "mover": c_mover, "ir": c_ir, "jog": c_jog,
       "parar": c_parar, "emerg": c_emerg, "drv": c_drv, "sg": c_sg, "sgzera": c_sgzera, "irun": c_irun, "rampa": c_rampa, "zero": c_zero, "vact": c_vact, "fim": c_fim,
       "st": c_st, "reg": c_reg, "salva": c_salva, "tjini": c_tjini, "tj": c_tj, "ping": lambda m: {}}


def _vigia_tmc():
    """a cada 0,5 s, com o TMC energizado: temperatura e curto, mesmo sem o painel conectado"""
    global tmc_quente, tmc_falha, corr_reduzida, t_erro
    if not (_usa_tmc() and tmc and tmc.addr is not None and tmc_info.get("ok") and vs.value()
            and en.value() == 0):
        return
    ds = tmc.le(DRV_STATUS, None, 1)
    if ds is None:
        return
    if ds & 0b111110 or ds & (3 << 10):          # ot, curtos (s2ga/s2gb/s2vsa/s2vsb), >150 °C
        tmc_falha = True
        t_erro = time.ticks_ms()
        oq = "SUPERAQUECEU" if ds & ((1 << 1) | (3 << 10)) else "curto numa fase do motor"
        abortar("TMC %s (DRV_STATUS 0x%08X): passos cortados e TMC desligado" % (oq, ds))
        en.value(1)
        return
    tmc_quente = bool(ds & (1 | (3 << 8)))        # otpw, >120 °C, >143 °C
    if tmc_quente and not corr_reduzida:
        corr_reduzida = True
        r = c_irun({"run": float(cfg["run"]) * 0.6})
        ev("TMC acima de 120 °C: corrente reduzida para %.2f A. Ligue a ventoinha e baixe a corrente" % r["irun"])


def _led_ini():
    global led_sm
    try:
        led_sm = StateMachine(3, _ws2812, freq=8_000_000, sideset_base=Pin(PIN_LED))
        led_sm.active(1)
    except Exception:
        led_sm = None


def _led(r, g, b):
    # 15% de brilho em conta inteira: float no MicroPython é alocado no heap (mais trabalho pro GC)
    global led_ult
    c = ((g * 38 >> 8) << 16) | ((r * 38 >> 8) << 8) | (b * 38 >> 8)
    if c != led_ult and led_sm:
        led_sm.put(c << 8)
        led_ult = c


def _recente(t, agora, ms):
    return t is not None and time.ticks_diff(agora, t) < ms


def _led_tick():
    """cor e piscada por prioridade: erro > travamento > temperatura > alimentação > operação"""
    agora = time.ticks_ms()
    fase = agora % 1000
    if tmc_falha or _recente(t_erro, agora, 6000):            # vermelho piscando rápido
        return _led(255, 0, 0) if (agora // 100) % 2 else _led(0, 0, 0)
    if _recente(t_trava, agora, 4000):                        # magenta, 2 piscadas por segundo
        return _led(255, 0, 255) if fase < 400 and (fase // 100) % 2 == 0 else _led(0, 0, 0)
    if tmc_quente:                                            # laranja piscando 1 Hz
        return _led(255, 70, 0) if fase < 500 else _led(0, 0, 0)
    if _usa_tmc() and not vs.value():                         # amarelo: piscada curta a cada 2 s (sem 24 V)
        return _led(255, 170, 0) if agora % 2000 < 250 else _led(0, 0, 0)
    if _usa_tmc() and not _tmc_on():                          # vermelho lento: TMC não responde
        return _led(255, 0, 0) if agora % 2000 < 1000 else _led(0, 0, 0)
    if mov:                                                   # movendo: ciano; parando: amarelo
        return _led(0, 170, 255) if mov.tipo != "parando" else _led(255, 170, 0)
    if tj and tj.on:
        return _led(0, 170, 255)
    if vact:
        return _led(0, 170, 255)
    if time.ticks_diff(agora, ult_rx) > 3000:                 # sem painel: azul "respirando"
        return _led(0, 0, 40 + 215 * abs(agora % 3000 - 1500) // 1500)
    if _energizado():                                         # energizado e parado: verde
        return _led(0, 255, 0)
    return _led(90, 90, 90)                                   # pronto, motor solto: branco


def _trata(s):
    global ult_rx
    ult_rx = time.ticks_ms()
    m = {}
    try:
        m = json.loads(s)
        r = CMD[m["c"]](m) or {}
        r["ok"] = 1
    except Exception as e:
        r = {"ok": 0, "erro": str(e) or type(e).__name__}
    if isinstance(m, dict):
        r["id"] = m.get("id")
    print(json.dumps(r))


LINHA_MAX = 4096          # as remessas da trajetória (tj) passam de 1 kB


def _erro_interno(e):
    global mov, t_erro
    t_erro = time.ticks_ms()
    msg = "erro interno (%s: %s): movimento cortado" % (type(e).__name__, e)
    try:
        if tj:
            tj.corta(msg)
        elif mov:
            abortar(msg)
        else:
            ev(msg)
    except Exception:
        era_tj = tj is not None
        _tj_solta()
        _troca(0, 0, prog_ini, RES)        # sem conseguir contar: corta assim mesmo
        mov = None
        if era_tj:                         # devolve STEP/DIR à SM0
            _pinos()
            _sm_novo()
        ev(msg + "; posição perdida")


def rodar():
    global ult_tmc_chk, led_chk
    _carrega_cfg()
    _pinos()
    _sm_novo()
    try:
        busca_tmc()
    except Exception as e:
        ev("TMC: %s" % e)
    pl = select.poll()
    pl.register(sys.stdin, select.POLLIN)
    linha = []
    _led_ini()
    print(json.dumps({"ev": ["pronto: %s · placa %s" % (FW, REV)]}))
    if not REV_OK:
        ev("placa.py com revisão desconhecida (%s): usando a pinagem da v17" % REV)
    try:
        while True:
            try:
                while pl.poll(0):
                    ch = sys.stdin.read(1)
                    if ch in "\r\n":
                        if linha:
                            _trata("".join(linha))
                            linha = []
                    elif len(linha) < LINHA_MAX:
                        linha.append(ch)
                    else:                  # lixo na serial sem fim de linha: não deixa a memória crescer
                        linha = []
                        ev("linha com mais de %d caracteres descartada" % LINHA_MAX)
                _vigia()
                if tj:
                    tj.vigia()
                _vigia_vact()
                agora = time.ticks_ms()
                if time.ticks_diff(agora, ult_tmc_chk) > 500:
                    ult_tmc_chk = agora
                    _vigia_tmc()
                if time.ticks_diff(agora, led_chk) > 40:
                    led_chk = agora
                    _led_tick()
            except Exception as e:         # nada derruba o laço: corta o movimento e segue atendendo
                _erro_interno(e)
    finally:
        _tj_solta()
        _troca(0, 0, prog_ini, RES)        # corta passos e DMA juntos, com o STEP baixo
        if sm:
            sm.active(0)
        en.value(1)
        ena.value(0)
        _led(120, 0, 255)                                     # roxo: firmware parado (REPL)
        if vact and tmc and tmc.addr is not None:
            tmc.escreve(VACTUAL, 0)
