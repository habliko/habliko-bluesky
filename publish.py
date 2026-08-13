#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Habliko Bluesky VIDEO publisher
-------------------------------
Publica 1 REEL (video 9x16) por ejecucion en Bluesky, rotando idioma.
Con cron 2 veces al dia => 2 videos/dia.

Coge un video aleatorio de R2:
  https://media.habliko.com/random/habliko/video/9x16/frase/<lang>
Texto del post: frase corta (Cerebras+Groq) + enlace a habliko.com + hashtags.

Flujo de video en Bluesky (mas complejo que imagen):
  1) login (createSession) -> accessJwt, did, y PDS host
  2) getServiceAuth (aud = did:web:<pds_host>, lxm uploadBlob)
  3) subir video a video.bsky.app/xrpc/app.bsky.video.uploadVideo
  4) getJobStatus hasta obtener el blob (procesado)
  5) createRecord con embed app.bsky.embed.video (+ aspectRatio 9:16)

Secrets:
  CEREBRAS_API_KEY y/o GROQ_API_KEY
  BLUESKY_HANDLE, BLUESKY_APP_PASSWORD
"""

import os
import sys
import json
import time
import datetime
import urllib.parse
import urllib.request
import urllib.error

USER_AGENT = "habliko-publisher/1.0"
ENTRYWAY = "https://bsky.social"
VIDEO_SVC = "https://video.bsky.app"
PLC = "https://plc.directory"

HABLIKO_URL = "https://habliko.com"
VIDEO_RANDOM = "https://media.habliko.com/random/habliko/video/9x16/frase/{lang}"

# --- Contacto (para el micro-CTA opcional del pie) ---
HABLIKO_EMAIL = "hola@habliko.com"
# WhatsApp: PENDIENTE. Formato internacional SIN "+", espacios ni guiones.
HABLIKO_WHATSAPP = ""  # p.ej. "352691234567"
# Micro-CTA de contacto en el pie del video. APAGADO por defecto: en un pie
# de 300 caracteres el enlace a la web ya basta y el email/WhatsApp ensucian.
# Ponlo en True si quieres que rote un contacto de vez en cuando (solo si cabe).
ADD_CONTACT_CTA = False

# --- Datos REALES de Habliko para el prompt (que la frase sea exacta si
#     menciona la app). El modelo NO debe inventar nada fuera de esto. ---
HABLIKO_FACTS = (
    "Habliko is a language-learning app; mascot Foxi (an AI fox tutor); "
    "8 languages; CEFR A1-C2; short lessons + mini-games; free to start; "
    "Premium 2 EUR/month or 24 EUR/year."
)

GROQ_RETRIES = 2

PROVIDERS = [
    {"name": "cerebras", "url": "https://api.cerebras.ai/v1/chat/completions",
     "key_env": "CEREBRAS_API_KEY", "model": "gpt-oss-120b",
     "max_tokens": 2000, "reasoning_effort": "low"},
    {"name": "groq", "url": "https://api.groq.com/openai/v1/chat/completions",
     "key_env": "GROQ_API_KEY", "model": "openai/gpt-oss-120b",
     "max_tokens": 2000, "reasoning_effort": "low"},
]

LANGUAGES = ["es", "en", "fr", "de", "nl", "it", "pt", "lb"]
LANG_NAMES = {
    "es": "Spanish (espanol de Espana)", "en": "English",
    "fr": "French (francais)", "de": "German (Deutsch)",
    "nl": "Dutch (Nederlands)", "it": "Italian (italiano)",
    "pt": "Portuguese (portugues de Portugal)",
    "lb": "Luxembourgish (Letzebuergesch)",
}
PROGRESS_FILE = "progress.json"

TOPICS = [
    {"num": 1,  "theme": "How to build a daily language-learning habit that sticks"},
    {"num": 2,  "theme": "The best way to memorize vocabulary long-term with spaced repetition"},
    {"num": 3,  "theme": "Understanding the CEFR levels: from A1 to C2 explained simply"},
    {"num": 4,  "theme": "How many words you really need to hold a conversation"},
    {"num": 5,  "theme": "Why speaking from day one accelerates your learning"},
    {"num": 6,  "theme": "Common mistakes beginners make and how to avoid them"},
    {"num": 7,  "theme": "How to stay motivated when learning a language feels slow"},
    {"num": 8,  "theme": "Learning a language as an adult: why it's never too late"},
    {"num": 9,  "theme": "The difference between active and passive vocabulary"},
    {"num": 10, "theme": "How to improve your accent and pronunciation"},
    {"num": 11, "theme": "Shadowing: the technique that improves fluency fast"},
    {"num": 12, "theme": "How to learn a language in just 15 minutes a day"},
    {"num": 13, "theme": "The role of comprehensible input in language acquisition"},
    {"num": 14, "theme": "How to start thinking in your target language"},
    {"num": 15, "theme": "Best strategies to overcome the fear of speaking"},
    {"num": 16, "theme": "How mini-games make learning a language fun and effective"},
    {"num": 17, "theme": "Setting realistic language goals with the CEFR framework"},
    {"num": 18, "theme": "Why immersion works and how to create it at home"},
    {"num": 19, "theme": "How to learn two languages at the same time"},
    {"num": 20, "theme": "The psychology of motivation in language learning"},
    {"num": 21, "theme": "How to remember grammar rules without boring drills"},
    {"num": 22, "theme": "Flashcards vs. context: which helps you learn faster"},
    {"num": 23, "theme": "How to expand your vocabulary every single day"},
    {"num": 24, "theme": "The most useful phrases to learn first in any language"},
    {"num": 25, "theme": "How to practice listening comprehension effectively"},
    {"num": 26, "theme": "Why making mistakes is essential to learning a language"},
    {"num": 27, "theme": "How to keep a learning streak going without burning out"},
    {"num": 28, "theme": "Learning idioms and expressions the natural way"},
    {"num": 29, "theme": "How to prepare for a language exam (A2, B1, B2)"},
    {"num": 30, "theme": "The benefits of learning a language for your brain"},
    {"num": 31, "theme": "How children learn languages and what adults can copy"},
    {"num": 32, "theme": "How to learn a language before a trip abroad"},
    {"num": 33, "theme": "Reading in a foreign language: where to start"},
    {"num": 34, "theme": "How to use an AI tutor to practice conversation"},
    {"num": 35, "theme": "The secret to consistent daily practice"},
    {"num": 36, "theme": "How to measure your progress in a new language"},
    {"num": 37, "theme": "Spanish for beginners: first steps and essentials"},
    {"num": 38, "theme": "English pronunciation tips for non-native speakers"},
    {"num": 39, "theme": "French grammar basics every beginner should know"},
    {"num": 40, "theme": "German cases explained simply for beginners"},
    {"num": 41, "theme": "Common false friends between languages and how to spot them"},
    {"num": 42, "theme": "How to learn Luxembourgish and why it's worth it"},
    {"num": 43, "theme": "Italian for travelers: essential words and phrases"},
    {"num": 44, "theme": "Portuguese and Spanish: key differences to know"},
    {"num": 45, "theme": "Dutch pronunciation: the sounds that trip learners up"},
    {"num": 46, "theme": "How to build sentences confidently in a new language"},
    {"num": 47, "theme": "The best times of day to study a language"},
    {"num": 48, "theme": "How to review vocabulary so you never forget it"},
    {"num": 49, "theme": "Learning through songs, films and podcasts"},
    {"num": 50, "theme": "How to talk about yourself in your target language"},
    {"num": 51, "theme": "Numbers, dates and time: mastering the basics"},
    {"num": 52, "theme": "How to order food and drinks in another language"},
    {"num": 53, "theme": "Greetings and small talk in any language"},
    {"num": 54, "theme": "How to ask for directions abroad without panic"},
    {"num": 55, "theme": "Everyday routines vocabulary for beginners"},
    {"num": 56, "theme": "How to describe people and places fluently"},
    {"num": 57, "theme": "Past, present and future: verb tenses made easy"},
    {"num": 58, "theme": "How to sound more polite in a foreign language"},
    {"num": 59, "theme": "Business language essentials for professionals"},
    {"num": 60, "theme": "How to write your first email in a new language"},
    {"num": 61, "theme": "The most common verbs you should learn first"},
    {"num": 62, "theme": "How to understand fast native speech"},
    {"num": 63, "theme": "Building confidence through small daily wins"},
    {"num": 64, "theme": "How to create a personalized study plan"},
    {"num": 65, "theme": "Why variety in practice keeps learning fresh"},
    {"num": 66, "theme": "How to learn vocabulary by topic (food, travel, work)"},
    {"num": 67, "theme": "The power of repetition without boredom"},
    {"num": 68, "theme": "How gamification boosts language retention"},
    {"num": 69, "theme": "How to practice speaking when you're alone"},
    {"num": 70, "theme": "Overcoming plateaus in language learning"},
    {"num": 71, "theme": "How bilingualism benefits your career"},
    {"num": 72, "theme": "Learning a language with your kids at home"},
    {"num": 73, "theme": "How to use spaced repetition the right way"},
    {"num": 74, "theme": "The role of grammar: how much do you really need"},
    {"num": 75, "theme": "How to make foreign-language friends online"},
    {"num": 76, "theme": "Cultural context: why it matters when learning a language"},
    {"num": 77, "theme": "How to prepare for real conversations"},
    {"num": 78, "theme": "Micro-learning: fitting practice into a busy life"},
    {"num": 79, "theme": "How to stop translating in your head"},
    {"num": 80, "theme": "The most effective free ways to practice every day"},
    {"num": 81, "theme": "How to keep learning after reaching B1"},
    {"num": 82, "theme": "Reaching C1 and C2: what advanced learners do differently"},
    {"num": 83, "theme": "How to teach yourself a language from scratch"},
    {"num": 84, "theme": "Study routines that actually work long-term"},
    {"num": 85, "theme": "How to enjoy the process, not just the goal"},
    {"num": 86, "theme": "Why tracking your streak keeps you accountable"},
    {"num": 87, "theme": "How a friendly tutor helps you learn a little every day"},
    {"num": 88, "theme": "From zero to conversation: a realistic timeline"},
    {"num": 89, "theme": "How to choose which language to learn next"},
    {"num": 90, "theme": "Turning language learning into a lifelong habit"},
]


# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------


def _req(url, data=None, headers=None, method="GET", timeout=120, raw=False):
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    if data is not None and not raw:
        data = json.dumps(data).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


def _read_http_error(e):
    try:
        return e.read().decode("utf-8", "replace")
    except Exception:
        return str(e)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            p = json.load(f)
    else:
        p = {}
    p.setdefault("lang_index", 0)
    p.setdefault("topic_pointer", {})
    for lang in LANGUAGES:
        p["topic_pointer"].setdefault(lang, 0)
    return p


def save_progress(p):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


def _parse_json_lenient(content):
    if not content:
        raise ValueError("IA devolvio VACIO")
    try:
        return json.loads(content)
    except Exception:
        pass
    s, e = content.find("{"), content.rfind("}")
    if s != -1 and e != -1 and e > s:
        return json.loads(content[s:e + 1])
    raise ValueError("No es JSON valido")


# ---------------------------------------------------------------------------
# IA (texto corto) multi-proveedor
# ---------------------------------------------------------------------------


def _provider_request(provider, system, user):
    payload = {
        "model": provider["model"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.85,
        "max_tokens": provider.get("max_tokens", 2000),
        "response_format": {"type": "json_object"},
    }
    if provider.get("reasoning_effort"):
        payload["reasoning_effort"] = provider["reasoning_effort"]
    headers = {"Authorization": "Bearer " + os.environ[provider["key_env"]]}
    out = _req(provider["url"], data=payload, headers=headers, method="POST", timeout=90)
    return (out["choices"][0]["message"]["content"] or "").strip()


def _multi_generate(system, user):
    active = [p for p in PROVIDERS if os.environ.get(p["key_env"])]
    if not active:
        raise RuntimeError("Ningun proveedor tiene API key (CEREBRAS/GROQ)")
    last = None
    for p in active:
        try:
            content = _provider_request(p, system, user)
            if p is not active[0]:
                print("   (respaldo: %s)" % p["name"])
            return content
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("   %s dio 429; pruebo el siguiente..." % p["name"])
                last = e
                continue
            last = e
            break
        except Exception as e:
            last = e
            break
    raise last or RuntimeError("Fallo la generacion en todos los proveedores")


def gen_short(lang, theme):
    lang_name = LANG_NAMES[lang]
    system = ("You write short, punchy social posts for Habliko, a friendly "
              "language-learning app whose mascot is Foxi, a fox tutor. Warm, "
              "useful, never spammy.")
    user = (
        "Write ONE short social post ENTIRELY in " + lang_name + " about:\n"
        + theme + "\n\n"
        "Rules:\n- MAX 200 characters. One concrete tip or inspiring phrase.\n"
        "- No links, no hashtags inside the text.\n"
        "- Natural tone. You may use 1-2 emojis.\n"
        "- If you mention the app, only use these real facts, never invent: "
        + HABLIKO_FACTS + "\n\n"
        'Return ONLY JSON: {"text": "...", "hashtags": ["#tag1", "#tag2"]}'
    )
    art = _parse_json_lenient(_multi_generate(system, user))
    if not art.get("text"):
        raise ValueError("IA no devolvio 'text'")
    if not isinstance(art.get("hashtags"), list):
        art["hashtags"] = []
    return art


# ---------------------------------------------------------------------------
# VIDEO desde R2
# ---------------------------------------------------------------------------


def fetch_video_bytes(lang):
    url = VIDEO_RANDOM.format(lang=lang)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# BLUESKY
# ---------------------------------------------------------------------------


def bsky_login():
    out = _req(ENTRYWAY + "/xrpc/com.atproto.server.createSession",
               data={"identifier": os.environ["BLUESKY_HANDLE"],
                     "password": os.environ["BLUESKY_APP_PASSWORD"]},
               method="POST")
    jwt, did = out["accessJwt"], out["did"]
    # Resolver el host del PDS (para el aud del service auth)
    pds_host = None
    doc = out.get("didDoc")
    if not doc:
        try:
            doc = _req(PLC + "/" + did)
        except Exception:
            doc = None
    if doc:
        for svc in doc.get("service", []):
            if svc.get("id", "").endswith("atproto_pds") or \
               svc.get("type") == "AtprotoPersonalDataServer":
                ep = svc.get("serviceEndpoint", "")
                pds_host = urllib.parse.urlparse(ep).netloc
                break
    if not pds_host:
        pds_host = "bsky.social"
    return jwt, did, pds_host


def bsky_service_auth(jwt, pds_host):
    exp = int(time.time()) + 60 * 25
    qs = urllib.parse.urlencode({
        "aud": "did:web:" + pds_host,
        "lxm": "com.atproto.repo.uploadBlob",
        "exp": exp,
    })
    out = _req(ENTRYWAY + "/xrpc/com.atproto.server.getServiceAuth?" + qs,
               headers={"Authorization": "Bearer " + jwt})
    return out["token"]


def bsky_upload_video(did, service_token, video_bytes):
    qs = urllib.parse.urlencode({"did": did, "name": "habliko.mp4"})
    url = VIDEO_SVC + "/xrpc/app.bsky.video.uploadVideo?" + qs
    req = urllib.request.Request(
        url, data=video_bytes, method="POST",
        headers={"Authorization": "Bearer " + service_token,
                 "Content-Type": "video/mp4", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            job = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 409 = ya subido antes: la respuesta trae el blob
        if e.code == 409:
            job = json.loads(_read_http_error(e))
        else:
            raise
    return job.get("jobStatus", job)


def bsky_wait_blob(job, service_token):
    blob = job.get("blob")
    if blob:
        return blob
    job_id = job.get("jobId")
    if not job_id:
        raise RuntimeError("uploadVideo no devolvio jobId ni blob: %s" % job)
    for _ in range(60):  # hasta ~2 min
        time.sleep(2)
        out = _req(VIDEO_SVC + "/xrpc/app.bsky.video.getJobStatus?jobId=" + job_id,
                   headers={"Authorization": "Bearer " + service_token})
        js = out.get("jobStatus", out)
        state = js.get("state", "")
        if js.get("blob"):
            return js["blob"]
        if state == "JOB_STATE_FAILED":
            raise RuntimeError("procesado de video fallo: %s" % js.get("error"))
    raise RuntimeError("timeout esperando el procesado del video")


def _facets_link(text, url):
    b = text.encode("utf-8")
    key = url.encode("utf-8")
    i = b.find(key)
    if i < 0:
        return None
    return [{"index": {"byteStart": i, "byteEnd": i + len(key)},
             "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]}]


def bsky_post_video(jwt, did, text, blob, lang):
    now = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")
    # Bluesky permite maximo 3 idiomas; usamos el del post.
    post_lang = "pt" if lang == "pt" else lang
    record = {"$type": "app.bsky.feed.post", "text": text, "createdAt": now,
              "langs": [post_lang],
              "embed": {"$type": "app.bsky.embed.video", "video": blob,
                        "aspectRatio": {"width": 9, "height": 16}}}
    fac = _facets_link(text, HABLIKO_URL)
    if fac:
        record["facets"] = fac
    out = _req(ENTRYWAY + "/xrpc/com.atproto.repo.createRecord",
               data={"repo": did, "collection": "app.bsky.feed.post",
                     "record": record},
               headers={"Authorization": "Bearer " + jwt}, method="POST")
    rkey = out.get("uri", "").split("/")[-1]
    return "https://bsky.app/profile/%s/post/%s" % (os.environ["BLUESKY_HANDLE"], rkey)


def _micro_cta(seq):
    """Micro-CTA rotatorio de contacto (solo si ADD_CONTACT_CTA=True).
    Alterna: nada / email / WhatsApp (si hay numero). Devuelve "" si off."""
    if not ADD_CONTACT_CTA:
        return ""
    opts = [""]
    opts.append("\u2709\ufe0f " + HABLIKO_EMAIL)
    if HABLIKO_WHATSAPP.strip():
        opts.append("WhatsApp: wa.me/" + HABLIKO_WHATSAPP.strip())
    return opts[seq % len(opts)]


def compose(art, seq=0):
    tags = " ".join(art.get("hashtags", [])[:2])
    text = art["text"].strip()
    tail = "\n\n" + HABLIKO_URL + ("\n" + tags if tags else "")
    cta = _micro_cta(seq)
    tail_with_cta = tail + ("\n" + cta if cta else "")
    # El CTA solo se incluye si deja hueco razonable para la frase.
    if cta and (295 - len(tail_with_cta)) >= 60:
        tail = tail_with_cta
    room = 295 - len(tail)
    if len(text) > room:
        text = text[:room - 1].rstrip() + "\u2026"
    return text + tail


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main():
    for v in ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"):
        if not os.environ.get(v):
            print("ERROR: falta secret %s" % v)
            sys.exit(1)
    active = [p["name"] for p in PROVIDERS if os.environ.get(p["key_env"])]
    if not active:
        print("ERROR: falta CEREBRAS_API_KEY y/o GROQ_API_KEY")
        sys.exit(1)
    print("Proveedores IA (en orden): %s" % ", ".join(active))

    progress = load_progress()
    lang = LANGUAGES[progress["lang_index"] % len(LANGUAGES)]
    topic_idx = progress["topic_pointer"][lang] % len(TOPICS)
    topic = TOPICS[topic_idx]

    print("== Habliko Bluesky VIDEO publisher ==")
    print("Idioma de este run: %s (%s) | Tema #%d: %s"
          % (lang, LANG_NAMES[lang], topic["num"], topic["theme"]))

    print("-> Login en Bluesky...")
    jwt, did, pds_host = bsky_login()
    print("   PDS host: %s" % pds_host)

    print("-> Generando texto...")
    art = gen_short(lang, topic["theme"])
    text = compose(art, topic["num"])

    print("-> Descargando video de R2...")
    video = fetch_video_bytes(lang)
    print("   video: %d KB" % (len(video) // 1024))

    print("-> Service auth + subida de video...")
    stoken = bsky_service_auth(jwt, pds_host)
    job = bsky_upload_video(did, stoken, video)
    print("-> Esperando procesado del video...")
    blob = bsky_wait_blob(job, stoken)

    print("-> Publicando post con video...")
    url = bsky_post_video(jwt, did, text, blob, lang)
    print("   OK publicado: %s" % url)

    # avanzar rotacion
    progress["topic_pointer"][lang] = topic_idx + 1
    progress["lang_index"] = (progress["lang_index"] + 1) % len(LANGUAGES)
    save_progress(progress)
    print("Siguiente idioma: %s" % LANGUAGES[progress["lang_index"]])


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        print("ERROR HTTP %s: %s" % (e.code, _read_http_error(e)))
        sys.exit(1)
    except Exception as e:
        print("ERROR: %r" % e)
        sys.exit(1)
