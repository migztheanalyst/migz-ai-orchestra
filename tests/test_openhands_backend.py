import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'conductor'))
from agent_backend_router import AgentBackendRouter, BackendPlan, BackendUnavailable, HEALTHY

class Completed:
    stdout='OPENHANDS_OK\n'
    stderr=''
    returncode=0

class OpenHandsBackendTests(unittest.TestCase):
    def make_router(self,root):
        r=AgentBackendRouter(repo=root,ollama_base='http://127.0.0.1:11434')
        r.openhands_executable='/fake/openhands'
        return r

    def test_probe_records_pass_and_promotes_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); r=self.make_router(root)
            with mock.patch('agent_backend_router.subprocess.run',return_value=Completed()):
                result=r.bounded_openhands_probe(timeout=1)
            self.assertEqual(result['status'],HEALTHY)
            data=json.loads((root/'evidence/core-final-closure/openhands-canary.json').read_text())
            self.assertEqual(data['state'],'PASSED')
            with mock.patch.object(r,'_lane_states',return_value={}):
                self.assertEqual(r.states()['openhands'].status,HEALTHY)

    def test_command_requires_scope(self):
        r=self.make_router(ROOT)
        plan=BackendPlan('openhands','custom-local-ollama','qwen2.5-coder:7b','coding','test')
        with self.assertRaises(BackendUnavailable):
            r.command(plan,ROOT,'edit safely',allowed_scope=[])
        command,env=r.command(plan,ROOT,'edit safely',allowed_scope=['README.md'])
        self.assertIn('--headless',command)
        self.assertEqual(env['LLM_MODEL'],'openai/qwen2.5-coder:7b')

if __name__=='__main__':
    unittest.main()
