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

    async def test_stale_or_foreign_exercise_callbacks_do_not_read_or_write_training(self):
        for payload in ('ex:done:1:999', 'run:history:1:999', 'lib:ex:core:999', 'obsolete:button'):
            q = SimpleNamespace(data=payload, answer=AsyncMock(), message=SimpleNamespace(chat_id=123, message_id=1))
            update = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=123, username='viewer'))
            context = SimpleNamespace(user_data={})
            with patch.object(bot, 'require_subscription', AsyncMock(return_value=True)), patch.object(bot, 'get_or_create_user', AsyncMock(return_value=1)), patch.object(bot, 'get_user_exercise_info', AsyncMock(return_value=(2, 1))), patch.object(bot, 'load_ui_preferences', AsyncMock()), patch.object(bot, 'compose_main_menu', AsyncMock(return_value=('Menu', None, None))), patch.object(bot, 'show_screen', AsyncMock()), patch.object(bot, 'get_or_create_today_session', AsyncMock()) as write, patch.object(bot, 'show_library_exercise_view', AsyncMock()) as view:
                await bot.menu_router(update, context)
                write.assert_not_awaited()
                view.assert_not_awaited()

    async def test_revoked_trainer_callback_cannot_fall_back_to_mutating_own_diary(self):
        q = SimpleNamespace(data='set:days_count:7', answer=AsyncMock(), message=SimpleNamespace(chat_id=123, message_id=1))
        update = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=123, username='trainer'))
        context = SimpleNamespace(user_data={'acting_user_id': 2, 'acting_can_edit': True})
        with patch.object(bot, 'get_or_create_user', AsyncMock(return_value=1)), patch.object(bot, 'get_trainer_link', AsyncMock(return_value=None)), patch.object(bot, 'set_workouts_per_week', AsyncMock()) as write:
            await bot.menu_router(update, context)
            write.assert_not_awaited()

    async def test_old_wizard_add_without_group_does_not_mutate_first(self):
        q = SimpleNamespace(answer=AsyncMock(), message=SimpleNamespace(chat_id=123, message_id=1))
        with patch.object(bot, 'toggle_user_exercise', AsyncMock()) as write:
            await bot.wizard_router(None, q, 'wiz:day:1:ex:add:10', 1, SimpleNamespace(user_data={}))
            write.assert_not_awaited()

    async def test_text_for_deleted_exercise_is_rejected_before_writing(self):
        message = SimpleNamespace(text='42', reply_text=AsyncMock())
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=123, username='viewer'))
        context = SimpleNamespace(user_data={bot.EXERCISE_NOTE_INPUT_KEY: {'day': 1, 'ue_id': 999}})
        with patch.object(bot, 'require_subscription', AsyncMock(return_value=True)), patch.object(bot, 'get_or_create_user', AsyncMock(return_value=1)), patch.object(bot, 'get_user_exercise_info', AsyncMock(return_value=None)), patch.object(bot, 'set_exercise_persistent_note', AsyncMock()) as write:
            await bot.text_router(update, context)
            write.assert_not_awaited()
        self.assertNotIn(bot.EXERCISE_NOTE_INPUT_KEY, context.user_data)
        message.reply_text.assert_awaited_once()

    async def test_broadcast_double_tap_does_not_start_second_delivery(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def deliver(*args):
            entered.set()
            await release.wait()
        q = SimpleNamespace(data='broadcast:send', answer=AsyncMock(), message=SimpleNamespace(chat_id=123))
        state = {'text': 'Test', 'step': 'await_confirm'}
        context = SimpleNamespace(user_data={bot.BROADCAST_STATE_KEY: state})
        with patch.object(bot, 'execute_broadcast', AsyncMock(side_effect=deliver)) as send:
            first = asyncio.create_task(bot.handle_broadcast_callback(q, context))
            await entered.wait()
            await bot.handle_broadcast_callback(q, context)
            release.set()
            await first
            self.assertEqual(send.await_count, 1)

    async def test_broadcast_rate_limit_retries_only_failed_recipient(self):
        from telegram.error import RetryAfter, Forbidden
        q = SimpleNamespace(message=SimpleNamespace(chat_id=999), answer=AsyncMock())
        sender = AsyncMock(side_effect=[RetryAfter(1), None, Forbidden('blocked')])
        context = SimpleNamespace(user_data={}, bot=SimpleNamespace(send_message=sender))
        with patch.object(bot, 'list_broadcast_targets', AsyncMock(return_value=[(101, 1), (102, 2)])), patch.object(bot.asyncio, 'sleep', AsyncMock()), patch.object(bot, 'send_main_message', AsyncMock()) as summary:
            await bot.execute_broadcast(q, context, {'text': 'Test'})
        self.assertEqual([c.args[0] for c in sender.await_args_list], [101, 101, 102])
        self.assertIn('Доставлено: 1', summary.await_args.args[2])

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
            for table in ("referral_attributions", "referral_first_seen", "referral_profiles", "ai_coach_requests", "subscriptions", "payments", "users"):
                await conn.execute(f"DELETE FROM {table}")
            await conn.commit()

    async def test_failed_ai_requests_refund_only_their_own_quota(self):
        import webapp_backend as backend
        user = await db.get_or_create_user(8090, 'ai_quota')
        await db.grant_subscription_days(user, 30)
        successful = await db.consume_ai_coach_quota(user, 'mistakes_analysis')
        context = {'user_profile': {}, 'day_snapshots': []}
        for provider_result in (RuntimeError('network unavailable'), {'parsed': {}}, {'parsed': {'summary': 'No plan', 'action_plan': {'actions': []}}}):
            provider = AsyncMock(side_effect=provider_result) if isinstance(provider_result, Exception) else AsyncMock(return_value=provider_result)
            with patch.object(backend, '_build_ai_context_payload', AsyncMock(return_value=context)), patch.object(backend, '_call_openai_chat', provider):
                with self.assertRaises(Exception):
                    await backend.ai_coach_query({'mode': 'new_system', 'message': 'make a plan'}, SimpleNamespace(user_id=user))
                self.assertEqual(provider.await_count, 1)
            self.assertEqual((await db.get_ai_coach_quota(user))['usage']['day'], 1)
        await db.release_ai_coach_quota(user+999, successful['request_id'])
        self.assertEqual((await db.get_ai_coach_quota(user))['usage']['day'], 1)

    async def test_crashed_ai_reservation_expires_but_completed_requests_remain(self):
        user = await db.get_or_create_user(8089, 'ai-crash')
        now = datetime.now(UTC)
        completed = await db.consume_ai_coach_quota(user, 'mistakes_analysis', now)
        abandoned = await db.consume_ai_coach_quota(user, 'mistakes_analysis', now, reserve=True)
        self.assertTrue(completed['ok'] and abandoned['ok'])
        self.assertEqual((await db.get_ai_coach_quota(user, now+timedelta(minutes=14)))['usage']['day'], 2)
        self.assertEqual((await db.get_ai_coach_quota(user, now+timedelta(minutes=16)))['usage']['day'], 1)
        await db.complete_ai_coach_quota(user+999, abandoned['request_id'])
        self.assertEqual((await db.get_ai_coach_quota(user, now+timedelta(minutes=16)))['usage']['day'], 1)
        await db.complete_ai_coach_quota(user, abandoned['request_id'])
        self.assertEqual((await db.get_ai_coach_quota(user, now+timedelta(minutes=16)))['usage']['day'], 2)

    async def test_successful_provider_result_confirms_reservation(self):
        import webapp_backend as api
        user = await db.get_or_create_user(8088, 'ai-success')
        await db.grant_subscription_days(user,30)
        with patch.object(api,'_run_ai_coach_query',AsyncMock(return_value={'ok':True})):
            await api.ai_coach_query({'mode':'mistakes_analysis'},SimpleNamespace(user_id=user))
        self.assertEqual((await db.get_ai_coach_quota(user, datetime.now(UTC)+timedelta(minutes=16)))['usage']['day'],1)

    async def test_yookassa_pending_poll_preserves_long_plan(self):
        import webapp_backend as backend
        for handler in (backend.subscription_payment_status, backend.payment_yookassa_status):
            user = await db.get_or_create_user(8100 + len(handler.__name__), handler.__name__)
            payment_id = handler.__name__
            await db.create_payment_record(user, 'yookassa', 60000, 'RUB', 'pending',
                payload={'plan': '6m', 'plan_id': '6m'}, external_id=payment_id, project_key=backend.PROJECT_KEY)
            ctx = SimpleNamespace(user_id=user)
            with patch.object(backend, '_yookassa_get_payment', AsyncMock(side_effect=[{'status': 'pending'}, {'status': 'succeeded'}, {'status': 'succeeded'}])):
                await handler(payment_id, ctx)
                await handler(payment_id, ctx)
                await handler(payment_id, ctx)
            sub = await db.get_active_subscription(user)
            self.assertAlmostEqual((sub['expires_at'] - datetime.now(UTC)).total_seconds(), 180*86400, delta=5)
            record = await db.get_payment_by_external_id(payment_id)
            self.assertEqual(record['payload']['granted_days'], 180)

    async def test_legacy_yookassa_metadata_plan_is_recovered(self):
        import webapp_backend as backend
        user = await db.get_or_create_user(8190, 'legacy_plan')
        await db.create_payment_record(user, 'yookassa', 100000, 'RUB', 'pending',
            payload={'metadata': {'plan_id': '12m'}}, external_id='legacy-plan', project_key=backend.PROJECT_KEY)
        with patch.object(backend, '_yookassa_get_payment', AsyncMock(return_value={'status': 'succeeded'})):
            await backend.subscription_payment_status('legacy-plan', SimpleNamespace(user_id=user))
        sub = await db.get_active_subscription(user)
        self.assertAlmostEqual((sub['expires_at'] - datetime.now(UTC)).total_seconds(), 365*86400, delta=5)

    async def test_referral_profiles_and_first_attribution_are_concurrent_safe(self):
        users = [await db.get_or_create_user(8200+i, f'ref{i}') for i in range(4)]
        profiles = await asyncio.gather(*(db.create_or_update_referral_profile(u, 'Same name') for u in users))
        self.assertEqual(len({p['slug'] for p in profiles}), 4)
        same = await asyncio.gather(*(db.create_or_update_referral_profile(users[0], 'Новое имя') for _ in range(3)))
        self.assertEqual({p['slug'] for p in same}, {profiles[0]['slug']})
        invited = await db.get_or_create_user(8299, 'invited')
        results = await asyncio.gather(*(db.assign_referral_attribution(invited, p['user_id'], p['slug']) for p in profiles))
        self.assertEqual(sum(results), 1)
        self.assertFalse(await db.assign_referral_attribution(users[0], users[1], 'missing-profile'))

    async def test_referral_links_support_russian_names_and_escape_html(self):
        user = await db.get_or_create_user(8300, 'russian')
        profile = await db.create_or_update_referral_profile(user, 'Миша <спорт>')
        self.assertRegex(profile['slug'], r'^[a-zA-Z0-9_-]+$')
        async with db.connect_db() as conn:
            await conn.execute('UPDATE referral_profiles SET slug=? WHERE user_id=?', ('старое-имя', user))
            await conn.commit()
        text, markup = await bot.build_referral_screen(user)
        self.assertIn('Миша &lt;спорт&gt;', text)
        from urllib.parse import urlparse, parse_qs
        payload = parse_qs(urlparse(markup.inline_keyboard[0][0].copy_text.text).query)['start'][0]
        self.assertRegex(payload, r'^[a-zA-Z0-9_-]{1,64}$')
        self.assertEqual((await db.get_referrer_by_slug(payload[4:]))['user_id'], user)

    async def test_referral_paid_days_exclude_gifts_and_invoice_duplicates(self):
        referrer = await db.get_or_create_user(8400, 'referrer')
        profile = await db.create_or_update_referral_profile(referrer, 'referrer')
        paid, gift = [await db.get_or_create_user(8401+i, f'guest{i}') for i in range(2)]
        for user in (paid, gift):
            await db.assign_referral_attribution(user, referrer, profile['slug'])
        await db.grant_subscription_days(gift, 365, plan='gift')
        await db.grant_subscription_days(paid, 100, plan='manual')
        for i in range(2):
            invoice = f'websub:{paid}:1m:{i}'
            await db.create_payment_record(paid, 'telegram', 100, 'XTR', 'paid', payload={'plan': '1m'}, external_id=invoice)
            charge = f'telegram:ref-charge-{i}'
            await db.create_payment_record(paid, 'telegram', 100, 'XTR', 'paid',
                payload={'invoice_payload': invoice, 'plan_code': '1m'}, external_id=charge, project_key='telegram')
            await db.finalize_payment_subscription_idempotent(external_id=charge, user_id=paid,
                expected_project_key='telegram', days=30, plan_code='1m', source='test')
        await db.create_payment_record(gift, 'yookassa', 60000, 'RUB', 'pending', payload={'plan': '6m'})
        stats = await db.get_referral_stats(referrer)
        self.assertEqual(stats['paid_users_total'], 1)
        self.assertEqual(stats['paid_days_total'], 60)
        self.assertEqual(stats['paid_days_month'], 60)
        self.assertEqual(stats['revenue_stars_total'], 200)
        self.assertEqual(stats['revenue_rub_total'], 0)

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
