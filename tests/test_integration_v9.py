import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from ai.designer import create_spec, create_patch
from ai.prompts import load_candidates
from engine.catalog import FONTS_DIR
from engine.workflow import DEFAULTS, EFFECT_FIELDS, normalize_spec, generate_from_spec
from engine.session_state import FontSession
from engine.ttf_validation import validate_ttf
from gui.tasks import make_draft_preview

def answer(params):
    return json.dumps({'action':'generate','parameters':params,'message':'test'})

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        cs=load_candidates('латиница Inter')
        self.base=next((c['id'] for c in cs if 'Inter/' in c['id']),cs[0]['id'])
    def test_chain(self):
        initial={k:DEFAULTS[k] for k in EFFECT_FIELDS}
        initial.update(base_font=self.base,weight_scale=1.12,counter_scale=1.1,corner_roundness=.12,serif_style='slab',serif_angle=5)
        spec,_=create_spec('латиница Inter',ask=lambda p:answer(initial))
        self.assertEqual(spec['counter_scale'],1.1)
        with patch('engine.workflow.OUTPUT_DIR',self.root/'output'):
            first=generate_from_spec(spec)
            session=FontSession.start(spec,first,sessions_dir=self.root/'sessions')
            session.set_slider('counter_scale',.85)
            current,rev=session.prepare_ai_request()
            def fake(p):
                self.assertIn('"counter_scale": 0.85',p)
                return answer({'weight_scale':1.24})
            changes,_=create_patch('толще',current,ask=fake)
            second,changed=session.apply_ai_patch(changes,rev)
            self.assertTrue(changed); self.assertEqual(session.params['counter_scale'],.85)
            self.assertEqual(session.params['weight_scale'],1.24); self.assertEqual(session.params['serif_angle'],5)
            self.assertEqual(validate_ttf(second,FONTS_DIR/self.base)['status'],'ok')
            session.set_slider('corner_roundness',.2)
            self.assertGreater(make_draft_preview(session.params).width,100)
            self.assertEqual(len(list((self.root/'output').iterdir())),2)
            third,changed=session.save_current()
            self.assertTrue(changed); self.assertFalse(session.needs_export)
            restored=FontSession.load(session.data['session_id'],sessions_dir=self.root/'sessions')
            self.assertEqual(restored.latest_ttf,third); self.assertEqual(restored.params['corner_roundness'],.2)
            self.assertEqual(restored.history[-1]['kind'],'manual_export')
    def test_invalid_patch(self):
        spec=normalize_spec({'base_font':self.base})
        for bad in [{'weight_scale':4},{'counter_scale':True},{'serif_style':[]},{'base_font':'other'},{'corner_roundness':float('nan')}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):create_patch('bad',spec,ask=lambda p:answer(bad))
        self.assertEqual(normalize_spec({**spec,'spacing':-20})['spacing'],-20)
        patch_result,_=create_patch('толще',{**spec,'family_name':'meta','parent_version':None},ask=lambda p:answer({'weight_scale':1.2}))
        self.assertEqual(patch_result,{'weight_scale':1.2})
    def test_old_session(self):
        old={'base_font':self.base,'width':1,'slant':0,'spacing':0,'script':'auto'}
        ttf=self.root/'old.ttf';ttf.write_bytes(b'mock')
        session=FontSession.start(old,ttf,sessions_dir=self.root/'sessions')
        data=session.data;data['current_params']=old.copy();data['versions'][0]['params']=old.copy();session.path.write_text(json.dumps(data))
        restored=FontSession.load(data['session_id'],sessions_dir=self.root/'sessions')
        self.assertEqual(restored.params['weight_scale'],1);self.assertFalse(restored.needs_export)
    def test_bad_file(self):
        bad=self.root/'bad.ttf';bad.write_bytes(b'invalid')
        with self.assertRaises(Exception):validate_ttf(bad)
