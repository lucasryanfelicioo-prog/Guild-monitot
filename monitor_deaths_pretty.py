"""
Bot de mortes + war - Naruto Vikings (NTO)
Monitora as mortes de AKATSUKI (nos) e NIRVANA (eles). Mortes normais (PvE ou
PvP contra gente de fora) geram um embed individual, como sempre.

Mortes onde o assassino e da guild rival contam como "war kill" - mas em vez
de mandar um embed por kill, o bot agrupa em SESSOES: quando comeca uma
sequencia de war kills, mantem uma mensagem "AO VIVO" sendo editada com o
placar da sessao. Quando passa um tempo sem nenhum war kill novo, a sessao e
encerrada e um resumo final e postado. Assim cada "war" vira um placar
proprio, sem misturar com a war da semana passada.

Na PRIMEIRA vez que o bot roda (deploy novo), se ja existir uma guerra em
andamento visivel nas paginas dos personagens, ele posta um resumo unico de
"backfill" (so uma vez) e depois passa a rodar normal.
"""

import requests
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# ==================== CONFIGURACAO ====================

WEBHOOK_URL = os.environ.get(
    "DEATH_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1537727788243746900/JIXI06TtDr44HhH9BSQrDvJKxCWupj3vrNXlNABPVm44XIqRd2jjnO4ZYFJMDRiw4-7D",
)

# webhook separado so pra mensagens de WAR (ao vivo / encerrada / resumo inicial)
WAR_WEBHOOK_URL = os.environ.get(
    "WAR_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1538361770303946823/_X-33nsri3hElnRbADABgoDYRi5iilNysHCu_9cohha_v5hkGUsVT2nY0GkVXoRN0Nj1",
)

GUILD_US_URL = os.environ.get("GUILD_US_URL", "https://ntovikings.com/guilds/A+K+A+T+S+U+K+I")
GUILD_THEM_URL = os.environ.get("GUILD_THEM_URL", "https://ntovikings.com/guilds/N+I+R+V+A+N+A")
GUILD_US_NAME = "AKATSUKI"
GUILD_THEM_NAME = "NIRVANA"

BASE_CHARACTER_URL = "https://ntovikings.com/characters/"
PORTRAIT_BASE_URL = "https://ntovikings.com/templates/naruto_vikings/assets/Portrait/"

DEATH_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "death_state.json")
WAR_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "war_state.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GuildMonitorBot/1.0)"}

MAX_KEYS_PER_CHAR = 40

COLOR_PVP = 0xC0392B
COLOR_PVE = 0x8E5A2E
COLOR_WAR_LIVE = 0xF1C40F
COLOR_WAR_FINAL = 0x9B59B6
COLOR_ALERT = 0xFF0000

# se ficar mais que isso sem nenhum war kill novo, a sessao de war e considerada encerrada
SESSION_GAP_MINUTES = int(os.environ.get("WAR_SESSION_GAP_MINUTES", "20"))

# so vira "war de verdade" (e comeca a postar no Discord) quando passar desse
# numero de kills dentro da janela curta abaixo. Antes disso fica em silencio.
MIN_KILLS_TO_DECLARE_WAR = int(os.environ.get("WAR_MIN_KILLS", "5"))
TRIGGER_WINDOW_MINUTES = int(os.environ.get("WAR_TRIGGER_WINDOW_MINUTES", "10"))

# Resumo da war de 16/08 23:06-23:23, calculado manualmente a partir do
# historico que o dono do bot colou. Enviado automaticamente SO na primeira
# vez que o bot roda (deploy novo), sem precisar re-raspar o site pra achar
# essa war de novo (ela ja pode ter saido da lista de mortes recentes).
KNOWN_BACKFILL_SCORE = {"us": 26, "them": 7}
KNOWN_BACKFILL_STATS = {
    "kills": {"Hiizzo": 25, "Brabinho": 24, "Legacy": 21, "Tuff": 15, "Pk Oshh": 6},
    "deaths": {"Saikopasu": 7, "Pk Oshh": 5, "Scooby": 5, "Tsukuyomi Infinito": 5, "Will": 4},
}
KNOWN_BACKFILL_TITLE = "🏁 Resumo da War (23:06 às 23:23 de 16/08)"


# ==================== DISCORD ====================

def send_discord_message(payload, webhook_url=None):
    url = webhook_url or WEBHOOK_URL
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code >= 300:
            print(f"[AVISO] Discord retornou status {r.status_code}: {r.text}")
    except Exception as e:
        print("[ERRO] Falha ao enviar para o Discord:", e)


