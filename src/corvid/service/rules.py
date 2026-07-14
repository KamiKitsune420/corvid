"""Rule application use-case: evaluate rules and execute their actions."""

from __future__ import annotations

import logging

from ..domain.entities import Message
from ..domain.rules import ActionType, RuleEngine
from ..infra.repositories import FolderRepository, MessageRepository, RuleRepository

log = logging.getLogger("corvid.rules")


class RuleService:
    """Loads rules and applies them to messages, mutating state via repositories."""

    def __init__(
        self,
        rules: RuleRepository,
        messages: MessageRepository,
        folders: FolderRepository,
    ) -> None:
        self._rules = rules
        self._messages = messages
        self._folders = folders

    def engine(self) -> RuleEngine:
        return RuleEngine(self._rules.list())

    def apply_to_message(
        self, account_id: int, message: Message, *, engine: RuleEngine | None = None
    ) -> list[ActionType]:
        """Apply matching rules to ``message``. Returns the action types performed."""
        if message.id is None:
            return []
        engine = engine or self.engine()
        performed: list[ActionType] = []
        for action in engine.evaluate(message):
            if self._execute(account_id, message, action.type, action.param):
                performed.append(action.type)
        return performed

    def _execute(
        self, account_id: int, message: Message, action: ActionType, param: str
    ) -> bool:
        assert message.id is not None
        if action is ActionType.MARK_READ:
            self._messages.set_seen(message.id, True)
        elif action is ActionType.MARK_UNREAD:
            self._messages.set_seen(message.id, False)
        elif action is ActionType.FLAG:
            self._messages.set_flagged(message.id, True)
        elif action is ActionType.DELETE:
            self._messages.set_deleted(message.id, True)
        elif action is ActionType.MOVE:
            target = self._resolve_folder(account_id, param)
            if target is None:
                log.warning("rule MOVE target not found: %r", param)
                return False
            self._messages.move_to_folder(message.id, target)
        else:
            return False
        return True

    def _resolve_folder(self, account_id: int, param: str) -> int | None:
        for folder in self._folders.list_for_account(account_id):
            if folder.id is not None and (
                folder.remote_name == param
                or folder.display_name == param
                or folder.type.value == param
            ):
                return folder.id
        return None
