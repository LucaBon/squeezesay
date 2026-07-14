"""AWS Lambda entry point for the 'impianto' Alexa custom skill.

Thin layer: it wires Alexa intents to the pure functions in :mod:`actions`,
which do the real work against LMS/Daphile. All the testable logic lives in
:mod:`actions` and :mod:`lms`; this file only handles Alexa plumbing.

Environment variables (see config.example.env):
    LMS_BASE_URL   e.g. https://xxxx.trycloudflare.com
    LMS_PLAYER_ID  MAC of the Daphile player, e.g. aa:bb:cc:dd:ee:ff
    LMS_USERNAME   optional (tunnel basic auth)
    LMS_PASSWORD   optional
"""

import os

from ask_sdk_core.dispatch_components import (
    AbstractExceptionHandler,
    AbstractRequestHandler,
)
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import is_intent_name, is_request_type

import actions
import blocklist_store
from lms import LMSClient
from messages import msg


# Config comes from environment variables (own-Lambda deploy) or, as a fallback,
# an optional config.py next to this file (handy for Alexa-hosted skills, which
# don't expose an env-var UI). See config.example.py.
try:
    import config as _config_mod  # optional
except Exception:  # pragma: no cover - config is optional
    _config_mod = None


def _cfg(key):
    value = os.environ.get(key)
    if value is not None:
        return value
    return getattr(_config_mod, key, None) if _config_mod else None


def _lms():
    return LMSClient(
        base_url=_cfg("LMS_BASE_URL"),
        player_id=_cfg("LMS_PLAYER_ID"),
        username=_cfg("LMS_USERNAME") or None,
        password=_cfg("LMS_PASSWORD") or None,
    )


def _store():
    # On Alexa-hosted skills DYNAMODB_PERSISTENCE_TABLE_NAME is set automatically;
    # for an own-Lambda deploy set BLOCKLIST_TABLE. Neither -> static-only no-op.
    table = _cfg("BLOCKLIST_TABLE") or os.environ.get("DYNAMODB_PERSISTENCE_TABLE_NAME")
    if not table:
        return blocklist_store.NoOpBlocklistStore()
    region = _cfg("BLOCKLIST_REGION") or os.environ.get("DYNAMODB_PERSISTENCE_REGION")
    return blocklist_store.BlocklistStore(table, region=region)


def _person_id(handler_input):
    """The recognized speaker's Voice ID, or None when not recognized."""
    ctx = handler_input.request_envelope.context
    system = getattr(ctx, "system", None)
    person = getattr(system, "person", None) if system else None
    return getattr(person, "person_id", None) if person else None


def _guard(handler_input):
    """Access gate for a request: restricted unless the speaker is the trusted
    owner. Effective blocklist = config baseline + voice-added stored terms, read
    fresh each request so edits apply on the very next utterance."""
    trusted = _cfg("TRUSTED_PERSON_ID")
    blocklist = actions.parse_blocklist(_cfg("KIDSAFE_BLOCKLIST")) + _store().get()
    restricted = bool(blocklist) and (
        not trusted or _person_id(handler_input) != trusted
    )
    return actions.Guard(restricted, blocklist)


def _is_owner(handler_input):
    trusted = _cfg("TRUSTED_PERSON_ID")
    return bool(trusted) and _person_id(handler_input) == trusted


def _slot(handler_input, name):
    slots = handler_input.request_envelope.request.intent.slots or {}
    slot = slots.get(name)
    return slot.value if slot else None


def _respond(handler_input, speech, end=True):
    rb = handler_input.response_builder.speak(speech)
    if not end:
        rb = rb.set_should_end_session(False)
    return rb.response


def _session(handler_input):
    return handler_input.attributes_manager.session_attributes


def _try_choose_by_name(handler_input, spoken):
    """If a numbered list is open, treat the request as a name-pick from it (so
    "metti Supernatural" after a list plays the listed item, not a fresh search).
    Returns the speech, or ``None`` when it isn't a selection so the caller falls
    through to a normal search. Mirrors the local router's branch 4b."""
    candidates = _session(handler_input).get("candidates")
    if not candidates:
        return None
    return actions.choose_by_name(
        _lms(), candidates, spoken, guard=_guard(handler_input)
    )


def _respond_play(handler_input, result):
    """Speak a play result; when it's a 'did you mean' list, stash the candidates
    and keep the session open so the follow-up 'metti la N' / name-pick works."""
    candidates = getattr(result, "candidates", None)
    if candidates:
        _session(handler_input)["candidates"] = candidates
    return _respond(handler_input, result, end=not candidates)


class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        # Log the recognized personId so the owner can read it from CloudWatch
        # once and paste it into TRUSTED_PERSON_ID (personalization bootstrap).
        person_id = _person_id(handler_input)
        if person_id:
            print(f"[personalization] personId={person_id}")
        speech = msg("launch")
        if person_id and not _cfg("TRUSTED_PERSON_ID"):
            speech += msg("launch_no_personalization")
        return _respond(handler_input, speech, end=False)


class PlaySongHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("RiproduciBranoIntent")(handler_input)

    def handle(self, handler_input):
        query = _slot(handler_input, "query")
        chosen = _try_choose_by_name(handler_input, query)  # pick from an open list first
        if chosen is not None:
            return _respond(handler_input, chosen)
        return _respond_play(
            handler_input,
            actions.play_song(_lms(), query, guard=_guard(handler_input)),
        )


class PlayArtistHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("RiproduciArtistaIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(
            handler_input,
            actions.play_artist(
                _lms(), _slot(handler_input, "artist"), guard=_guard(handler_input)
            ),
        )


class PlayPlaylistHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("RiproduciPlaylistIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(
            handler_input,
            actions.play_playlist(
                _lms(), _slot(handler_input, "name"), guard=_guard(handler_input)
            ),
        )


class PlayAlbumHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("RiproduciAlbumIntent")(handler_input)

    def handle(self, handler_input):
        album = _slot(handler_input, "album")
        chosen = _try_choose_by_name(handler_input, album)
        if chosen is not None:
            return _respond(handler_input, chosen)
        return _respond(
            handler_input,
            actions.play_album(_lms(), album, guard=_guard(handler_input)),
        )


class PlayLocalHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("RiproduciLocaleIntent")(handler_input)

    def handle(self, handler_input):
        query = _slot(handler_input, "query")
        chosen = _try_choose_by_name(handler_input, query)
        if chosen is not None:
            return _respond(handler_input, chosen)
        return _respond_play(
            handler_input,
            actions.play_local(_lms(), query, guard=_guard(handler_input)),
        )


class ListLocalAlbumsHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ElencaAlbumLocaleIntent")(handler_input)

    def handle(self, handler_input):
        result = actions.local_albums_list(
            _lms(), _slot(handler_input, "artist"), guard=_guard(handler_input)
        )
        handler_input.attributes_manager.session_attributes["candidates"] = result[
            "candidates"
        ]
        keep_open = bool(result["candidates"])
        return _respond(handler_input, result["speech"], end=not keep_open)


class ListTopTracksHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ElencaTopTracksIntent")(handler_input)

    def handle(self, handler_input):
        result = actions.top_tracks_list(
            _lms(), _slot(handler_input, "artist"), guard=_guard(handler_input)
        )
        # Stash the numbered candidates so the follow-up choice can play one.
        handler_input.attributes_manager.session_attributes["candidates"] = result[
            "candidates"
        ]
        keep_open = bool(result["candidates"])
        return _respond(handler_input, result["speech"], end=not keep_open)


class ChooseNumberHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ScegliNumeroIntent")(handler_input)

    def handle(self, handler_input):
        candidates = handler_input.attributes_manager.session_attributes.get("candidates")
        try:
            number = int(_slot(handler_input, "numero"))
        except (TypeError, ValueError):
            number = None
        return _respond(
            handler_input,
            actions.choose_from(_lms(), candidates, number, guard=_guard(handler_input)),
        )


class AggiungiBloccoHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AggiungiBloccoIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(
            handler_input,
            actions.add_block(
                _store(),
                _slot(handler_input, "term"),
                is_owner=_is_owner(handler_input),
            ),
        )


class RimuoviBloccoHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("RimuoviBloccoIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(
            handler_input,
            actions.remove_block(
                _store(),
                _slot(handler_input, "term"),
                is_owner=_is_owner(handler_input),
            ),
        )


class ElencaBlocchiHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ElencaBlocchiIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(
            handler_input,
            actions.list_blocks(_store(), is_owner=_is_owner(handler_input)),
        )


class PauseHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.PauseIntent")(handler_input) or is_intent_name(
            "AMAZON.StopIntent"
        )(handler_input) or is_intent_name("AMAZON.CancelIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(handler_input, actions.pause(_lms()))


class ResumeHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.ResumeIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(handler_input, actions.resume(_lms()))


class NextHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.NextIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(handler_input, actions.next_track(_lms()))


class PreviousHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.PreviousIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(handler_input, actions.previous_track(_lms()))


class VolumeUpHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AlzaVolumeIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(handler_input, actions.change_volume(_lms(), "up"))


class VolumeDownHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AbbassaVolumeIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(handler_input, actions.change_volume(_lms(), "down"))


class NowPlayingHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("CosaStaSuonandoIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(handler_input, actions.now_playing(_lms()))


class HelpHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(handler_input, msg("help"), end=False)


class FallbackHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        return _respond(handler_input, msg("alexa_fallback"), end=False)


class SessionEndedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        return _respond(handler_input, msg("alexa_error"))


sb = SkillBuilder()
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(PlaySongHandler())
sb.add_request_handler(PlayArtistHandler())
sb.add_request_handler(PlayPlaylistHandler())
sb.add_request_handler(PlayAlbumHandler())
sb.add_request_handler(PlayLocalHandler())
sb.add_request_handler(ListLocalAlbumsHandler())
sb.add_request_handler(ListTopTracksHandler())
sb.add_request_handler(ChooseNumberHandler())
sb.add_request_handler(AggiungiBloccoHandler())
sb.add_request_handler(RimuoviBloccoHandler())
sb.add_request_handler(ElencaBlocchiHandler())
sb.add_request_handler(PauseHandler())
sb.add_request_handler(ResumeHandler())
sb.add_request_handler(NextHandler())
sb.add_request_handler(PreviousHandler())
sb.add_request_handler(VolumeUpHandler())
sb.add_request_handler(VolumeDownHandler())
sb.add_request_handler(NowPlayingHandler())
sb.add_request_handler(HelpHandler())
sb.add_request_handler(FallbackHandler())
sb.add_request_handler(SessionEndedHandler())
sb.add_exception_handler(CatchAllExceptionHandler())

handler = sb.lambda_handler()
