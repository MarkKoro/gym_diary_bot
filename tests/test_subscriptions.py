import atexit
import asyncio
import importlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta, UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db.close()
atexit.register(lambda: os.path.exists(tmp_db.name) and os.remove(tmp_db.name))

os.environ["DB_PATH"] = tmp_db.name

import settings  # noqa: E402
importlib.reload(settings)
import db  # noqa: E402
importlib.reload(db)
import bot  # noqa: E402
importlib.reload(bot)


class InitDataValidationTests(unittest.TestCase):
    def signed(self, user, auth_date=1000):
        import hashlib
        import hmac
        import json
        from urllib.parse import urlencode
        data = {'auth_date': str(auth_date), 'user': json.dumps(user)}
        secret = hmac.new(b'WebAppData', b'test-token', hashlib.sha256).digest()
        data['hash'] = hmac.new(secret, '\n'.join(f'{k}={v}' for k, v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
        return urlencode(data)

    def test_valid_signed_data_and_expired_or_future_data(self):
        from telegram_webapp_auth import verify_and_parse_init_data, InitDataError
        self.assertEqual(verify_and_parse_init_data(self.signed({'id': 123}), 'test-token', now_ts=1000).user.id, 123)
        for timestamp in (0, 2000):
            with self.assertRaises(InitDataError):
                verify_and_parse_init_data(self.signed({'id': 123}, timestamp), 'test-token', now_ts=1000, max_age_sec=100)

    def test_invalid_user_shapes_raise_auth_error(self):
        from telegram_webapp_auth import verify_and_parse_init_data, InitDataError
        for user in (None, 123, [], {}, {'id': None}, {'id': True}, {'id': 0}, {'id': -1}, {'id': 1.5}, {'id': '123'}):
            with self.subTest(user=user), self.assertRaises(InitDataError):
                verify_and_parse_init_data(self.signed(user), 'test-token', now_ts=1000)

    def test_invalid_or_duplicate_hash_rejected_cleanly(self):
        from telegram_webapp_auth import verify_and_parse_init_data, InitDataError
        for data in ('hash=я', 'hash=' + 'z'*64, self.signed({'id': 123}) + '&hash=abc', self.signed({'id': 123}) + '&user=null'):
            with self.subTest(data=data), self.assertRaises(InitDataError):
                verify_and_parse_init_data(data, 'test-token', now_ts=1000)


class AdminCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_input_rechecks_revoked_or_read_only_trainer_permission(self):
        for link in (None, (1, 'accepted', 0)):
            with self.subTest(link=link):
                message = SimpleNamespace(reply_text=AsyncMock(), text='42')
                update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=123, username='trainer'))
                context = SimpleNamespace(user_data={'acting_user_id': 2, 'acting_can_edit': True})
                with patch.object(bot, 'require_subscription', new_callable=AsyncMock, return_value=True), patch.object(bot, 'get_or_create_user', new_callable=AsyncMock, return_value=1), patch.object(bot, 'get_trainer_link', new_callable=AsyncMock, return_value=link):
                    await bot.text_router(update, context)
                message.reply_text.assert_awaited_once()
                self.assertFalse(context.user_data.get('acting_can_edit'))

    async def test_wizard_cannot_change_read_only_trainee_settings(self):
        q = SimpleNamespace(answer=AsyncMock())
        context = SimpleNamespace(user_data={'acting_user_id': 2, 'acting_can_edit': False})
        with patch.object(bot, 'set_workouts_per_week', new_callable=AsyncMock) as write:
            await bot.wizard_router(None, q, 'wiz:week:set:5', 2, context)
            write.assert_not_awaited()
        q.answer.assert_awaited_once()

    async def test_ai_quota_reset_requires_admin(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=message, effective_user=SimpleNamespace(id=123, username='ordinary'))
        with patch.object(bot, 'ADMIN_IDS', {999}), patch.object(bot, 'reset_ai_coach_quota', new_callable=AsyncMock) as reset, patch.object(bot, 'get_or_create_user', new_callable=AsyncMock) as get_user:
            await bot.ai_pass_command(update, None)
            reset.assert_not_awaited()
            get_user.assert_not_awaited()
            update.effective_user.id = 999
            get_user.return_value = 42
            reset.return_value = 2
            await bot.ai_pass_command(update, None)
            reset.assert_awaited_once_with(42)


class _FakeBot:
    def __init__(self, status):
        self.status = status
        self.sent_messages: list[tuple[int, str]] = []
        self.membership_checks: list[tuple[object, int]] = []
        self._message_id = 1000

    async def get_chat_member(self, chat_id, user_id):
        self.membership_checks.append((chat_id, user_id))
        if isinstance(self.status, Exception):
            raise self.status
        return SimpleNamespace(status=self.status)

    async def send_message(
        self,
        chat_id,
        text,
        reply_markup=None,
        disable_web_page_preview=None,
    ):
        self._message_id += 1
        self.sent_messages.append((chat_id, text))
        return SimpleNamespace(chat_id=chat_id, message_id=self._message_id)


class SubscriptionDbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()

    async def asyncTearDown(self):
        async with db.connect_db() as conn:
            for table in ("subscriptions", "payments", "users"):
                await conn.execute(f"DELETE FROM {table}")
            await conn.commit()

    async def test_grant_subscription_extends_current(self):
        user_id = await db.get_or_create_user(7001, "active_user")
        first_expiry = await db.grant_subscription_days(user_id, 30, plan="month")
        second_expiry = await db.grant_subscription_days(user_id, 30, plan="month")
        self.assertGreater(second_expiry, first_expiry)
        info = await db.get_active_subscription(user_id)
        self.assertIsNotNone(info)
        self.assertIsNotNone(info["expires_at"])
        self.assertAlmostEqual(
            info["expires_at"].timestamp(), second_expiry.timestamp(), delta=1
        )

    async def test_concurrent_grants_accumulate_and_degrant_caps_old_active_rows(self):
        user = await db.get_or_create_user(7003, 'grant_race')
        await asyncio.gather(*(db.grant_subscription_days(user, 30) for _ in range(2)))
        before = await db.get_active_subscription(user)
        self.assertAlmostEqual((before['expires_at'] - datetime.now(UTC)).total_seconds(), 60*86400, delta=10)
        reduced = await db.degrant_subscription_days(user, 45)
        self.assertEqual((await db.get_active_subscription(user))['expires_at'], reduced)
        self.assertAlmostEqual((reduced - datetime.now(UTC)).total_seconds(), 15*86400, delta=10)

    async def test_gift_redemption_is_atomic_and_cannot_extend_twice(self):
        user = await db.get_or_create_user(7004, 'gift_owner')
        await db.create_gift_code('AUDIT-GIFT-ATOMIC', 30)
        async with db.connect_db() as conn:
            await conn.execute("CREATE TRIGGER fail_gift_grant BEFORE INSERT ON subscriptions BEGIN SELECT RAISE(ABORT, 'test grant failure'); END")
            await conn.commit()
        try:
            with self.assertRaises(Exception):
                await db.redeem_gift_code_with_status('AUDIT-GIFT-ATOMIC', user)
            async with db.connect_db() as conn:
                self.assertIsNone((await (await conn.execute("SELECT used_by_user_id FROM gift_codes WHERE code='AUDIT-GIFT-ATOMIC'")).fetchone())[0])
        finally:
            async with db.connect_db() as conn:
                await conn.execute('DROP TRIGGER fail_gift_grant')
                await conn.commit()
        results = await asyncio.gather(*(db.redeem_gift_code_with_status('audit-gift-atomic', user) for _ in range(3)))
        self.assertEqual(results.count(('ok', 30)), 1)
        self.assertEqual(results.count(('already_used', None)), 2)
        active = await db.get_active_subscription(user)
        self.assertAlmostEqual((active['expires_at'] - datetime.now(UTC)).total_seconds(), 30*86400, delta=10)

    async def test_telegram_payment_retries_extend_subscription_only_once(self):
        user_id = await db.get_or_create_user(7002, 'payment_retry')
        plan_code, plan = next(iter(bot.SUBSCRIPTION_PLANS.items()))
        payment = SimpleNamespace(invoice_payload=f'setsubstars:{user_id}:{plan_code}', telegram_payment_charge_id='charge-one', currency='XTR', total_amount=100)
        await db.create_payment_record(user_id, 'telegram', 100, 'XTR', 'pending', payload={'plan': plan_code}, external_id=payment.invoice_payload)
        message = SimpleNamespace(successful_payment=payment, reply_text=AsyncMock())
        update = SimpleNamespace(message=message)
        await asyncio.gather(*(bot.successful_payment_handler(update, None) for _ in range(3)))
        first = await db.get_active_subscription(user_id)
        self.assertAlmostEqual((first['expires_at']-datetime.now(UTC)).total_seconds(), plan['days']*86400, delta=10)
        self.assertEqual(message.reply_text.await_count, 1)
        import webapp_backend as backend
        for _ in range(3):
            status = await backend.subscription_payment_status(payment.invoice_payload, SimpleNamespace(user_id=user_id))
            self.assertEqual(status['status'], 'succeeded')
            self.assertFalse(status['activated'])
        self.assertEqual((await db.get_active_subscription(user_id))['expires_at'], first['expires_at'])
        async with db.connect_db() as conn:
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM payments WHERE external_id=?', ('telegram:charge-one',))).fetchone())[0], 1)
            self.assertEqual((await (await conn.execute("SELECT SUM(amount) FROM payments WHERE user_id=? AND status='paid'", (user_id,))).fetchone())[0], 100)
        payment.telegram_payment_charge_id = 'charge-two'
        await bot.successful_payment_handler(update, None)
        second = await db.get_active_subscription(user_id)
        self.assertAlmostEqual((second['expires_at']-first['expires_at']).total_seconds(), plan['days']*86400, delta=1)
        self.assertEqual(message.reply_text.await_count, 2)

    async def test_malformed_payment_payload_does_not_grant_subscription(self):
        message = SimpleNamespace(successful_payment=SimpleNamespace(invoice_payload='websub:not-a-user:month'), reply_text=AsyncMock())
        await bot.successful_payment_handler(SimpleNamespace(message=message), None)
        message.reply_text.assert_not_awaited()

    async def test_list_broadcast_targets_filters_admins_and_subscription(self):
        active_user = await db.get_or_create_user(7100, "with_sub")
        free_user = await db.get_or_create_user(7200, "without_sub")
        await db.grant_subscription_days(active_user, 30, plan="month")
        targets = await db.list_broadcast_targets(set())
        tg_ids = {tg for tg, _ in targets}
        self.assertIn(7200, tg_ids)
        self.assertIn(7100, tg_ids)
        free_only = await db.list_broadcast_targets(set(), only_without_subscription=True)
        free_ids = {tg for tg, _ in free_only}
        self.assertIn(7200, free_ids)
        self.assertNotIn(7100, free_ids)
        admin_filtered = await db.list_broadcast_targets({7200})
        admin_tg_ids = {tg for tg, _ in admin_filtered}
        self.assertNotIn(7200, admin_tg_ids)
        self.assertIn(7100, admin_tg_ids)

    async def test_expired_subscription_marked_and_hidden(self):
        user_id = await db.get_or_create_user(7300, "expired")
        await db.grant_subscription_days(user_id, 1, plan="month")
        past = datetime.now(UTC) - timedelta(days=1)
        async with db.connect_db() as conn:
            await conn.execute(
                "UPDATE subscriptions SET expires_at=?, status='active' WHERE user_id=?",
                (past.isoformat(), user_id),
            )
            await conn.commit()
        info = await db.get_active_subscription(user_id)
        self.assertIsNone(info)
        latest = await db.get_latest_subscription(user_id)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["status"], "expired")

    async def test_day_finish_counters_are_tracked(self):
        user_id = await db.get_or_create_user(7400, "counter")
        total = await db.increment_day_finish_total(user_id)
        self.assertEqual(total, 1)
        prompt_total = await db.get_subscription_prompt_total(user_id)
        self.assertEqual(prompt_total, 0)
        await db.set_subscription_prompt_total(user_id, total)
        prompt_total = await db.get_subscription_prompt_total(user_id)
        self.assertEqual(prompt_total, 1)
        total = await db.increment_day_finish_total(user_id)
        self.assertEqual(total, 2)

    async def test_channel_prompt_sent_every_five_completions(self):
        user_id = await db.get_or_create_user(7500, "prompted")
        fake_bot = _FakeBot(status="left")
        context = SimpleNamespace(bot=fake_bot, user_data={})
        q = SimpleNamespace(
            message=SimpleNamespace(chat_id=5555),
            from_user=SimpleNamespace(id=7500),
        )
        old_join_url = bot.JOIN_URL
        old_subscription_chat = bot.SUBSCRIPTION_CHAT
        bot.JOIN_URL = "https://t.me/testchannel"
        bot.SUBSCRIPTION_CHAT = "@testchannel"
        try:
            for _ in range(4):
                await bot.maybe_prompt_channel_support(q, context, user_id)
            self.assertEqual(fake_bot.sent_messages, [])
            await bot.maybe_prompt_channel_support(q, context, user_id)
            self.assertEqual(len(fake_bot.sent_messages), 1)
            prompt_total = await db.get_subscription_prompt_total(user_id)
            self.assertEqual(prompt_total, 5)
            for _ in range(4):
                await bot.maybe_prompt_channel_support(q, context, user_id)
            self.assertEqual(len(fake_bot.sent_messages), 1)
            await bot.maybe_prompt_channel_support(q, context, user_id)
            self.assertEqual(len(fake_bot.sent_messages), 2)
        finally:
            bot.JOIN_URL = old_join_url
            bot.SUBSCRIPTION_CHAT = old_subscription_chat

    async def test_channel_prompt_skipped_for_channel_members(self):
        user_id = await db.get_or_create_user(7600, "subscriber")
        fake_bot = _FakeBot(status="member")
        context = SimpleNamespace(bot=fake_bot, user_data={})
        q = SimpleNamespace(
            message=SimpleNamespace(chat_id=7777),
            from_user=SimpleNamespace(id=7600),
        )
        old_join_url = bot.JOIN_URL
        old_subscription_chat = bot.SUBSCRIPTION_CHAT
        bot.JOIN_URL = "https://t.me/testchannel"
        bot.SUBSCRIPTION_CHAT = "@testchannel"
        try:
            for _ in range(5):
                await bot.maybe_prompt_channel_support(q, context, user_id)
            self.assertEqual(fake_bot.sent_messages, [])
            prompt_total = await db.get_subscription_prompt_total(user_id)
            self.assertEqual(prompt_total, bot.SUBSCRIPTION_PROMPT_DISABLED)
            self.assertGreaterEqual(len(fake_bot.membership_checks), 1)
            for _ in range(5):
                await bot.maybe_prompt_channel_support(q, context, user_id)
            self.assertEqual(fake_bot.sent_messages, [])
            self.assertEqual(len(fake_bot.membership_checks), 1)
        finally:
            bot.JOIN_URL = old_join_url
            bot.SUBSCRIPTION_CHAT = old_subscription_chat


if __name__ == "__main__":
    unittest.main()
