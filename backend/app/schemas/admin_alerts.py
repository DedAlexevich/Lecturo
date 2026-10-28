from app.models import AlertKind
from app.schemas.common import Schema
from app.schemas.user import TelegramNotifications


class AlertSettingsIn(Schema):
    enabled: bool
    kinds: list[AlertKind]
    recoveries: bool


class AlertSettingsOut(AlertSettingsIn):
    telegram: TelegramNotifications
