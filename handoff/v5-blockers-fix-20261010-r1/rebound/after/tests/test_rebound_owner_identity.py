"""Source-only owner identity regression tests on the executing interpreter.

The frozen loader and its verified source capsule run unchanged in a fresh
process. No model, panel, capture, or private asset is loaded or written.
These tests do not replace the existing explicit Mac/private-asset opt-ins.
"""
import hashlib
import json
import marshal
import struct
import subprocess
import sys
import types
import unittest
from pathlib import Path

from v5_shadow import rebound_panel_repair as repair


BASE = Path(__file__).resolve().parents[1]
OWNER_SHA = "27da90f0e623e45fa1a27af7dcc3b6e5e1ff2320bae1c61bd903ed82050beb89"
BOOTSTRAP = "import sys; sys.path.insert(0, " + repr(str(BASE / "src")) + ");\n" + r'''
import hashlib, importlib, json, struct, types
from pathlib import Path
from v5_shadow import hk_preselection, rebound_panel_repair as repair
sources = hk_preselection._source_bytes()
sys.meta_path.insert(0, hk_preselection._HKLoader(sources))
owner = importlib.import_module('upstreams.v3_shared_data.shared_data.hk_0_2')
source_before = hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest()
# This call deliberately precedes any inspection of functions or code fields.
repair._verify_owner(owner)
def rejected(expected):
    try:
        repair._verify_owner(owner)
    except ValueError as error:
        assert str(error) == expected, (str(error), expected)
    else:
        raise AssertionError('TAMPERED_OWNER_ACCEPTED:' + expected)
'''
FOOTER = r'''
assert hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest() == source_before
print(json.dumps({'owner_sha256': source_before, 'source_unchanged': True}))
'''


class FrozenOwnerIdentityTests(unittest.TestCase):
    def child(self, script):
        process = subprocess.run([sys.executable, "-I", "-B", "-c", BOOTSTRAP + script + FOOTER],
            capture_output=True, text=True, check=False, timeout=60)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["owner_sha256"], OWNER_SHA)
        self.assertTrue(result["source_unchanged"])

    def test_frozen_loader_passes_before_code_inspection(self):
        self.child("repair._verify_owner(owner)\n")

    def test_holding_and_releasing_owner_docstrings_preserves_identity(self):
        self.child(r'''
held = [value.__doc__ for value in vars(owner).values()
        if type(value) is types.FunctionType and value.__doc__ is not None]
assert held
repair._verify_owner(owner)
del held
repair._verify_owner(owner)
''')

    def test_replaced_owner_function_is_rejected(self):
        self.child(r'''
owner._read_vipdoc_increment = lambda *args, **kwargs: ([], 0)
rejected('REPAIR_OWNER_FUNCTION_IDENTITY')
''')

    def test_owner_function_with_copied_globals_is_rejected(self):
        self.child(r'''
original = owner._normalize_code
owner._normalize_code = types.FunctionType(original.__code__, dict(original.__globals__),
    original.__name__, original.__defaults__, original.__closure__)
rejected('REPAIR_OWNER_FUNCTION_IDENTITY')
''')

    def test_changed_nested_code_is_rejected_with_unchanged_outer_bytecode(self):
        self.child(r'''
found = False
for function in tuple(vars(owner).values()):
    if type(function) is not types.FunctionType or function.__globals__ is not vars(owner):
        continue
    before = function.__code__
    for index, value in enumerate(before.co_consts):
        if type(value) is types.CodeType:
            replacement = compile('def injected():\n    return "changed nested behavior"\n',
                value.co_filename, 'exec', dont_inherit=True).co_consts[0]
            constants = list(before.co_consts)
            constants[index] = replacement
            function.__code__ = before.replace(co_consts=tuple(constants))
            assert function.__code__.co_code == before.co_code
            found = True
            break
    if found:
        break
assert found, 'FROZEN_OWNER_NESTED_CODE_MISSING'
rejected('REPAIR_OWNER_FUNCTION_MODIFIED')
''')

    def test_changed_function_constant_is_rejected_with_unchanged_bytecode(self):
        self.child(r'''
function = owner._normalize_code
before = function.__code__
constants = list(before.co_consts)
index = next(i for i, value in enumerate(constants) if type(value) is str and value)
constants[index] += '_changed_constant'
function.__code__ = before.replace(co_consts=tuple(constants))
assert function.__code__.co_code == before.co_code
rejected('REPAIR_OWNER_FUNCTION_MODIFIED')
''')

    def test_imported_callable_replacement_is_rejected(self):
        self.child(r'''
original = owner.sha256_file
class Replacement:
    def __call__(self, path):
        return original(path)
owner.sha256_file = Replacement()
rejected('REPAIR_OWNER_IMPORTED_HELPER_IDENTITY')
''')

    def test_imported_helper_code_mutation_is_rejected(self):
        self.child(r'''
function = owner.sha256_file
function.__code__ = compile('def sha256_file(path):\n    return "changed hash"\n',
    function.__code__.co_filename, 'exec', dont_inherit=True).co_consts[0]
rejected('REPAIR_OWNER_IMPORTED_HELPER_MODIFIED')
''')

    def test_imported_helper_with_copied_globals_is_rejected(self):
        self.child(r'''
original = owner.sha256_file
owner.sha256_file = types.FunctionType(original.__code__, dict(original.__globals__),
    original.__name__, original.__defaults__, original.__closure__)
rejected('REPAIR_OWNER_IMPORTED_GLOBALS')
''')

    def test_literal_module_constant_mutation_is_rejected(self):
        self.child(r'''
owner._MAX_CROSS_DAY_CLOSE_RATIO = 9.0
rejected('REPAIR_OWNER_CONSTANT_MODIFIED')
''')

    def test_native_layout_mutation_is_rejected(self):
        self.child(r'''
owner._VIPDOC_DAY_STRUCT = struct.Struct('>IfffffII')
rejected('REPAIR_OWNER_NATIVE_LAYOUT_MODIFIED')
''')


