"""Yatzy-protokoll – Streamlit + Supabase (mobiloptimerad, v3).

Svensk Yatzy, 5 tärningar, 15 rutor, bonus 50 p vid 63 p i övre delen.
Utan Supabase-nycklar körs appen i offline-läge (inget sparas till molnet).
"""

import base64
import html
import json
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_js_eval import streamlit_js_eval
from supabase import Client, create_client

# OBS: måste vara första Streamlit-anropet
st.set_page_config(
    page_title="Yatzy-protokoll",
    page_icon="🎲",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ----------------------------------------------------------------------------
# Databas-nycklar (offline-läge om de saknas)
# ----------------------------------------------------------------------------
try:
    SUPABASE_URL = st.secrets.get("SUPABASE_URL", None)
    SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", None)
except Exception:
    SUPABASE_URL = SUPABASE_KEY = None
DB_ENABLED = bool(SUPABASE_URL and SUPABASE_KEY)

# ----------------------------------------------------------------------------
# Konstanter
# ----------------------------------------------------------------------------
TZ = ZoneInfo("Europe/Stockholm")
BONUS_LIMIT = 63
BONUS_POINTS = 50
MAX_PLAYERS = 6
LS_KEY = "yatzy_names"
AVATAR_DIR = Path(__file__).parent / "avatars"
GUEST_PICK = ""
CREATE_PICK = "__new__"
PRESETS = [
    ("dice", "Tärning"),
    ("cat", "Katt"),
    ("boat", "Båt"),
    ("crown", "Krona"),
    ("fox", "Räv"),
    ("owl", "Uggla"),
    ("mushroom", "Svamp"),
    ("star", "Stjärna"),
    ("fish", "Fisk"),
    ("moon", "Måne"),
    ("flower", "Blomma"),
    ("penguin", "Pingvin"),
]

UPPER = [
    ("ones", "Ettor", 1),
    ("twos", "Tvåor", 2),
    ("threes", "Treor", 3),
    ("fours", "Fyror", 4),
    ("fives", "Femmor", 5),
    ("sixes", "Sexor", 6),
]
LOWER = [
    ("pair", "Ett par"),
    ("two_pairs", "Två par"),
    ("three", "Triss"),
    ("four", "Fyrtal"),
    ("small", "Liten stege"),
    ("large", "Stor stege"),
    ("house", "Kåk"),
    ("chance", "Chans"),
    ("yatzy", "Yatzy"),
]
ALL_CATS = [k for k, _, _ in UPPER] + [k for k, _ in LOWER]
LABELS = {k: l for k, l, _ in UPPER} | {k: l for k, l in LOWER}
UPPER_VALUE = {k: v for k, _, v in UPPER}
MULT = {"pair": 2, "three": 3, "four": 4}  # antal lika tärningar
FIXED = {"small": (15, [1, 2, 3, 4, 5]), "large": (20, [2, 3, 4, 5, 6]), "yatzy": (50, [6] * 5)}

GREEN, RED, MUTED = "var(--green)", "var(--red)", "var(--muted)"


def sbutton(target, label, **kw):
    """st.button som alltid fyller hela kolumnens bredd."""
    try:
        return target.button(label, width="stretch", **kw)
    except TypeError:
        return target.button(label, use_container_width=True, **kw)


def spopover(target, label):
    try:
        return target.popover(label, width="stretch")
    except TypeError:
        return target.popover(label, use_container_width=True)


# ----------------------------------------------------------------------------
# Supabase
# ----------------------------------------------------------------------------
@st.cache_resource
def sb() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_open_games() -> list[dict]:
    """Ofärdiga partier, nyast först. Högst åtta."""
    if not DB_ENABLED:
        return []
    try:
        res = (
            sb().table("active_games")
            .select("id,state,updated_at")
            .order("updated_at", desc=True)
            .limit(30)
            .execute()
        )
    except Exception:
        return []
    games = []
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=7)
    for row in res.data or []:
        stamp = row.get("updated_at")
        try:
            if not stamp or pd.to_datetime(stamp, utc=True) < cutoff:
                continue
        except Exception:
            continue
        state = row.get("state") or {}
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except Exception:
                continue
        if not isinstance(state, dict) or state.get("finished") or not state.get("players"):
            continue
        state["id"] = state.get("id") or row["id"]
        state["_updated_at"] = row.get("updated_at")
        games.append(state)
        if len(games) >= 8:
            break
    return games


def resume_label(state: dict) -> str:
    names = ", ".join(state.get("players") or [])
    scores = state.get("scores") or []
    done = min((len(sc) for sc in scores), default=0)
    runda = min(done + 1, len(ALL_CATS))
    return f"{names} · runda {runda}/{len(ALL_CATS)}"


_SHORT_MONTHS = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def open_when(stamp) -> str:
    """Igår med klockslag, annars dag och månad."""
    if not stamp:
        return ""
    dt = pd.to_datetime(stamp, utc=True).tz_convert(TZ)
    if dt.date() == datetime.now(TZ).date() - timedelta(days=1):
        return f"Igår {dt.strftime('%H:%M')}"
    return f"{dt.day} {_SHORT_MONTHS[dt.month - 1]}"


def open_round(state: dict) -> int:
    scores = state.get("scores") or []
    done = min((len(sc) for sc in scores), default=0)
    return min(done + 1, len(ALL_CATS))


def begin_new_player(seat: int | None):
    """Öppnar samma formulär som Ny spelare. seat är platsen på startsidan."""
    if seat is None:
        st.session_state.pop("seat_create", None)
    else:
        st.session_state["seat_create"] = seat
    st.session_state.page = "players"
    st.session_state["player_form"] = "new"
    st.session_state["player_open"] = None
    for key in ("pname_new", "avpick_new", "up_new"):
        st.session_state.pop(key, None)
    st.rerun()


def load_game(gid: str):
    """Hämtar ett pågående spel från databasen (None om det saknas)."""
    if not DB_ENABLED:
        return None
    try:
        res = sb().table("active_games").select("state").eq("id", gid).execute()
        return res.data[0]["state"] if res.data else None
    except Exception:
        return None


def persist():
    if not DB_ENABLED:
        return
    s = st.session_state.state
    try:
        sb().table("active_games").upsert(
            {"id": s["id"], "state": s, "updated_at": now_utc_iso()}
        ).execute()
    except Exception as e:
        st.toast(f"⚠️ Kunde inte spara spelet i databasen: {e}")


def cleanup_old_games():
    if not DB_ENABLED:
        return
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        sb().table("active_games").delete().lt("updated_at", cutoff).execute()
    except Exception:
        pass


def save_scores(state) -> bool:
    if not DB_ENABLED:
        return False
    rows = build_score_rows(state)
    try:
        sb().table("scores").delete().eq("game_id", state["id"]).execute()
        insert_score_rows(rows)
        get_highscores.clear()
        list_score_months.clear()
        return True
    except Exception as e:
        st.toast(f"⚠️ Kunde inte spara High Score: {e}")
        return False


def _utc_stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=TZ)
    end = datetime(year + 1, 1, 1, tzinfo=TZ) if month == 12 else datetime(year, month + 1, 1, tzinfo=TZ)
    return start, end


@st.cache_data(ttl=60, show_spinner=False)
def list_score_months() -> list[tuple[int, int]]:
    """År och månad som har sparade resultat, nyast först."""
    res = sb().table("scores").select("played_at").order("played_at", desc=True).execute()
    seen: list[tuple[int, int]] = []
    for row in res.data or []:
        dt = pd.to_datetime(row["played_at"], utc=True).tz_convert(TZ)
        key = (int(dt.year), int(dt.month))
        if key not in seen:
            seen.append(key)
    return seen


@st.cache_data(ttl=60, show_spinner=False)
def get_highscores(year: int | None = None, month: int | None = None):
    q = sb().table("scores").select("game_id,player_name,score,played_at")
    if year is not None and month is not None:
        start, end = month_bounds(year, month)
        q = q.gte("played_at", _utc_stamp(start)).lt("played_at", _utc_stamp(end))
    res = q.order("score", desc=True).order("played_at", desc=False).limit(25).execute()
    return res.data


def load_scorecard(game_id: str):
    """Alla spelare i ett avslutat spel, i samma ordning som på protokollet."""
    res = (
        sb().table("scores")
        .select("player_name,card,seat")
        .eq("game_id", game_id)
        .order("seat")
        .execute()
    )
    rows = res.data or []
    rows.sort(key=lambda c: (c.get("seat") is None, c.get("seat") or 0))
    return rows


# ----------------------------------------------------------------------------
# Spelare
# ----------------------------------------------------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def _list_players() -> list[dict]:
    res = (
        sb().table("players")
        .select("id,name,avatar_key,avatar_url")
        .order("name")
        .execute()
    )
    return res.data or []


def list_players() -> list[dict]:
    if not DB_ENABLED:
        return []
    try:
        rows = _list_players()
        st.session_state.pop("players_error", None)
        return rows
    except Exception as e:
        st.session_state["players_error"] = str(e)
        return []


def build_score_rows(state) -> list[dict]:
    ids = state.get("player_ids") or []
    by_name = {p["name"].casefold(): p["id"] for p in list_players()}
    rows = []
    for i, (name, sc) in enumerate(zip(state["players"], state["scores"])):
        pid = ids[i] if i < len(ids) and ids[i] else by_name.get(name.casefold())
        rows.append({
            "game_id": state["id"],
            "player_name": name,
            "score": total(sc),
            "seat": i,
            "card": {k: int(sc[k]) for k in ALL_CATS if k in sc},
            "player_id": pid,
        })
    return rows


def insert_score_rows(rows: list[dict]):
    try:
        sb().table("scores").insert(rows).execute()
    except Exception as e:
        if "player_id" not in str(e).lower():
            raise
        slim = [{k: v for k, v in row.items() if k != "player_id"} for row in rows]
        sb().table("scores").insert(slim).execute()


