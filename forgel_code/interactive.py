"""The interactive session of Forgel Code.

The owner writes sentences. The client turns one sentence into at most one of
the engine's own commands, shows what the engine answered, and re-reads the
task and release state from the engine after every request and before every
prompt, so progress shows up without the owner asking for a status. It never
calls a model, never reads a project and never runs a check.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence, TextIO, Tuple

from . import commands
from .engine import DEFAULT_TIMEOUT, Engine, EngineError
from .render import render_human
from .session import Session

# What the session prints while it waits for the owner.
PROMPT = "forgel> "

# Keys of an engine answer that are envelope, never part of the agent's reply.
META_KEYS = frozenset(["ok", "engine", "command", "args", "project"])

# Keys an engine answer may use for the collections the session shows.
TASK_KEYS = ("tasks", "items", "result")
PLAN_KEYS = ("tasks", "plan", "steps", "items")
REPLY_KEYS = ("reply", "answer", "text", "message")
RELEASE_KEYS = ("release", "milestone", "status")

ID_ALPHABET = frozenset(
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ._-#"
)
DIGITS = frozenset("0123456789")
ID_SEPARATORS = ("-", "_")

LEAVE_WORDS = frozenset(
    [
        "exit",
        "quit",
        "leave",
        "bye",
        "logout",
        "выход",
        "выйти",
        "пока",
        "хватит",
        "конец",
        "завершить",
        "заверши сеанс",
    ]
)

# Intents that stay explicit separate actions: a sentence never performs them.
SENSITIVE_MARKERS = (
    "adopt",
    "create project",
    "create a project",
    "new project",
    "secret",
    "token",
    "password",
    "credential",
    "api key",
    "configuration",
    "config file",
    "settings",
    "прими репозиторий",
    "адопт",
    "создай проект",
    "создать проект",
    "новый проект",
    "секрет",
    "токен",
    "пароль",
    "конфигурац",
    "настройк",
)

# Which words ask for which action. One sentence may name only one action.
ACTIONS = (
    (
        "accept",
        (
            "accept",
            "approve",
            "прими",
            "принять",
            "одобр",
            "согласен",
        ),
    ),
    (
        "rework",
        (
            "rework",
            "send back",
            "send it back",
            "reject",
            "верни",
            "на доработку",
            "доработк",
            "отклон",
        ),
    ),
    ("retry", ("retry", "повтори", "перезапуст", "ещё раз запусти")),
    ("pause", ("pause", "приостанов", "пауза", "на паузу", "останови работу")),
    (
        "resume",
        (
            "resume",
            "continue the work",
            "continue work",
            "продолж",
            "возобнов",
        ),
    ),
)

# Leading words that select another project; the rest of the line is the key.
SWITCH_PREFIXES = tuple(
    sorted(
        (
            "switch the project to ",
            "switch project to ",
            "change the project to ",
            "change project to ",
            "select the project ",
            "select project ",
            "switch to ",
            "use project ",
            "use ",
            "переключи проект на ",
            "переключись на ",
            "смени проект на ",
            "выбери проект ",
            "используй проект ",
            "используй ",
        ),
        key=len,
        reverse=True,
    )
)

# Leading words that ask for a plan; the rest of the line is the goal.
PLAN_PREFIXES = tuple(
    sorted(
        ("составь план ", "сделай план ", "спланируй ", "plan ", "план "),
        key=len,
        reverse=True,
    )
)
PLAN_EXACT = frozenset(["plan", "план", "спланируй", "составь план", "сделай план"])

# Words that belong to the sentence rather than to the identifier it names.
ID_STOPWORDS = frozenset(
    [
        "task",
        "tasks",
        "the",
        "a",
        "an",
        "please",
        "it",
        "this",
        "that",
        "finished",
        "done",
        "failed",
        "now",
        "задачу",
        "задача",
        "задание",
        "пожалуйста",
        "его",
        "эту",
        "это",
        "готовую",
        "упавшую",
        "сейчас",
    ]
)

# Connectors between the identifier and the remarks of a send-back.
REMARK_CONNECTORS = tuple(
    sorted(
        (
            "with the remarks",
            "with remarks",
            "with the reason",
            "with reason",
            "remarks",
            "reason",
            "с замечаниями",
            "замечания",
            "с причиной",
            "причина",
        ),
        key=len,
        reverse=True,
    )
)

# Words at the start of the remarks that name the action, not the remark.
REMARK_LEADERS = tuple(
    sorted(
        (
            "back for rework",
            "for rework",
            "to rework",
            "на доработку",
            "в доработку",
            "on rework",
        ),
        key=len,
        reverse=True,
    )
)

# Words that name key material. A label is one word or a compound name whose
# segments are joined by "_", "." or "-", and a compound label is
# secret-bearing when one of its segments is one of these words.
SECRET_WORDS = frozenset(
    [
        "token",
        "tokens",
        "secret",
        "secrets",
        "password",
        "passwords",
        "passwd",
        "passphrase",
        "passphrases",
        "apikey",
        "apikeys",
        "authorization",
        "bearer",
        "credential",
        "credentials",
        "key",
        "keys",
    ]
)

# Russian inflects its labels, so a Russian label is recognised by its stem.
SECRET_STEMS = ("парол", "секрет", "токен", "ключ")

# An authorization scheme word stays visible; the credential after it does not.
AUTH_SCHEMES = frozenset(
    [
        "apikey",
        "aws4-hmac-sha256",
        "basic",
        "bearer",
        "digest",
        "hawk",
        "hmac",
        "jwt",
        "negotiate",
        "ntlm",
        "oauth",
        "oauth2",
        "scram-sha-1",
        "scram-sha-256",
        "sso",
    ]
)

# A word that carries a value to the word after it: ``the token is VALUE``.
COPULAS = frozenset(
    [
        "am",
        "are",
        "be",
        "been",
        "being",
        "can",
        "could",
        "did",
        "do",
        "does",
        "had",
        "has",
        "have",
        "is",
        "may",
        "might",
        "must",
        "shall",
        "should",
        "was",
        "were",
        "will",
        "would",
        "был",
        "была",
        "были",
        "было",
        "будет",
        "быть",
        "есть",
        "это",
    ]
)

# Ordinary words never carry a secret: a label followed by one of them merely
# mentions the label instead of binding a value to it.
PROSE_WORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "also",
        "an",
        "and",
        "another",
        "any",
        "as",
        "at",
        "because",
        "before",
        "below",
        "between",
        "both",
        "but",
        "by",
        "down",
        "during",
        "each",
        "either",
        "else",
        "every",
        "few",
        "for",
        "from",
        "further",
        "here",
        "how",
        "however",
        "if",
        "in",
        "into",
        "it",
        "its",
        "just",
        "less",
        "many",
        "me",
        "more",
        "most",
        "much",
        "my",
        "neither",
        "never",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "out",
        "over",
        "own",
        "per",
        "please",
        "same",
        "she",
        "so",
        "some",
        "still",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "though",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "us",
        "very",
        "via",
        "we",
        "what",
        "when",
        "where",
        "whether",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "why",
        "with",
        "within",
        "without",
        "yet",
        "you",
        "your",
        "а",
        "без",
        "бы",
        "в",
        "вам",
        "вас",
        "весь",
        "во",
        "вот",
        "все",
        "вы",
        "где",
        "да",
        "даже",
        "для",
        "до",
        "его",
        "если",
        "же",
        "за",
        "здесь",
        "и",
        "из",
        "или",
        "им",
        "их",
        "к",
        "как",
        "ко",
        "когда",
        "кто",
        "ли",
        "между",
        "мы",
        "на",
        "над",
        "не",
        "него",
        "нет",
        "ни",
        "но",
        "о",
        "об",
        "однако",
        "он",
        "она",
        "они",
        "оно",
        "от",
        "перед",
        "по",
        "под",
        "после",
        "при",
        "про",
        "с",
        "со",
        "так",
        "там",
        "те",
        "тем",
        "то",
        "тоже",
        "только",
        "тот",
        "тут",
        "у",
        "уже",
        "что",
        "чтобы",
        "эта",
        "эти",
        "этот",
        "я",
    ]
)

# The one marker a hidden value turns into.
REDACTED = "[redacted]"

# A label is one word, or a compound name whose segments are joined by "_",
# "." or "-".
_LABEL_JOINERS = "._-"
_SPACES = " \t"
_QUOTES = "\"'`"
# A value never starts with punctuation that merely closes a clause.
_NOT_A_VALUE = frozenset(",;:!?)]}>»[")
# Punctuation after a value closes the clause; it is not part of the value.
_TRAILING = frozenset(",;:!?.)]}>»\"'`")
# A label in one of these positions starts a clause of its own.
_BOUNDARY = frozenset("\n:;,([{|}=\"'`.!?")
_BULLETS = frozenset(["-", "*", "\u2022"])
# Characters that mark a bare word as key material rather than as prose.
VALUE_MARKS = "!@#$%^&*+=~/\\?"

MESSAGES = {
    "project": {"en": "project: %s", "ru": "проект: %s"},
    "project_none": {
        "en": "project: none selected (the engine uses its own active project)",
        "ru": "проект: не выбран (движок использует свой активный проект)",
    },
    "tasks": {"en": "tasks:", "ru": "задачи:"},
    "tasks_empty": {"en": "(no tasks)", "ru": "(задач нет)"},
    "release": {"en": "release: %s", "ru": "релиз: %s"},
    "release_unknown": {"en": "unknown", "ru": "неизвестно"},
    "plan": {"en": "plan:", "ru": "план:"},
    "plan_item": {"en": "  %d. %s", "ru": "  %d. %s"},
    "left": {"en": "session ended", "ru": "сеанс завершён"},
    "clarify_several": {
        "en": (
            "that matches more than one action, so nothing was done. Name one "
            "action, for example accept, send back, retry, pause, resume or "
            "switch the project."
        ),
        "ru": (
            "запрос подходит к нескольким действиям, поэтому ничего не сделано. "
            "Назовите одно действие, например принять, вернуть на доработку, "
            "повторить, пауза, продолжить или переключить проект."
        ),
    },
    "clarify_task": {
        "en": (
            "that asks for an action on a task, but names no task. Write the "
            "task identifier together with the action."
        ),
        "ru": (
            "запрос просит действие с задачей, но задача не названа. Напишите "
            "идентификатор задачи вместе с действием."
        ),
    },
    "clarify_action": {
        "en": (
            "that names a task but no action the session can carry out, so "
            "nothing was done. Name one action, for example accept, send back, "
            "retry, pause or resume."
        ),
        "ru": (
            "запрос называет задачу, но не действие, которое сеанс может "
            "выполнить, поэтому ничего не сделано. Назовите одно действие, "
            "например принять, вернуть на доработку, повторить, пауза или "
            "продолжить."
        ),
    },
    "clarify_remarks": {
        "en": (
            "that sends a task back but carries no remarks. Write what has to "
            "change after the task identifier."
        ),
        "ru": (
            "запрос возвращает задачу, но замечаний нет. Напишите, что нужно "
            "изменить, после идентификатора задачи."
        ),
    },
    "clarify_project": {
        "en": "that selects a project but names none. Write the project key.",
        "ru": "запрос переключает проект, но проект не назван. Напишите ключ проекта.",
    },
    "sensitive": {
        "en": (
            "adopting a repository, creating a project, setting a secret and "
            "changing configuration are explicit separate actions and are never "
            "carried out from a sentence. Run the client's own command for it "
            "outside the session."
        ),
        "ru": (
            "принятие репозитория, создание проекта, установка секрета и "
            "изменение конфигурации — отдельные явные действия и никогда не "
            "выполняются по фразе. Выполните для этого собственную команду "
            "клиента вне сеанса."
        ),
    },
    "failure": {"en": "failed: %s", "ru": "не удалось: %s"},
    "next_step": {
        "en": (
            "next step: the session is still open. Check the engine with "
            "`forgel-code status` and send the request again."
        ),
        "ru": (
            "дальше: сеанс продолжается. Проверьте движок командой "
            "`forgel-code status` и повторите запрос."
        ),
    },
    "no_reply": {"en": "(the engine sent no reply)", "ru": "(движок не прислал ответа)"},
}


def language_of(text: str) -> str:
    """The language of the owner's message, as far as a reply must follow it."""
    for character in text:
        if "\u0400" <= character <= "\u04ff":
            return "ru"
    return "en"