def post_or_edit_webhook_message(payload, message_id=None, webhook_url=None):
    url_base = webhook_url or WEBHOOK_URL
    try:
        if message_id:
            url = f"{url_base}/messages/{message_id}"
            r = requests.patch(url, json=payload, timeout=10)
            if r.status_code >= 300:
                print(f"[AVISO] Falha ao editar mensagem ({r.status_code}): {r.text}")
                return None
            return message_id
        else:
            url = f"{url_base}?wait=true"
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code >= 300:
                print(f"[AVISO] Falha ao criar mensagem ({r.status_code}): {r.text}")
                return None
            return r.json().get("id")
    except Exception as e:
        print("[ERRO] Falha ao comunicar com o Discord:", e)
        return None


def send_normal_death_embed(name, vocation, level, date_text, is_pvp, killers=None, monster=None):
    thumbnail_url = PORTRAIT_BASE_URL + urllib.parse.quote(vocation) + ".png" if vocation else None

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
        }
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}
    send_discord_message({"embeds": [embed]})


def build_war_embed(score, stats, live=True, duration_text=None):
    score_us = score["us"]
    score_them = score["them"]

    if score_us > score_them:
        status = f"🏆 **{GUILD_US_NAME}** está na frente!"
    elif score_them > score_us:
        status = f"🏆 **{GUILD_THEM_NAME}** está na frente!"
    else:
        status = "⚖️ Empate!"

    top_killers = sorted(stats.get("kills", {}).items(), key=lambda x: -x[1])[:5]
    top_deaths = sorted(stats.get("deaths", {}).items(), key=lambda x: -x[1])[:5]

    fields = []
    if top_killers:
        killers_text = "\n".join(f"🗡️ **{n}** — {c}" for n, c in top_killers)
        fields.append({"name": "🏅 Top Assassinos", "value": killers_text, "inline": True})
    if top_deaths:
        deaths_text = "\n".join(f"💀 **{n}** — {c}" for n, c in top_deaths)
        fields.append({"name": "☠️ Mais Mortos", "value": deaths_text, "inline": True})

    if live:
        title = "⚔️ WAR EM ANDAMENTO"
        color = COLOR_WAR_LIVE
        footer_text = f"Atualizado automaticamente • encerra sozinha após {SESSION_GAP_MINUTES} min sem kills novos"
    else:
        title = "🏁 War Encerrada"
        color = COLOR_WAR_FINAL
        footer_text = duration_text or "War finalizada"

    return {
        "title": title,
        "description": f"## {GUILD_US_NAME}  `{score_us}`  x  `{score_them}`  {GUILD_THEM_NAME}\n\n{status}",
        "color": color,
        "fields": fields,
        "footer": {"text": footer_text},
    }


def build_backfill_embed(score, stats, title="🏁 Resumo da War (encontrada na primeira ativação)"):
    score_us = score["us"]
    score_them = score["them"]
    top_killers = sorted(stats.get("kills", {}).items(), key=lambda x: -x[1])[:5]
    top_deaths = sorted(stats.get("deaths", {}).items(), key=lambda x: -x[1])[:5]

    fields = []
    if top_killers:
        killers_text = "\n".join(f"🗡️ **{n}** — {c}" for n, c in top_killers)
        fields.append({"name": "🏅 Top Assassinos", "value": killers_text, "inline": True})
    if top_deaths:
        deaths_text = "\n".join(f"💀 **{n}** — {c}" for n, c in top_deaths)
        fields.append({"name": "☠️ Mais Mortos", "value": deaths_text, "inline": True})

    return {
        "title": title,
        "description": f"## {GUILD_US_NAME}  `{score_us}`  x  `{score_them}`  {GUILD_THEM_NAME}",
        "color": COLOR_WAR_FINAL,
        "fields": fields,
        "footer": {"text": "Baseado no historico visivel no momento da ativação • daqui pra frente, so sessoes novas"},
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
            "date": date_part, "description": desc_part, "killers": killers,
            "level": level, "monster": monster,
        })
    return deaths


def death_key(death):
    return f"{death['date']}|{death['description']}"


# ==================== ESTADO ====================

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def empty_stats():
    return {"kills": {}, "deaths": {}}


def default_war_state():
    return {
        "initial_backfill_done": False,
        "pending": {"events": []},
        "session": {
            "active": False,
            "score": {"us": 0, "them": 0},
            "stats": empty_stats(),
            "last_kill_detected_at": None,
            "message_id": None,
        },
    }


