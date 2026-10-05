# Testes de bancada do no.py: rodam na placa ligada na USB (sem 24 V e sem motor bastam).
#   SCARANODE_PORTA=/dev/serial/by-id/... uv run --with pytest --with pyserial pytest firmware/painel/tests -q
# Sem a variável, os testes são pulados. O no.py desta cópia vai para a placa como no_t.py (o no.py gravado
# não é tocado) e roda pelo raw REPL; no fim a placa reinicia no firmware dela.
import base64
import json
import os
import pathlib
import struct
import time

import pytest

serial = pytest.importorskip("serial")
PORTA = os.environ.get("SCARANODE_PORTA")
pytestmark = pytest.mark.skipif(not PORTA, reason="SCARANODE_PORTA não definida (teste de bancada)")
NO_PY = pathlib.Path(__file__).resolve().parents[1] / "no.py"


class RawRepl:
    def __init__(self, porta):
        self.s = serial.Serial(porta, 115200, timeout=0.1)
        self.buf = b""

    def le_ate(self, fim, seg=10.0):
        """consome a saída até fim (inclusive) e devolve o que veio antes; o resto fica no buffer"""
        t0 = time.time()
        while fim not in self.buf:
            if time.time() - t0 > seg:
                raise TimeoutError("esperava %r, veio %r" % (fim, self.buf[-300:]))
            self.buf += self.s.read(4096)
        antes, self.buf = self.buf.split(fim, 1)
        return antes

    def entra(self):
        self.s.write(b"\r\x03\x03")             # para o firmware (main.py -> no.rodar)
        time.sleep(0.3)
        self.s.reset_input_buffer()
        self.buf = b""
        self.s.write(b"\x01")
        self.le_ate(b"raw REPL; CTRL-B to exit\r\n>")
        self.s.write(b"\x04")                   # soft reset no raw REPL: heap limpo, sem rodar o main.py
        self.le_ate(b"raw REPL; CTRL-B to exit\r\n>")

    def executa(self, codigo, espera=True):
        self.s.write(codigo.encode())
        self.s.write(b"\x04")
        self.le_ate(b"OK")
        if espera:
            self.le_ate(b"\x04", 30)               # saída do código
            erro = self.le_ate(b"\x04>", 5)        # erro (vazio se rodou)
            assert not erro.strip(), erro.decode(errors="replace")

    def grava(self, nome, dados):
        self.executa("f=open(%r,'wb')\n" % nome)
        for i in range(0, len(dados), 256):
            self.executa("f.write(%r)\n" % dados[i:i + 256])
        self.executa("f.close()\n")

    def sai(self):
        self.s.write(b"\r\x03\x03")
        time.sleep(0.3)
        self.s.reset_input_buffer()
        self.buf = b""
        self.s.write(b"\x01")
        try:
            self.le_ate(b"raw REPL; CTRL-B to exit\r\n>", 3)
            self.executa("import os\ntry:\n os.remove('no_t.py')\nexcept OSError:\n pass\n")
        finally:
            self.s.write(b"\x02\x04")           # REPL normal + soft reset: volta ao main.py
            self.s.close()


class Linhas:
    """protocolo do painel: uma linha JSON por comando e por resposta"""

    def __init__(self, repl):
        self.s, self.nid, self.buf = repl.s, 0, repl.buf
        self.vistas = []                        # tudo o que a placa mandou (para a mensagem de falha)

    def espera(self, pred, seg):
        t0 = time.time()
        while time.time() - t0 < seg:
            self.buf += self.s.read(4096)
            while b"\n" in self.buf:
                linha, self.buf = self.buf.split(b"\n", 1)
                self.vistas.append(linha)
                try:
                    m = json.loads(linha)
                except ValueError:
                    continue
                if pred(m):
                    return m
        return None

    def cmd(self, m, seg=4.0):
        self.nid += 1
        m["id"] = self.nid
        self.s.write((json.dumps(m) + "\n").encode())
        return self.espera(lambda r: r.get("id") == self.nid, seg)


def _palavras(n):
    # segmentos de 10 ms com 600 passos (d >= TJ_DMIN), sentido alternado
    d = int((100000 - 5) / 600 - 7) // 2
    return [d | ((i & 1) << 20) | (600 << 21) for i in range(n)]


@pytest.fixture
def placa():
    r = RawRepl(PORTA)
    try:
        r.entra()
        r.grava("no_t.py", NO_PY.read_bytes())
        yield r
    finally:
        r.sai()


def test_linha_tj_longa_com_heap_fragmentado(placa):
    """Linha de ~1,3 kB (bloco tj do robo.html) com o heap sem nenhum bloco livre de 8 kB.
    Modo de falha que este teste impede: a linha montada caractere a caractere numa lista pedia
    8192 bytes contíguos ao passar de 1024 caracteres; com o heap fragmentado, MemoryError no
    laço principal, trajetória cortada no meio do desenho e o painel sem resposta."""
    placa.executa(
        "import gc, no_t\n"
        "gc.collect()\n"
        "G = []\n"
        "try:\n"
        "    while True: G.append(bytearray(6000))\n"
        "except MemoryError: pass\n"
        "P = []\n"
        "try:\n"
        "    while True: P.append(bytearray(48))\n"
        "except MemoryError: pass\n"
        "for i in range(0, len(G), 2): G[i] = None\n"   # buracos de 6000 bytes: nenhum de 8192
        "gc.collect()\n"
        "no_t.rodar()\n",
        espera=False,
    )
    p = Linhas(placa)
    assert p.espera(lambda m: "pronto" in str(m.get("ev")), 30), "no_t.rodar() não subiu"
    info = p.cmd({"c": "info"})
    assert info and info["ok"], info
    r = p.cmd({"c": "tjini", "k": [info["k"]], "tid": 1})
    assert r and r["ok"], r
    for _ in range(2):
        w = base64.b64encode(struct.pack("<240I", *_palavras(240))).decode()
        assert len(w) > 1024
        r = p.cmd({"c": "tj", "w": [w]})
        st = p.cmd({"c": "st"})
        assert r and r["ok"], "tj sem resposta; st=%s; placa: %r" % (st, p.vistas[-6:] + [p.buf[-400:]])
    assert r["esc"] == 480
