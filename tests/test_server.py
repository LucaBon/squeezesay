"""Startup resilience of the local web server (localvoice/server.py).

The hosting PC often wakes from sleep (or boots) before the network is back:
an unreachable LMS at that moment is transient, so startup must wait and
retry instead of dying with a traceback.
"""

from lms import LMSError

import server


def test_wait_for_players_retries_until_lms_answers(monkeypatch, capsys):
    sala = [{"playerid": "aa:bb:cc:dd:ee:ff", "name": "Sala"}]
    outcomes = [LMSError("rete giu"), LMSError("rete giu"), sala]

    class FlakyClient:
        def __init__(self, url, player_id):
            pass

        def get_players(self):
            out = outcomes.pop(0)
            if isinstance(out, Exception):
                raise out
            return out

    monkeypatch.setattr(server, "LMSClient", FlakyClient)
    naps = []
    players = server.wait_for_players("http://lms:9000", delay=5,
                                      sleep=naps.append)
    assert players == sala
    assert naps == [5, 5]  # one nap per failed attempt, then success
    out = capsys.readouterr().out
    assert "LMS non raggiungibile" in out
    assert "LMS raggiunto" in out


def test_wait_for_players_immediate_hit_stays_quiet(monkeypatch, capsys):
    sala = [{"playerid": "aa:bb:cc:dd:ee:ff", "name": "Sala"}]

    class HealthyClient:
        def __init__(self, url, player_id):
            pass

        def get_players(self):
            return sala

    monkeypatch.setattr(server, "LMSClient", HealthyClient)
    players = server.wait_for_players(
        "http://lms:9000", sleep=lambda s: (_ for _ in ()).throw(AssertionError))
    assert players == sala
    assert capsys.readouterr().out == ""  # no retry chatter when all is well
