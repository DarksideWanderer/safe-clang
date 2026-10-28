#!/usr/bin/env python3
"""A missing directive or stale source anchor must invalidate a catalog."""
import copy
import json
import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import compatibility_matrix as catalog
import release_check

class FeatureCatalog(unittest.TestCase):
 def setUp(self):
  self.data=json.loads(catalog.CATALOG.read_text())
 def test_pinned_coverage_and_remaining_work(self):
  coverage=catalog.validate_catalog(self.data)
  self.assertEqual(coverage['new_circle_directives'],41)
  self.assertEqual(coverage['documents'],30)
  self.assertTrue(coverage['documents_needing_review'])
  self.assertTrue(coverage['features_missing_negative_oracles'])
  self.assertFalse(self.data['inventory_complete'])
 def test_missing_directive_duplicate_and_stale_anchor_fail(self):
  missing=copy.deepcopy(self.data)
  missing['features']=[f for f in missing['features'] if f['id']!='circle.directive.choice']
  with self.assertRaisesRegex(ValueError,'directives'):
   catalog.validate_catalog(missing)
  duplicate=copy.deepcopy(self.data)
  duplicate['features'].append(duplicate['features'][0])
  with self.assertRaisesRegex(ValueError,'duplicate'):
   catalog.validate_catalog(duplicate)
  stale=copy.deepcopy(self.data)
  stale['features'][0]['implementation'][0]['line']=1
  with self.assertRaisesRegex(ValueError,'stale implementation'):
   catalog.validate_catalog(stale)
 def test_empty_passing_report_is_not_evidence(self):
  with tempfile.TemporaryDirectory() as directory:
   p=pathlib.Path(directory)/'forged.json'
   p.write_text(json.dumps({'status':'passed','snapshot_unchanged':True,'sha256':{'example.cpp':'wrong'}}))
   with self.assertRaisesRegex(ValueError,'does not bind'):
    catalog.current_acceptance(p)
 def test_catalog_dependencies_are_registered_in_the_executed_gate(self):
  registered=catalog.registered_regressions()
  self.assertIn('array_slice_conversions.py',registered)
  self.assertIn('threads.py',registered)
  for feature in self.data['features']:
   for test in feature['local_regressions']:
    self.assertIn(pathlib.Path(test).name,registered,feature['id'])
 def test_render_does_not_turn_unexecuted_tests_into_acceptance(self):
  data=copy.deepcopy(self.data)
  data['fully_compatible']=False
  for item in data['features']:item['current_regression_status']='not_executed'
  text=catalog.markdown(data)
  self.assertIn('not_executed',text)
  self.assertIn('Inventory complete: **False**',text)
  self.assertIn('unavailable',text)
 def test_release_rejects_replaced_or_missing_compiler(self):
  with tempfile.TemporaryDirectory() as directory:
   p=pathlib.Path(directory)/'compiler'
   p.write_bytes(b'accepted compiler')
   expected={str(p):catalog.digest(p)}
   release_check.verify_binaries(expected)
   p.write_bytes(b'different compiler')
   with self.assertRaisesRegex(RuntimeError,'binary changed'):
    release_check.verify_binaries(expected)
   p.unlink()
   with self.assertRaisesRegex(RuntimeError,'binary changed'):
    release_check.verify_binaries(expected)

if __name__=='__main__':unittest.main()
