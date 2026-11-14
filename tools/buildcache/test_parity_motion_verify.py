"""Release verification rejects stale receipts and a same-size old linked body."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import parity_motion_verify as gate


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.obj = self.root/'instance.o';self.obj.write_bytes(b'qualified object')
        self.elf = self.root/'player.elf';self.elf.write_bytes(b'linked player')
        self.code = b'\0'*248
        self.receipt = dict(schema=2, exit=0, adapter_sha256=gate.digest(gate.ADAPTER.read_bytes()),
                            c_body_sha256=gate.digest(gate.BODY.read_bytes()), object_file=self.obj.name,
                            object_sha256=gate.digest(self.obj.read_bytes()),
                            normalized_body_sha256=gate.normalized_body(self.code))
        self.write()

    def write(self):
        (self.root/'pm.json').write_text(json.dumps(self.receipt), encoding='utf-8')

    def mock_elf(self, linked_code=None):
        code = self.code
        class FakeElf:
            def __init__(obj, path):
                obj.data = path.read_bytes();obj.linked = path.suffix == '.elf'
            def function(obj, name):
                return 0x100000, (linked_code if obj.linked and linked_code is not None else code)
        return patch.object(gate, 'Elf', FakeElf)

    def test_current_receipt_and_identical_linked_body_pass(self):
        with self.mock_elf(), patch.object(gate, 'prove_motion', return_value={'slot_bytes':248}) as proof:
            result = gate.verify(self.elf, self.root)
        self.assertEqual(result['slot_bytes'], 248)
        proof.assert_called_once()

    def test_missing_receipt_fails(self):
        (self.root/'pm.json').unlink()
        with self.assertRaisesRegex(AssertionError, 'receipt required'):
            gate.verify(self.elf, self.root)

    def test_stale_adapter_and_source_fail(self):
        for field in ('adapter_sha256', 'c_body_sha256'):
            original = self.receipt[field];self.receipt[field] = 'stale';self.write()
            with self.subTest(field=field), self.assertRaisesRegex(AssertionError, 'Stale'):
                gate.verify(self.elf, self.root)
            self.receipt[field] = original

    def test_changed_object_fails(self):
        self.obj.write_bytes(b'old object')
        with self.assertRaisesRegex(AssertionError, 'Object differs'):
            gate.verify(self.elf, self.root)

    def test_same_size_old_linked_body_fails(self):
        with self.mock_elf(b'\x01'+self.code[1:]), self.assertRaisesRegex(AssertionError, 'Linked motion body differs'):
            gate.verify(self.elf, self.root)

    def test_normalization_only_ignores_arm_bl_displacements(self):
        a = struct.pack('<I', 0xeb000001)+self.code[4:]
        b = struct.pack('<I', 0xeb123456)+self.code[4:]
        self.assertEqual(gate.normalized_body(a), gate.normalized_body(b))
        self.assertNotEqual(gate.normalized_body(a), gate.normalized_body(struct.pack('<I', 0xea000001)+self.code[4:]))


if __name__ == '__main__':
    unittest.main()
