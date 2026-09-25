import hmac
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl


@dataclass(frozen=True)
class TelegramWebAppUser:
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


@dataclass(frozen=True)
class TelegramInitData:
    user: TelegramWebAppUser
    auth_date: int
    query_id: Optional[str] = None
    start_param: Optional[str] = None
    chat_instance: Optional[str] = None
    raw: str = ""


class InitDataError(Exception):
    pass


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def verify_and_parse_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_sec: int = 24 * 60 * 60,
    now_ts: Optional[int] = None,
) -> TelegramInitData:
    """
    Telegram WebApp initData validation:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
    """
    if not init_data or not isinstance(init_data, str):
        raise InitDataError("initData is empty")

    if not bot_token:
        raise InitDataError("bot_token is empty (TG_TOKEN)")

    # Parse query string into list of (k,v). Keep raw values.
    pairs = parse_qsl(init_data, keep_blank_values=True)

    data: Dict[str, str] = {}
    received_hash: Optional[str] = None

    for k, v in pairs:
        if k in data or (k == "hash" and received_hash is not None):
            raise InitDataError("duplicate initData field")
        if k == "hash":
            received_hash = v
        else:
            data[k] = v

    if not received_hash:
        raise InitDataError("hash is missing in initData")
    if len(received_hash) != 64 or any(c not in "0123456789abcdef" for c in received_hash):
        raise InitDataError("hash format is invalid")

    # Build data_check_string: keys sorted, "k=v" joined with "\n", excluding hash
    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))

    secret_key = _hmac_sha256(key=b"WebAppData", msg=bot_token.encode("utf-8"))
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InitDataError("hash mismatch (invalid initData)")

    # auth_date freshness
    if "auth_date" not in data:
        raise InitDataError("auth_date is missing")

    try:
        auth_date = int(data["auth_date"])
    except ValueError as e:
        raise InitDataError("auth_date is not int") from e

    if now_ts is None:
        import time
        now_ts = int(time.time())

    if max_age_sec is not None and max_age_sec > 0:
        if auth_date < now_ts - max_age_sec:
            raise InitDataError("initData is too old")
    if auth_date > now_ts + 60:
        raise InitDataError("auth_date is in the future")

    # user field is JSON
    if "user" not in data:
        raise InitDataError("user is missing")

    try:
        user_obj: Dict[str, Any] = json.loads(data["user"])
    except Exception as e:
        raise InitDataError("user JSON parse failed") from e

    if not isinstance(user_obj, dict) or "id" not in user_obj:
        raise InitDataError("user.id is missing")
    user_id = user_obj["id"]
    if type(user_id) is not int or user_id <= 0:
        raise InitDataError("user.id is invalid")

    user = TelegramWebAppUser(
        id=user_id,
        username=user_obj.get("username"),
        first_name=user_obj.get("first_name"),
        last_name=user_obj.get("last_name"),
    )

    return TelegramInitData(
        user=user,
        auth_date=auth_date,
        query_id=data.get("query_id"),
        start_param=data.get("start_param"),
        chat_instance=data.get("chat_instance"),
        raw=init_data,
    )