def _word_end(text: str, start: int) -> int:
    """The end of the word characters that start at ``start``."""
    end = start
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    return end


def _label_end(text: str, start: int) -> Optional[int]:
    """The end of the label that starts at ``start``, if one does."""
    end = _word_end(text, start)
    if end == start:
        return None
    while end < len(text) and text[end] in _LABEL_JOINERS:
        following = _word_end(text, end + 1)
        if following == end + 1:
            break
        end = following
    return end


def _labels(text: str):
    """Every label in ``text``, as ``(start, end)`` pairs."""
    position = 0
    while position < len(text):
        end = _label_end(text, position)
        if end is None:
            position += 1
            continue
        yield position, end
        position = end


def _segments(label: str) -> List[str]:
    """The segments of a label, as split by its joiners."""
    parts: List[str] = []
    current: List[str] = []
    for character in label:
        if character in _LABEL_JOINERS:
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
    parts.append("".join(current))
    return parts


def _secret_label(label: str) -> bool:
    """Whether a label word or compound name bears a secret."""
    lowered = label.lower()
    if lowered in SECRET_WORDS:
        return True
    for segment in _segments(lowered):
        if segment in SECRET_WORDS or segment.startswith(SECRET_STEMS):
            return True
    return False


def _skip_spaces(text: str, start: int) -> int:
    while start < len(text) and text[start] in _SPACES:
        start += 1
    return start