@st.cache_data(show_spinner=False)
def preset_uri(key: str) -> str:
    raw = (AVATAR_DIR / f"{key}.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def avatar_src(player: dict | None) -> str | None:
    if not player:
        return None
    if player.get("avatar_url"):
        return player["avatar_url"]
    key = player.get("avatar_key")
    if key and (AVATAR_DIR / f"{key}.png").exists():
        return preset_uri(key)
    return None


def avatar_file(player: dict | None):
    """Sökväg eller URL som st.image kan visa."""
    if not player:
        return None
    if player.get("avatar_url"):
        return player["avatar_url"]
    key = player.get("avatar_key")
    path = AVATAR_DIR / f"{key}.png"
    if key and path.exists():
        return str(path)
    return None


def roster_maps() -> tuple[dict, dict]:
    rows = list_players()
    return {p["id"]: p for p in rows}, {p["name"].casefold(): p for p in rows}


def player_record(state, index: int, by_id: dict, by_name: dict) -> dict | None:
    ids = state.get("player_ids") or []
    if index < len(ids) and ids[index] and ids[index] in by_id:
        return by_id[ids[index]]
    return by_name.get((state["players"][index] or "").casefold())


def square_jpeg(data: bytes) -> bytes:
    im = Image.open(BytesIO(data)).convert("RGBA")
    bg = Image.new("RGB", im.size, (244, 241, 222))
    bg.paste(im, mask=im.split()[-1])
    side = min(bg.size)
    left = (bg.width - side) // 2
    top = (bg.height - side) // 2
    bg = bg.crop((left, top, left + side, top + side))
    bg = bg.resize((256, 256), Image.Resampling.LANCZOS)
    buf = BytesIO()
    bg.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def upload_avatar(player_id: str, data: bytes) -> str:
    jpg = square_jpeg(data)
    path = f"{player_id}.jpg"
    store = sb().storage.from_("avatars")
    store.upload(path, jpg, file_options={"content-type": "image/jpeg", "upsert": "true"})
    url = store.get_public_url(path)
    stamp = int(datetime.now(timezone.utc).timestamp())
    join = "&" if "?" in url else "?"
    return f"{url}{join}v={stamp}"


def link_scores(player_id: str, name: str):
    (
        sb().table("scores")
        .update({"player_id": player_id})
        .is_("player_id", "null")
        .eq("player_name", name)
        .execute()
    )


def save_player(name: str, avatar_key: str | None, file_bytes: bytes | None, existing: dict | None) -> str:
    name = name.strip()
    payload = {"name": name, "avatar_key": avatar_key, "avatar_url": None}
    if existing and existing.get("avatar_url") and not avatar_key and not file_bytes:
        payload["avatar_url"] = existing["avatar_url"]
        payload["avatar_key"] = None
    try:
        if existing:
            pid = existing["id"]
            old = existing["name"]
            sb().table("players").update(payload).eq("id", pid).execute()
            if old != name:
                sb().table("scores").update({"player_name": name}).eq("player_id", pid).execute()
        else:
            res = sb().table("players").insert(payload).execute()
            pid = res.data[0]["id"]
        if file_bytes:
            url = upload_avatar(pid, file_bytes)
            sb().table("players").update({"avatar_url": url, "avatar_key": None}).eq("id", pid).execute()
        try:
            link_scores(pid, name)
        except Exception:
            pass
        get_highscores.clear()
        return pid
    finally:
        _list_players.clear()


def player_score_rows(player: dict) -> list[dict]:
    cols = "game_id,player_name,score,played_at,card,player_id"
    linked = sb().table("scores").select(cols).eq("player_id", player["id"]).execute().data or []
    legacy = (
        sb().table("scores").select(cols)
        .is_("player_id", "null")
        .eq("player_name", player["name"])
        .execute()
        .data or []
    )
    return linked + legacy


def count_wins(rows: list[dict]) -> int:
    mine: dict[str, int] = {}
    for row in rows:
        gid = row["game_id"]
        mine[gid] = max(mine.get(gid, 0), int(row["score"]))
    best: dict[str, int] = {}
    ids = list(mine)
    for i in range(0, len(ids), 80):
        chunk = ids[i:i + 80]
        found = sb().table("scores").select("game_id,score").in_("game_id", chunk).execute().data or []
        for row in found:
            gid = row["game_id"]
            best[gid] = max(best.get(gid, 0), int(row["score"] or 0))
    return sum(1 for gid, score in mine.items() if score == best.get(gid))


def card_numbers(card: dict) -> dict:
    return {k: int(v) for k, v in card.items() if k in LABELS}


# ----------------------------------------------------------------------------
# Spel-logik
# ----------------------------------------------------------------------------
def upper_stats(sc: dict):
    """(summa, avvikelse mot snitt 3 tärningar, antal ifyllda)"""
    filled = [(k, v) for k, _, v in UPPER if k in sc]
    s = sum(sc[k] for k, _ in filled)
    par = sum(3 * v for _, v in filled)
    return s, s - par, len(filled)


def bonus(sc: dict) -> int:
    return BONUS_POINTS if upper_stats(sc)[0] >= BONUS_LIMIT else 0


def total(sc: dict) -> int:
    lower = sum(sc[k] for k, _ in LOWER if k in sc)
    return upper_stats(sc)[0] + bonus(sc) + lower


def next_turn(state, from_p: int) -> int:
    n = len(state["players"])
    for step in range(1, n + 1):
        q = (from_p + step) % n
        if len(state["scores"][q]) < len(ALL_CATS):
            return q
    return from_p


def apply_score(p: int, cat: str, value):
    """value=None betyder 'Ledig' (rensa rutan)."""
    cur = st.session_state.state
    state = load_game(cur["id"]) or cur  # hämta senaste ifall en annan telefon ändrat
    sc = state["scores"][p]
    was_filled = cat in sc
    if value is None:
        if was_filled:
            del sc[cat]
            state["turn"] = p
    else:
        sc[cat] = value
        if not was_filled:
            state["turn"] = next_turn(state, p)

    if not state["finished"] and all(len(x) == len(ALL_CATS) for x in state["scores"]):
        state["finished"] = True
        state["saved"] = save_scores(state)

    st.session_state.state = state
    persist()


def start_game(names, player_ids=None):
    ids = list(player_ids or [])
    if len(ids) < len(names):
        ids.extend([None] * (len(names) - len(ids)))
    by_name = {p["name"].casefold(): p["id"] for p in list_players()}
    ids = [pid or by_name.get(name.casefold()) for pid, name in zip(ids, names)]
    state = {
        "id": str(uuid.uuid4()),
        "players": names,
        "player_ids": ids,
        "scores": [{} for _ in names],
        "turn": 0,
        "finished": False,
        "saved": False,
    }
    st.session_state.state = state
    st.query_params["g"] = state["id"]
    persist()
    cleanup_old_games()


def delete_open_game(gid: str):
    if not DB_ENABLED:
        return
    try:
        sb().table("active_games").delete().eq("id", gid).execute()
    except Exception as e:
        st.toast(f"Kunde inte ta bort partiet: {e}")


def leave_game(delete_remote: bool):
    state = st.session_state.state
    st.session_state["prefill"] = state["players"]
    if delete_remote and DB_ENABLED:
        try:
            sb().table("active_games").delete().eq("id", state["id"]).execute()
        except Exception:
            pass
    st.session_state.state = None
    st.session_state.pop("setup_ready", None)
    if "g" in st.query_params:
        del st.query_params["g"]


def reopen_game():
    state = st.session_state.state
    if DB_ENABLED:
        try:
            sb().table("scores").delete().eq("game_id", state["id"]).execute()
            get_highscores.clear()
            list_score_months.clear()
        except Exception as e:
            st.toast(f"⚠️ Kunde inte öppna spelet igen: {e}")
            return
    state["finished"] = False
    state["saved"] = False
    persist()


# ----------------------------------------------------------------------------
# Tärningsbilder (SVG → data-URI, används som knapp-bakgrund)
# ----------------------------------------------------------------------------
_PIPS = {
    1: [(1, 1)],
    2: [(0, 0), (2, 2)],
    3: [(0, 0), (1, 1), (2, 2)],
    4: [(0, 0), (2, 0), (0, 2), (2, 2)],
    5: [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)],
    6: [(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)],
}


@st.cache_data(show_spinner=False)
def dice_uri(values: tuple) -> str:
    size, gap, pad = 64, 6, 3
    w = pad * 2 + len(values) * size + (len(values) - 1) * gap
    h = size + pad * 2
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
        '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#e9ecf4"/>'
        "</linearGradient></defs>",
    ]
    for i, val in enumerate(values):
        x, y = pad + i * (size + gap), pad
        parts.append(f'<rect x="{x}" y="{y + 2}" width="{size}" height="{size}" rx="12" fill="#c9cedb"/>')
        parts.append(
            f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="12" '
            f'fill="url(#g)" stroke="#c9cedb" stroke-width="1.5"/>'
        )
        for cx, cy in _PIPS[val]:
            parts.append(f'<circle cx="{x + 16 + cx * 16}" cy="{y + 16 + cy * 16}" r="5.5" fill="#1f2430"/>')
    parts.append("</svg>")
    return "data:image/svg+xml;base64," + base64.b64encode("".join(parts).encode()).decode()


# ----------------------------------------------------------------------------
# Design (CSS). VIKTIGT: CSS-texten får inte innehålla tecknet "<" – Streamlits
# säkerhetsfilter tar annars bort hela style-blocket.
# ----------------------------------------------------------------------------
def inject_css(body: str):
    assert "<" not in body, "CSS får inte innehålla '<'"
    st.markdown(f"<style>{body}</style>", unsafe_allow_html=True)


