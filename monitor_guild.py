"""
Bot de monitoramento de guild - Naruto Vikings (NTO)
Monitora: level up, entrada/saida de membros, online/offline.
Envia notificacoes para um webhook do Discord.
"""

import requests
import time
import json
import os
from bs4 import BeautifulSoup

# ==================== CONFIGURACAO ====================
# WEBHOOK_URL vem de uma variavel de ambiente (GitHub Secret) por seguranca.
# Se nao houver variavel de ambiente definida, usa o valor fixo abaixo (uso local).

WEBHOOK_URL = os.environ.get(
    "WEBHOOK_URL",
    "https://discord.com/api/webhooks/1534968954336972931/aklZf5_F0W43SR9jvaP-dMWZ2OtL4wFpvv8xT-cE7VXB3WcnA8bdJQg3mJPrUllyGsFl",
)
GUILD_URL = os.environ.get("GUILD_URL", "https://ntovikings.com/guilds/N+I+R+V+A+N+A")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guild_state.json")

# ==================== DISCORD ====================

def send_to_discord(content, color=0x2ecc71, mention_everyone=False, title=None):
    """Envia uma mensagem simples como embed para o webhook."""
    embed = {
        "description": content,
        "color": color,
    }
    if title:
        embed["title"] = title
    payload = {"embeds": [embed]}
    if mention_everyone:
        payload["content"] = "@everyone"
        payload["allowed_mentions"] = {"parse": ["everyone"]}
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code >= 300:
            print(f"[AVISO] Discord retornou status {r.status_code}: {r.text}")
    except Exception as e:
        print("[ERRO] Falha ao enviar para o Discord:", e)


# ==================== SCRAPER ====================

def fetch_guild_members():
    """
    Busca a pagina da guild e retorna um dict:
    { nome_do_personagem: {"level": int, "status": "Online"/"Offline", "vocation": str, "rank": str} }
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; GuildMonitorBot/1.0)"}
    resp = requests.get(GUILD_URL, headers=headers, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    members = {}

    # Procura todas as tabelas da pagina e identifica a que tem os membros
    # (tem uma linha de cabecalho contendo "Nome" ou "Vocação")
    tables = soup.find_all("table")
    members_table = None
    for table in tables:
        header_text = table.get_text(" ", strip=True).lower()
        if "vocação" in header_text or "vocacao" in header_text or "nível" in header_text:
            members_table = table
            break

    if members_table is None:
        raise RuntimeError("Nao encontrei a tabela de membros na pagina. O site pode ter mudado de layout.")

    rows = members_table.find_all("tr")
    last_rank = ""

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue  # linha de cabecalho ou vazia

        # pula linha de cabecalho (celulas sem link de personagem e sem numero de level)
        link = row.find("a", href=lambda h: h and "/characters/" in h)
        if link is None:
            continue

        name = link.get_text(strip=True)

        # rank: se a celula de rank estiver vazia (rowspan), mantem o ultimo rank visto
        rank_text = cells[0].get_text(strip=True)
        if rank_text:
            last_rank = rank_text
        rank = last_rank

        # vocacao e level: procura pelas celulas que fazem sentido
        texts = [c.get_text(strip=True) for c in cells]
        vocation = ""
        level = None
        status = ""

        for t in texts:
            if t.isdigit() and level is None:
                level = int(t)
            elif t.lower() in ("online", "offline"):
                status = t

        # vocacao = penultima celula textual que nao seja nome/level/status/rank
        for t in texts:
            if t not in (rank_text, name, status) and not t.isdigit() and t != "":
                vocation = t
                break

        if level is None:
            continue  # nao conseguiu parsear essa linha direito

        members[name] = {
            "level": level,
            "status": status if status else "Offline",
            "vocation": vocation,
            "rank": rank,
        }

    return members


# ==================== ESTADO ====================

def load_previous_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ==================== COMPARACAO / EVENTOS ====================

def compare_and_notify(old_members, new_members):
    old_names = set(old_members.keys())
    new_names = set(new_members.keys())

    # Entrou na guild
    for name in new_names - old_names:
        m = new_members[name]
        send_to_discord(
            f"🟢 **{name}** entrou na guild! (Level {m['level']} - {m['vocation']})",
            color=0x3498db,
        )

    # Saiu da guild
    for name in old_names - new_names:
        m = old_members[name]
        send_to_discord(
            f"🔴 **{name}** saiu da guild. (era Level {m['level']} - {m['vocation']})",
            color=0xe74c3c,
        )

    # Level up e mudanca de status (so para quem continua na guild)
    for name in new_names & old_names:
        old_m = old_members[name]
        new_m = new_members[name]

        if new_m["level"] > old_m["level"]:
            send_to_discord(
                f"**{name}** subiu para Nível **{new_m['level']}**",
                color=0xf1c40f,
                mention_everyone=True,
                title="🆙 NTO Level Up",
            )

        if new_m["status"] != old_m["status"]:
            if new_m["status"] == "Online":
                send_to_discord(f"✅ **{name}** ficou online.", color=0x2ecc71)
            else:
                send_to_discord(f"⚫ **{name}** ficou offline.", color=0x95a5a6)


# ==================== EXECUCAO PRINCIPAL ====================
# Roda UMA checagem e encerra (pensado pra ser chamado por um agendador,
# tipo GitHub Actions, a cada X minutos). Para rodar continuamente no seu
# PC, use um agendador do Windows ou rode em loop via script .bat.

def main():
    print(f"Checando guild em: {GUILD_URL}")
    try:
        current_members = fetch_guild_members()
        previous_state = load_previous_state()

        if previous_state is None:
            print(f"[INFO] Primeira execucao - salvando estado inicial com {len(current_members)} membros.")
            save_state(current_members)
        else:
            compare_and_notify(previous_state, current_members)
            save_state(current_members)
            print(f"[OK] Checagem concluida - {len(current_members)} membros.")
    except Exception as e:
        print("[ERRO] Falha na checagem:", e)
        raise


if __name__ == "__main__":
    main()
