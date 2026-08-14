"""
Bot de monitoramento de mortes - Naruto Vikings (NTO)
Para cada membro da guild, verifica a secao "Mortes Recentes" da pagina do
personagem e notifica no Discord (em embeds bonitos, diferenciando PvP de PvE)
quando aparece uma morte nova.
"""

import requests
import json
import os
import re
import time
import urllib.parse
from bs4 import BeautifulSoup

# ==================== CONFIGURACAO ====================

# Webhook do canal de MORTES (diferente do canal de level up)
WEBHOOK_URL = os.environ.get(
    "DEATH_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1537727788243746900/JIXI06TtDr44HhH9BSQrDvJKxCWupj3vrNXlNABPVm44XIqRd2jjnO4ZYFJMDRiw4-7D",
)
GUILD_URL = os.environ.get("GUILD_URL", "https://ntovikings.com/guilds/N+I+R+V+A+N+A")
BASE_CHARACTER_URL = "https://ntovikings.com/characters/"
PORTRAIT_BASE_URL = "https://ntovikings.com/templates/naruto_vikings/assets/Portrait/"

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "death_state.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GuildMonitorBot/1.0)"}

MAX_KEYS_PER_CHAR = 30

COLOR_PVP = 0xC0392B   # vermelho intenso
COLOR_PVE = 0x8E5A2E   # marrom/ambar (monstro)

GUILD_NAME = "N I R V A N A"


# ==================== DISCORD ====================

def send_death_embed(name, vocation, level, date_text, is_pvp, killers=None, monster=None):
    thumbnail_url = None
    if vocation:
        thumbnail_url = PORTRAIT_BASE_URL + urllib.parse.quote(vocation) + ".png"

    if is_pvp:
        killers_str = "\n".join(f"⚔️ **{k}**" for k in killers) if killers else "Desconhecido"
        embed = {
            "author": {"name": f"{name} foi executado(a)!", "icon_url": thumbnail_url} if thumbnail_url else {"name": f"{name} foi executado(a)!"},
            "color": COLOR_PVP,
            "title": "☠️ Morte PvP",
            "fields": [
                {"name": "Nível", "value": f"**{level}**", "inline": True},
                {"name": "Quando", "value": date_text, "inline": True},
                {"name": "Assassino(s)", "value": killers_str, "inline": False},
            ],
            "footer": {"text": f"NTO Vikings • Guild {GUILD_NAME}"},
        }
    else:
        embed = {
            "author": {"name": f"{name} caiu em combate", "icon_url": thumbnail_url} if thumbnail_url else {"name": f"{name} caiu em combate"},
            "color": COLOR_PVE,
            "title": "💀 Morte por Monstro",
            "fields": [
                {"name": "Nível", "value": f"**{level}**", "inline": True},
                {"name": "Quando", "value": date_text, "inline": True},
                {"name": "Morto por", "value": f"🐺 **{monster}**", "inline": False},
            ],
            "footer": {"text": f"NTO Vikings • Guild {GUILD_NAME}"},
        }

    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}

    payload = {"embeds": [embed]}
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code >= 300:
            print(f"[AVISO] Discord retornou status {r.status_code}: {r.text}")
    except Exception as e:
        print("[ERRO] Falha ao enviar para o Discord:", e)


# ==================== SCRAPER: MEMBROS DA GUILD ====================

