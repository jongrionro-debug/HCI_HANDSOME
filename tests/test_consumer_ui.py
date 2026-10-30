"""E1's JavaScript fixture must stay on the actual Python command/state contract.

UI behavior is checked separately by check_consumer_browser.mjs. No DB, model,
key, browser installation, or server is needed for these cross-language checks.
"""
import json
from pathlib import Path
import shutil
import subprocess
import types
import typing
import unittest

from stylemate_memory.contracts import ConsumerCommand, ConsumerResult, ConsumerState


TRACE_SCRIPT = r"""
import assert from 'node:assert/strict';
import { createFixtureAdapter } from './src/stylemate_memory/consumer-fixture.js';
const adapter = createFixtureAdapter({delay: 0});
const states = [await adapter.state()], commands = [], results = [];
let serial = 0;
async function send(action) {
  const s = await adapter.state();
  const start = action.op === 'start_request';
  const command = {contract_version: s.contract_version, command_id: `test-${++serial}`,
    request_id: start ? null : s.request.id, expected: start ? null : s.expected, action};
  commands.push(command);
  const result = await adapter.command(command);
  results.push(result); states.push(result.state);
  assert.notEqual(result.outcome, 'rejected');
  return result;
}
const start = () => send({op: 'start_request', mode: 'shopping', timezone: 'Asia/Seoul',
  targets: [{target_id: 'pants', garment_type: 'Pants'}], text: null});
const ref = (s, type) => s.expected.object_versions.find(r => r.type === type);
const finish = async () => { await new Promise(resolve => setTimeout(resolve, 410));
  const s = await adapter.state(); states.push(s); return s; };
await start();
let s = await adapter.state();
const card = s.cards[0];
await send({op: 'submit_feedback', round_id: ref(s, 'round').id,
  candidate_set_id: ref(s, 'candidate_set').id, reaction: 'selected',
  selections: [{target_id: card.target_id, candidate_id: card.candidate_id,
    part_ref: {image_id: card.image_id, image_version: card.image_version,
      region_id: null, box: [0.1, 0.2, 0.8, 0.9]}}], text: null, question_id: null});
s = await finish();
assert.equal(s.memories.length, 0, 'selection alone must not invent a preference');
await send({op: 'submit_feedback', round_id: ref(s, 'round').id,
  candidate_set_id: ref(s, 'candidate_set').id, reaction: 'question_skipped',
  selections: [], text: null, question_id: s.questions[0].ref.id});
await finish();
await send({op: 'submit_feedback', round_id: null, candidate_set_id: null,
  reaction: 'text_only', selections: [], text: '이번 요청에서만 여유 있게', question_id: null});
const original = commands.at(-1), firstReceipt = results.at(-1);
assert.deepEqual(await adapter.command(original), firstReceipt, 'replay returns original receipt');
s = await finish();
assert.equal(s.memories[0].confirmed, false);
await send({op: 'prepare_review', purpose: 'confirm_content', subject_refs: [s.memories[0].ref], proposed_text: null});
s = await adapter.state();
await send({op: 'respond_review', display_ref: s.reviews[0].ref, decision: 'accept'});
s = await adapter.state();
assert.equal(s.memories.filter(m => m.scope === 'long_term').length, 0);
await send({op: 'prepare_review', purpose: 'future_reuse', subject_refs: [s.memories[0].ref], proposed_text: null});
s = await adapter.state();
await send({op: 'respond_review', display_ref: s.reviews[0].ref, decision: 'skip'});
assert.equal((await adapter.state()).memories.filter(m => m.scope === 'long_term').length, 0);
s = await adapter.state();
await send({op: 'prepare_review', purpose: 'future_reuse', subject_refs: [s.memories[0].ref], proposed_text: null});
s = await adapter.state();
await send({op: 'respond_review', display_ref: s.reviews[0].ref, decision: 'accept'});
s = await adapter.state();
await send({op: 'select_final', candidate_set_ref: ref(s, 'candidate_set'), candidate_id: s.cards[0].candidate_id});
assert.equal((await adapter.state()).request.status, 'open');
await send({op: 'end_request'});
assert.ok((await adapter.state()).request.final_selection);
await start(); s = await adapter.state();
assert.equal(s.memories.filter(m => m.scope === 'short_term').length, 0);
assert.equal(s.memories.filter(m => m.scope === 'long_term').length, 1);
const saved = s.memories.find(m => m.scope === 'long_term');
await send({op: 'prepare_review', purpose: 'replace', subject_refs: [saved.ref], proposed_text: '새로운 취향 표현'});
s = await adapter.state();
assert.equal(s.reviews[0].snapshot.meaning.scope, 'short_term');
await send({op: 'respond_review', display_ref: s.reviews[0].ref, decision: 'accept'});
s = await adapter.state();
assert.deepEqual(s.memories.find(m => m.scope === 'long_term'), saved, 'an edit preserves the original long-term preference');
assert.equal(s.memories.filter(m => m.scope === 'long_term').length, 1, 'a new meaning needs separate reuse consent');
for (const name of ['pending', 'model_error', 'stale', 'no_results', 'no_images', 'broken_images', 'running', 'blocked', 'normal']) {
  states.push(await adapter.setScenario(name));
}
await adapter.setScenario('model_error');
await send({op: 'submit_feedback', round_id: null, candidate_set_id: null,
  reaction: 'text_only', selections: [], text: '모델 오류 연습', question_id: null});
s = await adapter.state(); states.push(s);
assert.equal(s.operation, 'interpretation_pending');
assert.equal(s.error.code, 'provider_timeout');
await send({op: 'retry_extraction', feedback_ref: ref(s, 'feedback')});
console.log(JSON.stringify({states, commands, results}));
"""


class ConsumerUIContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("Node.js is required for the E1 UI fixture")
        result = subprocess.run(
            ["node", "--input-type=module", "-e", TRACE_SCRIPT],
            cwd=Path(__file__).resolve().parents[1], text=True,
            capture_output=True, check=True, timeout=20,
        )
        cls.trace = json.loads(result.stdout)

    def assert_shape(self, value, annotation, path="value"):
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)
        if origin in (typing.Union, types.UnionType):
            for choice in args:
                try:
                    self.assert_shape(value, choice, path)
                    return
                except AssertionError:
                    pass
            self.fail(f"{path} does not match {annotation}: {value!r}")
        elif origin is typing.Literal:
            self.assertIn(value, args, path)
        elif origin is typing.NotRequired:
            self.assert_shape(value, args[0], path)
        elif typing.is_typeddict(annotation):
            self.assertIsInstance(value, dict, path)
            fields = typing.get_type_hints(annotation, include_extras=True)
            self.assertTrue(annotation.__required_keys__ <= value.keys(), path)
            self.assertTrue(value.keys() <= fields.keys(), f"{path}: unknown fields")
            for key, item in value.items():
                self.assert_shape(item, fields[key], f"{path}.{key}")
        elif origin is list:
            self.assertIsInstance(value, list, path)
            for i, item in enumerate(value):
                self.assert_shape(item, args[0], f"{path}[{i}]")
        elif annotation is float:
            self.assertIn(type(value), (int, float), path)
        else:
            self.assertIs(type(value), annotation, path)

    def test_every_fixture_state_matches_consumer_state_without_private_fields(self):
        for i, state in enumerate(self.trace["states"]):
            with self.subTest(state=i):
                self.assert_shape(state, ConsumerState)

    def test_ui_commands_use_the_fixed_union_and_versioned_refs(self):
        for i, command in enumerate(self.trace["commands"]):
            with self.subTest(command=i):
                self.assert_shape(command, ConsumerCommand)

    def test_pending_reviews_final_and_error_results_match_consumer_result(self):
        for i, result in enumerate(self.trace["results"]):
            with self.subTest(result=i):
                self.assert_shape(result, ConsumerResult)


if __name__ == "__main__":
    unittest.main()
