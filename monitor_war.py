"""
Monitor de War - AKATSUKI x NIRVANA (NTO)
Cruza as mortes dos membros das duas guilds: quando um membro de uma guild
morre para um membro da outra, conta como ponto de war. So considera mortes
recentes (janela de tempo configuravel). Mantem um placar fixo (edita
a mesma mensagem) e manda um embed por kill de war.
"""

import requests
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

# O site mostra as datas de morte no fuso da Europa (CEST/CET) - usamos o
# mesmo fuso pra calcular quanto tempo faz desde a morte.
SITE_TIMEZONE = ZoneInfo("Europe/Berlin")

# So conta mortes que aconteceram nos ultimos X minutos (janela da war "ao vivo")
WAR_WINDOW_MINUTES = int(os.environ.get("WAR_WINDOW_MINUTES", "60"))

# Dispara um alerta com @everyone quando o numero de kills na janela passar disso
ALERT_THRESHOLD = int(os.environ.get("WAR_ALERT_THRESHOLD", "6"))

# ==================== CONFIGURACAO ====================

WEBHOOK_URL = os.environ.get(
    "WAR_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1538361770303946823/_X-33nsri3hElnRbADABgoDYRi5iilNysHCu_9cohha_v5hkGUsVT2nY0GkVXoRN0Nj1",
)

GUILD_US_URL = os.environ.get("GUILD_US_URL", "https://ntovikings.com/guilds/A+K+A+T+S+U+K+I")
GUILD_THEM_URL = os.environ.get("GUILD_THEM_URL", "https://ntovikings.com/guilds/N+I+R+V+A+N+A")
GUILD_US_NAME = "AKATSUKI"
GUILD_THEM_NAME = "NIRVANA"

BASE_CHARACTER_URL = "https://ntovikings.com/characters/"

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "war_state.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GuildMonitorBot/1.0)"}

COLOR_US_WIN = 0x2ECC71
COLOR_THEM_WIN = 0xC0392B
COLOR_SCOREBOARD = 0xF1C40F

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


# ==================== FILTRO DE TEMPO (JANELA DA WAR) ====================

def parse_death_datetime(date_text):
    """Converte 'Aug 15 2026, 22:26 CEST' num datetime com fuso."""
    match = re.search(r"([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4}),\s*(\d{1,2}):(\d{2})", date_text)
    if not match:
        return None
    month_str, day_str, year_str, hour_str, minute_str = match.groups()
    month = MONTHS.get(month_str.lower())
    if not month:
        return None
    try:
        return datetime(
            int(year_str), month, int(day_str), int(hour_str), int(minute_str),
            tzinfo=SITE_TIMEZONE,
        )
    except ValueError:
        return None


def is_recent(date_text, window_minutes=WAR_WINDOW_MINUTES):
    """Verifica se a morte aconteceu dentro da janela de tempo (war 'ao vivo')."""
    dt = parse_death_datetime(date_text)
    if dt is None:
        return False
    now = datetime.now(SITE_TIMEZONE)
    diff = now - dt
    return timedelta(0) <= diff <= timedelta(minutes=window_minutes)


# ==================== DISCORD ====================

def post_or_edit_webhook_message(payload, message_id=None):
    try:
        if message_id:
            url = f"{WEBHOOK_URL}/messages/{message_id}"
            r = requests.patch(url, json=payload, timeout=10)
            if r.status_code >= 300:
                print(f"[AVISO] Falha ao editar mensagem ({r.status_code}): {r.text}")
                return None
            return message_id
        else:
            url = f"{WEBHOOK_URL}?wait=true"
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code >= 300:
                print(f"[AVISO] Falha ao criar mensagem ({r.status_code}): {r.text}")
                return None
            return r.json().get("id")
    except Exception as e:
        print("[ERRO] Falha ao comunicar com o Discord:", e)
        return None


