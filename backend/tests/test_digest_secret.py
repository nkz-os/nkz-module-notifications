from unittest.mock import MagicMock, patch

import requests

from app.dispatcher import NotificationDispatcher


def test_dispatch_digest_sends_internal_secret():
    settings = MagicMock(email_service_url="http://email", internal_service_secret="sec")
    d = NotificationDispatcher(settings=settings)
    with patch.object(d, "_get_channels", return_value={"email": {"enabled": True, "to": "a@b.c"}}), \
         patch.object(d, "_record_delivery"), \
         patch.object(requests, "post", return_value=MagicMock(status_code=200)) as m:
        result = d.dispatch_digest("t", "subject", "body")
    assert m.call_args.kwargs["headers"]["X-Internal-Service-Secret"] == "sec"
    assert result[0]["status"] == "sent"