CSS = """
@import url('https://fonts.googleapis.com/css2?family=Kalam:wght@400;700&family=Nunito:wght@400;700;800&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Kalam:wght@400;700&display=swap');
:root{
  --primary:#C6A35A;
  --primary-dark:#E63946;
  --primary-soft:#3A2E1A;

  --bg:#0C2218;
  --paper:#0C2218;
  --field:#1B4D38;

  --line:#245C45;

  --text:#F4F1DE;
  --muted:#c4bba6;

  --green:#C6EE6A;
  --red:#E63946;

  --rh:2.55rem;
  --dh:4rem;
}

.stApp{
  font-family:'Kalam', cursive;

  background:
    radial-gradient(120% 70% at 50% -10%, rgba(46,110,72,.28), transparent 58%),
    #070b09;
}

[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"]{
  display:none !important;
}

[data-testid="stElementContainer"]:has(style),
[data-testid="element-container"]:has(style){
  display:none !important;
}

[data-testid="stElementContainer"]:has(iframe[title*="js_eval"]){
  position:absolute;
  height:0;
  width:0;
  overflow:hidden;
  opacity:0;
}

.block-container{
  padding:.6rem .6rem 1rem !important;
  max-width:720px;
}

[data-testid="stVerticalBlock"]{
  gap:.5rem;
}

[data-testid="stElementContainer"]:has(> [data-testid="stButton"]),
[data-testid="element-container"]:has(> [data-testid="stButton"]),
[data-testid="stButton"],
[data-testid="stPopover"]{
  width:100% !important;
}

[data-testid="stButton"] button,
[data-testid="stPopover"] button{
  width:100% !important;
  border-radius:10px;
  transition:.18s ease;
}

[data-testid="stButton"] button:hover{
  transform:translateY(-2px);
}

[class*="st-key-hs_"] button{
  justify-content:flex-start !important;
  text-align:left !important;
}

[class*="st-key-hs_"] button p{
  width:100%;
  text-align:left !important;
}

/* ----- kolumner ----- */

[data-testid="stHorizontalBlock"]{
  flex-wrap:nowrap !important;
  gap:.4rem !important;
}

[data-testid="stColumn"],
[data-testid="column"]{
  min-width:0 !important;
  flex:1 1 0 !important;
  width:auto !important;
}

.st-key-protokoll [data-testid="stHorizontalBlock"]{
  gap:3px !important;
}

.st-key-protokoll [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child,
.st-key-protokoll [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child{
  flex:1.9 1 0 !important;
}

.st-key-protokoll[data-testid="stVerticalBlock"],
.st-key-protokoll [data-testid="stVerticalBlock"]{
  gap:2px !important;
}

.st-key-topbar [data-testid="stColumn"]:not(:first-child),
.st-key-topbar [data-testid="column"]:not(:first-child){
  flex:0 0 2.8rem !important;
}

.st-key-topbar [data-testid="stColumn"]:has(.st-key-go_players),
.st-key-topbar [data-testid="column"]:has(.st-key-go_players){
  flex:0 0 auto !important;
  width:auto !important;
  min-width:6.4rem !important;
  max-width:8rem !important;
}

.st-key-topbar:has(.st-key-go_back) [data-testid="stColumn"]:first-child,
.st-key-topbar:has(.st-key-go_back) [data-testid="column"]:first-child{
  flex:0 0 auto !important;
  width:auto !important;
  min-width:8.6rem !important;
}

.st-key-topbar:has(.st-key-go_back) [data-testid="stColumn"]:not(:first-child),
.st-key-topbar:has(.st-key-go_back) [data-testid="column"]:not(:first-child){
  flex:1 1 auto !important;
  width:auto !important;
}

.st-key-gamebar [data-testid="stHorizontalBlock"]{
  gap:.35rem !important;
  align-items:center;
}

.st-key-gamebar [data-testid="stColumn"]:first-child,
.st-key-gamebar [data-testid="column"]:first-child{
  flex:0 0 2.35rem !important;
  width:2.35rem !important;
}

.st-key-gamebar [data-testid="stColumn"]:not(:first-child),
.st-key-gamebar [data-testid="column"]:not(:first-child){
  flex:1 1 auto !important;
  width:auto !important;
}

.st-key-gamebar [data-testid="stElementContainer"],
.st-key-gamebar [data-testid="element-container"],
.st-key-gamebar [data-testid="stVerticalBlock"]{
  margin:0 !important;
  padding:0 !important;
  min-height:0 !important;
  gap:0 !important;
}

.st-key-gamebar button{
  height:2rem !important;
  min-height:2rem !important;
  padding:0 !important;
  border-radius:12px !important;
}

.st-key-gamebar [data-testid="stIconMaterial"]{
  display:none !important;
}

.st-key-gamebar .turn{
  height:2rem;
  border-radius:12px;
  padding:0 .65rem;
  font-size:.92rem;
}

[data-baseweb="popover"]{
  min-width:16rem;
}

/* ----- topprad ----- */

.st-key-topbar button{
  height:2.6rem;
  min-height:2.6rem;

  background:#fff !important;

  border:1px solid var(--line) !important;

  box-shadow:0 3px 10px rgba(0,0,0,.15);
}

.st-key-go_back button{
  background:#1B4D38 !important;
  border:1px solid #245C45 !important;
  box-shadow:none !important;
  white-space:nowrap;
}

.st-key-go_back button p,
.st-key-go_players button p{
  color:#F4F1DE !important;
}

.st-key-go_players button{
  background:#1B4D38 !important;
  border:1px solid #245C45 !important;
  box-shadow:none !important;
  white-space:nowrap;
}

.turn{
  display:flex;
  justify-content:space-between;
  align-items:center;

  height:2.8rem;

  padding:0 .9rem;

  border-radius:16px;

  color:#F4F1DE;

  background:#133A2C;

  box-shadow:
    0 6px 18px rgba(0,0,0,.35);

  font-size:1rem;

  white-space:nowrap;
  overflow:hidden;
}

.turn .rd{
  font-size:.8rem;
  opacity:.85;
}

/* ----- protokoll ----- */

.st-key-protokoll{
  --rh:min(2.35rem, calc((100vh - 3.2rem) / 19));
  --rh:min(2.35rem, calc((100svh - 3.2rem) / 19));
  overflow-x:auto;
  overflow-y:hidden;
  background:linear-gradient(180deg, rgba(18,40,32,.78), rgba(8,16,13,.62));

  border-radius:18px;

  padding:8px 8px 6px;

  border:1px solid rgba(255,255,255,.06);

  box-shadow:0 16px 40px rgba(0,0,0,.35);

  position:relative;
}

.st-key-protokoll [data-testid="stElementContainer"],
.st-key-protokoll [data-testid="element-container"]{
  height:var(--rh) !important;
  min-height:0 !important;
  margin:0 !important;
  padding:0 !important;
}

.st-key-protokoll [data-testid="stButton"]{
  height:var(--rh) !important;
  min-height:0 !important;
  max-height:var(--rh) !important;
}

.st-key-protokoll button{
  display:flex;
  justify-content:center;
  align-items:center;

  background:rgba(6,14,12,.55) !important;

  border:1px solid rgba(255,255,255,.08) !important;

  border-radius:10px !important;

  padding:0 !important;

  height:var(--rh) !important;
  min-height:0 !important;
  max-height:var(--rh) !important;

  width:100% !important;
}

.st-key-protokoll button p,
.st-key-protokoll button div{
  margin:0 !important;

  font-family:'Nunito', sans-serif;

  font-size:calc(var(--rh) * .58);

  line-height:1;

  font-weight:800;

  color:#F4F1DE;
}

.st-key-protokoll button:hover,
.st-key-gamebar button:hover{
  border-color:var(--primary) !important;
  transform:none !important;
}

.st-key-protokoll button:disabled{
  opacity:1 !important;
}

.st-key-protokoll [data-testid="stPopover"]{
  width:var(--rh) !important;
  height:var(--rh) !important;
}

.st-key-protokoll .st-key-headleft{
  flex-direction:row !important;
  align-items:center !important;
  gap:.28rem !important;
  height:var(--rh) !important;
  min-height:0 !important;
}

.st-key-protokoll .st-key-headleft > [data-testid="stLayoutWrapper"]{
  width:var(--rh) !important;
  max-width:var(--rh) !important;
  flex:0 0 var(--rh) !important;
  min-width:0 !important;
}

.st-key-protokoll .st-key-headleft > [data-testid="stElementContainer"],
.st-key-protokoll .st-key-headleft > [data-testid="element-container"]{
  width:auto !important;
  max-width:none !important;
  flex:1 1 0 !important;
  min-width:0 !important;
}

.turnpill{
  display:flex;
  align-items:center;
  justify-content:center;
  gap:.28rem;
  height:calc(var(--rh) - 6px);
  max-width:100%;
  padding:0 .55rem;
  border-radius:999px;
  background:linear-gradient(180deg, #ffe7a8, #e2b04a);
  color:#3a2a10;
  font-family:'Nunito', sans-serif;
  font-weight:800;
  font-size:calc(var(--rh) * .34);
  line-height:1;
  width:max-content;
  max-width:100%;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
  box-shadow:0 0 14px rgba(224,180,90,.4);
}

.st-key-protokoll [data-testid="stPopover"] [data-testid="stIconMaterial"]{
  display:none !important;
}

/* ----- celler ----- */

.yc{
  font-size:calc(var(--rh) * .4);

  line-height:var(--rh);

  height:var(--rh);

  text-align:center;

  border-radius:9px;

  color:var(--text);
}

.yl{
  font-family:'Nunito', sans-serif;
  font-size:calc(var(--rh) * .46);
  font-weight:700;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  text-align:left;
  padding-left:4px;
  background:transparent;
  color:#F4F1DE;
}

.yl.yb{
  background:transparent;
  color:#F4F1DE;
}



.yh{
  background:transparent;

  color:#F4F1DE;

  font-family:'Nunito', sans-serif;

  font-weight:800;

  font-size:calc(var(--rh) * .4);

  border-radius:10px;

  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  padding:0 2px;
}

.yh.on{
  background:transparent;

  color:#f6d98a;

  box-shadow:none;
}

.yc.yh{
  height:var(--rh);
  line-height:1;
  display:flex;
  align-items:center;
  justify-content:center;
  gap:3px;
  white-space:nowrap;
  padding:0 2px;
}

.yh .pava{
  width:calc(var(--rh) * .55);
  height:calc(var(--rh) * .55);
  border-radius:50%;
  object-fit:cover;
  display:block;
  margin:0;
  flex:0 0 auto;
}

.yh span{
  display:block;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.rava{
  width:1.6rem;
  height:1.6rem;
  border-radius:50%;
  object-fit:cover;
  vertical-align:middle;
  margin-right:.35rem;
}

.ph-ava{
  width:2.4rem;
  height:2.4rem;
  border-radius:50%;
  background:rgba(255,255,255,.18);
  margin:.2rem auto;
}

[class*="st-key-seatbox_"] [data-testid="stColumn"]:first-child,
[class*="st-key-seatbox_"] [data-testid="column"]:first-child,
[class*="st-key-plrow_"] [data-testid="stColumn"]:first-child,
[class*="st-key-plrow_"] [data-testid="column"]:first-child{
  flex:0 0 3.4rem !important;
  max-width:3.4rem !important;
}

[class*="st-key-pl_"] button{
  justify-content:flex-start !important;
  text-align:left !important;
}

.ys:not(.yl),
.yt:not(.yl){
  background:transparent;

  color:#F4F1DE;

  font-weight:800;
}

.yc.ys{
  background:rgba(224,180,90,.13);
  box-shadow:inset 0 -1px 0 rgba(224,180,90,.4), inset 0 1px 0 rgba(224,180,90,.22);
}

.yb:not(.yl){
  background:transparent;

  color:#F4F1DE;

  font-weight:700;
}

.yt{

  font-family:'Nunito', sans-serif;

  font-size:calc(var(--rh) * .48);

  font-weight:800;

  letter-spacing:.04em;

  color:#f6d98a;
}

.sm{
  display:flex;
  align-items:center;
  justify-content:center;
  gap:.22rem;
}

.yl.sm{
  justify-content:flex-start;
}

.sm .sv{
  font-family:'Nunito', sans-serif;

  font-size:calc(var(--rh) * .48);

  font-weight:800;
}

.sm .cv{
  display:inline-flex;
  align-items:center;
  height:calc(var(--rh) * .46);
  padding:0 .32rem;
  border-radius:999px;
  font-family:'Nunito', sans-serif;
  font-size:calc(var(--rh) * .3);
  font-weight:800;
  line-height:1;
  color:#fff;
}

.sm .cv.up{
  background:#1f8a4c;
}

.sm .cv.dn{
  background:#c4373a;
}

.sm .cv.even{
  background:rgba(255,255,255,.16);
  color:#F4F1DE;
}

/* ----- popup ----- */

div[role="dialog"] [data-testid="stButton"] button{
  min-height:3.4rem;
  border-radius:12px;
  font-weight:700;
}

div[role="dialog"] [data-testid="stButton"] button p{
  font-size:1.2rem;
}

/* ----- alternativ ----- */

[class*="st-key-optneu_"] button{
  background:#fff4ec !important;
  border:1.5px solid #ffc7a8 !important;
  color:#9a3412 !important;
}

[class*="st-key-optneg_"] button{
  background:#fde8e8 !important;
  border:1.5px solid #f6b4b4 !important;
  color:#e23d3d !important;
}

[class*="st-key-optpos_"] button{
  background:#e7f6ec !important;
  border:1.5px solid #b7e4c7 !important;
  color:#178a45 !important;
}

/* ----- systemknappar ----- */

.st-key-dlg_cancel button{
  background:#f3eadc !important;
  color:#1e3a5f !important;
}

.st-key-dlg_clear button{
  background:#fff4ec !important;
  border:1px solid #ffc7a8 !important;
  color:#e85d2c !important;
}

.st-key-dlg_zero button{
  background:#fff !important;
  border:1px dashed #e23d3d !important;
  color:#e23d3d !important;
}

/* ----- tärningar ----- */

[class*="st-key-dz"],
[class*="st-key-dz"] [data-testid="stButton"]{
  width:100% !important;
}

[class*="st-key-dz"] button{
  width:100% !important;

  height:4rem !important;
  min-height:4rem !important;

  background-color:transparent !important;

  background-repeat:no-repeat !important;
  background-position:center !important;

  background-size:contain !important;

  border:none !important;
  box-shadow:none !important;
}

[class*="st-key-dz"] button:hover{
  transform:translateY(-2px) scale(1.03);
}

[class*="st-key-dz"] button p{
  font-size:0 !important;
}

[role="dialog"] [data-testid="stMarkdownContainer"],
[role="dialog"] [data-testid="stCaptionContainer"]{
  color:#F4F1DE !important;
}

[role="dialog"] button [data-testid="stMarkdownContainer"]{
  color:inherit !important;
}

[class*="st-key-dzsel_"] button{
  border:3px solid var(--primary) !important;

  background-color:var(--primary-soft) !important;
}

.dspace{
  height:var(--dh);
}

/* ----- nav: Spela, High Score, Spelare ----- */
.st-key-startnav{
  margin-bottom:.2rem;
}
.st-key-startnav [data-testid="stElementContainer"]:has(.on-play),
.st-key-startnav [data-testid="stElementContainer"]:has(.on-hs),
.st-key-startnav [data-testid="stElementContainer"]:has(.on-players),
.st-key-startnav [data-testid="element-container"]:has(.on-play),
.st-key-startnav [data-testid="element-container"]:has(.on-hs),
.st-key-startnav [data-testid="element-container"]:has(.on-players){
  display:none !important;
}
.st-key-startnav [data-testid="stColumn"],
.st-key-startnav [data-testid="column"]{
  display:flex !important;
  justify-content:center !important;
  align-items:center !important;
  flex:1 1 0 !important;
}
.st-key-nav_play button,
.st-key-nav_hs button,
.st-key-nav_players button,
.st-key-nav_back button{
  width:auto !important;
  background:transparent !important;
  border:none !important;
  box-shadow:none !important;
  min-height:2.15rem !important;
  padding:0 .35rem !important;
}
.st-key-nav_play button p,
.st-key-nav_hs button p,
.st-key-nav_players button p,
.st-key-nav_back button p{
  color:#f6edd4 !important;
  font-weight:600 !important;
  font-size:.92rem !important;
}
.st-key-nav_back button{
  min-width:2.4rem;
  padding:0 !important;
}
.st-key-nav_back button p{
  font-size:1.25rem !important;
  line-height:1 !important;
}
.st-key-startnav:has(.on-play) .st-key-nav_play button,
.st-key-startnav:has(.on-hs) .st-key-nav_hs button,
.st-key-startnav:has(.on-players) .st-key-nav_players button{
  background:linear-gradient(180deg, #ffe7a8, #e2b04a) !important;
  border-radius:999px !important;
  box-shadow:0 8px 18px rgba(0,0,0,.35) !important;
  min-width:6.4rem;
  padding:0 1rem !important;
}
.st-key-startnav:has(.on-play) .st-key-nav_play button p,
.st-key-startnav:has(.on-hs) .st-key-nav_hs button p,
.st-key-startnav:has(.on-players) .st-key-nav_players button p{
  color:#3a2a10 !important;
  font-weight:800 !important;
}

.st-key-start button{
  min-height:3.2rem;

  font-size:1.15rem;

  font-weight:900;

  background:#E63946 !important;

  color:white !important;
}
"""


