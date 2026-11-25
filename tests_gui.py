import unittest
from unittest.mock import patch
from gui.controls import SLIDER_CONFIG
from gui.tasks import make_draft_preview
from engine.workflow import EFFECT_FIELDS

class GUIConfigTests(unittest.TestCase):
    def test_fields_match_engine(self):
        self.assertEqual(set(SLIDER_CONFIG) | {'serif_style'}, EFFECT_FIELDS)

    def test_draft_uses_temp_root(self):
        with patch('gui.tasks.normalize_spec', return_value={}), patch('gui.tasks.generate_integrated', side_effect=RuntimeError('test')) as gen:
            with self.assertRaises(RuntimeError): make_draft_preview({})
            self.assertTrue(gen.call_args.args[1].name.startswith('ai_font_draft_'))

if __name__ == '__main__': unittest.main()