# ==================== LOGICA PRINCIPAL ====================

def process_character(name, vocation, side, death_state, rival_set, war_events, is_first_run_for_char):
    """
    Processa um personagem. Mortes normais sao notificadas na hora (exceto na
    primeira vez que o personagem e visto, que so salva baseline). War kills
    NAO sao notificadas aqui - sao devolvidas em war_events pra logica de
    sessao decidir o que fazer.
    """
    try:
        deaths = fetch_character_deaths(name)
    except Exception as e:
        print(f"[ERRO] Falha ao buscar mortes de {name}: {e}")
        return

    if not deaths:
        return

    current_keys = [death_key(d) for d in deaths]
    known_keys = set(death_state.get(name, []))

    if name not in death_state:
        # primeira vez vendo esse personagem: salva baseline
        death_state[name] = current_keys[:MAX_KEYS_PER_CHAR]
        if is_first_run_for_char:
            # no deploy inicial, ainda assim queremos ver se ha war kills
            # visiveis pra fazer o backfill (mas sem notificar individualmente)
            for d in deaths:
                if not d["killers"]:
                    continue
                rival_killers = [k for k in d["killers"] if k in rival_set]
                if rival_killers:
                    war_events.append({"victim": name, "side": side, "killers": rival_killers})
        return

    new_deaths = [d for d in reversed(deaths) if death_key(d) not in known_keys]

    for d in new_deaths:
        is_pvp = bool(d["killers"])

        if not is_pvp:
            if side == "them":  # so notifica morte normal (PvE) dos inimigos, nao dos nossos
                send_normal_death_embed(name, vocation, d["level"], d["date"], False, monster=d["monster"])
            continue

        rival_killers = [k for k in d["killers"] if k in rival_set]

        if rival_killers:
            war_events.append({"victim": name, "side": side, "killers": rival_killers})
        elif side == "them":  # so notifica PvP normal (fora da war) dos inimigos, nao dos nossos
            send_normal_death_embed(name, vocation, d["level"], d["date"], True, killers=d["killers"])

    death_state[name] = current_keys[:MAX_KEYS_PER_CHAR]


def apply_war_events(war_events, score, stats):
    for ev in war_events:
        if ev["side"] == "us":
            score["them"] += 1
        else:
            score["us"] += 1
        for k in ev["killers"]:
            stats["kills"][k] = stats["kills"].get(k, 0) + 1
        stats["deaths"][ev["victim"]] = stats["deaths"].get(ev["victim"], 0) + 1


