# Parsec Linux Host (`lowlat` + Painel Gráfico Qt6 + Anti-Eco PipeWire)

Host nativo compatível com **Parsec** para Linux (Wayland / X11), com captura direta via **DRM/KMS + Vulkan**, codificação acelerada por hardware (**VAAPI / Vulkan Video / NVENC**), **Painel de Controle Gráfico em PyQt6** e **Isolamento Automático de Áudio do Discord no PipeWire**.

---

## ✨ Recursos Principais

- **🖥️ Compatível com Qualquer Monitor e Entrada de Vídeo**: Detecta automaticamente qualquer monitor conectado (`HDMI-A-*`, `DP-*`, `eDP-*`, `DVI-*`, etc.) em qualquer GPU (`/dev/dri/card0`, `card1`, etc.), com suporte a troca de monitor em tempo real sem derrubar a transmissão.
- **🎨 Suporte a KDE Plasma Wayland (10-bit / 16-bit FP16 HDR) e GNOME**: Suporte nativo a framebuffers `AB4H` / `XB4H` (`R16G16B16A16_SFLOAT`), `AR30` / `AB30` (10-bit) e `AR24` / `AB24` (8-bit).
- **🔑 Login Gráfico na Conta Parsec**: Faça login direto pelo painel (`🔑 Conta Parsec`) com suporte a autenticação de 2 fatores (2FA), sem precisar usar o terminal.
- **🔇 Anti-Eco Automático para Discord / Voz (`lowlat-audio-guard`)**: Serviço de usuário para PipeWire que isola o áudio da transmissão automaticamente — seus amigos ouvem o som do jogo/PC, mas **não se ouvem de volta no Discord** sem precisar abrir o `qpwgraph` ou `helvum`.
- **👥 Controle de Convidados em Tempo Real**: Veja quem está conectado, libere ou bloqueie permissões de **Controle (Gamepad)**, **Teclado** e **Mouse** com um clique, ou desconecte convidados.

---

## 🚀 Instalação Rápida (Qualquer Distro Linux)

Suporta **Arch Linux / CachyOS / Manjaro**, **Ubuntu / Debian / Pop!_OS / Linux Mint** e **Fedora / Nobara**:

```bash
git clone <URL_DO_SEU_REPOSITORIO>
cd parsec-linux-host
./install-linux.sh
```

O script `install-linux.sh`:
1. Instala automaticamente as dependências da sua distribuição (`python-pyqt6`, `pipewire`, `vulkan`, etc.).
2. Compila o daemon `lowlatd` (ou usa o binário pré-compilado se você estiver usando o pacote `.tar.gz` de Release).
3. Instala e ativa os serviços `lowlatd.service` (sistema), `lowlat-session.service`, `lowlat-tray.service` e `lowlat-audio-guard.service` (usuário).
4. Abre o **Painel de Controle Parsec Linux Host** (`lowlat-gui`).

---

## 📦 Gerando um Pacote Portátil Pré-Compilado (`.tar.gz`) para Enviar a Amigos

Se quiser gerar um arquivo `.tar.gz` já com o binário compilado (para que seus amigos não precisem ter Rust/Cargo instalado):

```bash
./packaging/build-release-bundle.sh
```

Isso criará o arquivo:
- `dist/parsec-linux-host-x86_64.tar.gz`

Quem receber esse arquivo só precisa extrair e rodar:
```bash
tar -xzf parsec-linux-host-x86_64.tar.gz
cd parsec-linux-host
./install-linux.sh
```

---

## 🛠️ Comandos Úteis

- **Abrir o Painel de Controle Gráfico**:
  ```bash
  lowlat-gui
  ```
- **Verificar status e logs do Host**:
  ```bash
  journalctl -u lowlatd.service -f
  ```
- **Verificar monitores detectados pelo DRM**:
  ```bash
  sudo lowlatd --outputs
  ```

---

## 📄 Créditos e Licença

Baseado no projeto [`lowlat`](https://github.com/nomi-san/lowlat) sob licença MIT, estendido com suporte universal de conectores DRM/Wayland FP16, Painel de Controle Gráfico (`lowlat-gui`) e Isolamento Automático de Áudio PipeWire (`lowlat-audio-guard`).