def fetch_guild_members():
    """Retorna dict { nome: vocacao } dos personagens da guild."""
    resp = requests.get(GUILD_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    tables = soup.find_all("table")
    members_table = None
    for table in tables:
        header_text = table.get_text(" ", strip=True).lower()
        if "vocação" in header_text or "vocacao" in header_text or "nível" in header_text:
            members_table = table
            break

    if members_table is None:
        raise RuntimeError("Nao encontrei a tabela de membros na pagina da guild.")

    members = {}
    for row in members_table.find_all("tr"):
        link = row.find("a", href=lambda h: h and "/characters/" in h)
        if not link:
            continue
        name = link.get_text(strip=True)
        cells = [c.get_text(strip=True) for c in row.find_all("td")]

        vocation = ""
        status_idx = None
        for i, t in enumerate(cells):
            if t.lower() in ("online", "offline"):
                status_idx = i
                break
        if status_idx is not None:
            # a vocacao costuma ser a celula logo antes do nivel/status; pega o primeiro
            # texto (indo de tras pra frente a partir do status) que nao seja numero
            for i in range(status_idx - 1, -1, -1):
                t = cells[i]
                if t and not t.isdigit() and t != name:
                    vocation = t
                    break

        members[name] = vocation
    return members


# ==================== SCRAPER: MORTES DO PERSONAGEM ====================

def fetch_character_deaths(name):
    url = BASE_CHARACTER_URL + urllib.parse.quote(name.replace(" ", "+"), safe="+")
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    death_pattern = re.compile(r"(Died at level|Killed at level)")

    candidates = []
    for tag in soup.find_all(["li", "div", "tr", "p"]):
        text = tag.get_text(" ", strip=True)
        count = len(death_pattern.findall(text))
        if count == 1 and re.search(r"\d{4}", text):
            candidates.append(tag)

    leaf_candidates = []
    for tag in candidates:
        if not any(other is not tag and tag in other.descendants for other in candidates):
            leaf_candidates.append(tag)

    deaths = []
    for tag in leaf_candidates:
        full_text = tag.get_text(" ", strip=True)
        match = death_pattern.search(full_text)
        date_part = full_text[: match.start()].strip()
        desc_part = full_text[match.start():].strip()

        killers = [a.get_text(strip=True) for a in tag.find_all("a", href=lambda h: h and "/characters/" in h)]

        level_match = re.search(r"level\s+(\d+)", desc_part, re.IGNORECASE)
        level = level_match.group(1) if level_match else "?"

        monster = None
        if not killers:
            monster_match = re.search(r"by\s+(?:a[n]?\s+)?([^.]+)\.?$", desc_part, re.IGNORECASE)
            monster = monster_match.group(1).strip() if monster_match else "desconhecido"

        deaths.append({
            "date": date_part,
            "description": desc_part,
            "killers": killers,
            "level": level,
            "monster": monster,
        })

    return deaths


def death_key(death):
    return f"{death['date']}|{death['description']}"


# ==================== ESTADO ====================

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ==================== LOGICA PRINCIPAL ====================

def process_character(name, vocation, state):
    try:
        deaths = fetch_character_deaths(name)
    except Exception as e:
        print(f"[ERRO] Falha ao buscar mortes de {name}: {e}")
        return

    if not deaths:
        return

    current_keys = [death_key(d) for d in deaths]
    known_keys = set(state.get(name, []))

    if name not in state:
        state[name] = current_keys[:MAX_KEYS_PER_CHAR]
        return

    new_deaths = [d for d in reversed(deaths) if death_key(d) not in known_keys]

    for d in new_deaths:
        is_pvp = bool(d["killers"])
        send_death_embed(
            name=name,
            vocation=vocation,
            level=d["level"],
            date_text=d["date"],
            is_pvp=is_pvp,
            killers=d["killers"],
            monster=d["monster"],
        )

    state[name] = current_keys[:MAX_KEYS_PER_CHAR]


def main():
    print(f"Checando mortes da guild em: {GUILD_URL}")
    try:
        members = fetch_guild_members()
    except Exception as e:
        print("[ERRO] Falha ao buscar membros da guild:", e)
        raise

    state = load_state()

    for name, vocation in members.items():
        process_character(name, vocation, state)
        time.sleep(0.5)

    save_state(state)
    print(f"[OK] Checagem de mortes concluida - {len(members)} personagens verificados.")


if __name__ == "__main__":
    main()