class StructuralCodeIdentityTests(unittest.TestCase):
    SOURCE = ('def sample(value):\n'
              '    """A non-interned docstring whose reference count may change."""\n'
              '    return value + 17\n')

    def pair(self):
        reference = compile(self.SOURCE, '<identity-regression>', 'exec', dont_inherit=True).co_consts[0]
        namespace = {}
        exec(compile(self.SOURCE, '<identity-regression>', 'exec', dont_inherit=True), namespace)
        return reference, namespace['sample']

    def test_reference_docstring_hold_release_does_not_change_code_identity(self):
        reference, function = self.pair()
        # The old predicate changes with a held reference on affected builds.
        # Record it without requiring interpreter-specific marshal bytes.
        before = marshal.dumps(reference)
        self.assertTrue(repair._same_code(reference, function.__code__))
        held = reference.co_consts[0]
        while_held = marshal.dumps(reference)
        self.assertTrue(repair._same_code(reference, function.__code__))
        del held
        after = marshal.dumps(reference)
        self.assertTrue(repair._same_code(reference, function.__code__))
        self.assertEqual(before, after)
        self.assertIsInstance(while_held, bytes)

    def test_all_18_immutable_code_fields_are_compared(self):
        reference, _ = self.pair()
        fields = {
            'co_argcount': 0,
            'co_posonlyargcount': 1,
            'co_kwonlyargcount': 1,
            'co_nlocals': 2,
            'co_stacksize': reference.co_stacksize + 1,
            'co_flags': reference.co_flags ^ 0x40,
            'co_code': reference.co_code[:-2] + b'\x09\x00',
            'co_consts': reference.co_consts + ('changed',),
            'co_names': ('changed_name',),
            'co_varnames': ('renamed_value',),
            'co_filename': '<changed-filename>',
            'co_name': 'changed_name',
            'co_qualname': 'changed_qualname',
            'co_firstlineno': reference.co_firstlineno + 1,
            'co_linetable': b'',
            'co_exceptiontable': b'\x80\x01\x01\x00',
            'co_freevars': ('changed_free',),
            'co_cellvars': ('changed_cell',),
        }
        self.assertEqual(len(fields), 18)
        for name, value in fields.items():
            with self.subTest(field=name):
                arguments = {name: value}
                # CodeType enforces these constructor invariants.
                if name == 'co_kwonlyargcount':
                    arguments.update(co_nlocals=2, co_varnames=('value', 'keyword'))
                elif name == 'co_nlocals':
                    arguments['co_varnames'] = ('value', 'extra')
                changed = reference.replace(**arguments)
                self.assertFalse(repair._same_code(reference, changed))

    def test_nested_immutable_constant_values_compare_without_reference_identity(self):
        reference, _ = self.pair()
        left = reference.replace(co_consts=(None, ('value', (1, 2)), frozenset(('x', 'y')),
                                           slice(1, 9, 2), 3 + 4j, Ellipsis))
        right = reference.replace(co_consts=(None, tuple(['value', tuple([1, 2])]),
                                            frozenset(['y', 'x']), slice(1, 9, 2), 3 + 4j, Ellipsis))
        self.assertTrue(repair._same_code(left, right))
        changed = right.replace(co_consts=right.co_consts[:-1] + (None,))
        self.assertFalse(repair._same_code(left, changed))

    def test_equal_numeric_values_of_different_types_are_distinguished(self):
        reference, _ = self.pair()
        for left, right in ((1, True), (1, 1.0), (1.0, 1 + 0j), ((1,), (True,)),
                            (frozenset((1,)), frozenset((True,)))):
            with self.subTest(left=repr(left), right=repr(right)):
                self.assertFalse(repair._same_code(reference.replace(co_consts=(left,)),
                                                   reference.replace(co_consts=(right,))))

    def test_float_and_complex_signed_zero_bits_are_distinguished(self):
        reference, _ = self.pair()
        for left, right in ((0.0, -0.0), (complex(0.0, 1.0), complex(-0.0, 1.0)),
                            (complex(1.0, 0.0), complex(1.0, -0.0))):
            with self.subTest(left=repr(left), right=repr(right)):
                self.assertFalse(repair._same_code(reference.replace(co_consts=(left,)),
                                                   reference.replace(co_consts=(right,))))

    def test_nan_payloads_are_compared_by_bits(self):
        reference, _ = self.pair()
        first = struct.unpack('!d', bytes.fromhex('7ff8000000000001'))[0]
        same = struct.unpack('!d', bytes.fromhex('7ff8000000000001'))[0]
        different = struct.unpack('!d', bytes.fromhex('7ff8000000000002'))[0]
        self.assertTrue(repair._same_code(reference.replace(co_consts=(first,)),
                                          reference.replace(co_consts=(same,))))
        self.assertFalse(repair._same_code(reference.replace(co_consts=(first,)),
                                           reference.replace(co_consts=(different,))))

    def test_unknown_or_mutable_constant_types_fail_closed(self):
        reference, _ = self.pair()
        class EqualToAnything:
            def __eq__(self, other):
                raise AssertionError('UNTRUSTED_CONSTANT_EQUALITY_EXECUTED')
        for value in ([], {}, set(), EqualToAnything()):
            with self.subTest(type=type(value).__name__):
                changed = reference.replace(co_consts=(value,))
                self.assertFalse(repair._same_code(reference, changed))
                self.assertFalse(repair._same_code(changed, changed))


if __name__ == '__main__':
    unittest.main()