def send_war_kill_embed(victim, victim_side, killers, date_text, level, score_us, score_them):
    us_won = victim_side == "them"
    color = COLOR_US_WIN if us_won else COLOR_THEM_WIN
    killer_guild = GUILD_US_NAME if us_won else GUILD_THEM_NAME
    victim_guild = GUILD_THEM_NAME if us_won else GUILD_US_NAME
    killers_str = "\n".join(f"⚔️ **{k}**" for k in killers)

    embed = {
        "title": "⚔️ War Kill",
        "description": f"**{killer_guild}** abateu um membro da **{victim_guild}**!",
        "color": color,
        "fields": [
            {"name": "Vítima", "value": f"**{victim}** ({victim_guild})", "inline": True},
            {"name": "Nível", "value": f"**{level}**", "inline": True},
            {"name": "Quando", "value": date_text, "inline": False},
            {"name": "Assassino(s)", "value": killers_str, "inline": False},
        ],
        "footer": {"text": f"Placar atual: {GUILD_US_NAME} {score_us} x {score_them} {GUILD_THEM_NAME}"},
    }
    post_or_edit_webhook_message({"embeds": [embed]})


def send_war_alert(window_count, window_minutes):
    embed = {
        "title": "🚨 WAR ATIVA! 🚨",
        "description": (
            f"**{window_count} kills** entre as guilds nos últimos **{window_minutes} minutos**!\n"
            f"Bora pra guerra! ⚔️"
        ),
        "color": 0xFF0000,
    }
    post_or_edit_webhook_message({"content": "@everyone", "embeds": [embed]})


def build_scoreboard_embed(score_us, score_them, top_killers=None, top_deaths=None):
    if score_us > score_them:
        status = f"🏆 **{GUILD_US_NAME}** está na frente!"
    elif score_them > score_us:
        status = f"🏆 **{GUILD_THEM_NAME}** está na frente!"
    else:
        status = "⚖️ Empate!"

    fields = []
    if top_killers:
        killers_text = "\n".join(f"🗡️ **{name}** — {count} kill(s)" for name, count in top_killers)
        fields.append({"name": "🏅 Top Assassinos", "value": killers_text or "—", "inline": True})
    if top_deaths:
        deaths_text = "\n".join(f"💀 **{name}** — {count} morte(s)" for name, count in top_deaths)
        fields.append({"name": "☠️ Mais Mortos", "value": deaths_text or "—", "inline": True})

    return {
        "title": "📊 Placar da War",
        "description": (
            f"## {GUILD_US_NAME}  `{score_us}`  x  `{score_them}`  {GUILD_THEM_NAME}\n\n{status}"
        ),
        "color": COLOR_SCOREBOARD,
        "fields": fields,
        "footer": {"text": f"Conta mortes dos ultimos {WAR_WINDOW_MINUTES} min • Atualizado automaticamente"},
    }


# ==================== SCRAPER: MEMBROS DA GUILD ====================

def fetch_guild_members(guild_url):
    resp = requests.get(guild_url, headers=HEADERS, timeout=15)
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
        raise RuntimeError(f"Nao encontrei a tabela de membros em {guild_url}.")

    names = []
    for row in members_table.find_all("tr"):
        link = row.find("a", href=lambda h: h and "/characters/" in h)
        if link:
            names.append(link.get_text(strip=True))
    return names


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
        deaths.append({"date": date_part, "description": desc_part, "killers": killers, "level": level})

    return deaths


def death_key(death):
    return f"{death['date']}|{death['description']}"


# ==================== ESTADO ====================

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("kill_log", {})  # key -> data_iso
            data.setdefault("stats", {"kills": {}, "deaths": {}})
            data.setdefault("alert_active", False)
            return data
    return {
        "score": {"us": 0, "them": 0},
        "counted_keys": [],
        "scoreboard_message_id": None,
        "kill_log": {},
        "stats": {"kills": {}, "deaths": {}},
        "alert_active": False,
    }


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ==================== LOGICA PRINCIPAL ====================