def main():
    print("Checando mortes + war (AKATSUKI x NIRVANA)...")

    is_very_first_run = not os.path.exists(DEATH_STATE_FILE)

    us_members = fetch_guild_members(GUILD_US_URL)
    them_members = fetch_guild_members(GUILD_THEM_URL)
    us_set = set(us_members.keys())
    them_set = set(them_members.keys())

    death_state = load_json(DEATH_STATE_FILE, {})
    war_state = load_json(WAR_STATE_FILE, default_war_state())
    war_state.setdefault("initial_backfill_done", False)
    war_state.setdefault("pending", {"events": []})
    war_state.setdefault("session", default_war_state()["session"])

    war_events = []

    for name, vocation in us_members.items():
        process_character(name, vocation, "us", death_state, them_set, war_events, is_very_first_run)
        time.sleep(0.35)

    for name, vocation in them_members.items():
        process_character(name, vocation, "them", death_state, us_set, war_events, is_very_first_run)
        time.sleep(0.35)

    save_json(DEATH_STATE_FILE, death_state)

    now = datetime.now(timezone.utc)

    # ===== CASO 1: primeira ativacao -> manda o resumo ja calculado (fixo) =====
    if is_very_first_run and not war_state["initial_backfill_done"]:
        embed = build_backfill_embed(KNOWN_BACKFILL_SCORE, KNOWN_BACKFILL_STATS, title=KNOWN_BACKFILL_TITLE)
        send_discord_message({"embeds": [embed]}, webhook_url=WAR_WEBHOOK_URL)

        war_state["initial_backfill_done"] = True
        save_json(WAR_STATE_FILE, war_state)
        print(f"[OK] Backfill inicial (fixo) postado - {GUILD_US_NAME} {KNOWN_BACKFILL_SCORE['us']} x {KNOWN_BACKFILL_SCORE['them']} {GUILD_THEM_NAME}")
        return

    war_state["initial_backfill_done"] = True  # nao faz backfill de novo, mesmo que essa 1a rodada nao tivesse war

    session = war_state["session"]
    pending = war_state["pending"]

    # ===== CASO 2: tem war kills novos agora =====
    if war_events:
        if session["active"]:
            # ja tinha guerra declarada -> so soma normal
            last_detected = session.get("last_kill_detected_at")
            gap_minutes = None
            if last_detected:
                try:
                    last_dt = datetime.fromisoformat(last_detected)
                    gap_minutes = (now - last_dt).total_seconds() / 60
                except ValueError:
                    gap_minutes = None

            if gap_minutes is not None and gap_minutes > SESSION_GAP_MINUTES:
                # a "sessao ativa" na verdade ja tinha esfriado - trata como nova guerra
                session["active"] = False
                session["score"] = {"us": 0, "them": 0}
                session["stats"] = empty_stats()
                session["message_id"] = None

        if session["active"]:
            apply_war_events(war_events, session["score"], session["stats"])
            session["last_kill_detected_at"] = now.isoformat()

            embed = build_war_embed(session["score"], session["stats"], live=True)
            message_id = post_or_edit_webhook_message({"embeds": [embed]}, message_id=session.get("message_id"), webhook_url=WAR_WEBHOOK_URL)
            if message_id:
                session["message_id"] = message_id

            print(f"[OK] {len(war_events)} war kill(s) nova(s). Sessao ativa: {GUILD_US_NAME} {session['score']['us']} x {session['score']['them']} {GUILD_THEM_NAME}")
        else:
            # ainda nao foi declarada guerra - acumula no buffer de espera (silencioso)
            for ev in war_events:
                ev["detected_at"] = now.isoformat()
                pending["events"].append(ev)

            # remove do buffer eventos fora da janela curta
            fresh_events = []
            for ev in pending["events"]:
                try:
                    ev_dt = datetime.fromisoformat(ev["detected_at"])
                except ValueError:
                    continue
                if (now - ev_dt).total_seconds() / 60 <= TRIGGER_WINDOW_MINUTES:
                    fresh_events.append(ev)
            pending["events"] = fresh_events

            if len(pending["events"]) > MIN_KILLS_TO_DECLARE_WAR:
                # passou do limite -> declara guerra AGORA, com tudo que tava no buffer
                session["active"] = True
                session["score"] = {"us": 0, "them": 0}
                session["stats"] = empty_stats()
                session["message_id"] = None

                apply_war_events(pending["events"], session["score"], session["stats"])
                session["last_kill_detected_at"] = now.isoformat()
                pending["events"] = []

                embed = build_war_embed(session["score"], session["stats"], live=True)
                message_id = post_or_edit_webhook_message({"embeds": [embed]}, webhook_url=WAR_WEBHOOK_URL)
                if message_id:
                    session["message_id"] = message_id

                print(f"[OK] Guerra DECLARADA! {GUILD_US_NAME} {session['score']['us']} x {session['score']['them']} {GUILD_THEM_NAME}")
            else:
                print(f"[OK] {len(war_events)} kill(s) suspeita(s) - {len(pending['events'])}/{MIN_KILLS_TO_DECLARE_WAR + 1} pra declarar guerra (aguardando).")

    # ===== CASO 3: sem war kills novos - checa se uma sessao ativa deve encerrar =====
    elif session["active"]:
        last_detected = session.get("last_kill_detected_at")
        gap_minutes = None
        if last_detected:
            try:
                last_dt = datetime.fromisoformat(last_detected)
                gap_minutes = (now - last_dt).total_seconds() / 60
            except ValueError:
                gap_minutes = None

        if gap_minutes is not None and gap_minutes > SESSION_GAP_MINUTES:
            embed = build_war_embed(session["score"], session["stats"], live=False)
            post_or_edit_webhook_message({"embeds": [embed]}, message_id=session.get("message_id"), webhook_url=WAR_WEBHOOK_URL)

            print(f"[OK] War encerrada - placar final {GUILD_US_NAME} {session['score']['us']} x {session['score']['them']} {GUILD_THEM_NAME}")

            session["active"] = False
            session["score"] = {"us": 0, "them": 0}
            session["stats"] = empty_stats()
            session["message_id"] = None
        else:
            print("[OK] Nenhuma war kill nova. Sessao continua ativa (dentro da janela de tolerancia).")
    else:
        print("[OK] Nenhuma war kill nova. Sem sessao ativa.")

    war_state["session"] = session
    war_state["pending"] = pending
    save_json(WAR_STATE_FILE, war_state)


if __name__ == "__main__":
    main()
