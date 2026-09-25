# ScaraNode

<p align="center"><img src="docs/img/3d/placa-iso.png" width="640" alt="ScaraNode"></p>

Placa de nó de motor **Klipper** para braço SCARA: **RP2040-Zero** + **TMC2209** (NEMA 17) ou driver
externo **DM556** (NEMA 23). Face única, 76 × 64 mm, feita para fresar em casa.

| Projetista | Revisão | Data | Estado |
|---|---|---|---|
| Daniel M. Torres | v17 | 25/09/2026 | Validada: 126 pinos, ERC e paridade 0, DRC de cobre sem erro |

📘 **[Manual completo](docs/README.md)** · 📄 **[PDF](docs/ScaraNode-Manual-v17.pdf)** ·
🧾 **[Lista de materiais](docs/02-lista-de-materiais.md)** · 🔧 **[Montagem](docs/04-montagem.md)** ·
⚙️ **[Klipper](docs/07-firmware-klipper.md)**

## Estrutura

```
hardware/     placa e esquemático KiCad (ScaraNode.kicad_pro / .kicad_pcb / .kicad_sch + bibliotecas do projeto)
production/   arquivos para fabricar: gerber/, furação, BOM.csv
firmware/     configuração Klipper de referência
docs/         manual (Markdown + PDF), imagens, histórico de revisões
```

## Editar a placa

Abra `hardware/ScaraNode.kicad_pro` no **KiCad 10**: esquemático (`ScaraNode.kicad_sch`) e placa
(`ScaraNode.kicad_pcb`). As tabelas de biblioteca do projeto (`sym-lib-table`, `fp-lib-table`) apontam para as
bibliotecas padrão do KiCad 10 e para as próprias: `ScaraNode.kicad_sym` (RP2040-Zero, StepStick, 74ACT245, diodos)
e `ScaraNode.pretty` (soquetes do RP2040-Zero e do StepStick). Os comandos para
regerar Gerber e furação estão em [docs/03-fabricacao.md](docs/03-fabricacao.md#arquivos-de-produção).

Placa e esquemático foram gerados e conferidos por uma ferramenta própria em Python, que não faz parte deste
repositório (a paridade placa × esquemático é verificada pelo `kicad-cli`; a sincronização pela interface —
"Atualizar placa a partir do esquemático" — não foi testada). Os arquivos KiCad são completos e editáveis sem ela.

## Licença

Hardware sob **CERN-OHL-S-2.0** (ver [`LICENSE`](LICENSE)). Fotos de terceiros em `docs/img/componentes/`
mantêm as licenças listadas em [`CREDITOS.md`](docs/img/componentes/CREDITOS.md).

## Créditos

Modelos 3D das peças: bibliotecas oficiais do KiCad. Fotos de componentes: Wikimedia Commons, com
autores e licenças em [`docs/img/componentes/CREDITOS.md`](docs/img/componentes/CREDITOS.md).
