"""Actual native callbacks/readers on temporary owned data, with Telegram mocked."""
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import db
import bot


class NativeScope(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'gym.sqlite3')
        self.p = patch.object(db, 'DB_PATH', self.path)
        self.p.start()
        await db.init_db()
        self.owner = await db.get_or_create_user(900000000011, 'pupil')
        self.viewer = await db.get_or_create_user(900000000012, 'trainer')
        await db.ensure_training_system_defaults(self.owner)
        await db.set_workouts_per_week(self.owner, 3)
        async with db.connect_db() as conn:
            await conn.execute('UPDATE users SET is_trainer=1,trainer_accepts_requests=1 WHERE id=?', (self.viewer,))
            await conn.commit()
        self.link = await db.create_trainer_request(self.viewer, self.owner)
        await db.update_trainer_link_status(self.link, 'accepted')
        self.exercises = []
        for name, group in (('Quality strength', 'legs'), ('Quality running', 'run')):
            async with db.connect_db() as conn:
                cur = await conn.execute('INSERT INTO exercises(name,muscle_group,created_by_user_id) VALUES(?,?,?)', (name, group, self.owner))
                eid = cur.lastrowid
                await conn.commit()
            await db.add_user_exercise(self.owner, 1, eid)
            async with db.connect_db() as conn:
                row = await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND day_index=1 AND exercise_id=?', (self.owner, eid))).fetchone()
            self.exercises.append(row[0])

    async def asyncTearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def native(self, data, *, acting=False, owner=False):
        uid = 900000000011 if owner else 900000000012
        user = NS(id=uid, username='pupil' if owner else 'trainer')
        message = NS(chat_id=uid, chat=NS(id=uid), message_id=77, text='Changed name', reply_text=AsyncMock())
        query = NS(data=data, from_user=user, answer=AsyncMock(), message=message)
        update = NS(callback_query=query, effective_user=user, effective_chat=NS(id=uid, type='private'), message=message)
        state = {'acting_user_id': self.owner, 'acting_can_edit': False} if acting else {}
        context = NS(user_data=state, bot=NS(send_invoice=AsyncMock(), edit_message_text=AsyncMock()))
        return update, context

    async def diary_state(self):
        async with db.connect_db() as conn:
            return {t: await (await conn.execute(f'SELECT * FROM {t}')).fetchall()
                    for t in ('sessions', 'running_entries', 'users', 'training_systems', 'day_completion_history')}

    async def test_custom_labels_are_owner_scoped_even_after_other_diary_loads(self):
        secret = await db.add_custom_measurement(self.owner, 'Private body indicator')
        own = await db.add_custom_measurement(self.viewer, 'Own indicator')
        _, owner_context = self.native('noop', owner=True)
        _, viewer_context = self.native('noop')
        await bot.load_custom_measurements(self.owner, owner_context)
        await bot.load_custom_measurements(self.viewer, viewer_context)
        self.assertNotIn(secret, bot.MEASUREMENT_MAP)
        self.assertIsNone(bot.get_measurement_item(secret))
        self.assertIsNone(await bot.get_owned_measurement_item(self.viewer, secret))
        self.assertEqual((await bot.get_owned_measurement_item(self.owner, secret))['name'], 'Private body indicator')
        self.assertEqual((await bot.get_owned_measurement_item(self.viewer, own))['name'], 'Own indicator')
        viewer_context.user_data['_input_owner'] = self.owner
        self.assertEqual(bot.get_cached_custom_measurements(viewer_context), [])
        await db.delete_custom_measurement(self.owner, secret)
        self.assertIsNone(await bot.get_owned_measurement_item(self.owner, secret))

    async def test_four_foreign_label_callbacks_do_not_render_or_bind_input(self):
        secret = await db.add_custom_measurement(self.owner, 'Private body indicator')
        _, owner_context = self.native('noop', owner=True)
        await bot.load_custom_measurements(self.owner, owner_context)
        for data in (f'measure:add:item:custom:{secret}', f'measure:edit:metric:{secret}',
                     f'measure:edit:customdel:{secret}', f'measure:edit:customrm:{secret}'):
            update, context = self.native(data)
            with patch.object(bot, 'show_screen', AsyncMock()) as show:
                await bot.menu_router(update, context)
            show.assert_not_awaited()
            self.assertNotIn(bot.MEASUREMENT_INPUT_KEY, context.user_data)

    async def test_accepted_viewer_cannot_open_pupil_personal_sections(self):
        for data in ('set:subscription', 'set:subscription:planstars:1m', 'settings:referral',
                     'settings:referral:create', 'settings:notifications'):
            update, context = self.native(data, acting=True)
            with patch.object(bot, 'show_subscription_overview', AsyncMock()) as overview, \
                 patch.object(bot, 'start_subscription_payment_stars', AsyncMock()) as invoice, \
                 patch.object(bot, 'build_referral_screen', AsyncMock()) as referral:
                await bot.menu_router(update, context)
            overview.assert_not_awaited()
            invoice.assert_not_awaited()
            referral.assert_not_awaited()
            self.assertTrue(any('личный' in str(c.args[0]) for c in update.callback_query.answer.await_args_list if c.args))
        async with db.connect_db() as conn:
            self.assertEqual((await (await conn.execute('SELECT count(*) FROM payments')).fetchone())[0], 0)

    async def test_editable_training_link_does_not_authorize_pending_referral_name(self):
        await db.update_trainer_link_permissions(self.link, 1)
        update, context = self.native('noop', acting=True)
        context.user_data.update(acting_can_edit=True, **{bot.REFERRAL_NAME_INPUT_KEY: {'target_user_id': self.owner}})
        with patch.object(bot, 'create_or_update_referral_profile', AsyncMock()) as write:
            await bot.text_router(update, context)
        write.assert_not_awaited()
        self.assertNotIn(bot.REFERRAL_NAME_INPUT_KEY, context.user_data)

    async def test_direct_invoice_helper_checks_owner_and_own_invoice_still_works(self):
        update, context = self.native('noop')
        plan = next(iter(bot.SUBSCRIPTION_PLANS))
        await bot.start_subscription_payment_stars(update.callback_query, context, self.owner, plan)
        context.bot.send_invoice.assert_not_awaited()
        async with db.connect_db() as conn:
            self.assertEqual((await (await conn.execute('SELECT count(*) FROM payments')).fetchone())[0], 0)
        with patch.object(bot, 'show_subscription_overview', AsyncMock()):
            await bot.start_subscription_payment_stars(update.callback_query, context, self.viewer, plan)
        self.assertEqual(context.bot.send_invoice.call_args.kwargs['chat_id'], 900000000012)
        async with db.connect_db() as conn:
            self.assertEqual(await (await conn.execute('SELECT user_id,currency,status FROM payments')).fetchall(), [(self.viewer, 'XTR', 'pending')])

    async def test_first_native_exercise_view_is_a_read_for_strength_and_running(self):
        before = await self.diary_state()
        for ue in self.exercises:
            view = await bot.render_exercise_view(self.owner, 1, ue)
            self.assertIsNone(view.session_id)
        self.assertEqual(before, await self.diary_state())
        with self.assertRaises(ValueError): await bot.render_exercise_view(self.viewer, 1, self.exercises[0])

    async def test_readonly_individual_view_selection_and_progress_are_nonmutating(self):
        before = await self.diary_state()
        for ue in self.exercises:
            for data in (f'ex:view:1:{ue}:bot', f'ex:select:1:{ue}:1', f'ex:progress:1:{ue}'):
                update, context = self.native(data, acting=True)
                with patch.object(bot, 'show_screen', AsyncMock()): await bot.menu_router(update, context)
                self.assertEqual(before, await self.diary_state(), data)

    async def test_native_view_uses_owner_local_day_for_recorded_sets(self):
        sid = await db.get_or_create_today_session(self.owner, '2030-01-11', 1,
                                                   await db.peek_active_training_system_id(self.owner))
        await db.add_set(sid, self.exercises[0], reps=10, weight=30)
        with patch.object(bot, 'get_user_local_date', AsyncMock(return_value='2030-01-11')):
            view = await bot.render_exercise_view(self.owner, 1, self.exercises[0])
        self.assertEqual(view.session_id, sid)
        self.assertTrue(view.sets)

    async def test_explicit_running_input_still_creates_one_draft_and_readonly_actor_cannot_edit(self):
        ue = self.exercises[1]
        update, context = self.native(f'run:inc:1:{ue}:dist:1', owner=True)
        with patch.object(bot, 'show_screen', AsyncMock()): await bot.menu_router(update, context)
        async with db.connect_db() as conn:
            rows = await (await conn.execute('SELECT user_id,distance_km,is_draft FROM running_entries')).fetchall()
        self.assertEqual(rows, [(self.owner, 1.0, 1)])
        before = await self.diary_state()
        update, context = self.native(f'run:inc:1:{ue}:dist:1', acting=True)
        with patch.object(bot, 'show_screen', AsyncMock()): await bot.menu_router(update, context)
        self.assertEqual(before, await self.diary_state())
