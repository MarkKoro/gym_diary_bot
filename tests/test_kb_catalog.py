import unittest

from kb_catalog import (
    KB_CATEGORY_DEFINITION,
    KB_CATEGORY_LOOKUP,
    KB_MISC_CATEGORY,
    KB_EXERCISE_NAMES,
    categorize_kb_exercises,
    get_kb_catalog_page,
)


class KettlebellCatalogTests(unittest.TestCase):
    def test_known_exercises_follow_defined_order(self):
        indexed = list(enumerate(KB_EXERCISE_NAMES, start=1))
        blocks, page, total = get_kb_catalog_page(indexed, per_page=200)
        expected_keys = [key for key, _ in KB_CATEGORY_DEFINITION]
        actual_keys = [key for key, _ in blocks]
        self.assertEqual(page, 0)
        self.assertEqual(total, 1)
        self.assertEqual(actual_keys, expected_keys)

    def test_unknown_exercises_go_to_misc_sorted(self):
        items = [(1, "Зарядка Б"), (2, "зарядка А")]
        blocks = categorize_kb_exercises(items)
        self.assertEqual(len(blocks), 1)
        key, rows = blocks[0]
        self.assertEqual(key, KB_MISC_CATEGORY)
        self.assertEqual([name for _, name in rows], ["зарядка А", "Зарядка Б"])

    def test_lookup_has_all_seeded_exercises(self):
        for name in KB_EXERCISE_NAMES:
            self.assertIn(name, KB_CATEGORY_LOOKUP)


if __name__ == "__main__":
    unittest.main()


class KeyboardMatrixTests(unittest.TestCase):
    def test_all_builders_with_empty_full_and_read_only_data(self):
        import inspect
        from types import SimpleNamespace
        from telegram import InlineKeyboardMarkup
        import keyboards as kb
        checked = set()
        callbacks = []
        for empty in (False, True):
            for read_only in (False, True):
                for name, fn in inspect.getmembers(kb, inspect.isfunction):
                    if fn.__module__ != kb.__name__ or not name.endswith('_kb'):
                        continue
                    values = dict(days=[] if empty else [(1,'Day one'),(7,'Day seven')], support_url='https://example.com', join_url='https://example.com', url='https://example.com', ok_cb='menu:root', day_index=7, day=7, ue_id=99999999, trainee_user_id=99999999, can_edit=not read_only, group='chest', category='body', action='add', selected=set() if empty else {1,'chest'}, sets=3,reps=10,seconds=30,weight=20.5, mode='flex',kind='reps',with_weight=True,has_history=True,prefs=SimpleNamespace(mode='detailed'),back_callback='menu:root',can_delete_group=True,show_all=True,include_delete=True,enabled=True)
                    values['context'] = SimpleNamespace(user_data={'acting_can_edit':not read_only, 'acting_user_id':2 if read_only else None})
                    values['groups'] = [] if empty else [('chest',3)] if name=='library_menu_kb' else [('chest','Chest')]
                    values['categories'] = [] if empty else [('body','Body')]
                    values['metrics'] = [] if empty else [('weight','Weight')]
                    values['entries'] = [] if empty else [(1,'Monday')]
                    values['items'] = [] if empty else [(1,'Exercise',0)] if name=='day_group_kb' else [(1,'Exercise')]
                    values['ex_rows'] = [] if empty else [(1,'Exercise','chest',0,0,None)] if name=='day_kb' else [(1,'Exercise','chest',0,0)] if name=='del_exercises_kb' else [(1,'Exercise')]
                    params = inspect.signature(fn).parameters
                    kwargs = {k:values[k] for k in params if k in values}
                    # Defaults for mutually incompatible selected tuple/int arguments.
                    if name in ('reminder_day_kb','reminder_time_kb'):
                        kwargs.pop('selected',None)
                    with self.subTest(builder=name, empty=empty, read_only=read_only):
                        markup = fn(**kwargs)
                        if isinstance(markup, tuple):
                            markup = markup[0]
                        self.assertIsInstance(markup,InlineKeyboardMarkup)
                        self.assertTrue(markup.inline_keyboard)
                        for row in markup.inline_keyboard:
                            self.assertTrue(row)
                            for button in row:
                                self.assertTrue(button.text)
                                if button.callback_data:
                                    self.assertLessEqual(len(button.callback_data.encode('utf-8')),64,button.callback_data)
                                    callbacks.append(button.callback_data)
                        checked.add(name)
        self.assertGreaterEqual(len(checked),45)
        self.assertGreater(len(callbacks),500)

    def test_pagination_bounds_keep_timezone_and_exercise_choices(self):
        import keyboards as kb
        for page in (-100, 0, 100000):
            for per_page in (0, -1, 6):
                markup = kb.tz_select_kb(page,per_page)
                self.assertTrue(any(b.callback_data.startswith('wiz:tzsel:set:') for row in markup.inline_keyboard for b in row))
            for name in ('exercises_kb','day_add_exercises_kb','library_add_exercises_kb'):
                kwargs = dict(group='chest',ex_rows=[(1,'Exercise')],selected=set(),page=page)
                if name!='library_add_exercises_kb':
                    kwargs['day_index']=1
                markup = getattr(kb,name)(**kwargs)
                if isinstance(markup,tuple):
                    markup = markup[0]
                self.assertTrue(any(b.callback_data.endswith(':1') for row in markup.inline_keyboard for b in row))

    def test_read_only_exercise_modes_do_not_offer_mutations(self):
        import itertools
        from types import SimpleNamespace
        import keyboards as kb
        for kind, mode, amrap, for_time in itertools.product(('reps','duration'),('compact','detailed'),(False,True),(False,True)):
            markup = kb.exercise_actions_kb('flex',True,kind,True,SimpleNamespace(mode=mode),day=1,ue_id=1,group='workout',is_amrap=amrap,is_for_time=for_time,back_callback='menu:root',context=SimpleNamespace(user_data={'acting_user_id':2,'acting_can_edit':False}))
            self.assertTrue(all(b.callback_data in ('ex:progress:1:1','menu:root') for row in markup.inline_keyboard for b in row))