def _bare(token: str) -> str:
    """A token without its quotes and closing punctuation, lower-cased."""
    return token.strip(_QUOTES).rstrip(",;:!?)]}>»").lower()


def _looks_like_credential(token: str) -> bool:
    """Whether a bare word looks like key material rather than like prose."""
    core = token.strip(_QUOTES).rstrip(",;:!?)]}>»")
    if not core:
        return False
    if any(character.isdigit() for character in core):
        return True
    if core != core.lower() and core != core.upper():
        return True
    if len(core) >= 16:
        return True
    return any(character in VALUE_MARKS for character in core)


def _span(text: str, start: int) -> Optional[Tuple[int, int]]:
    """The one value token at ``start``, a quoted run included."""
    if start >= len(text) or text[start].isspace():
        return None
    if text.startswith(REDACTED, start):
        return start, start + len(REDACTED)
    if text[start] in _NOT_A_VALUE:
        return None
    if text[start] in _QUOTES:
        limit = len(text)
        newline = text.find("\n", start)
        if newline >= 0:
            limit = newline
        closing = text.find(text[start], start + 1, limit)
        if closing < 0:
            return None
        return start, closing + 1
    end = start
    while end < len(text) and not text[end].isspace():
        end += 1
    while end > start + 1 and text[end - 1] in _TRAILING:
        end -= 1
    return start, end


