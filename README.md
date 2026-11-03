<p align="center">
  <img src="packaging/tuxsec.png" alt="TuxSec Logo" width="220"/>
</p>

<h1 align="center">🐧 TuxSec — Parsec Linux Host</h1>

<p align="center">
  <b>Host nativo de baixa latência compatível com Parsec para Linux (Wayland & X11)</b><br/>
  Captura direta via DRM/KMS + Vulkan • Painel Gráfico em PyQt6 • Login Integrado • Anti-Eco Automático para Discord no PipeWire
</p>

---

## 📖 Sobre o Projeto

O cliente oficial do Parsec para Linux permite apenas *conectar* a outros PCs, mas não suporta **hospedar (Host)** partidas ou compartilhar a tela do seu próprio PC Linux.

O **TuxSec** resolve isso trazendo um **Host Parsec completo para Linux**, construído sobre o daemon em Rust `lowlatd` com diversas melhorias essenciais para o dia a dia no desktop Linux moderno:

1. **🖥️ Compatibilidade Universal de Monitores e GPUs**:
   - Detecta automaticamente qualquer entrada de vídeo (`HDMI-A-*`, `DP-*`, `eDP-*`, `DVI-*`, `Virtual`) em qualquer GPU (`/dev/dri/card0`, `card1`, etc.), tanto via propriedades legadas quanto via KMS Atômico (`CRTC_ID` / `FB_ID`).
   - Possui fallback inteligente para capturar automaticamente a primeira tela acesa caso o nome do conector mude entre o Wayland e o driver DRM.
   - Permite alternar entre monitores **em tempo real** pelo painel gráfico sem desconectar seus amigos.

2. **🎨 Suporte a KDE Plasma Wayland (HDR / 10-bit / 16-bit FP16) e GNOME**:
   - Suporte nativo a framebuffers `AB4H` / `XB4H` (`R16G16B16A16_SFLOAT` usados pelo KWin Wayland em modo wide-color/HDR), `AR30` / `AB30` (10-bit) e `AR24` / `AB24` (8-bit).

3. **🔇 Isolamento Automático de Áudio do Discord (`lowlat-audio-guard`)**:
   - No Linux, capturar o monitor de áudio padrão faz com que seus amigos no Discord se ouçam de volta (eco).
   - O **TuxSec** inclui um serviço automático para **PipeWire** que desconecta o Discord (`WEBRTC VoiceEngine`, `Discord`, `Vesktop`, `TeamSpeak`, `Mumble`) e o loopback físico da transmissão, roteando apenas o som dos jogos e aplicativos para o stream — **sem precisar abrir o `qpwgraph` ou `helvum` toda vez**.

4. **🎛️ Painel de Controle Gráfico (`TuxSec` / `lowlat-gui`)**:
   - **Login Gráfico na Conta Parsec (`🔑 Conta Parsec`)** com suporte a 2FA (autenticação de dois fatores).
   - **Troca em Tempo Real** de Monitor, FPS (`30`, `60`, `120`, `144`) e Bitrate (`10` a `80 Mbps`).
   - **Gerenciamento de Convidados**: veja quem está conectado, ative/desative permissões de **Controle (Gamepad)**, **Teclado** e **Mouse** individualmente, ou expulse convidados com 1 clique.
   - **Filtro de Áudio por Aplicativo**: escolha em tempo real quais aplicativos enviam som para a transmissão e quais ficam bloqueados.

---

## 🚀 Como Instalar e Rodar

Esta pasta **já inclui o executável pré-compilado (`bin/lowlatd`)** e o lançador **`./TuxSec`**, então você não precisa esperar compilação demorada!

### Opção 1: Instalação com 1 comando (Recomendado)

Funciona em **Arch Linux / CachyOS / Manjaro**, **Ubuntu / Debian / Pop!_OS / Linux Mint** e **Fedora / Nobara**:

```bash
git clone https://github.com/Javorka1/TuxSec.git
cd TuxSec
./install-linux.sh
```

Ou simplesmente execute o lançador direto da pasta:

```bash
./TuxSec
```

O instalador irá:
1. Instalar automaticamente as dependências leves do sistema (`python-pyqt6`, `pipewire`, `vulkan`, `polkit`).
2. Instalar o executável pré-compilado `lowlatd`, o comando `tuxsec` / `lowlat-gui` e o ícone do **TuxSec** no seu menu de aplicativos.
3. Ativar os serviços `lowlatd.service` (sistema), `lowlat-session.service`, `lowlat-tray.service` e `lowlat-audio-guard.service` (usuário).
4. Abrir o painel gráfico **TuxSec**.

---

## 🔑 Primeiros Passos Após Instalar

1. Com o painel **TuxSec** aberto, clique no botão roxo **`🔑 Conta Parsec`** no canto superior direito.
2. Digite seu **E-mail** e **Senha** do Parsec (e o código de 2 fatores, se sua conta usar 2FA).
   > **Nota:** Se o Parsec exibir erro de *Novo IP detectado*, basta clicar no link de confirmação que o Parsec envia para o seu e-mail e clicar em **Entrar** novamente.
3. Pronto! O status mudará para **`● ONLINE — Aguardando Conexão`** e seu computador Linux já aparecerá disponível no Parsec para você e seus amigos conectarem.

---

## 🛠️ Comandos Úteis no Terminal

| Comando | Descrição |
| :--- | :--- |
| `tuxsec` ou `lowlat-gui` | Abre o Painel de Controle Gráfico do TuxSec |
| `./TuxSec` | Abre o painel direto pela pasta do projeto |
| `sudo lowlatd --outputs` | Lista os monitores e conectores detectados pelo DRM/KMS |
| `journalctl -u lowlatd.service -f` | Exibe os logs em tempo real do servidor de streaming |
| `systemctl --user status lowlat-audio-guard.service` | Verifica o status do serviço Anti-Eco do Discord no PipeWire |

---

## 📦 Gerando Pacote Portátil (`.tar.gz`) para Enviar a Amigos

Se quiser gerar um arquivo `.tar.gz` autocontido com os binários prontos para enviar diretamente:

```bash
./packaging/build-release-bundle.sh
```

O arquivo será gerado em `dist/parsec-linux-host-x86_64.tar.gz`.

---

## 📄 Licença e Créditos

- Baseado no daemon [`lowlat`](https://github.com/nomi-san/lowlat) sob licença MIT, estendido com detecção universal de conectores DRM/KMS, suporte a buffers FP16 (`AB4H`), painel de controle gráfico em PyQt6 (`TuxSec`) e isolamento automático de áudio PipeWire (`lowlat-audio-guard`).
- **Créditos do Ícone:** <a href="https://www.flaticon.com/br/icones-gratis/pinguim" title="pinguim ícones">Pinguim ícones criados por Magnific - Flaticon</a>