# ----------------------------------------------------------------------------
# Startskärmens design (injiceras bara i setup_view, så spelvyn påverkas inte).
# Samma regel gäller här: inga "<"-tecken i CSS-texten.
# ----------------------------------------------------------------------------
SETUP_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@700;900&family=Great+Vibes&family=Orbitron:wght@700;900&display=swap');

/* ----- bakgrund: nästan svart med svag grön glöd ----- */
.stApp{
  background:
    radial-gradient(circle at 50% 16%, rgba(36,92,58,.55) 0%, rgba(12,28,20,.18) 28%, transparent 56%),
    linear-gradient(180deg, #101814 0%, #070b09 42%, #050705 100%) !important;
  background-attachment:fixed !important;
}

/* Navknapparnas utseende ligger i den vanliga CSS:en. */

/* ----- hero: guldtonad rubrik ----- */
.sx-hero{
  position:relative;
  text-align:center;
  padding:1.2rem 0 1.1rem;
}
.sx-club{
  font-family:'Great Vibes', cursive;
  font-size:clamp(2.1rem, 8vw, 3.3rem);
  letter-spacing:.01em;
  text-transform:none;
  color:#f3d48a;
  line-height:.85;
  margin-bottom:.15rem;
  text-shadow:0 2px 10px rgba(0,0,0,.45);
}
.sx-title{
  font-family:'Cinzel', serif;
  font-weight:900;
  font-size:clamp(3.5rem, 17vw, 5.8rem);
  line-height:.9;
  letter-spacing:.06em;
  padding-left:.06em;
  color:#f8e2a4;
  text-shadow:
    0 1px 0 #fff8dc,
    0 2px 0 #d7b15a,
    0 5px 0 #8d6b28,
    0 16px 26px rgba(0,0,0,.55);
}
.sx-dice{
  position:absolute;
  font-size:clamp(2.4rem, 10vw, 4.2rem);
  filter:drop-shadow(0 10px 14px rgba(0,0,0,.45));
  pointer-events:none;
  user-select:none;
}
.sx-d1{left:4%; top:1.6rem; animation:sx-f1 5s ease-in-out infinite;}
.sx-d2{right:4%; top:1.8rem; animation:sx-f2 6s ease-in-out infinite;}

@keyframes sx-f1{
  0%,100%{transform:translateY(0) rotate(-14deg);}
  50%{transform:translateY(-20px) rotate(10deg);}
}
@keyframes sx-f2{
  0%,100%{transform:translateY(0) rotate(16deg);}
  50%{transform:translateY(-26px) rotate(-8deg);}
}
@keyframes sx-flicker{
  0%,91%,100%{opacity:1;}
  93%{opacity:.86;}
  95%{opacity:1;}
  97%{opacity:.92;}
}

/* ----- etiketter ----- */
.st-key-n_players [data-testid="stWidgetLabel"] p,
[class*="st-key-name_"] [data-testid="stWidgetLabel"] p{
  color:rgba(255,255,255,.8) !important;
  font-family:'Orbitron', sans-serif;
  font-size:.72rem;
  letter-spacing:.2em;
  text-transform:uppercase;
}

/* ----- antal spelare som glas-pills ----- */
.st-key-n_players div[role="radiogroup"]{
  gap:.45rem;
  justify-content:center;
}
.st-key-n_players label[data-baseweb="radio"]{
  margin:0;
  padding:.5rem 1rem;
  background:rgba(255,255,255,.08);
  backdrop-filter:blur(12px);
  -webkit-backdrop-filter:blur(12px);
  border:1px solid rgba(255,255,255,.25);
  border-radius:14px;
  cursor:pointer;
  transition:.18s ease;
}
.st-key-n_players label[data-baseweb="radio"] > div:first-child,
.st-key-n_players input[type="radio"]{
  display:none !important;
}
.st-key-n_players label[data-baseweb="radio"] p{
  color:#fff !important;
  font-family:'Orbitron', sans-serif;
  font-weight:700;
  font-size:1rem;
}
.st-key-n_players label[data-baseweb="radio"]:hover{
  border-color:rgba(255,255,255,.6);
  transform:translateY(-2px);
}
.st-key-n_players label[data-baseweb="radio"]:has(input:checked){
  background:linear-gradient(135deg, #ffd000, #ff8c00);
  border-color:#fff;
  box-shadow:0 0 18px rgba(255,170,0,.7);
}
.st-key-n_players label[data-baseweb="radio"]:has(input:checked) p{
  color:#2b1500 !important;
}
.st-key-n_players [data-testid="stRadioOption"]{
  margin:0;
  width:2.45rem;
  height:2.45rem;
  padding:0;
  display:flex;
  align-items:center;
  justify-content:center;
  background:rgba(255,255,255,.05);
  border:1px solid rgba(255,255,255,.12);
  border-radius:10px;
}
.st-key-n_players [data-testid="stRadioOption"] > div > div:first-child{
  display:none !important;
}
.st-key-n_players [data-testid="stRadioOption"] p{
  color:rgba(255,255,255,.78) !important;
  font-family:'Orbitron', sans-serif;
  font-weight:700;
  font-size:.95rem;
}
.st-key-n_players [data-testid="stRadioOption"][data-selected="true"]{
  background:#1c6b45;
  border:2px solid #e0b45a;
  box-shadow:0 0 14px rgba(224,180,90,.35);
}
.st-key-n_players [data-testid="stRadioOption"][data-selected="true"] p{
  color:#f8edd2 !important;
}

/* ----- glasmorfism: namnfält ----- */
[class*="st-key-name_"] [data-baseweb="input"]{
  background:rgba(255,255,255,.08) !important;
  backdrop-filter:blur(14px) saturate(160%);
  -webkit-backdrop-filter:blur(14px) saturate(160%);
  border:1px solid rgba(255,255,255,.24) !important;
  border-radius:18px !important;
  box-shadow:0 8px 28px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.16);
  transition:border-color .25s ease, box-shadow .25s ease, transform .25s ease;
}
[class*="st-key-name_"] [data-testid="stTextInputRootElement"]:not([data-baseweb="input"]),
[class*="st-key-name_"] [data-baseweb="base-input"]:not([data-baseweb="input"]),
[class*="st-key-name_"] [data-baseweb="input"] > div{
  background:transparent !important;
  background-color:transparent !important;
  border:none !important;
  box-shadow:none !important;
}
[class*="st-key-name_"] [data-baseweb="input"]:focus-within{
  border-color:rgba(92,255,176,.9) !important;
  box-shadow:0 0 0 3px rgba(92,255,176,.2), 0 8px 28px rgba(0,0,0,.4);
  transform:translateY(-1px);
}
[class*="st-key-name_"] input{
  color:#fff !important;
  -webkit-text-fill-color:#fff !important;
  caret-color:#ffd000;
  background:transparent !important;
  font-size:1.1rem;
  padding:.8rem 1.1rem !important;
}
[class*="st-key-name_"] input::placeholder{
  color:rgba(255,255,255,.4) !important;
  -webkit-text-fill-color:rgba(255,255,255,.4) !important;
}

/* ----- episk startknapp ----- */
.st-key-start{
  margin-top:1.2rem;
}
.st-key-start button{
  min-height:4.4rem !important;
  background:linear-gradient(135deg, #ffd000 0%, #ff9100 55%, #ff6a00 100%) !important;
  border:2px solid rgba(255,255,255,.6) !important;
  border-radius:22px !important;
  color:#2b1500 !important;
  box-shadow:
    0 0 22px rgba(255,165,0,.75),
    0 0 60px rgba(255,120,0,.45),
    0 9px 0 #b45a00,
    0 16px 28px rgba(0,0,0,.55);
  animation:sx-pulse 1.8s ease-in-out infinite;
  transition:transform .12s ease !important;
}
.st-key-start button p{
  color:#2b1500 !important;
  font-family:'Orbitron', sans-serif !important;
  font-size:.92rem !important;
  font-weight:900 !important;
  letter-spacing:.06em;
  text-transform:uppercase;
}

/* ----- kort på startsidan ----- */
.st-key-openbox,
.st-key-newbox{
  background:rgba(14,24,20,.78);
  border:1px solid rgba(255,255,255,.1);
  border-radius:22px;
  padding:.9rem .85rem .4rem;
  margin:.35rem 0 .9rem;
  box-shadow:0 18px 40px rgba(0,0,0,.38);
}
[class*="st-key-openrow_"]{
  background:rgba(255,255,255,.045);
  border:1px solid rgba(255,255,255,.08);
  border-radius:14px;
  padding:.15rem .45rem;
  margin-bottom:.4rem;
}
.st-key-newbox{
  padding-bottom:1.3rem;
}
.sx-card-title{
  text-align:center;
  font-weight:700;
  color:#f4f1de;
  margin:0 0 .55rem;
}
[class*="st-key-openrow_"] [data-testid="stColumn"]:nth-child(2),
[class*="st-key-openrow_"] [data-testid="column"]:nth-child(2){
  flex:0 0 6.4rem !important;
  max-width:6.6rem !important;
}
[class*="st-key-openrow_"] [data-testid="stColumn"]:last-child,
[class*="st-key-openrow_"] [data-testid="column"]:last-child{
  flex:0 0 2.4rem !important;
  max-width:2.6rem !important;
}
[class*="st-key-drop_"] button{
  background:transparent !important;
  border:none !important;
  min-height:2rem !important;
  min-width:2rem !important;
  padding:0 !important;
  box-shadow:none !important;
}
[class*="st-key-drop_"] button p{
  color:#e07a72 !important;
  font-size:1.05rem !important;
}
[class*="st-key-resume_"] button{
  background:#1e7a46 !important;
  border:none !important;
  min-height:2rem !important;
  border-radius:999px !important;
  box-shadow:none !important;
}
[class*="st-key-pick_"] [role="group"]{
  background:rgba(6,12,10,.82) !important;
  border:1px solid rgba(255,255,255,.14) !important;
  border-radius:12px !important;
}
[class*="st-key-pick_"] input{
  color:#f4f1de !important;
  -webkit-text-fill-color:#f4f1de !important;
}
[class*="st-key-resume_"] button p{
  color:#F4F1DE !important;
  font-weight:700 !important;
}
.sx-open-meta{
  color:#f4f1de;
  font-weight:700;
  line-height:1.25;
}
.sx-open-round{
  color:rgba(244,241,222,.72);
  font-size:.86rem;
}
.st-key-start button:hover{
  transform:translateY(-3px) scale(1.02) !important;
  border-color:#fff !important;
}
.st-key-start button:active{
  transform:translateY(7px) !important;
  box-shadow:0 0 22px rgba(255,165,0,.75), 0 2px 0 #b45a00, 0 6px 12px rgba(0,0,0,.5);
}
@keyframes sx-pulse{
  0%,100%{
    box-shadow:0 0 18px rgba(255,165,0,.65), 0 0 40px rgba(255,120,0,.35),
               0 9px 0 #b45a00, 0 16px 28px rgba(0,0,0,.55);
  }
  50%{
    box-shadow:0 0 34px rgba(255,195,0,1), 0 0 95px rgba(255,140,0,.75),
               0 9px 0 #b45a00, 0 16px 28px rgba(0,0,0,.55);
  }
}

@media (prefers-reduced-motion: reduce){
  .sx-title, .sx-dice, .st-key-start button{animation:none !important;}
}
"""

SETUP_HERO = (
    '<div class="sx-hero">'
    '<span class="sx-dice sx-d1">🎲</span>'
    '<span class="sx-dice sx-d2">🎲</span>'
    '<div class="sx-club">UlriksBertils</div>'
    '<div class="sx-title">YATZY</div>'
    "</div>"
)


def protocol_css(state) -> str:
    rules = []
    # Fyra spelare fyller arkets bredd. Fler spelare behåller den kolumnbredden
    # och protokollet skrollar i sidled.
    n = len(state["scores"])
    if n > 4:
        rules.append(
            ".st-key-protokoll [data-testid='stHorizontalBlock']{"
            f"min-width:calc(100% * {1.9 + n} / 5.9) !important;}}"
        )

    for p, sc in enumerate(state["scores"]):
        for k, v in sc.items():
            if v == 0:
                rules.append(
                    f".st-key-cell_{p}_{k} button :is(p, div){{color:var(--red) !important;font-size:calc(var(--rh) * .7) !important;}}"
                )
            elif k in UPPER_VALUE and v != 3 * UPPER_VALUE[k]:
                color = "var(--green)" if v > 3 * UPPER_VALUE[k] else "var(--red)"
                rules.append(
                    f".st-key-cell_{p}_{k} button :is(p, div){{color:{color} !important;}}"
                )
            rules.append(
                f".st-key-cell_{p}_{k} button{{background:transparent !important;border-color:transparent !important;box-shadow:none !important;}}"
            )

    if not state["finished"]:
        t = state["turn"]
        filled = state["scores"][t]
        # Gul ram bara runt lediga rutor i den aktiva kolumnen.
        for k in ALL_CATS:
            if k not in filled:
                rules.append(
                    f".st-key-cell_{t}_{k} button{{"
                    "background:rgba(255,220,140,.07) !important;"
                    "border-color:rgba(224,180,90,.42) !important;"
                    "box-shadow:0 0 12px rgba(224,180,90,.16) !important;}"
                )
        # Hela protokollet ska rymmas på höjden. Menyn ligger i namnraden.
        rules.append(
            '[data-testid="stAppViewContainer"]{height:100svh !important;max-height:100svh !important;overflow:hidden !important;}'
            '.block-container:has(.st-key-protokoll){padding:.25rem .4rem .15rem !important;}'
            '.block-container:has(.st-key-protokoll) > [data-testid="stVerticalBlock"],'
            '.block-container:has(.st-key-protokoll) > div > [data-testid="stVerticalBlock"]{gap:.2rem !important;}'
        )

    return "".join(rules)


# ----------------------------------------------------------------------------
# Popup (st.dialog) – inga uträkningar för användaren
# ----------------------------------------------------------------------------
def commit(p: int, cat: str, value):
    apply_score(p, cat, value)
    st.rerun()


def pick(target, label: str, key: str, kind: str) -> bool:
    """Textknapp vars färg styrs av nyckelns prefix (se CSS: optneu_, optneg_ ...)."""
    return sbutton(target, label, key=f"opt{kind}_{key}")


def grid(n_items: int, ncols: int):
    cols_out = []
    for start in range(0, n_items, ncols):
        cols = st.columns(ncols)
        cols_out.extend(cols[: min(ncols, n_items - start)])
    return cols_out


def open_score_dialog(p: int, cat: str):
    st.session_state["dlg"] = {"a": None, "b": None}
    score_dialog(p, cat)


@st.dialog("Fyll i ruta")
def score_dialog(p: int, cat: str):
    state = st.session_state.state
    current = state["scores"][p].get(cat)
    sel = st.session_state.setdefault("dlg", {"a": None, "b": None})
    rules = []  # CSS-regler för tärningsbilderna

    def dice_btn(target, key, values, selected=False, prefix="dz") -> bool:
        k = f"{prefix + 'sel' if selected else prefix}_{key}"
        rules.append(f'.st-key-{k} button{{background-image:url("{dice_uri(tuple(values))}") !important;}}')
        return sbutton(target, str(values[0]), key=k)

    def spacer(target):
        target.markdown('<div class="dspace"></div>', unsafe_allow_html=True)

    head = f"**{state['players'][p]}** · {LABELS[cat]}"
    if current is not None:
        head += f"  ·  nu: **{current} p**"
    st.markdown(head)

    # --- Rad överst: Ledig / Stryk / Avbryt -------------------------------
    has_zero = cat != "chance"
    top = st.columns(3 if has_zero else 2)
    if sbutton(top[0], "Ledig", key="dlg_clear", disabled=current is None):
        commit(p, cat, None)
    if has_zero and sbutton(top[1], "Stryk", key="dlg_zero"):
        commit(p, cat, 0)
    if sbutton(top[-1], "Avbryt", key="dlg_cancel"):
        st.rerun()

    # --- Övre delen: 1–5 tärningar av den valören -------------------------
    if cat in UPPER_VALUE:
        face = UPPER_VALUE[cat]
        st.caption(f"Tryck på så många {LABELS[cat].lower()} du fick.")
        for n in range(1, 6):
            if dice_btn(st, f"{cat}{n}", [face] * n, prefix="dzc"):
                commit(p, cat, n * face)

    # --- Ett par / Triss / Fyrtal ----------------
    elif cat in MULT:
        m = MULT[cat]

        st.caption(
            "Tryck på tärningarna du fick. Appen räknar ut poängen."
        )

        for v in range(1, 7):
            if dice_btn(st, f"{cat}{v}", [v] * m):
                commit(p, cat, m * v)


    # --- Två par / Kåk ---------------------------
    elif cat in ("two_pairs", "house"):

        left_n, right_n = (
            (2, 2)
            if cat == "two_pairs"
            else (3, 2)
        )

        st.caption(
            "Tryck på de två paren du fick."
            if cat == "two_pairs"
            else "Tryck på vilken triss (vänster) och vilket par (höger) du fick."
        )

        cols = st.columns(2)

        if cat == "house":
            cols[0].caption("Triss")
            cols[1].caption("Par")

        a, b = sel["a"], sel["b"]

        clicked = None

        for v in range(1, 7):

            if b == v:
                spacer(cols[0])

            elif dice_btn(
                cols[0],
                f"{cat}a{v}",
                [v] * left_n,
                a == v,
            ):
                clicked = ("a", v)

            if a == v:
                spacer(cols[1])

            elif dice_btn(
                cols[1],
                f"{cat}b{v}",
                [v] * right_n,
                b == v,
            ):
                clicked = ("b", v)

        if clicked:

            side, v = clicked

            sel[side] = (
                None
                if sel[side] == v
                else v
            )

            if sel["a"] and sel["b"]:

                pts = (
                    2 * (sel["a"] + sel["b"])
                    if cat == "two_pairs"
                    else 3 * sel["a"] + 2 * sel["b"]
                )

                commit(p, cat, pts)

            st.rerun(scope="fragment")

    # --- Stegar och Yatzy: tryck på tärningsbilden ------------------------
    elif cat in FIXED:
        pts, faces = FIXED[cat]
        st.caption(f"Tryck på tärningarna – {pts} poäng.")
        if dice_btn(st, f"{cat}ok", faces):
            commit(p, cat, pts)

    # --- Chans: värde 5–30 ------------------------------------------------
    else:
        st.caption("Välj summan av alla fem tärningar.")
        for i, col in enumerate(grid(26, 5)):
            if pick(col, str(5 + i), f"ch{5 + i}", "neu"):
                commit(p, cat, 5 + i)

    if rules:
        inject_css("".join(rules))


# ----------------------------------------------------------------------------
# UI-komponenter
# ----------------------------------------------------------------------------
def hcell(text: str, cls: str = "", color: str | None = None) -> str:
    style = f' style="color:{color}"' if color else ""
    return f'<div class="yc {cls}"{style}>{text}</div>'


def name_html(name: str, src: str | None, active: bool) -> str:
    cls = "yh on" if active else "yh"
    img = f'<img class="pava" alt="" src="{html.escape(src, quote=True)}">' if src else ""
    return hcell(f'{img}<span>{html.escape(name)}</span>', cls)


def summary_row(widths, label, values, turn=-1, base_cls="ys"):
    cols = st.columns(widths, vertical_alignment="center")
    cols[0].markdown(hcell(label, f"yl {base_cls}"), unsafe_allow_html=True)
    for i, (txt, color) in enumerate(values):
        cls = base_cls + (" act" if i == turn else "")
        cols[i + 1].markdown(hcell(txt, cls, color), unsafe_allow_html=True)


def sum_cell(s: int, d: int, cnt: int) -> str:
    """Delsumman med en liten grön eller röd bricka för avståndet mot snittet."""
    if cnt == 0:
        return "–"
    if d > 0:
        cls, t = "up", f"+{d}"
    elif d < 0:
        cls, t = "dn", f"−{abs(d)}"
    else:
        cls, t = "even", "±0"
    return f'<span class="sv">{s}</span><span class="cv {cls}">{t}</span>'


def cell_label(cat: str, v) -> str:
    """Knappens text. Tom ruta är blank; färg sätts i protocol_css."""
    if v is None:
        return " "
    if v == 0:
        return "–"
    return f"**{v}**"


def render_protocol(state, with_menu: bool = True):
    players, scores = state["players"], state["scores"]
    n, fin = len(players), state["finished"]
    turn = -1 if fin else state["turn"]
    widths = [1.7] + [1] * n

    def input_row(cat, label):
        cols = st.columns(widths, vertical_alignment="center")
        cols[0].markdown(hcell(html.escape(label), "yl"), unsafe_allow_html=True)
        for p in range(n):
            if sbutton(cols[p + 1], cell_label(cat, scores[p].get(cat)), key=f"cell_{p}_{cat}", disabled=fin):
                open_score_dialog(p, cat)

    with st.container(key="protokoll"):
        head = st.columns(widths, vertical_alignment="center")
        if with_menu:
            with head[0].container(key="headleft"):
                with spopover(st, "☰"):
                    if sbutton(st, "🏆 High Score", key="go_hs"):
                        st.session_state.page = "hs"
                        st.rerun()
                    menu_contents()
                if turn >= 0:
                    who = html.escape(players[turn])
                    st.markdown(
                        f'<div class="turnpill">🎲 {who}s tur</div>',
                        unsafe_allow_html=True,
                    )
        else:
            head[0].markdown(hcell("Kategori", "yl"), unsafe_allow_html=True)
        by_id, by_name = roster_maps()
        for p, name in enumerate(players):
            rec = player_record(state, p, by_id, by_name)
            head[p + 1].markdown(
                name_html(name, avatar_src(rec), p == turn),
                unsafe_allow_html=True,
            )

        for key, label, _ in UPPER:
            input_row(key, label)

        stats = [upper_stats(sc) for sc in scores]
        summary_row(
            widths, "Delsumma",
            [(sum_cell(s, d, c), None) for s, d, c in stats], turn, base_cls="ys sm",
        )

        bon = []
        for s, _, cnt in stats:
            if s >= BONUS_LIMIT:
                bon.append((f"✓ {BONUS_POINTS}", "#E8C56B"))
            elif cnt == len(UPPER):
                bon.append(("0", RED))
            else:
                bon.append(("–", MUTED))
        summary_row(widths, f"Bonus ({BONUS_LIMIT}p)", bon, turn, base_cls="yb")

        for key, label in LOWER:
            input_row(key, label)

        summary_row(widths, "TOTALT", [(str(total(sc)), None) for sc in scores], turn, base_cls="yt")



def render_results(state):
    ranking = sorted(
        zip(state["players"], state["scores"]), key=lambda x: total(x[1]), reverse=True
    )
    medals = ["🥇", "🥈", "🥉"]
    by_id, by_name = roster_maps()
    ids = state.get("player_ids") or []
    pid_for = {
        pname: ids[i]
        for i, pname in enumerate(state["players"])
        if i < len(ids) and ids[i]
    }
    with st.container(border=True):
        for i, (name, sc) in enumerate(ranking):
            rec = by_id.get(pid_for.get(name)) or by_name.get(name.casefold())
            src = avatar_src(rec)
            img = f'<img class="rava" alt="" src="{html.escape(src, quote=True)}">' if src else ""
            place = medals[i] if i < 3 else f"{i + 1}."
            st.markdown(
                f'{img}{place} <b>{html.escape(name)}</b> – {total(sc)} p',
                unsafe_allow_html=True,
            )
        if not DB_ENABLED:
            st.info("Offline-läge – resultaten sparas inte i High Score.")
        elif state["saved"]:
            st.success("Resultaten är sparade i High Score.")
        else:
            st.warning("Resultaten kunde inte sparas i High Score.")
            if st.button("Försök spara igen", key="retry_save"):
                state["saved"] = save_scores(state)
                persist()
                st.rerun()
        c1, c2 = st.columns(2)
        if c1.button("✏️ Rätta något", key="reopen"):
            reopen_game()
            st.rerun()
        if c2.button("🎲 Nytt spel", type="primary", key="newgame"):
            leave_game(delete_remote=False)
            st.rerun()


def menu_contents():
    st.caption(
        f"Brickan vid delsumman visar avståndet mot snittet 3 per ruta. "
        f"Grön är över, röd är under. Bonus {BONUS_POINTS} p vid {BONUS_LIMIT} p."
    )
    if DB_ENABLED:
        st.caption("Spelet sparas i databasen.")
    else:
        st.caption("Offline-läge: spelet finns bara i den här fliken.")
    if st.button("🗑️ Avsluta spelet", key="menu_abort"):
        leave_game(delete_remote=False)
        st.rerun()


def topbar(left_html: str, with_menu: bool = False, back: bool = False, players: bool = False):
    if with_menu:
        with st.container(key="gamebar"):
            cols = st.columns([1, 8], vertical_alignment="center")
            with spopover(cols[0], "☰"):
                if sbutton(st, "🏆 High Score", key="go_hs"):
                    st.session_state.page = "hs"
                    st.rerun()
                menu_contents()
            cols[1].markdown(left_html, unsafe_allow_html=True)
        return
    with st.container(key="topbar"):
        if back:
            cols = st.columns([1.5, 5], vertical_alignment="center")
            if sbutton(cols[0], "← Tillbaka", key="go_back"):
                st.session_state.page = "play"
                st.session_state["player_form"] = None
                st.session_state.pop("seat_create", None)
                st.rerun()
            cols[1].markdown(left_html, unsafe_allow_html=True)
        else:
            cols = st.columns([6, 1.6, 1] if players else [6, 1], vertical_alignment="center")
            cols[0].markdown(left_html, unsafe_allow_html=True)
            trophy = cols[2] if players else cols[1]
            if players and sbutton(cols[1], "Spelare", key="go_players"):
                st.session_state.page = "players"
                st.session_state["player_form"] = None
                st.rerun()
            if sbutton(trophy, "🏆", key="go_hs"):
                st.session_state.page = "hs"
                st.rerun()


# ----------------------------------------------------------------------------
# Vyer
# ----------------------------------------------------------------------------
def parse_saved(raw):
    try:
        data = json.loads(raw) if raw else []
        return [str(x).strip() for x in data if str(x).strip()][:MAX_PLAYERS]
    except Exception:
        return []


def go_start():
    st.session_state.page = "play"
    st.session_state["player_form"] = None
    st.session_state.pop("seat_create", None)
    st.rerun()


def start_nav(active: str = "play", back: bool = False):
    with st.container(key="startnav"):
        st.markdown(f'<div class="on-{active}"></div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3, vertical_alignment="center")
        if back:
            if sbutton(c1, "←", key="nav_back"):
                go_start()
        else:
            sbutton(c1, "Spela", key="nav_play")
        if sbutton(c2, "🏆 High Score", key="nav_hs"):
            st.session_state.page = "hs"
            st.session_state["player_form"] = None
            st.session_state.pop("seat_create", None)
            st.rerun()
        if sbutton(c3, "👤 Spelare", key="nav_players"):
            st.session_state.page = "players"
            st.session_state["player_form"] = None
            st.session_state.pop("seat_create", None)
            st.rerun()


def setup_view():
    inject_css(SETUP_CSS)
    start_nav()
    st.markdown(SETUP_HERO, unsafe_allow_html=True)

    # Förifyll namn: först från förra spelet i denna session, annars från local storage
    if "setup_ready" not in st.session_state:
        saved = st.session_state.pop("prefill", None)
        if saved is None:
            raw = streamlit_js_eval(
                js_expressions=f"localStorage.getItem({json.dumps(LS_KEY)}) || ''",
                key="ls_read",
            )
            if raw is None and not st.session_state.get("ls_skip"):
                st.info("Hämtar sparade namn…")
                if st.button("Fortsätt utan sparade namn", key="skip_ls"):
                    st.session_state["ls_skip"] = True
                    st.rerun()
                return
            saved = parse_saved(raw)
        st.session_state["n_players"] = max(1, len(saved)) if saved else 2
        for i, nm in enumerate(saved):
            st.session_state[f"name_{i}"] = nm
        for i in range(MAX_PLAYERS):
            st.session_state.pop(f"pick_{i}", None)
        st.session_state["setup_ready"] = True

    if DB_ENABLED:
        open_games = list_open_games()
        if open_games:
            with st.container(key="openbox"):
                st.markdown('<div class="sx-card-title">Pågående partier</div>', unsafe_allow_html=True)
                for game in open_games:
                    show_open_game(game)

    with st.container(key="newbox"):
        st.markdown('<div class="sx-card-title">Nytt parti</div>', unsafe_allow_html=True)
        n = st.radio(
            "Antal spelare",
            list(range(1, MAX_PLAYERS + 1)),
            horizontal=True,
            key="n_players",
            label_visibility="collapsed",
        )
        roster = list_players() if DB_ENABLED else []
        names, ids = collect_seats(n, roster)

        if st.button("Kasta tärningarna & starta", type="primary", key="start"):
            if any(not x for x in names):
                st.error("Alla spelare behöver ett namn.")
            elif len({x.casefold() for x in names}) < len(names):
                st.error("Namnen måste vara olika.")
            else:
                start_game(names, ids)
                st.rerun()


def show_open_game(game: dict):
    when = open_when(game.get("_updated_at"))
    names = ", ".join(game.get("players") or [])
    head = f"{when} | {names}" if when else names
    with st.container(key=f"openrow_{game['id']}"):
        cols = st.columns([4, 1.3, 0.5], vertical_alignment="center")
        cols[0].markdown(
            f'<div class="sx-open-meta">{html.escape(head)}</div>'
            f'<div class="sx-open-round">Omgång {open_round(game)}/{len(ALL_CATS)}</div>',
            unsafe_allow_html=True,
        )
        if sbutton(cols[1], "Fortsätt", key=f"resume_{game['id']}"):
            game.pop("_updated_at", None)
            st.session_state.state = game
            st.query_params["g"] = game["id"]
            st.rerun()
        if sbutton(cols[2], "🗑️", key=f"drop_{game['id']}"):
            delete_open_game(game["id"])
            st.rerun()


def collect_seats(n: int, roster: list[dict]) -> tuple[list[str], list]:
    """Namn och spelar-id för varje plats. Utan databas blir det textfält."""
    if not DB_ENABLED:
        names = [
            st.text_input(
                f"Spelare {i + 1}", key=f"name_{i}", max_chars=20, placeholder="Namn"
            ).strip()
            for i in range(n)
        ]
        return names, [None] * n

    by_id = {p["id"]: p for p in roster}
    by_name = {p["name"].casefold(): p["id"] for p in roster}
    options = [GUEST_PICK] + [p["id"] for p in roster] + [CREATE_PICK]

    def label(value):
        if value == CREATE_PICK:
            return "Skapa ny spelare"
        if value == GUEST_PICK:
            return "Välj spelare"
        return by_id[value]["name"]

    names, ids = [], []
    for i in range(n):
        if st.session_state.get(f"pick_{i}") == CREATE_PICK:
            prev = st.session_state.get(f"pick_prev_{i}", GUEST_PICK)
            st.session_state[f"pick_{i}"] = prev if prev in by_id else GUEST_PICK
            begin_new_player(i)
        if f"pick_{i}" not in st.session_state:
            saved = (st.session_state.get(f"name_{i}") or "").strip()
            st.session_state[f"pick_{i}"] = by_name.get(saved.casefold()) or GUEST_PICK
        if st.session_state[f"pick_{i}"] not in options:
            st.session_state[f"pick_{i}"] = GUEST_PICK
        picked = st.selectbox(
            f"Spelare {i + 1}",
            options,
            format_func=label,
            key=f"pick_{i}",
            label_visibility="collapsed",
        )
        if picked and picked in by_id:
            st.session_state[f"pick_prev_{i}"] = picked
            names.append(by_id[picked]["name"])
            ids.append(picked)
        else:
            names.append("")
            ids.append(None)
    return names, ids


def preset_picker(form_id: str, existing: dict | None) -> str | None:
    pick_key = f"avpick_{form_id}"
    if pick_key not in st.session_state:
        current = (existing or {}).get("avatar_key")
        if current:
            st.session_state[pick_key] = current
        elif existing and existing.get("avatar_url"):
            st.session_state[pick_key] = None
        else:
            st.session_state[pick_key] = "dice"
    st.caption("Välj en bild")
    cols = st.columns(4)
    for i, (key, title) in enumerate(PRESETS):
        with cols[i % 4]:
            st.image(str(AVATAR_DIR / f"{key}.png"), width=72)
            chosen = st.session_state.get(pick_key) == key
            if st.button(title, key=f"{pick_key}_{key}", type="primary" if chosen else "secondary"):
                st.session_state[pick_key] = key
                st.rerun()
    return st.session_state.get(pick_key)


def player_editor(existing: dict | None):
    form_id = existing["id"] if existing else "new"
    name_key = f"pname_{form_id}"
    if name_key not in st.session_state:
        st.session_state[name_key] = "" if existing is None else existing["name"]
    name = st.text_input("Namn", max_chars=20, key=name_key).strip()
    current = avatar_file(existing)
    if current and existing and existing.get("avatar_url"):
        st.caption("Nuvarande bild")
        st.image(current, width=72)
    picked = preset_picker(form_id, existing)
    uploaded = st.file_uploader(
        "Eller ladda upp en egen bild (högst 2 MB)",
        type=["jpg", "jpeg", "png", "webp"],
        key=f"up_{form_id}",
    )
    if not st.button("Spara spelare", key=f"save_player_{form_id}"):
        return
    if not name:
        st.error("Skriv ett namn.")
        return
    if uploaded is not None and uploaded.size > 2 * 1024 * 1024:
        st.error("Bilden får vara högst 2 MB.")
        return
    taken = {
        p["name"].casefold()
        for p in list_players()
        if not existing or p["id"] != existing["id"]
    }
    if name.casefold() in taken:
        st.error("Det namnet finns redan.")
        return
    try:
        file_bytes = uploaded.getvalue() if uploaded else None
        pid = save_player(name, None if file_bytes else picked, file_bytes, existing)
    except Exception as e:
        msg = str(e).lower()
        if "duplicate" in msg or "23505" in msg:
            st.error("Det namnet finns redan.")
        else:
            st.error(f"Kunde inte spara spelaren. Kör supabase/players.sql om tabellen eller bucketen saknas. {e}")
        return
    st.session_state["player_form"] = None
    seat = st.session_state.pop("seat_create", None)
    if seat is not None:
        st.session_state[f"pick_{seat}"] = pid
        st.session_state.page = "play"
    else:
        st.session_state["player_open"] = pid
    st.rerun()


def show_player_stats(player: dict):
    try:
        rows = player_score_rows(player)
    except Exception as e:
        st.error(f"Kunde inte hämta statistik: {e}")
        return
    if not rows:
        st.info("Inga avslutade spel än.")
        return
    scores = [int(r["score"]) for r in rows]
    known = [r for r in rows if isinstance(r.get("card"), dict)]
    c1, c2, c3 = st.columns(3)
    c1.metric("Spel", len(rows))
    c2.metric("Snitt", f"{sum(scores) / len(scores):.0f}")
    c3.metric("Bästa", max(scores))
    d1, d2, d3 = st.columns(3)
    try:
        d1.metric("Vinster", count_wins(rows))
    except Exception:
        d1.metric("Vinster", "–")
    if known:
        bonus_n = sum(1 for r in known if upper_stats(card_numbers(r["card"]))[0] >= BONUS_LIMIT)
        yatzy_n = sum(1 for r in known if int((r["card"] or {}).get("yatzy") or 0) > 0)
        d2.metric("Bonus", f"{round(100 * bonus_n / len(known))} %")
        d3.metric("Yatzy", yatzy_n)
    else:
        d2.metric("Bonus", "–")
        d3.metric("Yatzy", "–")
    latest = max(rows, key=lambda r: r.get("played_at") or "")
    when = pd.to_datetime(latest["played_at"], utc=True).tz_convert(TZ).strftime("%Y-%m-%d")
    st.caption(f"Senaste resultatet: {int(latest['score'])} p den {when}.")


def players_view():
    start_nav(active="players", back=True)
    if not DB_ENABLED:
        st.info("Offline-läge: spelare kan inte sparas utan databas.")
        return
    roster = list_players()
    err = st.session_state.get("players_error")
    if err and not roster:
        missing = "schema cache" in err or "PGRST205" in err
        if missing:
            st.error("Spelartabellen saknas. Kör supabase/players.sql en gång i Supabase och ladda om sidan.")
        else:
            st.error(f"Kunde inte hämta spelare: {err}")
    if st.session_state.get("player_form") == "new":
        st.subheader("Ny spelare")
        player_editor(None)
        if st.button("Avbryt", key="cancel_player"):
            back_to_seat = st.session_state.pop("seat_create", None) is not None
            st.session_state["player_form"] = None
            if back_to_seat:
                st.session_state.page = "play"
            st.rerun()
        return
    if sbutton(st, "Ny spelare", key="new_player"):
        begin_new_player(None)
    if not roster and not err:
        st.caption("Inga spelare än.")
    open_id = st.session_state.get("player_open")
    chosen = None
    for player in roster:
        with st.container(key=f"plrow_{player['id']}"):
            cols = st.columns([1, 5], vertical_alignment="center")
            img = avatar_file(player)
            if img:
                cols[0].image(img, width=48)
            if sbutton(
                cols[1],
                player["name"],
                key=f"pl_{player['id']}",
                type="primary" if player["id"] == open_id else "secondary",
            ):
                st.session_state["player_open"] = player["id"]
                st.rerun()
        if player["id"] == open_id:
            chosen = player
    if chosen:
        show_player_stats(chosen)
        st.subheader("Ändra")
        player_editor(chosen)


def game_view():
    state = st.session_state.state

    # Spara namnen i webbläsarens local storage (körs bara när namnen ändras)
    payload = json.dumps(json.dumps(state["players"]))
    streamlit_js_eval(
        js_expressions=f"localStorage.setItem({json.dumps(LS_KEY)}, {payload})",
        key="ls_write",
    )

    if state["finished"]:
        render_results(state)

    css = protocol_css(state)
    if css:
        inject_css(css)
    render_protocol(state)


def show_table(rows, key: str):
    """Ett klick på raden väljer det spelet. Valet sparas i hs_game."""
    if not rows:
        st.info("Inga resultat än.")
        return
    dates = pd.to_datetime(
        [r["played_at"] for r in rows], utc=True
    ).tz_convert(TZ).strftime("%Y-%m-%d")
    medals = ["🥇", "🥈", "🥉"]
    chosen = st.session_state.get("hs_row")
    for i, r in enumerate(rows):
        place = medals[i] if i < 3 else f"{i + 1}."
        label = f"{place}  {r['player_name']}  ·  {r['score']} p  ·  {dates[i]}"
        if st.button(
            label,
            key=f"{key}_{i}",
            type="primary" if chosen == (key, i) else "secondary",
            width="stretch",
        ):
            st.session_state["hs_game"] = r["game_id"]
            st.session_state["hs_row"] = (key, i)
            st.rerun()


def show_scorecard(game_id: str):
    """Visar hela protokollet för ett sparat spel."""
    cards = load_scorecard(game_id)
    if not cards or any(c.get("card") is None for c in cards):
        st.info("Bara totalen sparades för det här spelet.")
        return
    state = {
        "players": [c["player_name"] for c in cards],
        "scores": [{k: int(v) for k, v in (c.get("card") or {}).items()} for c in cards],
        "finished": True,
        "turn": 0,
    }
    css = protocol_css(state)
    if css:
        inject_css(css)
    render_protocol(state, with_menu=False)


def highscore_view():
    start_nav(active="hs", back=True)
    if not DB_ENABLED:
        st.info("Offline-läge: ingen databas ansluten, så det finns ingen High Score att visa.")
        return
    months = ["januari", "februari", "mars", "april", "maj", "juni", "juli",
              "augusti", "september", "oktober", "november", "december"]
    now = datetime.now(TZ)
    tab_month, tab_all = st.tabs(["Månadens High Score", "Total High Score (All Time)"])
    with tab_month:
        try:
            options = list_score_months()
        except Exception as e:
            options = []
            st.error(f"Kunde inte hämta månader: {e}")
        current = (now.year, now.month)
        if current not in options:
            options.insert(0, current)
        labels = [f"{months[m - 1].capitalize()} {y}" for y, m in options]
        picked = st.selectbox("Månad", labels, key="hs_month_pick")
        year, month = options[labels.index(picked)]
        if st.session_state.get("hs_month_ym") != (year, month):
            st.session_state["hs_month_ym"] = (year, month)
            if st.session_state.get("hs_row", (None,))[0] == "hs_month":
                st.session_state["hs_row"] = None
        try:
            show_table(get_highscores(year, month), "hs_month")
        except Exception as e:
            st.error(f"Kunde inte hämta High Score: {e}")
    with tab_all:
        st.caption("Bästa enskilda resultat genom tiderna (topp 25).")
        try:
            show_table(get_highscores(), "hs_all")
        except Exception as e:
            st.error(f"Kunde inte hämta High Score: {e}")
    game_id = st.session_state.get("hs_game")
    if game_id:
        try:
            show_scorecard(game_id)
        except Exception as e:
            st.error(f"Kunde inte visa protokollet: {e}")


# ----------------------------------------------------------------------------
# Start
# ----------------------------------------------------------------------------
def init_state():
    st.session_state.setdefault("page", "play")
    if "state" not in st.session_state:
        st.session_state.state = None
        gid = st.query_params.get("g")
        if gid:
            loaded = load_game(gid)
            if loaded:
                st.session_state.state = loaded
            else:
                del st.query_params["g"]


def main():
    inject_css(CSS)
    init_state()

    if st.session_state.page == "hs":
        highscore_view()
    elif st.session_state.page == "players":
        players_view()
    elif st.session_state.state is None:
        setup_view()
    else:
        game_view()

    if not DB_ENABLED and st.session_state.state is None and st.session_state.page == "play":
        st.caption("⚠️ Offline-läge: databas-nycklar saknas, så inget sparas till molnet.")


main()
