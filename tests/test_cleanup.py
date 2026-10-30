"""B4 deletion lifecycle tests use temporary synthetic databases only."""

import json
import unittest
from datetime import timedelta

from stylemate_memory import contracts as c
from stylemate_memory.context import build_context_v1
from stylemate_memory.registry import load_registry
from stylemate_memory.store import MemoryStore
from tests import test_feedback as feedback_tests
from tests import test_store_transitions as transitions


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.h = transitions.V1TransitionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def delete(self, memory, nonce='erase-once'):
        h = self.h
        event = h.review(memory, 'delete')
        action = {'op': 'delete', 'memory_id': memory['id'], 'expected_version': memory['version'], 'user_event_ref': event}
        expected = h.expected()
        target_ref = transitions.ref('memory', memory)
        if target_ref not in expected['object_versions']:
            expected['object_versions'].append(target_ref)
        return action, expected, lambda: h.batch([action], nonce=nonce, expected=expected)

    def context(self, *, semantic=None):
        snapshot = self.h.snapshot()
        return build_context_v1(snapshot, snapshot['request']['targets'],
                                registry=load_registry(c.V1_REGISTRY_VERSION), semantic=semantic)

    def test_request_erasure_preserves_independent_long_term_proof(self):
        h = self.h
        long, _ = h.promote(h.confirm(h.candidate()))
        until = long['retention_until']
        h.store.delete_request('u1', h.request['id'])
        h.request = h.start('next')
        snap = h.snapshot()
        self.assertEqual([m['id'] for m in snap['memories']], [long['id']])
        self.assertEqual(snap['memories'][0]['retention_until'], until)
        self.assertEqual(len(snap['consents']), 1)
        sources = self.context()['model_input']['sources']
        self.assertEqual(len(sources), 1)
        self.assertIn(long['content'], sources[0]['content'])
        self.assertFalse(h.store.connection.execute('PRAGMA foreign_key_check').fetchall())
        h.assert_error('idempotency_conflict', lambda: h.start('first'))

    def test_independent_confirmed_support_survives_with_valid_proof(self):
        h = self.h
        first = h.confirm(h.candidate())
        second = h.confirm(h.candidate(content=h.content(content='독립적으로 확인한 다른 취향')))
        conn = h.store.connection
        conn.execute('BEGIN')
        h.store._v1._link(h.store._request_row('u1', h.request['id']), second, first, 'supports', h.now)
        conn.commit()
        self.delete(first)[2]()
        context = self.context()
        sources = context['model_input']['sources']
        self.assertEqual(len(sources), 1)
        self.assertIn(second['content'], sources[0]['content'])

    def test_multi_delete_reviews_are_validated_before_shared_family_is_erased(self):
        h = self.h
        short = h.confirm(h.candidate())
        long, _ = h.promote(short)
        actions = [self.delete(m)[0] for m in (short, long)]
        result = h.batch(actions, nonce='delete-family-batch')
        self.assertEqual(result['outcome'], 'applied')
        self.assertEqual(h.snapshot()['memories'], [])
        self.assertEqual(h.store.connection.execute('SELECT count(*) FROM v1_objects').fetchone()[0], 0)
        self.assertEqual(h.batch(actions, nonce='delete-family-batch'), result)

    def test_surviving_confirmation_removes_deleted_extra_review_subject(self):
        h = self.h
        first = h.candidate()
        second = h.candidate()
        event = h.review(second, extra_refs=[transitions.ref('memory', first)])
        h.batch([h.confirm_action(second, event)])
        self.delete(first)[2]()
        proofs = h.snapshot()['confirmations']
        self.assertEqual(len(proofs), 1)
        self.assertNotIn(first['id'], json.dumps(proofs))
        self.assertEqual(len(self.context()['model_input']['sources']), 1)

    def test_withdrawal_preserves_supported_memory_after_shared_quote_redaction(self):
        h = self.h
        source = h.intake('철회할 취향. 유지할 취향.')
        for text in ('철회할 취향', '유지할 취향'):
            h.batch([{'op': 'create', 'memory': h.content(content=text), 'source_refs': [source], 'bindings': [],
                     'confirmation_event_ref': None, 'consent_event_ref': None}])
        first = h.confirm(next(m for m in h.snapshot()['memories'] if m['content'] == '철회할 취향'))
        second = h.confirm(next(m for m in h.snapshot()['memories'] if m['content'] == '유지할 취향'))
        conn = h.store.connection
        conn.execute('BEGIN')
        h.store._v1._link(h.store._request_row('u1', h.request['id']), second, first, 'supports', h.now)
        conn.commit()
        event = h.review(first, 'withdraw')
        h.batch([{'op': 'withdraw', 'memory_id': first['id'], 'expected_version': first['version'], 'user_event_ref': event}])
        self.assertEqual([m['content'] for m in h.snapshot()['memories']], ['유지할 취향'])
        self.assertEqual(h.snapshot()['memories'][0]['status'], 'active')
        self.assertIn('유지할 취향', self.context()['model_input']['sources'][0]['content'])
        self.assertEqual([e['quote'] for e in h.snapshot()['evidence']], ['유지할 취향'])

    def test_long_term_erasure_clears_family_proofs_and_opaque_replay(self):
        h = self.h
        long, _ = h.promote(h.confirm(h.candidate()))
        action, expected, run = self.delete(long)
        result = run()
        self.assertEqual(h.snapshot()['memories'], [])
        self.assertEqual(h.snapshot()['consents'], [])
        self.assertEqual(h.snapshot()['evidence'], [])
        receipt = dict(h.store.connection.execute('SELECT * FROM deletion_receipts').fetchone())
        self.assertNotIn(long['id'], json.dumps(receipt))
        self.assertNotIn(long['content'], json.dumps(receipt))
        self.assertEqual(run(), result)
        changed = action | {'expected_version': 100}
        h.assert_error('idempotency_conflict', lambda: h.batch([changed], nonce='erase-once', expected=expected))
        self.assertFalse(h.store.connection.execute('PRAGMA foreign_key_check').fetchall())

    def test_supports_does_not_erase_unrelated_memory_but_copy_does(self):
        h = self.h
        first = h.candidate()
        second = h.candidate(content=h.content(content='다른 독립 기억'))
        third = h.candidate(content=h.content(content='첫 기억의 복제'))
        conn = h.store.connection
        conn.execute('BEGIN')
        h.store._v1._link(h.store._request_row('u1', h.request['id']), second, first, 'supports', h.now)
        h.store._v1._link(h.store._request_row('u1', h.request['id']), third, first, 'derived_from', h.now)
        conn.commit()
        self.delete(first)[2]()
        self.assertEqual([m['id'] for m in h.snapshot()['memories']], [second['id']])
        self.assertEqual(h.snapshot()['links'], [])

    def test_derived_cleanup_failure_rolls_back_and_same_command_retries(self):
        h = self.h
        memory = h.candidate()
        _, _, run = self.delete(memory)
        before = h.snapshot()
        def fail(stage, *_):
            if stage == 'cleanup_derived':
                raise RuntimeError('synthetic index unavailable')
        h.store._failure_hook = fail
        h.assert_error('cleanup_pending', run)
        self.assertEqual(h.snapshot(), before)
        self.assertEqual(h.store.connection.execute('SELECT count(*) FROM deletion_receipts').fetchone()[0], 0)
        h.store._failure_hook = None
        run()
        self.assertEqual(h.snapshot()['memories'], [])

    def test_sqlite_failure_rollback_and_post_commit_cleanup_retry(self):
        h = self.h
        memory = h.candidate()
        _, _, run = self.delete(memory)
        def fail(stage, *_):
            if stage == 'cleanup_after_objects':
                raise RuntimeError('synthetic sqlite write failure')
        h.store._failure_hook = fail
        h.assert_error('storage_failed', run)
        self.assertEqual(len(h.snapshot()['memories']), 1)
        def vacuum_fail(stage, *_):
            if stage == 'cleanup_before_vacuum':
                raise RuntimeError('synthetic vacuum failure')
        h.store._failure_hook = vacuum_fail
        h.assert_error('cleanup_pending', run)
        self.assertEqual(h.snapshot()['memories'], [])
        self.assertEqual(h.store.connection.execute('SELECT count(*) FROM v1_cleanup_pending').fetchone()[0], 1)
        h.store.close()
        h.store = MemoryStore(h.path, clock=lambda: h.now)
        run()
        self.assertEqual(h.store.connection.execute('SELECT count(*) FROM v1_cleanup_pending').fetchone()[0], 0)

    def test_expiry_prune_restart_does_not_renew_long_term(self):
        h = self.h
        long, _ = h.promote(h.confirm(h.candidate()))
        h.now += timedelta(days=31)
        result = h.store.prune_expired('u1')
        self.assertEqual(result['requests'], 1)
        h.store.close()
        h.store = MemoryStore(h.path, clock=lambda: h.now)
        h.request = h.start('after-expiry')
        self.assertEqual(h.snapshot()['memories'][0]['retention_until'], long['retention_until'])
        h.now += timedelta(days=335)
        h.store.prune_expired('u1')
        h.request = h.start('after-long-expiry')
        self.assertEqual(h.snapshot()['memories'], [])

    def test_withdrawal_invalidates_copies_sources_and_cache_with_bounded_history(self):
        h = self.h
        long, _ = h.promote(h.confirm(h.candidate()))
        copy = h.candidate(content=h.content(content='장기 기억으로부터 파생된 사본'))
        conn = h.store.connection
        conn.execute('BEGIN')
        h.store._v1._link(h.store._request_row('u1', h.request['id']), copy, long, 'derived_from', h.now)
        derived = h.store._v1._metadata('u1', h.request['id'], h.now, long['retention_until']) | {
            'source_refs': [transitions.ref('memory', long)], 'summary': long['content']}
        h.store._v1._put('derived', derived, {'source': derived['source_refs']})
        conn.commit()
        event = h.review(long, 'withdraw')
        h.batch([{'op': 'withdraw', 'memory_id': long['id'], 'expected_version': long['version'], 'user_event_ref': event}])
        self.assertEqual(h.snapshot()['memories'], [])
        self.assertEqual(conn.execute('SELECT count(*) FROM v1_derived').fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT count(*) FROM v1_evidence').fetchone()[0], 0)
        rows = conn.execute('SELECT o.retention_us,m.status FROM v1_objects o JOIN v1_memories m ON m.id=o.id').fetchall()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['status'] == 'withdrawn' for r in rows))
        latest = h.now + timedelta(days=30)
        from stylemate_memory.store_v1 import _us
        self.assertTrue(all(r['retention_us'] <= _us(latest) for r in rows))
        h.store.close()
        h.store = MemoryStore(h.path, clock=lambda: h.now)
        self.assertEqual(self.context()['model_input']['sources'], [])
        h.now = latest + timedelta(microseconds=1)
        h.store.prune_expired('u1')
        self.assertEqual(h.store.connection.execute('SELECT count(*) FROM v1_memories').fetchone()[0], 0)

    def test_withdrawn_memory_can_be_deleted_with_a_new_trusted_review(self):
        h = self.h
        memory = h.confirm(h.candidate())
        event = h.review(memory, 'withdraw')
        h.batch([{'op': 'withdraw', 'memory_id': memory['id'], 'expected_version': memory['version'], 'user_event_ref': event}])
        row = h.store.connection.execute('SELECT o.*,m.payload_json FROM v1_objects o JOIN v1_memories m ON m.id=o.id').fetchone()
        withdrawn = h.store._v1._object(row)
        self.delete(withdrawn)[2]()
        self.assertEqual(h.store.connection.execute('SELECT count(*) FROM v1_memories').fetchone()[0], 0)
        self.assertEqual(h.store.connection.execute('SELECT count(*) FROM v1_confirmations').fetchone()[0], 0)

    def test_mixed_evidence_retains_only_proven_disjoint_excerpt(self):
        h = self.h
        source = h.intake('삭제할 문장과 다른 문장이 섞인 원문')
        def create(text):
            return {'op': 'create', 'memory': h.content(content=text), 'source_refs': [source],
                    'bindings': [], 'confirmation_event_ref': None, 'consent_event_ref': None}
        h.batch([create('삭제할 문장'), create('다른 문장')])
        memory = next(m for m in h.snapshot()['memories'] if m['content'] == '삭제할 문장')
        self.delete(memory)[2]()
        snapshot = h.snapshot()
        self.assertEqual([m['content'] for m in snapshot['memories']], ['다른 문장'])
        self.assertEqual([e['quote'] for e in snapshot['evidence']], ['다른 문장'])
        self.assertEqual(snapshot['evidence'][0]['version'], source['version'] + 1)
        self.assertEqual(snapshot['interpretations'][0]['status'], 'complete')
        h.assert_error('version_conflict', lambda: h.batch([create('늦은 모델 응답')]))
        # Even a caller that refreshes the feedback ref cannot reinterpret the
        # redacted intake using a cached model response or a new extraction key.
        late = {'op': 'record_extraction', 'feedback_ref': transitions.ref('feedback', snapshot['feedback'][0]),
                'extraction_key': 'cached-old-model', 'error': None,
                'result': {'candidates': [], 'questions': ['삭제할 문장']}}
        h.assert_error('stale_context', lambda: h.batch([late]))

    def test_overlapping_quotes_are_not_reconstructed_or_reconfirmed(self):
        h = self.h
        source = h.intake('가나다라마바사')
        def action(text):
            return {'op': 'create', 'memory': h.content(content=text), 'source_refs': [source], 'bindings': [],
                    'confirmation_event_ref': None, 'consent_event_ref': None}
        h.batch([action('가나다'), action('다라마'), action('바사')])
        first = next(m for m in h.snapshot()['memories'] if m['content'] == '가나다')
        self.delete(first)[2]()
        self.assertEqual([m['content'] for m in h.snapshot()['memories']], ['바사'])
        self.assertEqual([e['quote'] for e in h.snapshot()['evidence']], ['바사'])

    def test_partial_redaction_changes_versions_and_excludes_old_index_hits(self):
        h = self.h
        source = h.intake('삭제할 취향. 보존할 취향.')
        for text in ('삭제할 취향', '보존할 취향'):
            h.batch([{'op': 'create', 'memory': h.content(content=text), 'source_refs': [source], 'bindings': [],
                     'confirmation_event_ref': None, 'consent_event_ref': None}])
        first = next(m for m in h.snapshot()['memories'] if m['content'] == '삭제할 취향')
        second = next(m for m in h.snapshot()['memories'] if m['content'] == '보존할 취향')
        second = h.confirm(second)
        old = transitions.ref('memory', second)
        before = self.context()['basis']['index_version']
        self.delete(first)[2]()
        class OldIndex:
            def search(self, query, eligible_refs, *, index_version):
                self.eligible = eligible_refs
                return [old]
        semantic = OldIndex()
        context = self.context(semantic=semantic)
        self.assertNotIn(old, semantic.eligible)
        self.assertNotEqual(before, context['basis']['index_version'])
        self.assertIn('semantic_stale_index', context['questions'])
        self.assertNotIn('삭제할 취향', json.dumps(context, ensure_ascii=False))
        rebuilt = self.context()
        self.assertEqual(len(rebuilt['model_input']['sources']), 1)
        self.assertIn('보존할 취향', rebuilt['model_input']['sources'][0]['content'])

    def test_target_based_comparison_and_final_selection_are_erased(self):
        f = feedback_tests.FeedbackTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        memory = f.image_memory()
        old_feedback = f.snapshot()['feedback'][0]
        old_response = {'op': 'record_extraction', 'feedback_ref': feedback_tests.ref('feedback', old_feedback),
                        'extraction_key': 'old-image-response', 'error': None, 'result': {'candidates': [], 'questions': ['old']}}
        round_obj = f.publish()
        f.batch([{'op': 'select_final', 'candidate_set_ref': round_obj['candidate_set_ref'], 'candidate_id': 'card-1'}])
        event = f.accept(f.display(memory, 'delete'))
        f.catalog.version += 1
        f.batch([{'op': 'delete', 'memory_id': memory['id'], 'expected_version': memory['version'], 'user_event_ref': event}], catalog=False)
        snapshot = f.snapshot()
        self.assertIsNone(snapshot['request']['final_selection'])
        self.assertFalse(any(s['id'] == round_obj['candidate_set_ref']['id'] for s in snapshot['candidate_sets']))
        removed_questions = {ref['id'] for ref in round_obj['question_refs']}
        self.assertFalse(any(q['id'] in removed_questions for q in snapshot['questions']))
        old_question = snapshot['questions'][0]
        f.assert_error('invalid_input', lambda: f.batch([{'op': 'submit_feedback', 'round_id': None, 'candidate_set_id': None,
            'reaction': 'text_only', 'selections': [], 'text': '오래된 비교 질문을 일반 질문처럼 사용', 'question_id': old_question['id']}]))
        f.assert_error('not_found', lambda: f.batch([old_response]))
        self.assertFalse(f.store.connection.execute('PRAGMA foreign_key_check').fetchall())

    def test_request_vacuum_failure_can_be_retried_after_restart_without_retaining_id(self):
        h = self.h
        h.candidate()
        request_id = h.request['id']
        def fail(stage, *_):
            if stage == 'cleanup_before_vacuum':
                raise RuntimeError('synthetic vacuum failure')
        h.store._failure_hook = fail
        h.assert_error('cleanup_pending', lambda: h.store.delete_request('u1', request_id))
        receipt = dict(h.store.connection.execute('SELECT * FROM v1_request_deletions').fetchone())
        self.assertNotIn(request_id, json.dumps(receipt))
        h.store.close()
        h.store = MemoryStore(h.path, clock=lambda: h.now)
        self.assertTrue(h.store.delete_request('u1', request_id)['deleted'])
        self.assertEqual(h.store.connection.execute('SELECT count(*) FROM v1_cleanup_pending').fetchone()[0], 0)
        h.assert_error('not_found', lambda: h.store.delete_request('another-user', request_id))
        h.now += timedelta(hours=25)
        h.assert_error('not_found', lambda: h.store.delete_request('u1', request_id))

    def test_mixed_feedback_keeps_selection_fact_without_deleted_text_or_reextraction(self):
        f = feedback_tests.FeedbackTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.publish()
        receipt = f.batch([f.action(text='삭제할 선택 이유')])
        text_ref = next(feedback_tests.ref('evidence', e) for e in f.snapshot()['evidence'] if e['kind'] == 'user_text')
        content = transitions.V1TransitionTests.content(content='삭제할 선택 이유')
        f.batch([{'op': 'create', 'memory': content, 'source_refs': [text_ref], 'bindings': [],
                 'confirmation_event_ref': None, 'consent_event_ref': None}])
        memory = f.snapshot()['memories'][0]
        event = f.accept(f.display(memory, 'delete'))
        f.batch([{'op': 'delete', 'memory_id': memory['id'], 'expected_version': memory['version'], 'user_event_ref': event}], catalog=False)
        snapshot = f.snapshot()
        self.assertEqual([e['kind'] for e in snapshot['evidence']], ['image_selection'])
        self.assertEqual(snapshot['feedback'][0]['reaction'], 'selected')
        self.assertEqual(len(snapshot['feedback'][0]['evidence_refs']), 1)
        self.assertEqual(snapshot['interpretations'][0]['status'], 'complete')
        self.assertNotIn('삭제할 선택 이유', json.dumps(snapshot, ensure_ascii=False))
        late = {'op': 'record_extraction', 'feedback_ref': f.feedback_ref(receipt), 'extraction_key': 'late-old-output',
                'error': None, 'result': {'candidates': [], 'questions': ['삭제할 선택 이유']}}
        f.assert_error('version_conflict', lambda: f.batch([late]))

    def test_request_cleanup_failure_is_retryable_and_keeps_input_tombstone(self):
        h = self.h
        h.candidate()
        def fail(stage, *_):
            if stage == 'cleanup_derived':
                raise RuntimeError('synthetic cleanup failure')
        h.store._failure_hook = fail
        h.assert_error('cleanup_pending', lambda: h.store.delete_request('u1', h.request['id']))
        self.assertTrue(h.snapshot()['memories'])
        h.store._failure_hook = None
        h.store.delete_request('u1', h.request['id'])
        h.assert_error('idempotency_conflict', lambda: h.start('first'))
        h.now += timedelta(hours=25)
        h.start('first')

    def test_prune_failure_rolls_back_all_requests_and_retries_without_renewal(self):
        h = self.h
        h.candidate()
        first = h.request
        h.start('second-expiring-request')
        h.now += timedelta(days=31)
        before = [tuple(row) for row in h.store.connection.execute('SELECT id,retention_until FROM requests ORDER BY id')]
        def fail(stage, *_):
            if stage == 'cleanup_after_objects':
                raise RuntimeError('synthetic SQLite failure before commit')
        h.store._failure_hook = fail
        h.assert_error('storage_failed', lambda: h.store.prune_expired('u1'))
        self.assertEqual([tuple(row) for row in h.store.connection.execute('SELECT id,retention_until FROM requests ORDER BY id')], before)
        self.assertEqual(h.store.connection.execute('SELECT count(*) FROM v1_request_deletions').fetchone()[0], 0)
        h.store._failure_hook = None
        h.store.close()
        h.store = MemoryStore(h.path, clock=lambda: h.now)
        result = h.store.prune_expired('u1')
        self.assertEqual(result, {'requests': 2, 'memories': 1})
        h.assert_error('not_found', lambda: h.store.snapshot('u1', first['id'], contract_version=c.CONTRACT_VERSION))

    def test_mixed_summary_with_a_lost_source_is_invalidated_wholly(self):
        h = self.h
        first = h.candidate()
        extra = h.intake('별도의 문장')
        h.batch([{'op': 'create', 'memory': h.content(content='두 근거를 섞은 요약'),
                  'source_refs': first['source_refs'] + [extra], 'bindings': [],
                  'confirmation_event_ref': None, 'consent_event_ref': None}])
        self.delete(first)[2]()
        self.assertEqual(h.snapshot()['memories'], [])
        self.assertEqual(h.snapshot()['evidence'], [])

    def test_erasure_does_not_touch_another_owners_retained_objects(self):
        h = self.h
        other = h.start('other-owner', user='u2')
        memory = h.candidate()
        self.delete(memory)[2]()
        h.store.delete_request('u1', h.request['id'])
        h.store.prune_expired('u1')
        self.assertEqual(h.snapshot(other, user='u2')['request']['id'], other['id'])