def _scheme_value(text: str, after: int) -> Optional[Tuple[int, int]]:
    """The credential after an authorization scheme word, if there is one."""
    span = _span(text, _skip_spaces(text, after))
    if span is None:
        return None
    if _bare(text[span[0]:span[1]]) in PROSE_WORDS:
        # ``bearer of good news`` names no credential.
        return None
    return span


def _bound_value(text: str, start: int) -> Optional[Tuple[int, int]]:
    """The value a joiner at ``start`` binds, past an authorization scheme."""
    span = _span(text, _skip_spaces(text, start))
    if span is None:
        return None
    if _bare(text[span[0]:span[1]]) in AUTH_SCHEMES:
        # The scheme word may stay visible; the credential after it may not.
        return _scheme_value(text, span[1])
    return span


def _stands_alone(text: str, start: int) -> bool:
    """Whether a label starts a clause, the way ``token abc`` does."""
    lead = text[:start].rstrip(_SPACES)
    if not lead:
        return True
    if lead[-1] in _BOUNDARY:
        return True
    return lead.rsplit("\n", 1)[-1].strip() in _BULLETS


def _binding(text: str, start: int, label_end: int) -> Optional[Tuple[int, int]]:
    """The span of the value bound to the label that starts at ``start``."""
    while True:
        if label_end >= len(text):
            return None
        character = text[label_end]
        if character in _QUOTES:
            return _span(text, label_end)
        if character in "=:":
            return _bound_value(text, label_end + 1)
        if character not in _SPACES:
            return None
        after = _skip_spaces(text, label_end)
        if after >= len(text):
            return None
        if text[after] in "=:":
            label_end = after
            continue
        if text[after] in _QUOTES:
            return _span(text, after)
        following = _label_end(text, after)
        if following is None:
            return None
        word = _bare(text[after:following])
        if word in AUTH_SCHEMES:
            # ``token Bearer VALUE``: the scheme word stays, the value goes.
            return _scheme_value(text, following)
        if _secret_label(text[after:following]):
            # A compound label may be written as several words.
            label_end = following
            continue
        if word in COPULAS:
            # ``the token is VALUE``: the copula stays, the value goes.
            position = _skip_spaces(text, following)
            if position < len(text) and text[position] in "=:":
                return _bound_value(text, position + 1)
            span = _bound_value(text, following)
            if span is None:
                return None
            if not _looks_like_credential(text[span[0]:span[1]]):
                return None
            return span
        if word in PROSE_WORDS:
            # The label is mentioned, not bound to a value.
            return None
        if not _stands_alone(text, start) and not _looks_like_credential(word):
            return None
        return _bound_value(text, after)


