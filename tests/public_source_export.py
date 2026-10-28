#!/usr/bin/env python3
"""The source exporter must refuse unsafe inputs and omit private history inputs."""
import hashlib
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('public_export', ROOT/'tools/prepare_public_source.py')
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)


class SourceExport(unittest.TestCase):
    def test_private_inputs_are_excluded_even_if_tracked(self):
        for name in ('standards/n4861/source/basic.tex', 'downloads/reference/code.cpp',
                     'build/lib.so', '.debugtmp/probe.cpp', 'scratch_probe.cpp',
                     'COMPILER-COMPATIBILITY-PROMPT.md', 'SOURCE-MANIFEST.json'):
            self.assertEqual(EXPORT.classification(name), 'excluded', name)
        with self.assertRaisesRegex(ValueError, 'unclassified'):
            EXPORT.classification('unreviewed-token.txt')
        with self.assertRaisesRegex(ValueError, 'unsafe path'):
            EXPORT.classification('src/../../outside.cpp')

    def test_binary_symlink_and_credentials_are_refused_without_disclosure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root/'src').mkdir()
            source = root/'src/test.cpp'
            credential = b'gh' + b'p_' + b'a' * 36
            source.write_bytes(credential)
            with patch.object(EXPORT, 'candidates', return_value=['src/test.cpp']):
                with self.assertRaisesRegex(ValueError, 'possible credentials') as caught:
                    EXPORT.source_files(root)
                self.assertNotIn(credential.decode(), str(caught.exception))
                source.write_bytes(b'\0binary')
                with self.assertRaisesRegex(ValueError, 'binary input'):
                    EXPORT.source_files(root)
                source.unlink()
                source.symlink_to(root/'missing.cpp')
                with self.assertRaisesRegex(ValueError, 'regular in-tree'):
                    EXPORT.source_files(root)

    def test_snapshot_binds_patch_and_includes_license_scopes(self):
        files, excluded = EXPORT.source_files(ROOT)
        for name in ('include/LICENSE', 'runtime/LICENSE', 'examples/LICENSE',
                     'include/std2/LICENSE', 'LICENSES/LLVM.txt', 'LICENSING.md'):
            self.assertIn(name, files)
        for name, expected in files.items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), expected)
        self.assertFalse(any(name.startswith('standards/n4861/source/') for name in files))
        # Both the private development tree and its clean public snapshot work.
        self.assertFalse(set(files) & set(excluded))


if __name__ == '__main__':
    unittest.main()