def collect_war_kills(victims, rival_names_set, victim_side):
    kills = []
    for victim in victims:
        try:
            deaths = fetch_character_deaths(victim)
        except Exception as e:
            print(f"[ERRO] Falha ao buscar mortes de {victim}: {e}")
            continue

        for d in deaths:
            if not d["killers"]:
                continue
            if not is_recent(d["date"]):
                continue  # ignora mortes fora da janela de tempo da war
            rival_killers = [k for k in d["killers"] if k in rival_names_set]
            if rival_killers:
                kills.append({
                    "victim": victim,
                    "victim_side": victim_side,
                    "killers": rival_killers,
                    "date": d["date"],
                    "level": d["level"],
                    "key": f"{victim}|{death_key(d)}",
                })
        time.sleep(0.4)
    return kills


def main():
    print("Checando war AKATSUKI x NIRVANA (janela de tempo)...")

    us_members = fetch_guild_members(GUILD_US_URL)
    them_members = fetch_guild_members(GUILD_THEM_URL)

    us_set = set(us_members)
    them_set = set(them_members)

    kills_for_us = collect_war_kills(them_members, us_set, victim_side="them")
    kills_for_them = collect_war_kills(us_members, them_set, victim_side="us")

    all_kills = kills_for_us + kills_for_them

    state = load_state()
    counted = set(state.get("counted_keys", []))
    score = state.get("score", {"us": 0, "them": 0})
    kill_log = state.get("kill_log", {})
    stats = state.get("stats", {"kills": {}, "deaths": {}})

    new_kills = [k for k in all_kills if k["key"] not in counted]

    for k in new_kills:
        if k["victim_side"] == "them":
            score["us"] += 1
        else:
            score["them"] += 1

        for killer_name in k["killers"]:
            stats["kills"][killer_name] = stats["kills"].get(killer_name, 0) + 1
        stats["deaths"][k["victim"]] = stats["deaths"].get(k["victim"], 0) + 1

        send_war_kill_embed(
            victim=k["victim"],
            victim_side=k["victim_side"],
            killers=k["killers"],
            date_text=k["date"],
            level=k["level"],
            score_us=score["us"],
            score_them=score["them"],
        )
        counted.add(k["key"])

        dt = parse_death_datetime(k["date"])
        if dt:
            kill_log[k["key"]] = dt.isoformat()

        time.sleep(0.5)

    # limpa entradas antigas do kill_log (fora da janela) e conta quantas estao ativas agora
    now = datetime.now(SITE_TIMEZONE)
    active_count = 0
    pruned_kill_log = {}
    for key, iso in kill_log.items():
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            continue
        if timedelta(0) <= (now - dt) <= timedelta(minutes=WAR_WINDOW_MINUTES):
            pruned_kill_log[key] = iso
            active_count += 1
    kill_log = pruned_kill_log

    # dispara o alerta se passou do limite e ainda nao tinha disparado pra essa "onda"
    if active_count > ALERT_THRESHOLD and not state.get("alert_active", False):
        send_war_alert(active_count, WAR_WINDOW_MINUTES)
        state["alert_active"] = True
    elif active_count <= ALERT_THRESHOLD:
        state["alert_active"] = False

    top_killers = sorted(stats["kills"].items(), key=lambda x: -x[1])[:3]
    top_deaths = sorted(stats["deaths"].items(), key=lambda x: -x[1])[:3]

    if new_kills or state.get("scoreboard_message_id") is None:
        scoreboard_embed = build_scoreboard_embed(score["us"], score["them"], top_killers, top_deaths)
        message_id = post_or_edit_webhook_message(
            {"embeds": [scoreboard_embed]}, message_id=state.get("scoreboard_message_id")
        )
        if message_id:
            state["scoreboard_message_id"] = message_id

    state["counted_keys"] = list(counted)[-500:]
    state["score"] = score
    state["kill_log"] = kill_log
    state["stats"] = stats
    save_state(state)

    print(f"[OK] War checada - {len(new_kills)} kill(s) nova(s). Ativos na janela: {active_count}. Placar: {GUILD_US_NAME} {score['us']} x {score['them']} {GUILD_THEM_NAME}")


if __name__ == "__main__":
    main()