def redact(text: str) -> str:
    """Never let key material reach the screen."""
    if not text:
        return text
    out: List[str] = []
    copied = 0
    for start, end in _labels(text):
        if start < copied or not _secret_label(text[start:end]):
            continue
        span = _binding(text, start, end)
        if span is None:
            continue
        out.append(text[copied:span[0]])
        out.append(REDACTED)
        copied = span[1]
    out.append(text[copied:])
    return "".join(out)


def _normalise(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _message(key: str, lang: str) -> str:
    return MESSAGES[key][lang]


def _is_identifier(token: str) -> bool:
    bare = token.lstrip("#")
    if not bare:
        return False
    if any(character not in ID_ALPHABET for character in bare):
        return False
    if not any(character in DIGITS for character in bare):
        return False
    return any(separator in bare for separator in ID_SEPARATORS)


def _task_id(tokens: Sequence[str]) -> Optional[str]:
    """The task identifier a sentence names, if it names one."""
    for token in tokens:
        bare = token.strip("\"'`,;:()")
        if not bare or _normalise(bare) in ID_STOPWORDS:
            continue
        if not _is_identifier(bare):
            continue
        return bare.lstrip("#")
    return None


def _strip_leaders(text: str) -> str:
    changed = True
    while changed:
        changed = False
        text = text.strip().lstrip(":—-,").strip()
        lowered = text.lower()
        for leader in REMARK_LEADERS:
            if lowered.startswith(leader):
                text = text[len(leader):]
                changed = True
                break
    return text


def _remarks(rest: str) -> str:
    text = _strip_leaders(rest)
    lowered = text.lower()
    best: Optional[tuple] = None
    for connector in REMARK_CONNECTORS:
        index = lowered.find(connector)
        if index >= 0 and (best is None or index < best[0]):
            best = (index, connector)
    if best is not None:
        text = text[best[0] + len(best[1]):]
    return _strip_leaders(text).strip(" \t\"'")


def _switch_key(stripped: str, prefix: str) -> str:
    """The project key after a switch prefix, in the owner's own spelling."""
    if len(stripped) > len(prefix):
        return stripped[len(prefix):].strip().strip("\"'`")
    return ""


def resolve(text: str) -> Dict[str, Any]:
    """Decide which single action one sentence asks for.

    ``kind`` is one of ``leave``, ``sensitive``, ``switch``, ``plan``,
    ``clarify``, ``action`` or ``say``.
    """
    stripped = text.strip()
    lowered = _normalise(stripped)

    if lowered.strip(" !.?,:;") in LEAVE_WORDS:
        return {"kind": "leave"}

    if any(marker in lowered for marker in SENSITIVE_MARKERS):
        return {"kind": "sensitive"}

    # A switch prefix may end the sentence, so the line is compared with a
    # trailing space: ``switch to`` still asks for a project key.
    padded = lowered + " "
    for prefix in SWITCH_PREFIXES:
        if padded.startswith(prefix):
            key = _switch_key(stripped, prefix)
            if not key:
                return {"kind": "clarify", "reason": "clarify_project"}
            return {"kind": "switch", "key": key}

    if lowered.strip(" !.?,:;") in PLAN_EXACT:
        return {"kind": "plan", "goal": ""}
    for prefix in PLAN_PREFIXES:
        if lowered.startswith(prefix):
            return {"kind": "plan", "goal": stripped[len(prefix):].strip()}

    tokens = stripped.split()
    matched = [
        name for name, words in ACTIONS if any(word in lowered for word in words)
    ]
    if len(matched) > 1:
        return {"kind": "clarify", "reason": "clarify_several"}
    if not matched:
        if _task_id(tokens) is not None:
            # The owner names a task but no action the session can carry out.
            return {"kind": "clarify", "reason": "clarify_action"}
        return {"kind": "say", "text": stripped}

    name = matched[0]
    if name in ("pause", "resume"):
        return {"kind": "action", "action": name}

    task_id = _task_id(tokens)
    if task_id is None:
        return {"kind": "clarify", "reason": "clarify_task"}
    remarks = ""
    if name == "rework":
        index = next(
            (
                position
                for position, token in enumerate(tokens)
                if token.strip("\"'`.,;:()").lstrip("#") == task_id
            ),
            None,
        )
        rest = " ".join(tokens[index + 1:]) if index is not None else ""
        remarks = _remarks(rest)
        if not remarks:
            return {"kind": "clarify", "reason": "clarify_remarks"}
    return {
        "kind": "action",
        "action": name,
        "task": task_id,
        "remarks": remarks,
    }


def default_engine() -> Engine:
    """The engine the environment names, with the bounded call limit."""
    binary = os.environ.get("FORGEL_ENGINE") or "forgel"
    raw = os.environ.get("FORGEL_CODE_TIMEOUT")
    timeout = DEFAULT_TIMEOUT
    if raw is not None and raw.strip():
        try:
            timeout = float(raw)
        except ValueError:
            timeout = DEFAULT_TIMEOUT
    return Engine(binary, timeout)


def _field(entry: Dict[str, Any], names: Sequence[str]) -> Optional[str]:
    for name in names:
        value = entry.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def task_entries(payload: Any) -> List[Dict[str, Any]]:
    """The tasks of an engine answer, in the engine's own order."""
    entries = commands.listing_entries(payload)
    if entries:
        return [entry for entry in entries if isinstance(entry, dict)]
    if isinstance(payload, dict):
        for key in TASK_KEYS:
            value = payload.get(key)
            if isinstance(value, dict):
                nested = task_entries(value)
                if nested:
                    return nested
    return []


def plan_entries(payload: Any) -> List[Dict[str, Any]]:
    """The planned tasks of an answer, in the order the engine planned them."""
    if isinstance(payload, dict):
        for key in PLAN_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [entry for entry in value if isinstance(entry, dict)]
            if isinstance(value, dict):
                nested = plan_entries(value)
                if nested:
                    return nested
    return []


def task_line(entry: Dict[str, Any]) -> str:
    parts = [
        _field(entry, ("id", "task_id")) or "?",
        _field(entry, ("state", "status", "phase")) or "?",
        _field(entry, ("title", "name", "summary")) or "",
    ]
    return "  - " + "  ".join(part for part in parts if part)


def release_text(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in RELEASE_KEYS:
        value = payload.get(key)
        if isinstance(value, dict):
            parts = [
                _field(value, (name,))
                for name in ("name", "version", "tag", "state", "status", "phase")
            ]
            parts = [part for part in parts if part]
            if parts:
                return " ".join(parts)
        elif isinstance(value, str) and value.strip():
            return value.strip()
    return None


def reply_text(payload: Any) -> Optional[str]:
    """The agent's reply inside an engine answer, without the envelope."""
    if not isinstance(payload, dict):
        return None
    for key in REPLY_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            lines = render_human(value)
            if lines:
                return "\n".join(lines)
    shown = set(PLAN_KEYS) | set(RELEASE_KEYS)
    rest = {
        key: value
        for key, value in payload.items()
        if key not in META_KEYS and key not in shown
    }
    if rest:
        return "\n".join(render_human(rest))
    return None


class InteractiveSession:
    """One conversation with the engine's project agent."""

    def __init__(
        self,
        engine: Engine,
        store: Session,
        out: TextIO,
        inp: TextIO,
    ) -> None:
        self.engine = engine
        self.store = store
        self.out = out
        self.input = inp
        self.stopped = False
        self.project: Optional[str] = store.project() if store.selected() else None
        self.lang = "en"
        self.last_state: Optional[str] = None

    # -- output ---------------------------------------------------------

    def write(self, text: str = "", end: str = "\n") -> None:
        self.out.write(redact(text) + end)
        self.out.flush()

    def project_line(self) -> str:
        if self.project:
            return _message("project", self.lang) % self.project
        return _message("project_none", self.lang)

    def show_failure(self, exc: EngineError) -> None:
        self.write(_message("failure", self.lang) % exc.message)
        self.write(_message("next_step", self.lang))

    # -- engine ---------------------------------------------------------

    def call(
        self, argv: Sequence[str], quiet: bool = False
    ) -> Optional[Dict[str, Any]]:
        """One engine command; a failure is shown and the session continues."""
        if self.stopped:
            return None
        try:
            return self.engine.run(argv)
        except EngineError as exc:
            if not quiet:
                self.show_failure(exc)
            return None

    def command(self, name: str, **options: Any) -> List[str]:
        return commands.build(name, self.project, **options)

    # -- state ----------------------------------------------------------

    def state_lines(self, quiet: bool = False) -> Optional[List[str]]:
        """Read the task and release state from the engine.

        ``quiet`` swallows a failure: the refresh must never turn into a wall
        of text when the engine is briefly unreachable.
        """
        tasks = self.call(self.command("tasks"), quiet=quiet)
        if tasks is None:
            return None
        status = self.call(self.command("status"), quiet=quiet)
        if status is None:
            return None

        lines = [self.project_line(), _message("tasks", self.lang)]
        entries = task_entries(tasks)
        if entries:
            lines.extend(task_line(entry) for entry in entries)
        else:
            lines.append("  " + _message("tasks_empty", self.lang))

        release = release_text(status) or _message("release_unknown", self.lang)
        lines.append(_message("release", self.lang) % release)
        return lines

    def refresh(self, force: bool = False, quiet: bool = False) -> None:
        """Re-read the state and show it when it changed, without being asked."""
        if self.stopped:
            return
        lines = self.state_lines(quiet=quiet)
        if lines is None:
            return
        text = "\n".join(lines)
        if force or text != self.last_state:
            self.last_state = text
            self.write(text)

    # -- requests -------------------------------------------------------

    def show_plan(self, payload: Dict[str, Any]) -> None:
        entries = plan_entries(payload)
        if not entries:
            self.write(reply_text(payload) or _message("no_reply", self.lang))
            return
        self.write(_message("plan", self.lang))
        for position, entry in enumerate(entries, 1):
            parts = [
                _field(entry, ("state", "status", "phase")) or "?",
                _field(entry, ("title", "name", "summary")) or "?",
            ]
            self.write(
                _message("plan_item", self.lang) % (position, "  ".join(parts))
            )

    def speak(self, text: str) -> None:
        payload = self.call(self.command("say", text=text))
        if payload is None:
            return
        self.write(reply_text(payload) or _message("no_reply", self.lang))

    def ask_plan(self, goal: str) -> None:
        payload = self.call(self.command("plan", goal=goal))
        if payload is None:
            return
        self.show_plan(payload)

    def switch_project(self, key: str) -> None:
        payload = self.call(commands.build("use", key=key))
        if payload is None:
            # The engine refused the project: the previous selection stays.
            return
        self.store.save_project(key)
        self.project = key
        self.last_state = None
        self.write(self.project_line())

    def perform(self, action: str, task: Optional[str], remarks: str) -> None:
        if action in ("pause", "resume"):
            payload = self.call(self.command(action))
        else:
            payload = self.call(self.command(action, task_id=task, notes=remarks))
        if payload is None:
            return
        text = reply_text(payload)
        if text:
            self.write(text)

    def handle(self, text: str) -> str:
        """Carry out one sentence; ``leave`` ends the session."""
        self.lang = language_of(text)
        intent = resolve(text)
        kind = intent["kind"]

        if kind == "leave":
            return "leave"
        if kind == "sensitive":
            self.write(_message("sensitive", self.lang))
            return "continue"
        if kind == "clarify":
            self.write(_message(intent["reason"], self.lang))
            return "continue"

        try:
            if kind == "switch":
                self.switch_project(intent["key"])
            elif kind == "plan":
                self.ask_plan(intent["goal"])
            elif kind == "action":
                self.perform(
                    intent["action"], intent.get("task"), intent.get("remarks", "")
                )
            else:
                self.speak(intent["text"])
        except EngineError as exc:
            # The intent itself was refused; the session stays usable.
            self.show_failure(exc)
        self.refresh(force=True)
        return "continue"

    # -- lifecycle ------------------------------------------------------

    def run(self) -> int:
        self.write(self.project_line())
        self.refresh(force=True, quiet=True)
        try:
            while True:
                # Keep the state current between requests, without being asked.
                self.refresh(quiet=True)
                self.write(PROMPT, end="")
                line = self.input.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                if self.handle(line.rstrip("\n")) == "leave":
                    break
        except KeyboardInterrupt:  # pragma: no cover - interactive convenience
            pass
        finally:
            self.stopped = True
            self.write(_message("left", self.lang))
        return 0


def run(
    engine: Optional[Engine] = None,
    store: Optional[Session] = None,
    out: Optional[TextIO] = None,
    inp: Optional[TextIO] = None,
) -> int:
    """Open the interactive session and keep it open until the owner leaves."""
    session = InteractiveSession(
        engine if engine is not None else default_engine(),
        store if store is not None else Session(),
        out if out is not None else sys.stdout,
        inp if inp is not None else sys.stdin,
    )
    return session.run()
